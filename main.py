import os
import json
import uuid
import shutil
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Request, Form, File, UploadFile, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import (
    get_db, init_db, get_rates_dict, calculate_wages_for_shipment, DB_DIR
)
from seed_data import generate_qr_image

app = FastAPI(title="Sistem Logistik Woodchip & Upah Pekerja")

# Ensure required upload directories exist
UPLOAD_DIR = os.path.join(DB_DIR, "uploads")
STATIC_DIR = os.path.join(DB_DIR, "static")
TEMPLATES_DIR = os.path.join(DB_DIR, "templates")

os.makedirs(os.path.join(UPLOAD_DIR, "woodchip"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "weighing"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "payment"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_DIR, "qr"), exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Helper function to save uploaded file
def save_uploaded_file(file: UploadFile, subfolder: str) -> Optional[str]:
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename)[1].lower()
    if not ext:
        ext = ".jpg"
    unique_name = f"{uuid.uuid4().hex[:12]}{ext}"
    target_path = os.path.join(UPLOAD_DIR, subfolder, unique_name)
    with open(target_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return f"/uploads/{subfolder}/{unique_name}"

# Jinja custom filter for formatting rupiah & numbers
def format_rupiah(value):
    try:
        val = float(value or 0)
        return f"Rp {val:,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"

def format_number(value, decimals=2):
    try:
        val = float(value or 0)
        formatted = f"{val:,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return formatted
    except Exception:
        return "0"

templates.env.filters["rupiah"] = format_rupiah
templates.env.filters["num"] = format_number

@app.on_event("startup")
def startup_event():
    init_db()

# Helper for rendering template response compatible with newer Starlette
def render(request: Request, template_name: str, context: dict = None):
    ctx = context or {}
    return templates.TemplateResponse(request=request, name=template_name, context=ctx)

# ==========================================
# 1. DASHBOARD
# ==========================================
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_view(request: Request):
    conn = get_db()
    cursor = conn.cursor()

    # Metrics
    cursor.execute("SELECT COUNT(*) as cnt, COALESCE(SUM(net_ton), 0) as total_ton, COALESCE(SUM(total_amount), 0) as total_value FROM inbound_supplier")
    inbound_summary = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) as total_trips, COALESCE(SUM(pltu_net_ton), 0) as pltu_ton, COALESCE(SUM(departure_net_ton), 0) as dep_ton FROM shipments WHERE status IN ('ARRIVED_PLTU', 'SETTLED')")
    delivered_summary = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) as in_transit FROM shipments WHERE status = 'IN_TRANSIT'")
    transit_count = cursor.fetchone()["in_transit"]

    cursor.execute("SELECT COUNT(*) as draft_count FROM shipments WHERE status = 'DRAFT'")
    draft_count = cursor.fetchone()["draft_count"]

    cursor.execute("SELECT COUNT(*) as pending_cnt, COALESCE(SUM(amount_due), 0) as pending_amount FROM wage_settlements WHERE payment_status = 'PENDING'")
    wage_pending = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) as pending_cnt, COALESCE(SUM(total_amount), 0) as pending_amount FROM inbound_supplier WHERE payment_status = 'PENDING'")
    supplier_pending = cursor.fetchone()

    cursor.execute("""
        SELECT s.*, 
            (SELECT COUNT(*) FROM wage_settlements ws WHERE ws.shipment_id = s.id AND ws.payment_status = 'PENDING') as pending_wages
        FROM shipments s 
        ORDER BY s.id DESC LIMIT 8
    """)
    recent_shipments = cursor.fetchall()

    cursor.execute("SELECT * FROM inbound_supplier ORDER BY id DESC LIMIT 5")
    recent_inbound = cursor.fetchall()

    conn.close()

    return render(request, "dashboard.html", {
        "inbound_summary": inbound_summary,
        "delivered_summary": delivered_summary,
        "transit_count": transit_count,
        "draft_count": draft_count,
        "wage_pending": wage_pending,
        "supplier_pending": supplier_pending,
        "recent_shipments": recent_shipments,
        "recent_inbound": recent_inbound,
        "active_page": "dashboard"
    })

