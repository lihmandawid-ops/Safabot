#!/usr/bin/env bash
# One-shot VPS installer for Safabot (Ubuntu 22.04/24.04).
#
# Usage (as root, or via sudo):
#   curl -fsSL <raw-url-to-this-file> | BOT_TOKEN='123456:ABC-your-token' bash
#
# Idempotent: safe to re-run (e.g. to pull a newer commit and restart the
# service) - it reuses the existing clone/venv/user instead of recreating
# them, and always ends by restarting the systemd service.
#
# Postgres-migration stage: a FRESH install (no existing .env) now
# provisions PostgreSQL by default instead of SQLite - pass
# DB_ENGINE=sqlite to opt back into the old behavior. An EXISTING
# install's .env (and therefore its DATABASE_URL) is never touched by a
# normal re-run - switching an already-running production bot from
# SQLite to PostgreSQL is a deliberate, separate operation (see
# deploy/backup_sqlite.py, deploy/migrate_to_postgres.py,
# deploy/verify_migration.py, and the "Migrating to PostgreSQL" section
# of README.md), never a side effect of pulling new code.
set -euo pipefail

REPO_URL="https://github.com/lihmandawid-ops/Safabot.git"
BRANCH="claude/safabot-telegram-bot-256prh"
APP_DIR="/opt/safabot/app"
ENV_FILE="$APP_DIR/.env"
FRESH_INSTALL=1
if [ -f "$ENV_FILE" ]; then
  FRESH_INSTALL=0
fi
DB_ENGINE="${DB_ENGINE:-postgres}"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run this as root (e.g. 'sudo -i' first, or pipe through 'sudo bash')." >&2
  exit 1
fi

if [ "$FRESH_INSTALL" -eq 1 ] && [ -z "${BOT_TOKEN:-}" ]; then
  echo "ERROR: BOT_TOKEN is not set." >&2
  echo "Usage: curl -fsSL <this-script-url> | BOT_TOKEN='123456:ABC...' bash" >&2
  exit 1
fi

echo "==> Installing system packages"
apt-get update -y
apt-get install -y git curl software-properties-common
if ! apt-cache show python3.12 >/dev/null 2>&1; then
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -y
fi
apt-get install -y python3.12 python3.12-venv python3.12-dev

if [ "$FRESH_INSTALL" -eq 1 ] && [ "$DB_ENGINE" = "postgres" ]; then
  echo "==> Installing and provisioning PostgreSQL"
  apt-get install -y postgresql
  systemctl enable --now postgresql
  DB_PASSWORD="${DB_PASSWORD:-$(openssl rand -hex 24)}"
  # Idempotent: safe if a previous run already created these (e.g. this
  # script was interrupted after this step but before the .env write).
  sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='safabot_app'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE ROLE safabot_app LOGIN PASSWORD '${DB_PASSWORD}';"
  sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='safabot'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE safabot OWNER safabot_app;"
  # NEVER the postgres superuser for the app - a compromised bot process
  # must not be able to touch roles/other databases on the same instance.
  DATABASE_URL_LINE="DATABASE_URL=postgresql+asyncpg://safabot_app:${DB_PASSWORD}@localhost:5432/safabot"
  echo "    PostgreSQL role 'safabot_app' / database 'safabot' ready."
elif [ "$FRESH_INSTALL" -eq 1 ]; then
  DATABASE_URL_LINE="DATABASE_URL=sqlite+aiosqlite:///./safabot.db"
fi

echo "==> Creating the safabot service user"
id -u safabot &>/dev/null || useradd -r -m -d /opt/safabot -s /bin/bash safabot

echo "==> Fetching the code"
mkdir -p /opt/safabot
if [ -d "$APP_DIR/.git" ]; then
  sudo -u safabot git -C "$APP_DIR" fetch origin
  sudo -u safabot git -C "$APP_DIR" checkout "$BRANCH"
  sudo -u safabot git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
  sudo -u safabot git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

echo "==> Installing Python dependencies"
cd "$APP_DIR"
sudo -u safabot python3.12 -m venv .venv
sudo -u safabot .venv/bin/pip install --upgrade pip -q
sudo -u safabot .venv/bin/pip install -r requirements.txt -q

if [ "$FRESH_INSTALL" -eq 0 ]; then
  echo "==> Existing install detected - .env and DATABASE_URL left untouched"
  if grep -q '^DATABASE_URL=sqlite' "$ENV_FILE" 2>/dev/null; then
    echo "    Still running on SQLite. To move this production install to PostgreSQL,"
    echo "    see the 'Migrating to PostgreSQL' section of README.md - do not do it by"
    echo "    re-running this script."
  fi
else
echo "==> Writing .env"
sudo -u safabot bash -c "cat > '$APP_DIR/.env'" <<ENVEOF
BOT_TOKEN=${BOT_TOKEN}
${DATABASE_URL_LINE}
LOG_LEVEL=INFO
DEFAULT_TIMEZONE=UTC
TRIAL_DAYS=7
DEFAULT_DAILY_NEW_WORDS=4
MAX_DAILY_REVIEWS=30
DEFAULT_MORNING_TIME=09:00
DEFAULT_AFTERNOON_TIME=14:00
DEFAULT_EVENING_TIME=20:00
AI_PROVIDER=none
AI_API_KEY=
AI_MODEL=deepseek-chat
AI_BASE_URL=
AI_ENABLED=true
OCR_API_KEY=
OCR_MODEL=gpt-4o-mini
OCR_BASE_URL=
OCR_ENABLED=true
STT_API_KEY=
STT_MODEL=whisper-1
STT_BASE_URL=
STT_ENABLED=true
ENVEOF
chmod 600 "$APP_DIR/.env"
chown safabot:safabot "$APP_DIR/.env"
fi

echo "==> Running database migrations"
sudo -u safabot "$APP_DIR/.venv/bin/alembic" upgrade head

echo "==> Installing the systemd service"
cat > /etc/systemd/system/safabot.service <<UNITEOF
[Unit]
Description=Safabot Telegram Bot
After=network.target

[Service]
Type=simple
User=safabot
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python ${APP_DIR}/bot.py
Restart=on-failure
RestartSec=5
EnvironmentFile=${APP_DIR}/.env

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable safabot
systemctl restart safabot
sleep 2

echo "==> Done. Service status:"
systemctl status safabot --no-pager

if [ "$FRESH_INSTALL" -eq 1 ] && [ "$DB_ENGINE" = "postgres" ]; then
  echo
  echo "PostgreSQL is now the production database (role: safabot_app, database: safabot)."
  echo "The generated password is saved in ${ENV_FILE} (chmod 600, safabot:safabot only)."
fi
