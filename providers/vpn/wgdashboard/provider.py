"""
GhYiAb V2 — WGDashboard Provider Adapter (REST API)
====================================================

مرز معماری: V2 Core → VPNProvider → این Adapter → WGDashboard REST API → WireGuard

قواعد سخت
---------
- فقط از طریق REST API پنل (``/api/...``) با توکن Bearer (JWT).
- تغییر مکان WGDashboard به سرور دیگر = فقط تغییر ``WGDASHBOARD_BASE_URL`` (و توکن).
- NOT_CONFIGURED/BLOCKED هرگز شبیه‌سازی نمی‌شود: ``NotConfiguredError``.
- توکن هرگز لاگ/نمایش داده نمی‌شود.
- WGDashboard برای WireGuard است، نه Xray - متدها کمی متفاوتند.
- Circuit breaker سبک.

مرجع API: WGDashboard API
واحدها: ``data_limit`` در پنل **بایت** است؛ ``expiry_time`` epoch ثانیه.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence
from urllib.parse import quote

import requests

from providers.vpn.base import (
    ClientSpec, ClientState, NotConfiguredError, ProviderAuthError,
    ProviderRejectedError, ProviderUnavailableError, VPNProviderError,
)

logger = logging.getLogger("ghyiab.providers.wgdashboard")


def _truthy(v: str, default: bool = True) -> bool:
    v = (v or "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


def _env_int(*names: str, default: int) -> int:
    for n in names:
        raw = os.getenv(n, "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                break
    return default


@dataclass(frozen=True)
class WGDashboardConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    timeout: int = 10
    verify_tls: bool = True
    sub_url_base: str = ""
    max_retries: int = 2

    # Cached JWT token
    _token: str = ""
    _token_expires: float = 0.0

    @classmethod
    def from_env(cls) -> "WGDashboardConfig":
        base = (os.getenv("WGDASHBOARD_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            username=os.getenv("WGDASHBOARD_USERNAME", "").strip(),
            password=os.getenv("WGDASHBOARD_PASSWORD", "").strip(),
            timeout=_env_int("WGDASHBOARD_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("WGDASHBOARD_VERIFY_TLS", "1")),
            sub_url_base=os.getenv("WGDASHBOARD_SUB_URL_BASE", "").strip(),
            max_retries=min(5, _env_int("WGDASHBOARD_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def __repr__(self) -> str:
        return (f"WGDashboardConfig(base_url={self.base_url!r}, username={self.username!r}, "
                f"timeout={self.timeout}, verify_tls={self.verify_tls})")


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class WGDashboardProvider:
    name = "wgdashboard"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30
    TOKEN_BUFFER_S = 60

    def __init__(self, config: Optional[WGDashboardConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or WGDashboardConfig.from_env()
        self._session = session or requests.Session()
        self._sleep = sleep
        self._lock = threading.Lock()
        self._fails = 0
        self._open_until = 0.0

    # ---- پیکربندی ---------------------------------------------------------
    def is_configured(self) -> bool:
        return self.config.is_configured

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise NotConfiguredError(
                "NOT_CONFIGURED: WGDASHBOARD_BASE_URL، WGDASHBOARD_USERNAME و WGDASHBOARD_PASSWORD تنظیم نشده‌اند.")

    # ---- Authentication ----------------------------------------------------
    def _get_token(self) -> str:
        now = time.monotonic()
        if self.config._token and now < self.config._token_expires - self.TOKEN_BUFFER_S:
            return self.config._token

        self._require_configured()
        url = f"{self.config.base_url}/api/login"
        data = {"username": self.config.username, "password": self.config.password}
        headers = {"Content-Type": "application/json"}

        try:
            resp = self._session.post(url, json=data, headers=headers,
                                      timeout=self.config.timeout, verify=self.config.verify_tls)
        except requests.RequestException as exc:
            raise ProviderUnavailableError(f"اتصال به پنل WGDashboard ناموفق ({type(exc).__name__})") from exc

        if resp.status_code >= 500:
            raise ProviderUnavailableError(f"خطای سرور پنل (HTTP {resp.status_code})")
        if resp.status_code in (401, 403):
            raise ProviderAuthError("نام کاربری یا رمز عبور WGDashboard نامعتبر است")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر API یافت نشد", status=404)

        try:
            payload = resp.json()
        except ValueError:
            raise ProviderRejectedError(f"پاسخ نامعتبر از پنل (HTTP {resp.status_code})", status=resp.status_code)

        if not isinstance(payload, dict) or "token" not in payload:
            raise ProviderRejectedError(
                f"پنل توکن صادر نکرد: {_clean(payload.get('message', ''))}",
                status=resp.status_code)

        expires_in = payload.get("expires_in", 3600)
        self.config._token = payload["token"]
        self.config._token_expires = now + expires_in
        return self.config._token

    # ---- HTTP -------------------------------------------------------------
    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("پنل WGDashboard موقتاً در دسترس نیست (circuit open)")

    def _breaker_record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._fails = 0
                self._open_until = 0.0
            else:
                self._fails += 1
                if self._fails >= self.BREAKER_THRESHOLD:
                    self._open_until = time.monotonic() + self.BREAKER_COOLDOWN_S

    def _request(self, method: str, path: str, *, json_body: Any = None, params: Any = None) -> Any:
        self._require_configured()
        self._breaker_check()
        url = f"{self.config.base_url}/api{path}"
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        attempts = (self.config.max_retries + 1) if method == "GET" else 1
        last_exc: Optional[Exception] = None

        for i in range(attempts):
            try:
                resp = self._session.request(
                    method, url, json=json_body, params=params, headers=headers,
                    timeout=self.config.timeout, verify=self.config.verify_tls)
            except requests.RequestException as exc:
                last_exc = ProviderUnavailableError(f"اتصال به پنل ناموفق ({type(exc).__name__})")
                self._breaker_record(False)
                if i + 1 < attempts:
                    self._sleep(min(2.0, 0.25 * (2 ** i)))
                    self._breaker_check()
                    continue
                raise last_exc from None

            if resp.status_code >= 500:
                last_exc = ProviderUnavailableError(f"خطای سرور پنل (HTTP {resp.status_code})")
                self._breaker_record(False)
                if i + 1 < attempts:
                    self._sleep(min(2.0, 0.25 * (2 ** i)))
                    self._breaker_check()
                    continue
                raise last_exc

            if resp.status_code == 401:
                if i == 0:
                    self.config._token = ""
                    self.config._token_expires = 0.0
                    continue
                raise ProviderAuthError("توکن منقضی شده یا نامعتبر")

            break

        self._breaker_record(True)

        if resp.status_code == 403:
            raise ProviderAuthError("دسترسی ناکافی (HTTP 403)")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر/منبع یافت نشد", status=404)

        try:
            payload = resp.json()
        except ValueError:
            raise ProviderRejectedError(
                f"پاسخ نامعتبر از پنل (HTTP {resp.status_code})", status=resp.status_code) from None

        return payload

    # ---- سلامت ------------------------------------------------------------
    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            self._request("GET", "/status")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    # ---- Inbound/Peer ----------------------------------------------------------
    def list_inbounds(self) -> list[dict]:
        """Get all WireGuard interfaces (servers)."""
        try:
            data = self._request("GET", "/wg/server/list")
            return data if isinstance(data, list) else []
        except VPNProviderError:
            return []

    def list_peers(self, server_id: str) -> list[dict]:
        """Get all peers for a server."""
        try:
            data = self._request("GET", f"/wg/peer/list/{server_id}")
            return data if isinstance(data, list) else []
        except VPNProviderError:
            return []

    # ---- کلاینت (Peer) -----------------------------------------------------------
    def _to_client_state(self, peer: dict, server_id: str = "") -> ClientState:
        """Convert WGDashboard peer to ClientState."""
        enable = peer.get("enable", True)
        expiry = peer.get("expiry_time", 0)
        expiry_ms = int(expiry * 1000) if expiry and expiry < 1e12 else int(expiry or 0)
        total_bytes = int(peer.get("data_limit", 0) or 0)

        return ClientState(
            email=peer.get("name", "") or peer.get("username", ""),
            enable=enable,
            expiry_ms=expiry_ms,
            total_bytes=total_bytes,
            up_bytes=int(peer.get("upload", 0) or 0),
            down_bytes=int(peer.get("download", 0) or 0),
            sub_id=peer.get("id", "") or "",
            uuid=peer.get("public_key", "") or "",
            inbound_ids=(server_id,) if server_id else (),
        )

    def get_traffic(self, email: str) -> Optional[ClientState]:
        """Search for peer across all servers."""
        try:
            servers = self.list_inbounds()
            for server in servers:
                server_id = str(server.get("id", ""))
                peers = self.list_peers(server_id)
                for peer in peers:
                    if peer.get("name") == email or peer.get("username") == email:
                        return self._to_client_state(peer, server_id)
            return None
        except ProviderRejectedError as e:
            if e.status == 404:
                return None
            raise

    def get_client(self, email: str) -> Optional[ClientState]:
        return self.get_traffic(email)

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        if not inbound_ids:
            raise ProviderRejectedError("حداقل یک server (inbound) لازم است")

        server_id = str(inbound_ids[0])

        # Generate WireGuard keys if not provided
        # Note: In production, you'd want proper key generation
        # For WireGuard, we need public/private key pair
        # This is simplified - real implementation would generate keys

        peer_data = {
            "name": spec.email,
            "server_id": server_id,
            "enable": spec.enable,
            "expiry_time": int(spec.expiry_ms / 1000) if spec.expiry_ms > 0 else 0,
            "data_limit": int(spec.total_bytes) if spec.total_bytes > 0 else 0,
            "dns": "1.1.1.1, 8.8.8.8",
            "mtu": 1420,
            "keep_alive": 25,
            "allowed_ips": "0.0.0.0/0, ::/0",
        }

        self._request("POST", "/wg/peer/create", json_body=peer_data)

        created = self.get_client(spec.email)
        if created is None:
            raise ProviderUnavailableError("Peer پس از ساخت قابل تأیید نبود")
        return created

    def _find_peer(self, email: str) -> tuple[dict, str]:
        """Find peer and return (peer_data, server_id)."""
        servers = self.list_inbounds()
        for server in servers:
            server_id = str(server.get("id", ""))
            peers = self.list_peers(server_id)
            for peer in peers:
                if peer.get("name") == email or peer.get("username") == email:
                    return peer, server_id
        raise ProviderRejectedError("Peer یافت نشد", status=404)

    def _raw_record(self, email: str) -> dict:
        peer, _ = self._find_peer(email)
        return peer

    def update_client(self, email: str, **changes) -> ClientState:
        peer, server_id = self._find_peer(email)
        peer_id = str(peer.get("id", ""))

        update_data = {}
        mapping = {
            "enable": "enable",
            "expiry_ms": "expiry_time",
            "total_bytes": "data_limit",
            "limit_ip": "limit_ip",  # Not directly supported
            "comment": "note",  # Not directly supported
        }

        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")
            api_key = mapping[k]
            if k == "expiry_ms":
                update_data[api_key] = int(v / 1000) if v > 0 else 0
            elif k == "total_bytes":
                update_data[api_key] = int(v) if v > 0 else 0
            else:
                update_data[api_key] = v

        self._request("PUT", f"/wg/peer/update/{server_id}/{peer_id}", json_body=update_data)

        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("Peer پس از بروزرسانی قابل تأیید نبود")
        return fresh

    def delete_client(self, email: str) -> None:
        peer, server_id = self._find_peer(email)
        peer_id = str(peer.get("id", ""))
        self._request("DELETE", f"/wg/peer/delete/{server_id}/{peer_id}")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        if reset_traffic:
            try:
                peer, server_id = self._find_peer(email)
                peer_id = str(peer.get("id", ""))
                self._request("POST", f"/wg/peer/reset/{server_id}/{peer_id}")
            except VPNProviderError:
                pass
        return self.update_client(email, **changes)

    def get_links(self, email: str) -> list[str]:
        """Get WireGuard config file content as link."""
        try:
            peer, server_id = self._find_peer(email)
            peer_id = str(peer.get("id", ""))
            # Get config file
            config = self._request("GET", f"/wg/peer/config/{server_id}/{peer_id}")
            if config:
                return [str(config)]
        except VPNProviderError:
            pass
        return []

    def get_subscription_url(self, sub_id: str) -> Optional[str]:
        # WGDashboard doesn't have traditional subscription URLs
        base = self.config.sub_url_base
        if not base or not sub_id:
            return None
        return base.rstrip("/") + "/" + quote(sub_id, safe="")

    def reset_traffic(self, email: str) -> None:
        try:
            peer, server_id = self._find_peer(email)
            peer_id = str(peer.get("id", ""))
            self._request("POST", f"/wg/peer/reset/{server_id}/{peer_id}")
        except VPNProviderError:
            raise ProviderRejectedError("ریست ترافیک ناموفق بود")

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))


def build_default_provider() -> WGDashboardProvider:
    return WGDashboardProvider(WGDashboardConfig.from_env())