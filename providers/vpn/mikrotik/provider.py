"""
GhYiAb V2 — Mikrotik Provider Adapter (REST API)
=================================================

مرز معماری: V2 Core → VPNProvider → این Adapter → Mikrotik REST API (RouterOS) → WireGuard/PPTP/L2TP

Mikrotik RouterOS API برای مدیریت کاربران VPN (PPP secrets، WireGuard peers، PPP profiles).
این provider برای محیط‌های ISP/سازمان‌های بزرگ مناسب است.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid as _uuid
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import requests

from providers.vpn.base import (
    ClientSpec, ClientState, NotConfiguredError, ProviderAuthError,
    ProviderRejectedError, ProviderUnavailableError, VPNProviderError,
)

logger = logging.getLogger("ghyiab.providers.mikrotik")


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
class MikrotikConfig:
    base_url: str = ""  # e.g., https://router.example.com/rest
    username: str = ""
    password: str = ""
    timeout: int = 10
    verify_tls: bool = True
    # PPP profile name for VPN users
    ppp_profile: str = "ghyiab-vpn"
    # WireGuard interface name
    wg_interface: str = "wireguard1"
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "MikrotikConfig":
        base = (os.getenv("MIKROTIK_BASE_URL") or "").strip().rstrip("/")
        return cls(
            base_url=base,
            username=os.getenv("MIKROTIK_USERNAME", "").strip(),
            password=os.getenv("MIKROTIK_PASSWORD", "").strip(),
            timeout=_env_int("MIKROTIK_TIMEOUT", default=10),
            verify_tls=_truthy(os.getenv("MIKROTIK_VERIFY_TLS", "1")),
            ppp_profile=os.getenv("MIKROTIK_PPP_PROFILE", "ghyiab-vpn").strip(),
            wg_interface=os.getenv("MIKROTIK_WG_INTERFACE", "wireguard1").strip(),
            max_retries=min(5, _env_int("MIKROTIK_MAX_RETRIES", default=2)),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def __repr__(self) -> str:
        return (f"MikrotikConfig(base_url={self.base_url!r}, username={self.username!r}, "
                f"timeout={self.timeout}, verify_tls={self.verify_tls})")


_SAFE_MSG = re.compile(r"[^\w\s\-.:,;/()@؀-ۿ]")


def _clean(msg: Any, limit: int = 160) -> str:
    return _SAFE_MSG.sub("", str(msg or ""))[:limit]


class MikrotikProvider:
    name = "mikrotik"
    BREAKER_THRESHOLD = 3
    BREAKER_COOLDOWN_S = 30

    def __init__(self, config: Optional[MikrotikConfig] = None, *, session: Optional[requests.Session] = None,
                 sleep=time.sleep):
        self.config = config or MikrotikConfig.from_env()
        self._session = session or requests.Session()
        self._session.auth = (self.config.username, self.config.password)
        self._sleep = sleep
        self._lock = threading.Lock()
        self._fails = 0
        self._open_until = 0.0

    def is_configured(self) -> bool:
        return self.config.is_configured

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise NotConfiguredError("NOT_CONFIGURED: MIKROTIK_BASE_URL، USERNAME و PASSWORD تنظیم نشده‌اند.")

    def _breaker_check(self) -> None:
        with self._lock:
            if self._open_until and time.monotonic() < self._open_until:
                raise ProviderUnavailableError("میکروتیک موقتاً در دسترس نیست (circuit open)")

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
        # RouterOS REST API uses /rest/ prefix
        url = f"{self.config.base_url}/rest{path}"
        headers = {"Accept": "application/json"}
        attempts = (self.config.max_retries + 1) if method == "GET" else 1
        last_exc: Optional[Exception] = None

        for i in range(attempts):
            try:
                resp = self._session.request(
                    method, url, json=json_body, params=params, headers=headers,
                    timeout=self.config.timeout, verify=self.config.verify_tls)
            except requests.RequestException as exc:
                last_exc = ProviderUnavailableError(f"اتصال به میکروتیک ناموفق ({type(exc).__name__})")
                self._breaker_record(False)
                if i + 1 < attempts:
                    self._sleep(min(2.0, 0.25 * (2 ** i)))
                    self._breaker_check()
                    continue
                raise last_exc from None

            if resp.status_code >= 500:
                last_exc = ProviderUnavailableError(f"خطای سرور میکروتیک (HTTP {resp.status_code})")
                self._breaker_record(False)
                if i + 1 < attempts:
                    self._sleep(min(2.0, 0.25 * (2 ** i)))
                    self._breaker_check()
                    continue
                raise last_exc

            break

        self._breaker_record(True)

        if resp.status_code in (401, 403):
            raise ProviderAuthError(f"احراز هویت ناموفق (HTTP {resp.status_code})")
        if resp.status_code == 404:
            raise ProviderRejectedError("مسیر/منبع یافت نشد", status=404)

        try:
            payload = resp.json()
        except ValueError:
            # RouterOS may return plain text for some endpoints
            return resp.text

        # RouterOS REST returns list of objects
        if isinstance(payload, list):
            return payload
        return payload

    def health_check(self) -> dict:
        if not self.is_configured():
            return {"status": "NOT_CONFIGURED", "detail": None}
        started = time.monotonic()
        try:
            self._request("GET", "/system/resource")
        except VPNProviderError as exc:
            return {"status": "BLOCKED", "detail": _clean(exc)}
        return {"status": "OK", "latency_ms": round((time.monotonic() - started) * 1000)}

    def list_inbounds(self) -> list[dict]:
        """Get PPP profiles and WireGuard interfaces as 'inbounds'."""
        try:
            profiles = self._request("GET", "/ppp/profile")
            interfaces = self._request("GET", "/interface/wireguard")
            result = []
            for p in profiles if isinstance(profiles, list) else []:
                result.append({"id": p.get("name"), "name": p.get("name"), "type": "ppp_profile"})
            for i in interfaces if isinstance(interfaces, list) else []:
                result.append({"id": i.get("name"), "name": i.get("name"), "type": "wireguard"})
            return result
        except VPNProviderError:
            return []

    def _to_client_state(self, secret: dict, profile: str = "") -> ClientState:
        """Convert PPP secret to ClientState."""
        enable = not secret.get("disabled", "false") == "true"
        # Mikrotik doesn't have built-in expiry/traffic limits in PPP secrets
        # These would need to be stored in comments or external DB
        comment = secret.get("comment", "")
        expiry_ms = 0
        total_bytes = 0
        if comment:
            # Parse custom fields from comment: expiry=1234567890;limit=1073741824
            import re
            exp_match = re.search(r'expiry=(\d+)', comment)
            lim_match = re.search(r'limit=(\d+)', comment)
            if exp_match:
                expiry_ms = int(exp_match.group(1))
            if lim_match:
                total_bytes = int(lim_match.group(1))

        return ClientState(
            email=secret.get("name", ""),
            enable=enable,
            expiry_ms=expiry_ms,
            total_bytes=total_bytes,
            up_bytes=0,
            down_bytes=0,
            sub_id=secret.get(".id", "") or "",
            uuid="",
            inbound_ids=(profile,) if profile else (),
        )

    def get_traffic(self, email: str) -> Optional[ClientState]:
        try:
            secrets = self._request("GET", "/ppp/secret", params={"name": email})
            if isinstance(secrets, list) and secrets:
                return self._to_client_state(secrets[0], self.config.ppp_profile)
            return None
        except ProviderRejectedError as e:
            if e.status == 404:
                return None
            raise

    def get_client(self, email: str) -> Optional[ClientState]:
        return self.get_traffic(email)

    def create_client(self, spec: ClientSpec, inbound_ids: Sequence[int]) -> ClientState:
        # For Mikrotik, we create a PPP secret
        profile = self.config.ppp_profile
        if inbound_ids:
            profile = str(inbound_ids[0])

        # Build comment with expiry and limit
        comment_parts = []
        if spec.expiry_ms > 0:
            comment_parts.append(f"expiry={spec.expiry_ms}")
        if spec.total_bytes > 0:
            comment_parts.append(f"limit={spec.total_bytes}")
        if spec.comment:
            comment_parts.append(f"note={spec.comment}")

        secret_data = {
            "name": spec.email,
            "password": spec.client_uuid or str(_uuid.uuid4())[:16],
            "profile": profile,
            "service": "any",
            "comment": ";".join(comment_parts),
            "disabled": "false" if spec.enable else "true",
        }

        self._request("POST", "/ppp/secret", json_body=secret_data)

        created = self.get_client(spec.email)
        if created is None:
            raise ProviderUnavailableError("PPP secret پس از ساخت قابل تأیید نبود")
        return created

    def _find_secret(self, email: str) -> dict:
        secrets = self._request("GET", "/ppp/secret", params={"name": email})
        if isinstance(secrets, list) and secrets:
            return secrets[0]
        raise ProviderRejectedError("PPP secret یافت نشد", status=404)

    def _raw_record(self, email: str) -> dict:
        return self._find_secret(email)

    def update_client(self, email: str, **changes) -> ClientState:
        secret = self._find_secret(email)
        secret_id = secret.get(".id", "")

        update_data = {}
        mapping = {
            "enable": "disabled",
            "expiry_ms": "comment",
            "total_bytes": "comment",
            "limit_ip": "comment",  # Store in comment
            "comment": "comment",
        }

        current_comment = secret.get("comment", "")
        # Parse existing comment
        import re
        exp_match = re.search(r'expiry=(\d+)', current_comment)
        lim_match = re.search(r'limit=(\d+)', current_comment)
        note_match = re.search(r'note=([^;]+)', current_comment)

        expiry_val = exp_match.group(1) if exp_match else ""
        limit_val = lim_match.group(1) if lim_match else ""
        note_val = note_match.group(1) if note_match else ""

        for k, v in changes.items():
            if k not in mapping:
                raise ProviderRejectedError(f"فیلد قابل‌تغییر نیست: {k}")

            if k == "enable":
                update_data["disabled"] = "false" if v else "true"
            elif k == "expiry_ms":
                expiry_val = str(int(v)) if v > 0 else ""
            elif k == "total_bytes":
                limit_val = str(int(v)) if v > 0 else ""
            elif k == "comment":
                note_val = v

        # Rebuild comment
        comment_parts = []
        if expiry_val:
            comment_parts.append(f"expiry={expiry_val}")
        if limit_val:
            comment_parts.append(f"limit={limit_val}")
        if note_val:
            comment_parts.append(f"note={note_val}")
        update_data["comment"] = ";".join(comment_parts)

        self._request("PUT", f"/ppp/secret/{secret_id}", json_body=update_data)

        fresh = self.get_client(email)
        if fresh is None:
            raise ProviderUnavailableError("Secret پس از بروزرسانی قابل تأیید نبود")
        return fresh

    def delete_client(self, email: str) -> None:
        secret = self._find_secret(email)
        secret_id = secret.get(".id", "")
        self._request("DELETE", f"/ppp/secret/{secret_id}")

    def renew_client(self, email: str, *, new_expiry_ms: int, total_bytes: Optional[int] = None,
                     reset_traffic: bool = True) -> ClientState:
        changes: dict = {"expiry_ms": int(new_expiry_ms), "enable": True}
        if total_bytes is not None:
            changes["total_bytes"] = int(total_bytes)
        return self.update_client(email, **changes)

    def get_links(self, email: str) -> list[str]:
        # Mikrotik doesn't have subscription links in traditional sense
        # Could return PPP config or WireGuard config
        return []

    def get_subscription_url(self, sub_id: str) -> Optional[str]:
        return None

    def reset_traffic(self, email: str) -> None:
        # Mikrotik PPP doesn't have built-in traffic reset
        # Would need to use Radius accounting or external tracking
        pass

    def set_enabled(self, email: str, enabled: bool) -> ClientState:
        return self.update_client(email, enable=bool(enabled))


def build_default_provider() -> MikrotikProvider:
    return MikrotikProvider(MikrotikConfig.from_env())