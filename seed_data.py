import os
import json
import qrcode
from datetime import datetime, timedelta
from database import get_db, init_db, calculate_wages_for_shipment, DB_DIR

def generate_qr_image(data_text: str, filename: str) -> str:
    qr_dir = os.path.join(DB_DIR, "uploads", "qr")
    os.makedirs(qr_dir, exist_ok=True)
    file_path = os.path.join(qr_dir, filename)
    
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=3,
    )
    qr.add_data(data_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(file_path)
    return f"/uploads/qr/{filename}"

def seed():
    init_db()
    conn = get_db()
    cursor = conn.cursor()

    # 1. Master Rates
    rates = [
        ("rate_cutter_per_ton", "Upah Pemotong Kayu", 25000, "Rp / TON", "Upah untuk tenaga kerja pemotong kayu log per tonase PLTU"),
        ("rate_driver_per_ton", "Upah Supir / Driver", 40000, "Rp / TON", "Upah supir pengantar truk woodchip per tonase PLTU"),
        ("rate_operator_per_ton", "Upah Operator Mesin", 20000, "Rp / TON", "Upah operator mesin chipper / excavator per tonase PLTU"),
        ("rate_wood_purchase_per_ton", "Harga Beli Kayu Pemasok", 350000, "Rp / TON", "Harga pembelian bahan baku kayu log dari pemasok ke workshop")
    ]
    for r in rates:
        cursor.execute("""
            INSERT OR IGNORE INTO settings_rates (rate_key, rate_name, rate_value, unit, description)
            VALUES (?, ?, ?, ?, ?)
        """, r)

    # 2. Master Workers
    workers = [
        ("Budi Santoso", "driver", "0812-3456-7890", "BCA", "1234567890", "Budi Santoso"),
        ("Ahmad Fauzi", "driver", "0813-9876-5432", "BRI", "0021-01-089765-50-1", "Ahmad Fauzi"),
        ("Joko Prasetyo", "driver", "0821-4567-8901", "Mandiri", "1370018928374", "Joko Prasetyo"),
        ("Slamet Riyadi", "pemotong", "0852-1122-3344", "BRI", "0021-01-034521-50-8", "Slamet Riyadi"),
        ("Wahyudi", "pemotong", "0853-2233-4455", "BNI", "0847291847", "Wahyudi"),
        ("Hendra Setiawan", "pemotong", "0877-3344-5566", "BCA", "4567891230", "Hendra Setiawan"),
        ("Rudi Hartono", "operator", "0819-4455-6677", "Mandiri", "1370029384756", "Rudi Hartono"),
        ("Eko Supriyanto", "operator", "0812-5566-7788", "BCA", "7890123456", "Eko Supriyanto")
    ]
    for w in workers:
        cursor.execute("SELECT id FROM workers WHERE name = ? AND role = ?", (w[0], w[1]))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO workers (name, role, phone, bank_name, account_number, account_holder)
                VALUES (?, ?, ?, ?, ?, ?)
            """, w)

    # 3. Master Suppliers
    suppliers = [
        ("CV Rimba Abadi (Pak Gunawan)", "0811-2233-445", "Jl. Raya Hutan KM 14, Riau", "Mandiri", "1080017263541", "Gunawan Wibisono"),
        ("Koperasi Tani Kayu Sejahtera", "0812-9988-776", "Desa Sukamaju Blok B", "BRI", "0142-01-002948-53-9", "Kop Tani Sejahtera"),
        ("UD Sumber Berkah (H. Mulyadi)", "0822-7766-554", "Jl. Lintas Timur KM 32", "BCA", "8291039482", "Mulyadi")
    ]
    for s in suppliers:
        cursor.execute("SELECT id FROM suppliers WHERE name = ?", (s[0],))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO suppliers (name, phone, address, bank_name, account_number, account_holder)
                VALUES (?, ?, ?, ?, ?, ?)
            """, s)

    conn.commit()

    # 4. Contoh Inbound Supplier Transaksi
    cursor.execute("SELECT id, name, bank_name, account_number, account_holder FROM suppliers LIMIT 2")
    sup_list = cursor.fetchall()

    if sup_list:
        # Transaksi 1: Sudah Lunas
        tx1_code = "INB-20260917-001"
        cursor.execute("SELECT id FROM inbound_supplier WHERE transaction_code = ?", (tx1_code,))
        if not cursor.fetchone():
            s1 = sup_list[0]
            gross = 16800.0
            tare = 7200.0
            net_kg = gross - tare
            net_ton = round(net_kg / 1000.0, 3)
            price_ton = 350000.0
            total_amt = round(net_ton * price_ton, 2)
            qr_file = generate_qr_image(tx1_code, f"{tx1_code}.png")

            cursor.execute("""
                INSERT INTO inbound_supplier (
                    transaction_code, supplier_id, supplier_name, truck_plate, driver_name,
                    material_type, gross_weight_kg, tare_weight_kg, net_weight_kg, net_ton,
                    price_per_ton, total_amount, bank_name, account_number, account_holder,
                    qr_code_path, payment_status, payment_date, payment_reference, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PAID', ?, ?, ?)
            """, (
                tx1_code, s1["id"], s1["name"], "BM 8124 TA", "Surono",
                "Kayu Log Akasia", gross, tare, net_kg, net_ton,
                price_ton, total_amt, s1["bank_name"], s1["account_number"], s1["account_holder"],
                qr_file, "2026-09-17 14:30:00", "TRF-MDR-99281726", "Pengiriman kayu gelondong kering siap chip"
            ))

        # Transaksi 2: Pending Pembayaran (Menunggu transfer manual kasir)
        tx2_code = "INB-20260918-002"
        cursor.execute("SELECT id FROM inbound_supplier WHERE transaction_code = ?", (tx2_code,))
        if not cursor.fetchone():
            s2 = sup_list[1]
            gross = 19400.0
            tare = 7500.0
            net_kg = gross - tare
            net_ton = round(net_kg / 1000.0, 3)
            price_ton = 350000.0
            total_amt = round(net_ton * price_ton, 2)
            qr_file = generate_qr_image(tx2_code, f"{tx2_code}.png")

            cursor.execute("""
                INSERT INTO inbound_supplier (
                    transaction_code, supplier_id, supplier_name, truck_plate, driver_name,
                    material_type, gross_weight_kg, tare_weight_kg, net_weight_kg, net_ton,
                    price_per_ton, total_amount, bank_name, account_number, account_holder,
                    qr_code_path, payment_status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            """, (
                tx2_code, s2["id"], s2["name"], "BM 9043 QK", "Kurniawan",
                "Kayu Log Sengon Campur", gross, tare, net_kg, net_ton,
                price_ton, total_amt, s2["bank_name"], s2["account_number"], s2["account_holder"],
                qr_file, "Masuk pagi jam 09:15, rekening sudah diverifikasi siap bayar"
            ))

    # 5. Contoh Surat Jalan Pengiriman ke PLTU (Shipments)
    cursor.execute("SELECT id, name FROM workers WHERE role = 'driver' LIMIT 2")
    drivers = cursor.fetchall()
    cursor.execute("SELECT id, name FROM workers WHERE role = 'pemotong' LIMIT 2")
    cutters = cursor.fetchall()
    cursor.execute("SELECT id, name FROM workers WHERE role = 'operator' LIMIT 1")
    operators = cursor.fetchall()

    if drivers and cutters and operators:
        # Shipment 1: SUDAH SAMPAI DI PLTU & DIHITUNG UPAH
        sj1_code = "SJ-PLTU-20260918-001"
        cursor.execute("SELECT id FROM shipments WHERE shipment_code = ?", (sj1_code,))
        existing_sj1 = cursor.fetchone()
        if not existing_sj1:
            qr1_path = generate_qr_image(sj1_code, f"{sj1_code}.png")
            c_ids = [c["id"] for c in cutters]
            c_names = ", ".join([c["name"] for c in cutters])
            op_ids = [operators[0]["id"]]
            op_names = operators[0]["name"]

            cursor.execute("""
                INSERT INTO shipments (
                    shipment_code, qr_token, qr_code_path,
                    driver_id, driver_name, truck_plate, destination_pltu,
                    cutter_worker_ids, cutter_names, operator_worker_ids, operator_names,
                    supplier_id, supplier_name, status,
                    departure_time, departure_gross_kg, departure_tare_kg, departure_net_kg, departure_net_ton,
                    pltu_arrival_time, pltu_gross_kg, pltu_tare_kg, pltu_net_kg, pltu_net_ton,
                    pltu_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ARRIVED_PLTU', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sj1_code, sj1_code, qr1_path,
                drivers[0]["id"], drivers[0]["name"], "BA 8821 QU", "PLTU Tenayan Raya 2x110MW",
                json.dumps(c_ids), c_names, json.dumps(op_ids), op_names,
                sup_list[0]["id"] if sup_list else None, sup_list[0]["name"] if sup_list else None,
                "2026-09-18 08:30:00", 22500, 8500, 14000, 14.0,
                "2026-09-18 11:45:00", 22420, 8500, 13920, 13.92,
                "Diterima di timbangan PLTU Hopper #2, kondisi woodchip kadar air standar 38%"
            ))
            sj1_id = cursor.lastrowid
            conn.commit()
            calculate_wages_for_shipment(sj1_id)

        # Shipment 2: SEDANG DALAM PERJALANAN (IN_TRANSIT)
        sj2_code = "SJ-PLTU-20260918-002"
        cursor.execute("SELECT id FROM shipments WHERE shipment_code = ?", (sj2_code,))
        if not cursor.fetchone():
            qr2_path = generate_qr_image(sj2_code, f"{sj2_code}.png")
            c_ids = [cutters[0]["id"]]
            c_names = cutters[0]["name"]
            op_ids = [operators[0]["id"]]
            op_names = operators[0]["name"]

            cursor.execute("""
                INSERT INTO shipments (
                    shipment_code, qr_token, qr_code_path,
                    driver_id, driver_name, truck_plate, destination_pltu,
                    cutter_worker_ids, cutter_names, operator_worker_ids, operator_names,
                    status, departure_time, departure_gross_kg, departure_tare_kg, departure_net_kg, departure_net_ton,
                    departure_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'IN_TRANSIT', ?, ?, ?, ?, ?, ?)
            """, (
                sj2_code, sj2_code, qr2_path,
                drivers[1]["id"], drivers[1]["name"], "BK 9102 XY", "PLTU Teluk Sirih 2x112MW",
                json.dumps(c_ids), c_names, json.dumps(op_ids), op_names,
                "2026-09-18 13:10:00", 21800, 8400, 13400, 13.4,
                "Driver telah scan barcode & melampirkan foto woodchip di bak truk sebelum berangkat."
            ))

        # Shipment 3: DRAFT (BARU DIBUAT DI WORKSHOP, MENUNGGU DRIVER SCAN)
        sj3_code = "SJ-PLTU-20260918-003"
        cursor.execute("SELECT id FROM shipments WHERE shipment_code = ?", (sj3_code,))
        if not cursor.fetchone():
            qr3_path = generate_qr_image(sj3_code, f"{sj3_code}.png")
            c_ids = [c["id"] for c in cutters]
            c_names = ", ".join([c["name"] for c in cutters])
            op_ids = [operators[0]["id"]]
            op_names = operators[0]["name"]

            cursor.execute("""
                INSERT INTO shipments (
                    shipment_code, qr_token, qr_code_path,
                    driver_id, driver_name, truck_plate, destination_pltu,
                    cutter_worker_ids, cutter_names, operator_worker_ids, operator_names,
                    status, departure_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?)
            """, (
                sj3_code, sj3_code, qr3_path,
                drivers[0]["id"], drivers[0]["name"], "BA 8821 QU", "PLTU Tenayan Raya 2x110MW",
                json.dumps(c_ids), c_names, json.dumps(op_ids), op_names,
                "Siap muat di Workshop Chipper Yard #1. Driver perlu scan QR untuk mulai perjalanan."
            ))

    conn.commit()
    conn.close()
    print("Database seeded successfully!")

if __name__ == "__main__":
    seed()