# ==========================================
# 2. INBOUND WORKSHOP (BARANG MASUK PEMASOK)
# ==========================================
@app.get("/inbound", response_class=HTMLResponse)
async def inbound_list(request: Request):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inbound_supplier ORDER BY id DESC")
    transactions = cursor.fetchall()

    cursor.execute("SELECT * FROM suppliers ORDER BY name ASC")
    suppliers = cursor.fetchall()

    rates = get_rates_dict()
    default_price = rates.get("rate_wood_purchase_per_ton", 350000)

    conn.close()
    return render(request, "inbound_supplier.html", {
        "transactions": transactions,
        "suppliers": suppliers,
        "default_price": default_price,
        "active_page": "inbound"
    })

@app.post("/inbound/create")
async def inbound_create(
    supplier_id: Optional[int] = Form(None),
    supplier_name: str = Form(...),
    truck_plate: str = Form(...),
    driver_name: Optional[str] = Form(""),
    material_type: str = Form("Kayu Log"),
    gross_weight_kg: float = Form(...),
    tare_weight_kg: float = Form(...),
    price_per_ton: float = Form(...),
    bank_name: str = Form(...),
    account_number: str = Form(...),
    account_holder: str = Form(...),
    notes: Optional[str] = Form(""),
    photo_material: Optional[UploadFile] = File(None),
    photo_weighing_ticket: Optional[UploadFile] = File(None),
):
    net_kg = max(0.0, gross_weight_kg - tare_weight_kg)
    net_ton = round(net_kg / 1000.0, 3)
    total_amount = round(net_ton * price_per_ton, 2)

    now_str = datetime.now().strftime("%Y%m%d")
    tx_code = f"INB-{now_str}-{uuid.uuid4().hex[:4].upper()}"

    qr_path = generate_qr_image(tx_code, f"{tx_code}.png")
    photo_mat_path = save_uploaded_file(photo_material, "woodchip")
    photo_ticket_path = save_uploaded_file(photo_weighing_ticket, "weighing")

    conn = get_db()
    cursor = conn.cursor()

    if not supplier_id and supplier_name:
        cursor.execute("SELECT id FROM suppliers WHERE name = ?", (supplier_name.strip(),))
        row = cursor.fetchone()
        if row:
            supplier_id = row["id"]
        else:
            cursor.execute("""
                INSERT INTO suppliers (name, bank_name, account_number, account_holder)
                VALUES (?, ?, ?, ?)
            """, (supplier_name.strip(), bank_name, account_number, account_holder))
            supplier_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO inbound_supplier (
            transaction_code, supplier_id, supplier_name, truck_plate, driver_name,
            material_type, gross_weight_kg, tare_weight_kg, net_weight_kg, net_ton,
            price_per_ton, total_amount, bank_name, account_number, account_holder,
            photo_material, photo_weighing_ticket, qr_code_path, payment_status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
    """, (
        tx_code, supplier_id, supplier_name, truck_plate.upper(), driver_name,
        material_type, gross_weight_kg, tare_weight_kg, net_kg, net_ton,
        price_per_ton, total_amount, bank_name, account_number, account_holder,
        photo_mat_path, photo_ticket_path, qr_path, notes
    ))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/inbound", status_code=303)

@app.get("/inbound/{id}/ticket", response_class=HTMLResponse)
async def inbound_ticket_view(request: Request, id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inbound_supplier WHERE id = ?", (id,))
    item = cursor.fetchone()
    conn.close()
    if not item:
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")
    return render(request, "inbound_ticket.html", {"item": item})

# ==========================================
# 3. SHIPMENTS (PENGIRIMAN WOODCHIP KE PLTU)
# ==========================================
@app.get("/shipments", response_class=HTMLResponse)
async def shipments_list(request: Request):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM shipments ORDER BY id DESC")
    shipments = cursor.fetchall()

    cursor.execute("SELECT * FROM workers WHERE role = 'driver' AND is_active = 1 ORDER BY name ASC")
    drivers = cursor.fetchall()

    cursor.execute("SELECT * FROM workers WHERE role = 'pemotong' AND is_active = 1 ORDER BY name ASC")
    cutters = cursor.fetchall()

    cursor.execute("SELECT * FROM workers WHERE role = 'operator' AND is_active = 1 ORDER BY name ASC")
    operators = cursor.fetchall()

    cursor.execute("SELECT * FROM suppliers ORDER BY name ASC")
    suppliers = cursor.fetchall()

    rates = get_rates_dict()

    conn.close()
    return render(request, "shipments.html", {
        "shipments": shipments,
        "drivers": drivers,
        "cutters": cutters,
        "operators": operators,
        "suppliers": suppliers,
        "rates": rates,
        "active_page": "shipments"
    })

@app.post("/shipments/create")
async def shipments_create(
    driver_id: int = Form(...),
    truck_plate: str = Form(...),
    destination_pltu: str = Form("PLTU Tenayan Raya"),
    cutter_worker_ids: List[int] = Form(...),
    operator_worker_ids: List[int] = Form(...),
    supplier_id: Optional[int] = Form(None),
    departure_gross_kg: Optional[float] = Form(0.0),
    departure_tare_kg: Optional[float] = Form(0.0),
    departure_notes: Optional[str] = Form(""),
):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM workers WHERE id = ?", (driver_id,))
    driver = cursor.fetchone()
    driver_name = driver["name"] if driver else "Driver"

    c_names = []
    if cutter_worker_ids:
        placeholders = ",".join(["?"] * len(cutter_worker_ids))
        cursor.execute(f"SELECT name FROM workers WHERE id IN ({placeholders})", cutter_worker_ids)
        c_names = [row["name"] for row in cursor.fetchall()]

    op_names = []
    if operator_worker_ids:
        placeholders = ",".join(["?"] * len(operator_worker_ids))
        cursor.execute(f"SELECT name FROM workers WHERE id IN ({placeholders})", operator_worker_ids)
        op_names = [row["name"] for row in cursor.fetchall()]

    supplier_name = None
    if supplier_id:
        cursor.execute("SELECT name FROM suppliers WHERE id = ?", (supplier_id,))
        sup_row = cursor.fetchone()
        if sup_row:
            supplier_name = sup_row["name"]

    now_str = datetime.now().strftime("%Y%m%d")
    sj_code = f"SJ-PLTU-{now_str}-{uuid.uuid4().hex[:4].upper()}"
    qr_token = sj_code
    qr_path = generate_qr_image(sj_code, f"{sj_code}.png")

    dep_gross = departure_gross_kg or 0.0
    dep_tare = departure_tare_kg or 0.0
    dep_net_kg = max(0.0, dep_gross - dep_tare)
    dep_net_ton = round(dep_net_kg / 1000.0, 3)

    rates = get_rates_dict()

    cursor.execute("""
        INSERT INTO shipments (
            shipment_code, qr_token, qr_code_path,
            driver_id, driver_name, truck_plate, destination_pltu,
            cutter_worker_ids, cutter_names, operator_worker_ids, operator_names,
            supplier_id, supplier_name, status,
            departure_gross_kg, departure_tare_kg, departure_net_kg, departure_net_ton,
            departure_notes,
            rate_cutter_per_ton, rate_driver_per_ton, rate_operator_per_ton, rate_supplier_per_ton
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sj_code, qr_token, qr_path,
        driver_id, driver_name, truck_plate.upper(), destination_pltu,
        json.dumps(cutter_worker_ids), ", ".join(c_names),
        json.dumps(operator_worker_ids), ", ".join(op_names),
        supplier_id, supplier_name,
        dep_gross, dep_tare, dep_net_kg, dep_net_ton,
        departure_notes,
        rates.get("rate_cutter_per_ton", 25000),
        rates.get("rate_driver_per_ton", 40000),
        rates.get("rate_operator_per_ton", 20000),
        rates.get("rate_wood_purchase_per_ton", 0) if supplier_id else 0
    ))
    conn.commit()
    conn.close()

    return RedirectResponse(url="/shipments", status_code=303)

