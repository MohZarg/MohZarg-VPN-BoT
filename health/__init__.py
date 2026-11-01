"""
GhYiAb V2 — Health Check Server
===============================

FastAPI سرور کوچک برای health check در Docker و Railway.
این سرور روی پورت 8000 اجرا می‌شود و endpointهای زیر را فراهم می‌کند:
- GET /health — بررسی سلامت کلی سیستم
- GET /ready — بررسی آمادگی برای دریافت ترافیک
- GET /live — بررسی زنده بودن فرآیند (liveness probe)
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from bootstrap import build_app_context, AppContext
from security.secret_loader import BotSecrets, secrets as secret_provider


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str = "2.0.0"
    checks: dict


class ReadyResponse(BaseModel):
    ready: bool
    timestamp: str
    checks: dict


app_ctx: AppContext | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """مدیریت چرخه عمر اپلیکیشن."""
    global app_ctx
    from security.env_file import load_env_file
    from security.logging_setup import setup_logging

    load_env_file()
    setup_logging()

    bot_secrets = BotSecrets(secret_provider)
    app_ctx = build_app_context(bot_secrets)

    yield

    # Cleanup
    pass


app = FastAPI(
    title="GhYiAb V2 Health Check",
    description="Health check endpoints for Docker and Railway",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    بررسی جامع سلامت سیستم.
    شامل: دیتابیس، ردیس، تنظیمات، و سایر وابستگی‌ها.
    """
    if not app_ctx:
        raise HTTPException(status_code=503, detail="Application not initialized")

    checks = {}
    overall_status = "healthy"

    # چک دیتابیس
    try:
        with app_ctx.unit_of_work() as uow:
            uow.users.count_all()
        checks["database"] = {"status": "healthy", "message": "Connected"}
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "message": str(e)}
        overall_status = "unhealthy"

    # چک ردیس
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        r.ping()
        checks["redis"] = {"status": "healthy", "message": "Connected"}
    except Exception as e:
        checks["redis"] = {"status": "unhealthy", "message": str(e)}
        overall_status = "degraded"  # ردیس critical نیست

    # چک تنظیمات
    try:
        with app_ctx.unit_of_work() as uow:
            locked = app_ctx.settings.get("locked", "0")
        checks["settings"] = {"status": "healthy", "locked": locked == "1"}
    except Exception as e:
        checks["settings"] = {"status": "unhealthy", "message": str(e)}
        overall_status = "degraded"

    # چک توکن ربات
    try:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        checks["telegram_bot"] = {
            "status": "healthy" if bot_token else "unhealthy",
            "message": "Token configured" if bot_token else "Token missing"
        }
        if not bot_token:
            overall_status = "unhealthy"
    except Exception as e:
        checks["telegram_bot"] = {"status": "unhealthy", "message": str(e)}
        overall_status = "unhealthy"

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat() + "Z",
        checks=checks,
    )


@app.get("/ready", response_model=ReadyResponse)
async def readiness_check() -> ReadyResponse:
    """
    بررسی آمادگی برای دریافت ترافیک (Readiness Probe).
    فقط چک‌های حیاتی برای سرویس‌دهی.
    """
    if not app_ctx:
        return ReadyResponse(
            ready=False,
            timestamp=datetime.utcnow().isoformat() + "Z",
            checks={"app": {"status": "not_initialized"}}
        )

    checks = {}
    ready = True

    # دیتابیس باید در دسترس باشد
    try:
        with app_ctx.unit_of_work() as uow:
            uow.users.count_all()
        checks["database"] = {"status": "ready"}
    except Exception as e:
        checks["database"] = {"status": "not_ready", "error": str(e)}
        ready = False

    # توکن ربات باید تنظیم شده باشد
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    checks["telegram_bot"] = {"status": "ready" if bot_token else "not_ready"}
    if not bot_token:
        ready = False

    return ReadyResponse(
        ready=ready,
        timestamp=datetime.utcnow().isoformat() + "Z",
        checks=checks,
    )


@app.get("/live")
async def liveness_check() -> dict:
    """
    بررسی زنده بودن فرآیند (Liveness Probe).
    همیشه true برمی‌گرداند اگر فرآیند در حال اجراست.
    """
    return {
        "alive": True,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "pid": os.getpid(),
    }


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "service": "GhYiAb V2",
        "version": "2.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "ready": "/ready",
            "live": "/live",
        }
    }


def main() -> None:
    """اجرا به عنوان سرور مستقل (برای تست)."""
    import uvicorn
    port = int(os.getenv("HEALTH_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()