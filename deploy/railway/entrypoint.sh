#!/bin/bash
# GhYiAb V2 — Railway Entrypoint Script
# This script handles different service modes: bot, worker, health, migrate

set -e

# Wait for database to be ready
wait_for_db() {
    local db_url="$1"
    local max_attempts=30
    local attempt=1

    echo "Waiting for database at $db_url..."

    while [ $attempt -le $max_attempts ]; do
        if python -c "
import os
import sys
db_url = os.getenv('DATABASE_URL', '$db_url')
try:
    if db_url.startswith('postgresql'):
        import psycopg2
        conn = psycopg2.connect(db_url)
        conn.close()
    elif db_url.startswith('mysql'):
        import pymysql
        # Parse MySQL URL
        # mysql://user:pass@host:port/db
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        conn = pymysql.connect(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip('/')
        )
        conn.close()
    print('Database connection successful')
    sys.exit(0)
except Exception as e:
    print(f'Database connection failed: {e}')
    sys.exit(1)
"; then
            echo "Database is ready!"
            return 0
        fi

        echo "Attempt $attempt/$max_attempts: Database not ready, waiting..."
        sleep 2
        attempt=$((attempt + 1))
    done

    echo "ERROR: Database did not become ready in time"
    return 1
}

# Run database migrations
run_migrations() {
    echo "Running database migrations..."
    python -m alembic upgrade head
    echo "Migrations completed!"
}

# Main entrypoint logic
case "${SERVICE_MODE:-bot}" in
    bot)
        echo "Starting GhYiAb V2 Bot..."
        wait_for_db "${DATABASE_URL}"
        run_migrations
        exec python -m bot
        ;;

    worker)
        echo "Starting GhYiAb V2 Worker..."
        wait_for_db "${DATABASE_URL}"
        run_migrations
        exec python -m worker
        ;;

    health)
        echo "Starting Health Check Server..."
        wait_for_db "${DATABASE_URL}"
        exec python -m health
        ;;

    migrate)
        echo "Running migrations only..."
        wait_for_db "${DATABASE_URL}"
        run_migrations
        echo "Migrations completed successfully!"
        ;;

    *)
        echo "ERROR: Unknown SERVICE_MODE: ${SERVICE_MODE}"
        echo "Valid modes: bot, worker, health, migrate"
        exit 1
        ;;
esac