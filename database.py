import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "woodchip_system.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    os.makedirs(os.path.join(DB_DIR, "uploads", "woodchip"), exist_ok=True)
    os.makedirs(os.path.join(DB_DIR, "uploads", "weighing"), exist_ok=True)
    os.makedirs(os.path.join(DB_DIR, "uploads", "payment"), exist_ok=True)
    os.makedirs(os.path.join(DB_DIR, "uploads", "qr"), exist_ok=True)

    conn = get_db()
    cursor = conn.cursor()

    # Table: Suppliers (Pemasok Kayu)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        address TEXT,
        bank_name TEXT NOT NULL,
        account_number TEXT NOT NULL,
        account_holder TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Table: Workers (Pemotong, Driver, Operator)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS workers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT NOT NULL, -- 'pemotong', 'driver', 'operator'
        phone TEXT,
        bank_name TEXT NOT NULL,
        account_number TEXT NOT NULL,
        account_holder TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Table: Settings & Rates (Tarif per TON)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings_rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rate_key TEXT UNIQUE NOT NULL,
        rate_name TEXT NOT NULL,
        rate_value REAL NOT NULL,
        unit TEXT DEFAULT 'Rp / TON',
        description TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Table: Inbound Supplier (Barang Masuk Kayu / Woodchip dari Pemasok ke Workshop)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inbound_supplier (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_code TEXT UNIQUE NOT NULL,
        supplier_id INTEGER,
        supplier_name TEXT NOT NULL,
        truck_plate TEXT NOT NULL,
        driver_name TEXT,
        material_type TEXT DEFAULT 'Kayu Log / Bulat',
        gross_weight_kg REAL NOT NULL,
        tare_weight_kg REAL NOT NULL,
        net_weight_kg REAL NOT NULL,
        net_ton REAL NOT NULL,
        price_per_ton REAL NOT NULL,
        total_amount REAL NOT NULL,
        bank_name TEXT NOT NULL,
        account_number TEXT NOT NULL,
        account_holder TEXT NOT NULL,
        photo_material TEXT,
        photo_weighing_ticket TEXT,
        qr_code_path TEXT,
        payment_status TEXT DEFAULT 'PENDING', -- PENDING, PAID
        payment_date TEXT,
        payment_reference TEXT,
        payment_proof_path TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
    )
    """)

    # Table: Shipments (Pengiriman Woodchip ke PLTU)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shipments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shipment_code TEXT UNIQUE NOT NULL,
        qr_token TEXT UNIQUE NOT NULL,
        qr_code_path TEXT,
        driver_id INTEGER,
        driver_name TEXT NOT NULL,
        truck_plate TEXT NOT NULL,
        destination_pltu TEXT NOT NULL,
        cutter_worker_ids TEXT, -- JSON array of worker IDs e.g. [1, 2]
        cutter_names TEXT,
        operator_worker_ids TEXT, -- JSON array of worker IDs e.g. [3]
        operator_names TEXT,
        supplier_id INTEGER,
        supplier_name TEXT,
        status TEXT DEFAULT 'DRAFT', -- DRAFT, IN_TRANSIT, ARRIVED_PLTU, SETTLED
        
        -- Workshop departure data
        departure_time TEXT,
        departure_gross_kg REAL DEFAULT 0,
        departure_tare_kg REAL DEFAULT 0,
        departure_net_kg REAL DEFAULT 0,
        departure_net_ton REAL DEFAULT 0,
        departure_photo_woodchip TEXT,
        departure_notes TEXT,
        
        -- PLTU arrival & final weighing data
        pltu_arrival_time TEXT,
        pltu_gross_kg REAL DEFAULT 0,
        pltu_tare_kg REAL DEFAULT 0,
        pltu_net_kg REAL DEFAULT 0,
        pltu_net_ton REAL DEFAULT 0,
        pltu_photo_ticket TEXT,
        pltu_notes TEXT,
        
        -- Wage rate snapshots per TON (stored at time of delivery to lock rates)
        rate_cutter_per_ton REAL DEFAULT 0,
        rate_driver_per_ton REAL DEFAULT 0,
        rate_operator_per_ton REAL DEFAULT 0,
        rate_supplier_per_ton REAL DEFAULT 0,
        
        -- Calculated wages
        cutter_total_wage REAL DEFAULT 0,
        driver_total_wage REAL DEFAULT 0,
        operator_total_wage REAL DEFAULT 0,
        supplier_total_cost REAL DEFAULT 0,
        total_operational_wage REAL DEFAULT 0,
        
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (driver_id) REFERENCES workers(id),
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
    )
    """)

    # Table: Wage Settlements (Detail rincian pembayaran upah per individu)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wage_settlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shipment_id INTEGER,
        inbound_id INTEGER,
        recipient_type TEXT NOT NULL, -- 'WORKER' or 'SUPPLIER'
        worker_id INTEGER,
        supplier_id INTEGER,
        role TEXT NOT NULL, -- 'pemotong', 'driver', 'operator', 'supplier'
        recipient_name TEXT NOT NULL,
        bank_name TEXT NOT NULL,
        account_number TEXT NOT NULL,
        account_holder TEXT NOT NULL,
        ton_basis REAL NOT NULL,
        rate_per_ton REAL NOT NULL,
        amount_due REAL NOT NULL,
        payment_status TEXT DEFAULT 'PENDING', -- PENDING, PAID
        payment_date TEXT,
        payment_reference TEXT,
        payment_proof_path TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (shipment_id) REFERENCES shipments(id),
        FOREIGN KEY (inbound_id) REFERENCES inbound_supplier(id)
    )
    """)

    conn.commit()
    conn.close()

def get_rates_dict() -> Dict[str, float]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT rate_key, rate_value FROM settings_rates")
    rows = cursor.fetchall()
    conn.close()
    return {row["rate_key"]: float(row["rate_value"]) for row in rows}

def calculate_wages_for_shipment(shipment_id: int):
    """
    Kalkulasi upah pekerja berdasarkan data tonase aktual PLTU (pltu_net_ton).
    Memperbarui tabel shipments dan membuat record di wage_settlements.
    """
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
    shipment = cursor.fetchone()
    if not shipment:
        conn.close()
        return None
    
    net_ton = float(shipment["pltu_net_ton"] or 0)
    if net_ton <= 0:
        # Fallback to departure net ton if PLTU net ton is not yet set
        net_ton = float(shipment["departure_net_ton"] or 0)
        
    rates = get_rates_dict()
    rate_cutter = float(shipment["rate_cutter_per_ton"] or rates.get("rate_cutter_per_ton", 25000))
    rate_driver = float(shipment["rate_driver_per_ton"] or rates.get("rate_driver_per_ton", 40000))
    rate_operator = float(shipment["rate_operator_per_ton"] or rates.get("rate_operator_per_ton", 20000))
    rate_supplier = float(shipment["rate_supplier_per_ton"] or rates.get("rate_supplier_per_ton", 0))
    
    cutter_total = round(net_ton * rate_cutter, 2)
    driver_total = round(net_ton * rate_driver, 2)
    operator_total = round(net_ton * rate_operator, 2)
    supplier_total = round(net_ton * rate_supplier, 2)
    total_wage = cutter_total + driver_total + operator_total

    cursor.execute("""
        UPDATE shipments 
        SET rate_cutter_per_ton = ?,
            rate_driver_per_ton = ?,
            rate_operator_per_ton = ?,
            rate_supplier_per_ton = ?,
            cutter_total_wage = ?,
            driver_total_wage = ?,
            operator_total_wage = ?,
            supplier_total_cost = ?,
            total_operational_wage = ?,
            status = 'SETTLED',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        rate_cutter, rate_driver, rate_operator, rate_supplier,
        cutter_total, driver_total, operator_total, supplier_total, total_wage,
        shipment_id
    ))

    # Bersihkan settlement lama jika belum dibayar untuk menghindari duplikasi saat re-calculate
    cursor.execute("""
        DELETE FROM wage_settlements 
        WHERE shipment_id = ? AND payment_status = 'PENDING'
    """, (shipment_id,))

    # 1. Driver settlement
    driver_id = shipment["driver_id"]
    if driver_id:
        cursor.execute("SELECT * FROM workers WHERE id = ?", (driver_id,))
        driver = cursor.fetchone()
        if driver:
            cursor.execute("""
                INSERT INTO wage_settlements (
                    shipment_id, recipient_type, worker_id, role,
                    recipient_name, bank_name, account_number, account_holder,
                    ton_basis, rate_per_ton, amount_due
                ) VALUES (?, 'WORKER', ?, 'driver', ?, ?, ?, ?, ?, ?, ?)
            """, (
                shipment_id, driver["id"], driver["name"],
                driver["bank_name"], driver["account_number"], driver["account_holder"],
                net_ton, rate_driver, driver_total
            ))

    # 2. Cutters settlement (bagi rata jika ada lebih dari 1 orang di tim)
    cutter_ids = []
    if shipment["cutter_worker_ids"]:
        try:
            cutter_ids = json.loads(shipment["cutter_worker_ids"])
        except Exception:
            cutter_ids = []
            
    if cutter_ids:
        cutter_share = round(cutter_total / len(cutter_ids), 2)
        for cid in cutter_ids:
            cursor.execute("SELECT * FROM workers WHERE id = ?", (cid,))
            worker = cursor.fetchone()
            if worker:
                cursor.execute("""
                    INSERT INTO wage_settlements (
                        shipment_id, recipient_type, worker_id, role,
                        recipient_name, bank_name, account_number, account_holder,
                        ton_basis, rate_per_ton, amount_due
                    ) VALUES (?, 'WORKER', ?, 'pemotong', ?, ?, ?, ?, ?, ?, ?)
                """, (
                    shipment_id, worker["id"], worker["name"],
                    worker["bank_name"], worker["account_number"], worker["account_holder"],
                    net_ton, rate_cutter, cutter_share
                ))

    # 3. Operators settlement (bagi rata jika ada lebih dari 1 operator)
    operator_ids = []
    if shipment["operator_worker_ids"]:
        try:
            operator_ids = json.loads(shipment["operator_worker_ids"])
        except Exception:
            operator_ids = []
            
    if operator_ids:
        operator_share = round(operator_total / len(operator_ids), 2)
        for oid in operator_ids:
            cursor.execute("SELECT * FROM workers WHERE id = ?", (oid,))
            worker = cursor.fetchone()
            if worker:
                cursor.execute("""
                    INSERT INTO wage_settlements (
                        shipment_id, recipient_type, worker_id, role,
                        recipient_name, bank_name, account_number, account_holder,
                        ton_basis, rate_per_ton, amount_due
                    ) VALUES (?, 'WORKER', ?, 'operator', ?, ?, ?, ?, ?, ?, ?)
                """, (
                    shipment_id, worker["id"], worker["name"],
                    worker["bank_name"], worker["account_number"], worker["account_holder"],
                    net_ton, rate_operator, operator_share
                ))

    # 4. Supplier settlement (bila terikat ke shipment)
    supplier_id = shipment["supplier_id"]
    if supplier_id and supplier_total > 0:
        cursor.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
        supplier = cursor.fetchone()
        if supplier:
            cursor.execute("""
                INSERT INTO wage_settlements (
                    shipment_id, recipient_type, supplier_id, role,
                    recipient_name, bank_name, account_number, account_holder,
                    ton_basis, rate_per_ton, amount_due
                ) VALUES (?, 'SUPPLIER', ?, 'supplier', ?, ?, ?, ?, ?, ?, ?)
            """, (
                shipment_id, supplier["id"], supplier["name"],
                supplier["bank_name"], supplier["account_number"], supplier["account_holder"],
                net_ton, rate_supplier, supplier_total
            ))

    conn.commit()
    conn.close()
    return True
