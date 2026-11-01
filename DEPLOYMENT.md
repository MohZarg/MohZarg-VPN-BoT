# GhYiAb V2 — Deployment Guide

> **توسعه‌دهنده:** [MohZarg](https://github.com/MohZarg) | **حمایت مالی:** [https://github.com/MohZarg](https://github.com/MohZarg)

## Overview

GhYiAb V2 is a Telegram bot for selling VPN services with support for multiple VPN providers, payment gateways, and a Telegram Mini App.

## Architecture

- **Bot**: Main Telegram bot handler (Python, python-telegram-bot)
- **Worker**: Background jobs (APScheduler)
- **Health**: Health check server (FastAPI)
- **Mini App**: Telegram Web App frontend (React, TypeScript, Vite)
- **Database**: PostgreSQL (production) / MySQL (Railway) / SQLite (dev)
- **Redis**: Caching and sessions
- **Adminer**: Database management UI

## Quick Start (Docker Compose)

### 1. Prerequisites

- Docker & Docker Compose
- Telegram Bot Token (from @BotFather)
- Telegram Owner ID (your user ID)

### 2. Configuration

```bash
cp .env.example .env
# Edit .env with your values
```

Required variables:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_OWNER_ID`
- `DATABASE_URL`
- `REDIS_URL`
- `XUI_BASE_URL`, `XUI_USERNAME`, `XUI_PASSWORD` (for VPN)

### 3. Start Services

```bash
cd deploy
docker-compose up -d
```

Services:
- Bot: Runs in background
- Worker: Background jobs
- Health: http://localhost:8000/health
- Adminer: http://localhost:8080
- Mini App: http://localhost:3000

### 4. View Logs

```bash
docker-compose logs -f bot
docker-compose logs -f worker
```

## Railway Deployment

### 1. Connect Repository

1. Go to [Railway](https://railway.app)
2. Create new project from GitHub repo
3. Select the `ghyiab_v2` folder

### 2. Add Services

Railway will auto-detect `railway.json` and create:
- **bot**: Main bot service
- **worker**: Background jobs
- **health**: Health checks

### 3. Add Databases

Add these plugins:
- **PostgreSQL** (or MySQL)
- **Redis**

### 4. Configure Variables

In Railway dashboard, add all variables from `.env.example`

Required:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_OWNER_ID`
- `DATABASE_URL` (auto-provided by Railway)
- `REDIS_URL` (auto-provided by Railway)
- `XUI_BASE_URL`, `XUI_USERNAME`, `XUI_PASSWORD`

### 5. Deploy

Railway will build and deploy automatically.

## Database Migrations

### Run Migrations

```bash
# Using Docker
docker-compose run --rm bot migrate

# Or locally
DATABASE_URL=postgresql://... python -m alembic upgrade head
```

### Create New Migration

```bash
# After model changes
python -m alembic revision --autogenerate -m "description"
python -m alembic upgrade head
```

## Services Detail

### Bot (`python -m bot`)

Main Telegram bot with:
- User management
- Product catalog
- Orders & payments
- Wallet system
- Referral program
- Admin panel

### Worker (`python -m worker`)

Background jobs:
- Panel health checks (every 5 min)
- Auto-renew services (daily 2 AM)
- Process pending payments (every 10 min)
- Sync provisioned clients (every 15 min)
- Check crypto invoices (every 5 min)
- Send expiry notifications (daily 10 AM)
- Backup database (weekly)
- Cleanup old logs (weekly)

### Health (`python -m health`)

FastAPI endpoints:
- `GET /health` - Full health check
- `GET /ready` - Readiness probe
- `GET /live` - Liveness probe

### Mini App (`npm run build` → Nginx)

React SPA served by Nginx:
- Home page
- Services listing
- Purchase flow
- Wallet recharge
- Profile & settings
- Payment gateway selection

## VPN Providers Supported

1. **X-UI / 3x-ui** (default)
2. **Marzban**
3. **Hiddify**
4. **WGDashboard**
5. **Marzneshin**
6. **Mikrotik RouterOS**
7. **Alireza**
8. **S-UI (Sanaei UI)**
9. **Guard**
10. **Manualsale**
11. **IBSng**

## Payment Gateways

### Iranian Gateways
- Zarinpal
- IDPay
- Zibal
- NextPay
- Aqayepardakht
- PayPing

### Crypto
- TON (via tonapi.io)
- TRX/TRC20 (via Tronscan)
- USDT (ERC20/TRC20)

### Manual
- Card-to-Card (admin approval)

## Environment Variables Reference

See `.env.example` for all available variables.

## Monitoring

### Health Checks

```bash
# Full health
curl http://localhost:8000/health

# Readiness (for load balancer)
curl http://localhost:8000/ready

# Liveness (for container orchestration)
curl http://localhost:8000/live
```

### Logs

Structured logging with structlog. Logs include:
- Request/response logging
- Error tracking
- Audit trail
- Performance metrics

## Backup & Restore

### Automated Backup

Worker runs backup job weekly (Sunday 3 AM):
- SQLite: File copy
- PostgreSQL: pg_dump
- MySQL: mysqldump

### Manual Backup

```bash
# PostgreSQL
docker-compose exec postgres pg_dump -U ghyiab ghyiab > backup.sql

# MySQL
docker-compose exec mysql mysqldump -u ghyiab -p ghyiab > backup.sql
```

### Restore

```bash
# PostgreSQL
docker-compose exec -T postgres psql -U ghyiab ghyiab < backup.sql

# MySQL
docker-compose exec -T mysql mysql -u ghyiab -p ghyiab < backup.sql
```

## Scaling

### Horizontal Scaling

- **Bot**: Multiple replicas (use Redis for session state)
- **Worker**: Single instance (jobs use distributed locks)
- **Health**: Multiple replicas behind load balancer
- **Mini App**: Static files, CDN recommended

### Database

- PostgreSQL: Read replicas for scaling reads
- Connection pooling: PgBouncer

## Troubleshooting

### Bot Not Starting

1. Check `TELEGRAM_BOT_TOKEN` is valid
2. Check database connection
3. Check logs: `docker-compose logs bot`

### Worker Jobs Not Running

1. Check worker logs
2. Verify `scheduled_jobs` table has enabled jobs
3. Check APScheduler is running

### Database Connection Issues

1. Verify `DATABASE_URL` format
2. Check database is healthy: `docker-compose ps`
3. Check firewall/network

### Mini App Not Loading

1. Check build completed: `docker-compose logs mini-app`
2. Verify `VITE_API_URL` points to bot
3. Check nginx config

## Security

- All secrets in environment variables (never in code)
- Non-root user in containers
- Read-only filesystem where possible
- Health checks for orchestration
- Rate limiting on bot
- Input validation on all endpoints

## License

MIT License