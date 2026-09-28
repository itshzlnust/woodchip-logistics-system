import unittest
import os
import json
from database import (
    get_db, init_db, get_rates_dict, calculate_wages_for_shipment, DB_DIR
)
from seed_data import seed

class TestWoodchipSystem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Inisialisasi database dan data awal
        seed()

    def test_rates_and_settings(self):
        rates = get_rates_dict()
        self.assertIn("rate_cutter_per_ton", rates)
        self.assertIn("rate_driver_per_ton", rates)
        self.assertIn("rate_operator_per_ton", rates)
        self.assertIn("rate_wood_purchase_per_ton", rates)
        self.assertGreater(rates["rate_cutter_per_ton"], 0)
        self.assertGreater(rates["rate_driver_per_ton"], 0)
        self.assertGreater(rates["rate_operator_per_ton"], 0)

    def test_inbound_supplier_calculation(self):
        conn = get_db()
        cursor = conn.cursor()
        
        gross = 20000.0
        tare = 8000.0
        net_kg = gross - tare # 12000.0 kg
        net_ton = round(net_kg / 1000.0, 3) # 12.0 TON
        price_per_ton = 350000.0
        expected_total = net_ton * price_per_ton # 4,200,000.0

        tx_code = "TEST-INB-001"
        cursor.execute("""
            INSERT OR REPLACE INTO inbound_supplier (
                transaction_code, supplier_name, truck_plate, material_type,
                gross_weight_kg, tare_weight_kg, net_weight_kg, net_ton,
                price_per_ton, total_amount, bank_name, account_number, account_holder
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tx_code, "Supplier Uji Coba", "BK 1234 TEST", "Kayu Log",
            gross, tare, net_kg, net_ton,
            price_per_ton, expected_total, "BCA", "123456789", "Uji Coba"
        ))
        conn.commit()

        cursor.execute("SELECT * FROM inbound_supplier WHERE transaction_code = ?", (tx_code,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["net_ton"], 12.0)
        self.assertEqual(row["total_amount"], 4200000.0)
        self.assertEqual(row["payment_status"], "PENDING")
        conn.close()

    def test_shipment_workflow_and_wage_calculation(self):
        conn = get_db()
        cursor = conn.cursor()

        # Ambil 1 driver, 2 pemotong, 1 operator
        cursor.execute("SELECT id, name FROM workers WHERE role = 'driver' LIMIT 1")
        driver = cursor.fetchone()
        cursor.execute("SELECT id, name FROM workers WHERE role = 'pemotong' LIMIT 2")
        cutters = cursor.fetchall()
        cursor.execute("SELECT id, name FROM workers WHERE role = 'operator' LIMIT 1")
        operator = cursor.fetchone()

        c_ids = [c["id"] for c in cutters]
        op_ids = [operator["id"]]

        sj_code = "TEST-SJ-PLTU-999"
        cursor.execute("""
            INSERT OR REPLACE INTO shipments (
                shipment_code, qr_token, driver_id, driver_name, truck_plate, destination_pltu,
                cutter_worker_ids, cutter_names, operator_worker_ids, operator_names,
                status, departure_gross_kg, departure_tare_kg, departure_net_kg, departure_net_ton
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', 22000, 8000, 14000, 14.0)
        """, (
            sj_code, sj_code, driver["id"], driver["name"], "BM 9999 TEST", "PLTU Uji Coba",
            json.dumps(c_ids), ", ".join([c["name"] for c in cutters]),
            json.dumps(op_ids), operator["name"]
        ))
        conn.commit()
        cursor.execute("SELECT id FROM shipments WHERE shipment_code = ?", (sj_code,))
        shipment_id = cursor.fetchone()["id"]

        # Tahap 1: Driver Scan Keberangkatan (Status -> IN_TRANSIT)
        cursor.execute("""
            UPDATE shipments 
            SET status = 'IN_TRANSIT', 
                departure_time = '2026-09-18 08:00:00',
                departure_photo_woodchip = '/uploads/woodchip/sample.jpg'
            WHERE id = ?
        """, (shipment_id,))
        conn.commit()

        # Tahap 2: Tiba di PLTU & Timbang Final (Gross 22.500 kg, Tara 8.000 kg -> Netto 14.500 kg = 14.50 TON)
        pltu_gross = 22500.0
        pltu_tare = 8000.0
        pltu_net_kg = pltu_gross - pltu_tare # 14500 kg
        pltu_net_ton = round(pltu_net_kg / 1000.0, 3) # 14.5 TON

        cursor.execute("""
            UPDATE shipments
            SET status = 'ARRIVED_PLTU',
                pltu_arrival_time = '2026-09-18 11:30:00',
                pltu_gross_kg = ?,
                pltu_tare_kg = ?,
                pltu_net_kg = ?,
                pltu_net_ton = ?,
                pltu_photo_ticket = '/uploads/weighing/sample_pltu.jpg'
            WHERE id = ?
        """, (pltu_gross, pltu_tare, pltu_net_kg, pltu_net_ton, shipment_id))
        conn.commit()
        conn.close()

        # Panggil kalkulasi upah
        res = calculate_wages_for_shipment(shipment_id)
        self.assertTrue(res)

        # Verifikasi hasil perhitungan upah
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
        s = cursor.fetchone()

        rates = get_rates_dict()
        expected_cutter_total = round(14.5 * rates["rate_cutter_per_ton"], 2)
        expected_driver_total = round(14.5 * rates["rate_driver_per_ton"], 2)
        expected_operator_total = round(14.5 * rates["rate_operator_per_ton"], 2)
        expected_total_wage = expected_cutter_total + expected_driver_total + expected_operator_total

        self.assertEqual(s["pltu_net_ton"], 14.5)
        self.assertEqual(s["cutter_total_wage"], expected_cutter_total)
        self.assertEqual(s["driver_total_wage"], expected_driver_total)
        self.assertEqual(s["operator_total_wage"], expected_operator_total)
        self.assertEqual(s["total_operational_wage"], expected_total_wage)

        # Periksa rincian wage_settlements
        cursor.execute("SELECT * FROM wage_settlements WHERE shipment_id = ?", (shipment_id,))
        settlements = cursor.fetchall()
        # Harus ada: 1 driver + 2 cutters + 1 operator = 4 records
        self.assertEqual(len(settlements), 4)

        driver_settle = next(ws for ws in settlements if ws["role"] == "driver")
        self.assertEqual(driver_settle["amount_due"], expected_driver_total)
        self.assertEqual(driver_settle["recipient_name"], driver["name"])
        self.assertIsNotNone(driver_settle["account_number"])

        cutter_settles = [ws for ws in settlements if ws["role"] == "pemotong"]
        self.assertEqual(len(cutter_settles), 2)
        # Karena 2 pemotong, upah dibagi 2 sama rata
        self.assertEqual(cutter_settles[0]["amount_due"], round(expected_cutter_total / 2, 2))

        # Tes pelunasan upah manual (Payment)
        test_ws_id = driver_settle["id"]
        cursor.execute("""
            UPDATE wage_settlements 
            SET payment_status = 'PAID', 
                payment_reference = 'TRF-TEST-888', 
                payment_date = '2026-09-18 12:00:00'
            WHERE id = ?
        """, (test_ws_id,))
        conn.commit()

        cursor.execute("SELECT payment_status, payment_reference FROM wage_settlements WHERE id = ?", (test_ws_id,))
        paid_ws = cursor.fetchone()
        self.assertEqual(paid_ws["payment_status"], "PAID")
        self.assertEqual(paid_ws["payment_reference"], "TRF-TEST-888")

        conn.close()

if __name__ == "__main__":
    unittest.main()
