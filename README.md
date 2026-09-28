# Sistem Logistik Woodchip — Aplikasi Pencatatan & Upah Pekerja PLTU

Sistem pencatatan barang masuk woodchip, pengiriman ke PLTU, dan perhitungan upah pekerja berbasis QR Barcode Scanner.

## Fitur Utama

- 📷 **QR Scanner berbasis kamera browser** — driver scan langsung dari HP
- 🚚 **Surat Jalan digital** dengan QR code unik per pengiriman
- ⚖️ **Timbangan Workshop & PLTU** — selisih Netto jadi dasar upah
- 💰 **Kalkulasi upah otomatis** — Pemotong Kayu, Driver, Operator, Pemasok
- 🏪 **Barang masuk dari Pemasok** — timbang, hitung ton, catat rekening bank
- 📊 **Dashboard KPI** real-time
- 🖨️ **Cetak Surat Jalan & Slip Upah**

## Cara Menjalankan (Lokal / Windows)

```bash
# Install dependencies
pip install -r requirements.txt

# Jalankan aplikasi
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Buka browser
http://localhost:8000
```

Atau klik ganda `run.bat` untuk Windows.

## Deploy ke Server Linux (Production)

Lihat panduan lengkap di folder `deploy/`:

```
deploy/
├── setup_server.sh   # Setup awal server (jalankan sekali)
├── deploy.sh         # Deploy update kode terbaru
├── woodchip.service  # Systemd service config
└── nginx.conf        # Nginx reverse proxy config
```

### Setup Awal Server

```bash
# 1. SSH ke server
ssh -i ~/.ssh/id_rsa root@IP_SERVER

# 2. Download & jalankan script setup
curl -O https://raw.githubusercontent.com/itshzlnust/woodchip-logistics-system/main/deploy/setup_server.sh
bash setup_server.sh
```

### Deploy Update

```bash
# Dari komputer lokal, jalankan:
bash deploy/deploy.sh
```

## Stack Teknologi

| Komponen | Teknologi |
|---|---|
| Backend | FastAPI (Python) |
| Database | SQLite |
| Frontend | Jinja2 Templates + Tailwind CSS |
| QR Scanner | HTML5-QRCode (browser-based) |
| Server | Uvicorn + Nginx |
| Process Manager | Systemd |

## Struktur Roles & Upah

Upah dihitung berdasarkan **berat NETTO TON di PLTU** × tarif per ton:

| Role | Tarif Acuan |
|---|---|
| Pemotong Kayu | Rp / TON (bisa dibagi rata jika >1 orang) |
| Driver Truk | Rp / TON |
| Operator Mesin | Rp / TON |
| Pemasok Kayu | Rp / TON (pembayaran pembelian kayu) |

Tarif dapat disesuaikan lewat menu **Master Data → Pengaturan Tarif**.
