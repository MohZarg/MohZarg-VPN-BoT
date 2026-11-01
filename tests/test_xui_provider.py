import os

import pytest

from providers.vpn.base import (
    ClientSpec, NotConfiguredError, ProviderAuthError, ProviderRejectedError, ProviderUnavailableError,
)
from providers.vpn.xui.provider import ThreeXUIProvider, XuiConfig
from tests.fake_xui import FakeXui

GB = 1024 ** 3


@pytest.fixture
def xui():
    s = FakeXui(token="tok-123").start()
    yield s
    s.stop()


def mk(xui, **kw):
    cfg = XuiConfig(base_url=xui.url, api_token=kw.pop("token", "tok-123"), timeout=2,
                    sub_url_base=kw.pop("sub", ""), max_retries=kw.pop("retries", 2), verify_tls=True)
    return ThreeXUIProvider(cfg, sleep=lambda s: None)


def spec(email="gy1"):
    return ClientSpec(email=email, sub_id="sub1", total_bytes=10 * GB, expiry_ms=1_900_000_000_000)


# ---- mode: NOT_CONFIGURED ----
def test_not_configured_never_fakes_success():
    p = ThreeXUIProvider(XuiConfig())
    assert not p.is_configured()
    assert p.health_check()["status"] == "NOT_CONFIGURED"
    with pytest.raises(NotConfiguredError):
        p.create_client(spec(), [1])
    with pytest.raises(NotConfiguredError):
        p.get_traffic("x")


def test_env_new_and_legacy_names(monkeypatch):
    for k in ("XUI_BASE_URL", "XUI_PANEL_URL", "XUI_API_TOKEN", "XUI_TIMEOUT", "XUI_PANEL_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    assert not XuiConfig.from_env().is_configured
    monkeypatch.setenv("XUI_PANEL_URL", "https://old.example/x/")
    monkeypatch.setenv("XUI_API_TOKEN", "t")
    c = XuiConfig.from_env()
    assert c.is_configured and c.base_url == "https://old.example/x"
    monkeypatch.setenv("XUI_BASE_URL", "https://new.example")
    monkeypatch.setenv("XUI_TIMEOUT", "7")
    monkeypatch.setenv("XUI_VERIFY_TLS", "0")
    c = XuiConfig.from_env()
    assert c.base_url == "https://new.example" and c.timeout == 7 and c.verify_tls is False
    assert XuiConfig().verify_tls is True  # TLS verification on by default


def test_token_never_in_repr_or_errors(xui):
    p = mk(xui, token="WRONG-SECRET")
    assert "WRONG-SECRET" not in repr(p.config)
    with pytest.raises(ProviderAuthError) as ei:
        p.list_inbounds()
    assert "WRONG-SECRET" not in str(ei.value)


# ---- mode: configured (same-server = localhost URL; remote = other host/path, config only) ----
def test_health_and_inbounds(xui):
    p = mk(xui)
    h = p.health_check()
    assert h["status"] == "OK" and "latency_ms" in h
    assert p.list_inbounds()[0]["id"] == 1


def test_secret_base_path_supported():
    s = FakeXui(token="t", base_path="/secretpath").start()
    try:
        p = ThreeXUIProvider(XuiConfig(base_url=s.url, api_token="t", timeout=2))
        assert p.health_check()["status"] == "OK"
    finally:
        s.stop()


def test_create_get_update_delete_roundtrip(xui):
    p = mk(xui)
    assert p.get_client("gy1") is None  # obj=null → None, not error
    st = p.create_client(spec(), [1])
    assert st.email == "gy1" and st.total_bytes == 10 * GB and st.enable
    xui.use("gy1", up=GB, down=2 * GB)
    t = p.get_traffic("gy1")
    assert t.used_bytes == 3 * GB and t.remaining_bytes == 7 * GB
    assert p.set_enabled("gy1", False).enable is False
    assert p.set_enabled("gy1", True).enable is True
    p.delete_client("gy1")
    assert p.get_client("gy1") is None


def test_update_preserves_untouched_fields(xui):
    p = mk(xui)
    p.create_client(spec(), [1])
    xui.clients["gy1"]["flow"] = "xtls-rprx-vision"
    p.update_client("gy1", comment="x")
    assert xui.clients["gy1"]["flow"] == "xtls-rprx-vision"
    assert xui.clients["gy1"]["totalGB"] == 10 * GB


def test_renew_is_absolute_and_resets_traffic(xui):
    p = mk(xui)
    p.create_client(spec(), [1])
    xui.use("gy1", up=GB, down=GB)
    new_exp = 2_000_000_000_000
    for _ in range(2):  # idempotent: repeating gives identical state
        st = p.renew_client("gy1", new_expiry_ms=new_exp, total_bytes=20 * GB)
        assert st.expiry_ms == new_exp and st.total_bytes == 20 * GB and st.used_bytes == 0


def test_links_and_subscription(xui):
    p = mk(xui, sub="https://sub.example:2096/sub/")
    p.create_client(spec(), [1])
    assert p.get_links("gy1")[0].startswith("vless://")
    assert p.get_subscription_url("sub1") == "https://sub.example:2096/sub/sub1"
    assert mk(xui).get_subscription_url("sub1") is None  # never guessed


# ---- mode: unavailable / failing ----
def test_unavailable_raises_not_success(xui):
    p = mk(xui, retries=1)
    xui.down = True
    assert p.health_check()["status"] == "BLOCKED"
    with pytest.raises(ProviderUnavailableError):
        p.get_traffic("gy1")


def test_get_retries_then_succeeds(xui):
    p = mk(xui, retries=2)
    xui.fail_next = 2
    assert p.health_check()["status"] == "OK"


def test_post_is_never_auto_retried(xui):
    p = mk(xui, retries=3)
    xui.fail_next = 1
    before = len(xui.requests)
    with pytest.raises(ProviderUnavailableError):
        p.delete_client("gy1")
    assert len(xui.requests) - before == 1


def test_circuit_breaker_stops_hammering_dead_panel(xui):
    p = mk(xui, retries=0)
    xui.down = True
    for _ in range(3):
        with pytest.raises(ProviderUnavailableError):
            p.get_traffic("a")
    n = len(xui.requests)
    with pytest.raises(ProviderUnavailableError):
        p.get_traffic("a")
    assert len(xui.requests) == n  # short-circuited, no new request


def test_unreachable_host_is_unavailable():
    p = ThreeXUIProvider(XuiConfig(base_url="http://127.0.0.1:1", api_token="t", timeout=1, max_retries=0))
    with pytest.raises(ProviderUnavailableError):
        p.list_inbounds()
    assert p.health_check()["status"] == "BLOCKED"


def test_panel_rejection_and_lying_panel(xui):
    p = mk(xui)
    xui.reject_writes = True
    with pytest.raises(ProviderRejectedError):
        p.create_client(spec(), [1])
    xui.reject_writes = False
    xui.drop_writes = True  # panel says success but nothing was created → we must NOT claim success
    with pytest.raises(ProviderUnavailableError):
        p.create_client(spec("gy9"), [1])


# ---- mode: remote server over HTTPS (TLS verification default ON) ----
@pytest.fixture
def tls_pair(tmp_path):
    import shutil
    import subprocess
    openssl = shutil.which("openssl")
    if openssl is None and os.name == "nt":
        # Git for Windows ships openssl but does not always put it on PATH.
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramW6432", r"C:\Program Files")):
            cand = os.path.join(base, "Git", "usr", "bin", "openssl.exe")
            if os.path.isfile(cand):
                openssl = cand
                break
    if openssl is None:
        pytest.skip("openssl binary not available to generate a test certificate")
    cert, key = str(tmp_path / "c.pem"), str(tmp_path / "k.pem")
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert,
                    "-days", "1", "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
                   check=True, capture_output=True)
    return cert, key


