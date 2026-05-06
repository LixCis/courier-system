#!/bin/sh
set -e

echo "[entrypoint] Waiting for database..."
python - <<'PY'
import time
import psycopg2
import os
from urllib.parse import urlparse

uri = os.environ.get("DATABASE_URI", "postgresql://courier:courier@db:5432/courier")
p = urlparse(uri)
for i in range(30):
    try:
        conn = psycopg2.connect(
            host=p.hostname, port=p.port or 5432,
            user=p.username, password=p.password,
            dbname=p.path.lstrip("/"),
        )
        conn.close()
        print("[entrypoint] DB reachable")
        break
    except Exception as e:
        print(f"[entrypoint] DB not ready yet ({e}), retrying...")
        time.sleep(1)
else:
    raise SystemExit("[entrypoint] DB never became reachable")
PY

echo "[entrypoint] Ensuring tables exist..."
python -c "
from app import app
from models import db, User
with app.app_context():
    db.create_all()
    if not User.query.first():
        print('[entrypoint] Empty DB detected — seeding sample data')
        import subprocess, sys
        subprocess.run([sys.executable, '-m', 'flask', 'seed-db'], check=False)
    else:
        print('[entrypoint] DB already has users, skipping seed')
"

echo "[entrypoint] Starting app..."
exec python app.py
