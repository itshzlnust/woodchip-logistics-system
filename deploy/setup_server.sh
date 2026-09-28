#!/bin/bash
# =============================================================
# setup_server.sh — Script setup awal server (jalankan SEKALI)
# Jalankan langsung di server via SSH
#
# CARA PAKAI DI SERVER:
#   ssh -i ~/.ssh/id_rsa root@IP_SERVER
#   bash setup_server.sh
# =============================================================

set -e

APP_DIR="/opt/woodchip-app"
APP_USER="woodchip"

echo "=========================================="
echo " Setup Server: Sistem Logistik Woodchip"
echo "=========================================="

# 1. Update system
echo "📦 Update system packages..."
apt-get update -y && apt-get upgrade -y

# 2. Install dependencies sistem
echo "📦 Install Python, Nginx, Git..."
apt-get install -y python3 python3-pip python3-venv nginx git curl

# 3. Buat user khusus untuk aplikasi (lebih aman daripada root)
echo "👤 Buat user aplikasi: $APP_USER"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --no-create-home --shell /bin/false $APP_USER
    echo "   User '$APP_USER' berhasil dibuat."
else
    echo "   User '$APP_USER' sudah ada."
fi

# 4. Buat direktori aplikasi
echo "📁 Setup direktori aplikasi di $APP_DIR..."
mkdir -p $APP_DIR
mkdir -p $APP_DIR/uploads/{woodchip,weighing,payment,qr}
mkdir -p $APP_DIR/static

# 5. Clone dari GitHub (atau bisa pakai rsync dari lokal)
echo "📥 Clone repository dari GitHub..."
if [ -d "$APP_DIR/.git" ]; then
    echo "   Repo sudah ada, pull terbaru..."
    cd $APP_DIR && git pull origin main
else
    # Ganti URL dengan repo Anda
    git clone https://github.com/itshzlnust/woodchip-logistics-system.git $APP_DIR
fi

# 6. Setup Python virtual environment
echo "🐍 Setup Python virtual environment..."
cd $APP_DIR
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "   Dependencies terinstall."

# 7. Inisialisasi database
echo "🗄️  Inisialisasi database..."
python3 -c "from database import init_db; init_db(); print('   Database siap.')"

# 8. Set permission
echo "🔒 Set permission..."
chown -R $APP_USER:$APP_USER $APP_DIR
chmod -R 755 $APP_DIR
chmod -R 777 $APP_DIR/uploads  # uploads bisa ditulis

# 9. Install systemd service
echo "⚙️  Install systemd service..."
cat > /etc/systemd/system/woodchip.service << 'SERVICE'
[Unit]
Description=Woodchip Logistics System - FastAPI App
After=network.target

[Service]
Type=simple
User=woodchip
Group=woodchip
WorkingDirectory=/opt/woodchip-app
ExecStart=/opt/woodchip-app/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable woodchip
systemctl start woodchip
echo "   Service woodchip berjalan."

# 10. Konfigurasi Nginx
echo "🌐 Setup Nginx reverse proxy..."
cat > /etc/nginx/sites-available/woodchip << 'NGINX'
server {
    listen 80;
    server_name _;

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }

    location /uploads/ {
        alias /opt/woodchip-app/uploads/;
        expires 7d;
    }

    location /static/ {
        alias /opt/woodchip-app/static/;
        expires 30d;
    }
}
NGINX

# Aktifkan konfigurasi Nginx
ln -sf /etc/nginx/sites-available/woodchip /etc/nginx/sites-enabled/woodchip
rm -f /etc/nginx/sites-enabled/default  # Hapus default
nginx -t && systemctl restart nginx
echo "   Nginx aktif."

# 11. Setup firewall (UFW)
echo "🔥 Setup Firewall..."
ufw --force enable
ufw allow ssh
ufw allow http
ufw allow https
echo "   Firewall aktif (SSH, HTTP, HTTPS diizinkan)."

echo ""
echo "=========================================="
echo " ✅ SETUP SELESAI!"
echo "=========================================="
echo ""
echo " Akses aplikasi di: http://$(curl -s ifconfig.me)"
echo " Status service   : systemctl status woodchip"
echo " Log aplikasi     : journalctl -u woodchip -f"
echo ""
echo " LANGKAH SELANJUTNYA:"
echo " 1. Isi Master Data (pekerja, pemasok, tarif) lewat web"
echo " 2. (Opsional) Setup domain + SSL dengan: certbot --nginx"
echo "=========================================="