@app.get("/shipments/{id}", response_class=HTMLResponse)
async def shipment_detail_view(request: Request, id: int):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM shipments WHERE id = ?", (id,))
    shipment = cursor.fetchone()
    if not shipment:
        conn.close()
        raise HTTPException(status_code=404, detail="Surat Jalan tidak ditemukan")

    cursor.execute("SELECT * FROM wage_settlements WHERE shipment_id = ? ORDER BY id ASC", (id,))
    settlements = cursor.fetchall()

    conn.close()
    return render(request, "shipment_detail.html", {
        "shipment": shipment,
        "settlements": settlements,
        "active_page": "shipments"
    })

@app.get("/shipments/{id}/print", response_class=HTMLResponse)
async def shipment_print_view(request: Request, id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shipments WHERE id = ?", (id,))
    shipment = cursor.fetchone()
    conn.close()
    if not shipment:
        raise HTTPException(status_code=404, detail="Surat Jalan tidak ditemukan")
    return render(request, "shipment_print.html", {"shipment": shipment})

# ==========================================
# 4. MOBILE QR SCANNER PORTAL FOR DRIVERS
# ==========================================
@app.get("/scanner", response_class=HTMLResponse)
async def driver_scanner_portal(request: Request, code: Optional[str] = None):
    shipment_data = None
    if code:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shipments WHERE shipment_code = ? OR qr_token = ?", (code.strip(), code.strip()))
        shipment_data = cursor.fetchone()
        conn.close()

    return render(request, "driver_scanner.html", {
        "initial_code": code or "",
        "shipment": shipment_data,
        "active_page": "scanner"
    })

@app.get("/api/shipments/lookup")
async def api_shipment_lookup(code: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shipments WHERE shipment_code = ? OR qr_token = ?", (code.strip(), code.strip()))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return JSONResponse(status_code=404, content={"success": False, "message": "Surat Jalan / Barcode tidak ditemukan"})
    return JSONResponse(content={"success": True, "shipment": dict(row)})

@app.post("/api/shipments/confirm-departure")
async def api_confirm_departure(
    shipment_id: int = Form(...),
    departure_gross_kg: Optional[float] = Form(None),
    departure_tare_kg: Optional[float] = Form(None),
    notes: Optional[str] = Form(""),
    photo_woodchip: Optional[UploadFile] = File(None)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
    shipment = cursor.fetchone()
    if not shipment:
        conn.close()
        return JSONResponse(status_code=404, content={"success": False, "message": "Shipment tidak ditemukan"})

    photo_path = save_uploaded_file(photo_woodchip, "woodchip")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    dep_gross = departure_gross_kg if departure_gross_kg is not None else shipment["departure_gross_kg"]
    dep_tare = departure_tare_kg if departure_tare_kg is not None else shipment["departure_tare_kg"]
    dep_net_kg = max(0.0, (dep_gross or 0) - (dep_tare or 0))
    dep_net_ton = round(dep_net_kg / 1000.0, 3) if dep_net_kg > 0 else shipment["departure_net_ton"]

    cursor.execute("""
        UPDATE shipments
        SET status = 'IN_TRANSIT',
            departure_time = ?,
            departure_photo_woodchip = COALESCE(?, departure_photo_woodchip),
            departure_gross_kg = ?,
            departure_tare_kg = ?,
            departure_net_kg = ?,
            departure_net_ton = ?,
            departure_notes = CASE WHEN ? != '' THEN ? ELSE departure_notes END,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        now_str, photo_path, dep_gross, dep_tare, dep_net_kg, dep_net_ton,
        notes, notes, shipment_id
    ))
    conn.commit()
    conn.close()

    return JSONResponse(content={
        "success": True,
        "message": "Keberangkatan berhasil diverifikasi. Status: Dalam Perjalanan (In-Transit).",
        "status": "IN_TRANSIT"
    })

@app.post("/api/shipments/confirm-arrival")
async def api_confirm_arrival(
    shipment_id: int = Form(...),
    pltu_gross_kg: float = Form(...),
    pltu_tare_kg: float = Form(...),
    pltu_notes: Optional[str] = Form(""),
    photo_weighing_pltu: Optional[UploadFile] = File(None)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
    shipment = cursor.fetchone()
    if not shipment:
        conn.close()
        return JSONResponse(status_code=404, content={"success": False, "message": "Shipment tidak ditemukan"})

    photo_path = save_uploaded_file(photo_weighing_pltu, "weighing")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    pltu_net_kg = max(0.0, pltu_gross_kg - pltu_tare_kg)
    pltu_net_ton = round(pltu_net_kg / 1000.0, 3)

    cursor.execute("""
        UPDATE shipments
        SET status = 'ARRIVED_PLTU',
            pltu_arrival_time = ?,
            pltu_gross_kg = ?,
            pltu_tare_kg = ?,
            pltu_net_kg = ?,
            pltu_net_ton = ?,
            pltu_photo_ticket = COALESCE(?, pltu_photo_ticket),
            pltu_notes = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        now_str, pltu_gross_kg, pltu_tare_kg, pltu_net_kg, pltu_net_ton,
        photo_path, pltu_notes, shipment_id
    ))
    conn.commit()
    conn.close()

    # Hitung upah otomatis pekerja berdasarkan Netto Tonase PLTU
    calculate_wages_for_shipment(shipment_id)

    return JSONResponse(content={
        "success": True,
        "message": f"Konfirmasi tiba di PLTU berhasil! Netto: {pltu_net_ton} TON. Upah pekerja telah otomatis dihitung.",
        "status": "ARRIVED_PLTU",
        "pltu_net_ton": pltu_net_ton
    })

# ==========================================
# 5. MODUL KEUANGAN & PEMBAYARAN MANUAL
# ==========================================
@app.get("/finance", response_class=HTMLResponse)
async def finance_dashboard(request: Request, tab: str = "wages", status_filter: str = "ALL"):
    conn = get_db()
    cursor = conn.cursor()

    query_wages = """
        SELECT ws.*, s.shipment_code, s.truck_plate, s.pltu_arrival_time, s.destination_pltu
        FROM wage_settlements ws
        JOIN shipments s ON ws.shipment_id = s.id
    """
    params_wages = []
    if status_filter != "ALL":
        query_wages += " WHERE ws.payment_status = ?"
        params_wages.append(status_filter)
    query_wages += " ORDER BY ws.id DESC"
    cursor.execute(query_wages, params_wages)
    wage_records = cursor.fetchall()

    query_inbound = "SELECT * FROM inbound_supplier"
    params_inbound = []
    if status_filter != "ALL":
        query_inbound += " WHERE payment_status = ?"
        params_inbound.append(status_filter)
    query_inbound += " ORDER BY id DESC"
    cursor.execute(query_inbound, params_inbound)
    inbound_records = cursor.fetchall()

    cursor.execute("SELECT COALESCE(SUM(amount_due), 0) as total FROM wage_settlements WHERE payment_status = 'PENDING'")
    total_pending_wages = cursor.fetchone()["total"]

    cursor.execute("SELECT COALESCE(SUM(total_amount), 0) as total FROM inbound_supplier WHERE payment_status = 'PENDING'")
    total_pending_suppliers = cursor.fetchone()["total"]

    cursor.execute("SELECT COALESCE(SUM(amount_due), 0) as total FROM wage_settlements WHERE payment_status = 'PAID'")
    total_paid_wages = cursor.fetchone()["total"]

    cursor.execute("SELECT COALESCE(SUM(total_amount), 0) as total FROM inbound_supplier WHERE payment_status = 'PAID'")
    total_paid_suppliers = cursor.fetchone()["total"]

    conn.close()

    return render(request, "finance_payroll.html", {
        "active_tab": tab,
        "status_filter": status_filter,
        "wage_records": wage_records,
        "inbound_records": inbound_records,
        "total_pending_wages": total_pending_wages,
        "total_pending_suppliers": total_pending_suppliers,
        "total_paid_wages": total_paid_wages,
        "total_paid_suppliers": total_paid_suppliers,
        "active_page": "finance"
    })

@app.post("/finance/settle-wage/{id}")
async def settle_wage_payment(
    id: int,
    payment_reference: str = Form(...),
    payment_date: str = Form(...),
    notes: Optional[str] = Form(""),
    payment_proof: Optional[UploadFile] = File(None)
):
    proof_path = save_uploaded_file(payment_proof, "payment")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE wage_settlements
        SET payment_status = 'PAID',
            payment_reference = ?,
            payment_date = ?,
            payment_proof_path = COALESCE(?, payment_proof_path),
            notes = ?,
            created_at = created_at
        WHERE id = ?
    """, (payment_reference, payment_date, proof_path, notes, id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/finance?tab=wages", status_code=303)

@app.post("/finance/settle-inbound/{id}")
async def settle_inbound_payment(
    id: int,
    payment_reference: str = Form(...),
    payment_date: str = Form(...),
    notes: Optional[str] = Form(""),
    payment_proof: Optional[UploadFile] = File(None)
):
    proof_path = save_uploaded_file(payment_proof, "payment")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE inbound_supplier
        SET payment_status = 'PAID',
            payment_reference = ?,
            payment_date = ?,
            payment_proof_path = COALESCE(?, payment_proof_path),
            notes = CASE WHEN ? != '' THEN ? ELSE notes END
        WHERE id = ?
    """, (payment_reference, payment_date, proof_path, notes, notes, id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/finance?tab=suppliers", status_code=303)

@app.get("/finance/slip/{id}", response_class=HTMLResponse)
async def print_wage_slip(request: Request, id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ws.*, s.shipment_code, s.truck_plate, s.pltu_arrival_time, s.destination_pltu, s.pltu_net_ton
        FROM wage_settlements ws
        JOIN shipments s ON ws.shipment_id = s.id
        WHERE ws.id = ?
    """, (id,))
    item = cursor.fetchone()
    conn.close()
    if not item:
        raise HTTPException(status_code=404, detail="Data upah tidak ditemukan")
    return render(request, "wage_slip.html", {"item": item})

# ==========================================
# 6. MASTER DATA & SETTINGS
# ==========================================
@app.get("/master", response_class=HTMLResponse)
async def master_data_view(request: Request):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings_rates ORDER BY id ASC")
    rates = cursor.fetchall()

    cursor.execute("SELECT * FROM workers ORDER BY role ASC, name ASC")
    workers = cursor.fetchall()

    cursor.execute("SELECT * FROM suppliers ORDER BY name ASC")
    suppliers = cursor.fetchall()

    conn.close()
    return render(request, "master_data.html", {
        "rates": rates,
        "workers": workers,
        "suppliers": suppliers,
        "active_page": "master"
    })

@app.post("/master/rates/update")
async def update_rates(
    rate_cutter: float = Form(...),
    rate_driver: float = Form(...),
    rate_operator: float = Form(...),
    rate_wood: float = Form(...)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE settings_rates SET rate_value = ?, updated_at = CURRENT_TIMESTAMP WHERE rate_key = 'rate_cutter_per_ton'", (rate_cutter,))
    cursor.execute("UPDATE settings_rates SET rate_value = ?, updated_at = CURRENT_TIMESTAMP WHERE rate_key = 'rate_driver_per_ton'", (rate_driver,))
    cursor.execute("UPDATE settings_rates SET rate_value = ?, updated_at = CURRENT_TIMESTAMP WHERE rate_key = 'rate_operator_per_ton'", (rate_operator,))
    cursor.execute("UPDATE settings_rates SET rate_value = ?, updated_at = CURRENT_TIMESTAMP WHERE rate_key = 'rate_wood_purchase_per_ton'", (rate_wood,))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/master", status_code=303)

@app.post("/master/workers/create")
async def create_worker(
    name: str = Form(...),
    role: str = Form(...),
    phone: Optional[str] = Form(""),
    bank_name: str = Form(...),
    account_number: str = Form(...),
    account_holder: str = Form(...)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO workers (name, role, phone, bank_name, account_number, account_holder)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name.strip(), role, phone, bank_name, account_number, account_holder))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/master", status_code=303)

@app.post("/master/suppliers/create")
async def create_supplier(
    name: str = Form(...),
    phone: Optional[str] = Form(""),
    address: Optional[str] = Form(""),
    bank_name: str = Form(...),
    account_number: str = Form(...),
    account_holder: str = Form(...)
):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO suppliers (name, phone, address, bank_name, account_number, account_holder)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name.strip(), phone, address, bank_name, account_number, account_holder))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/master", status_code=303)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
