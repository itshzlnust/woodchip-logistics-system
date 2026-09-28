#!/bin/bash
# =============================================================
# deploy.sh — Script deploy otomatis ke server via SSH
# Jalankan dari komputer lokal (Windows Git Bash / WSL / Linux)
#
# CARA PAKAI:
#   chmod +x deploy/deploy.sh
#   ./deploy/deploy.sh
# =============================================================

set -e  # Berhenti jika ada error

# ─── KONFIGURASI — SESUAIKAN INI ─────────────────────────────
SERVER_IP="xxx.xxx.xxx.xxx"        # Ganti dengan IP server Anda
SERVER_USER="root"                  # Atau user sudo lainnya
SSH_KEY="~/.ssh/id_rsa"             # Path ke private key SSH Anda
APP_DIR="/opt/woodchip-app"         # Lokasi install di server
# ─────────────────────────────────────────────────────────────

echo "🚀 Mulai deploy ke server $SERVER_IP ..."

# Upload kode terbaru ke server
echo "📦 Upload file ke server..."
rsync -avz \
  --exclude='.git' \
  --exclude='*.db' \
  --exclude='uploads/' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='deploy/' \
  -e "ssh -i $SSH_KEY" \
  ./ $SERVER_USER@$SERVER_IP:$APP_DIR/

echo "⚙️  Setup di server..."
ssh -i $SSH_KEY $SERVER_USER@$SERVER_IP << EOF
  set -e

  # Install pip dependencies
  cd $APP_DIR
  source venv/bin/activate
  pip install -r requirements.txt --quiet

  # Inisialisasi database jika belum ada
  python -c "from database import init_db; init_db(); print('Database OK')"

  # Restart service
  sudo systemctl daemon-reload
  sudo systemctl restart woodchip
  sudo systemctl status woodchip --no-pager

  echo "✅ Deploy selesai!"
EOF
