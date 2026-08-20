#!/usr/bin/env bash
# One-shot VPS installer for Safabot (Ubuntu 22.04/24.04).
#
# Usage (as root, or via sudo):
#   curl -fsSL <raw-url-to-this-file> | BOT_TOKEN='123456:ABC-your-token' bash
#
# Idempotent: safe to re-run (e.g. to pull a newer commit and restart the
# service) - it reuses the existing clone/venv/user instead of recreating
# them, and always ends by restarting the systemd service.
set -euo pipefail

REPO_URL="https://github.com/lihmandawid-ops/Safabot.git"
BRANCH="claude/safabot-telegram-bot-256prh"
APP_DIR="/opt/safabot/app"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run this as root (e.g. 'sudo -i' first, or pipe through 'sudo bash')." >&2
  exit 1
fi

if [ -z "${BOT_TOKEN:-}" ]; then
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

echo "==> Writing .env"
sudo -u safabot bash -c "cat > '$APP_DIR/.env'" <<ENVEOF
BOT_TOKEN=${BOT_TOKEN}
DATABASE_URL=sqlite+aiosqlite:///./safabot.db
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
OCR_API_KEY=
ENVEOF
chmod 600 "$APP_DIR/.env"
chown safabot:safabot "$APP_DIR/.env"

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