def test_remote_https_verifies_tls_by_default_and_works_with_trusted_ca(tls_pair):
    cert, key = tls_pair
    s = FakeXui(token="t", base_path="/p", tls=(cert, key)).start()
    try:
        # پیش‌فرض: گواهی ناشناس رد می‌شود (امن) → BLOCKED، نه موفقیت
        p = ThreeXUIProvider(XuiConfig(base_url=s.url, api_token="t", timeout=2, max_retries=0))
        assert p.health_check()["status"] == "BLOCKED"
        # فقط با غیرفعال‌سازی صریح (یا CA معتبر) کار می‌کند
        p2 = ThreeXUIProvider(XuiConfig(base_url=s.url, api_token="t", timeout=2, verify_tls=False))
        assert p2.health_check()["status"] == "OK"
        # CA سفارشی (گواهی همان سرور) → verify=True با bundle
        import requests
        sess = requests.Session()
        sess.verify = cert  # نقطهٔ تزریق تست؛ تولید از CA سیستم استفاده می‌کند
        p3 = ThreeXUIProvider(XuiConfig(base_url=s.url, api_token="t", timeout=2, verify_tls=True), session=sess)
        # provider verify=True را صریحاً پاس می‌دهد؛ با env REQUESTS_CA_BUNDLE معادل است:
        import os
        os.environ["REQUESTS_CA_BUNDLE"] = cert
        try:
            assert p3.health_check()["status"] == "OK"
        finally:
            os.environ.pop("REQUESTS_CA_BUNDLE", None)
    finally:
        s.stop()


def test_remote_wrong_token_is_auth_error_not_unavailable():
    s = FakeXui(token="right").start()
    try:
        p = ThreeXUIProvider(XuiConfig(base_url=s.url, api_token="wrong", timeout=2))
        with pytest.raises(ProviderAuthError):
            p.list_inbounds()
        assert p.health_check()["status"] == "BLOCKED"
    finally:
        s.stop()
