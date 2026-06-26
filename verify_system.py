import time
import threading
import json
import urllib.request
import urllib.error
import sqlite3
from datetime import datetime, timedelta
from db import init_db, get_db_connection, DB_PATH
from app import app

BASE_URL = "http://127.0.0.1:5000"

def run_flask_in_thread():
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

def post_json(url, payload=None):
    req = urllib.request.Request(url, method="POST")
    req.add_header('Content-Type', 'application/json')
    data = json.dumps(payload or {}).encode('utf-8')
    try:
        with urllib.request.urlopen(req, data=data) as response:
            status = response.status
            body = json.loads(response.read().decode('utf-8'))
            return status, body
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = json.loads(e.read().decode('utf-8'))
        except Exception:
            body = {"message": str(e)}
        return status, body

def verify_all():
    print("==================================================")
    print("STARTING AUTOMATED VERIFICATION FOR RECON ENGINE  ")
    print("==================================================")

    # 1. Initialize fresh test database
    init_db(force=True)
    print("[1/6] Database initialized and seeded with mock data.")

    # 2. Start the Flask server in the background
    server_thread = threading.Thread(target=run_flask_in_thread, daemon=True)
    server_thread.start()
    print("[2/6] Flask server started in background thread.")
    
    # Wait for the server to spin up
    time.sleep(2)

    # 3. Test Webhook Ingestion & Flow
    print("\n--- Test 1: Simulating Healthy Order & Webhook Payment ---")
    
    # Create order
    status, order_data = post_json(f"{BASE_URL}/api/simulate/order")
    assert status == 200, f"Failed to create order, got status {status}"
    order_id = order_data["order_id"]
    amount = order_data["amount"]
    print(f"Created order: {order_id} (Amount: {amount})")

    # Pay order via webhook simulator
    status, _ = post_json(f"{BASE_URL}/api/simulate/webhook/valid")
    assert status == 200, f"Webhook payment failed, got status {status}"
    print("Simulated payment webhook successfully.")

    # Verify db status
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,))
    order_status = cursor.fetchone()["status"]
    assert order_status == "paid", f"Order status should be paid, got {order_status}"
    print(f"Verified order {order_id} status is 'paid'.")

    # Verify ledger entries
    cursor.execute("SELECT * FROM ledger_entries WHERE order_id = ?", (order_id,))
    entry = cursor.fetchone()
    assert entry is not None, "Ledger entry was not created"
    assert entry["amount"] == amount, f"Ledger entry amount mismatch: {entry['amount']} vs {amount}"
    print(f"Verified ledger entry posted for {amount} USD (Direction: {entry['direction']}).")
    conn.close()
    print("[3/6] Test 1 (Healthy Webhook Flow) PASSED.")


    # 4. Test Stalled Order Anomaly
    print("\n--- Test 2: Simulating Stalled Order ---")
    
    # Let's check anomalies (our db.py seeded ord_002 created 120s ago in 'pending' status)
    # Trigger reconciliation
    status, _ = post_json(f"{BASE_URL}/api/simulate/reconcile")
    assert status == 200, "Failed to run reconciliation"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM anomalies WHERE type = 'stalled_order' AND reference_id = 'ord_002' AND status = 'active'")
    anomaly = cursor.fetchone()
    assert anomaly is not None, "Stalled order anomaly was not detected for ord_002"
    anomaly_id_stalled = anomaly["anomaly_id"]
    print(f"Detected stalled order anomaly for ord_002. Description: '{anomaly['description']}'")

    # Test Resolution: Cancel the stalled order
    status, res_data = post_json(f"{BASE_URL}/api/resolve/stalled_order", {"anomaly_id": anomaly_id_stalled, "action": "cancel"})
    assert status == 200, f"Failed to resolve stalled order, got status {status}"
    
    # Check if order is now cancelled
    cursor.execute("SELECT status FROM orders WHERE order_id = 'ord_002'")
    order_status_check = cursor.fetchone()["status"]
    assert order_status_check == "cancelled", f"Order status should be cancelled, got {order_status_check}"
    
    # Check if anomaly is now resolved
    cursor.execute("SELECT status, resolved_at FROM anomalies WHERE anomaly_id = ?", (anomaly_id_stalled,))
    row = cursor.fetchone()
    assert row["status"] == "resolved", "Anomaly status should be resolved"
    assert row["resolved_at"] is not None, "resolved_at timestamp must be set"
    print(f"Verified stalled order resolved (Order status: {order_status_check}, Anomaly status: {row['status']}).")
    conn.close()
    print("[4/6] Test 2 (Stalled Order & Cancel Resolution) PASSED.")


    # 5. Test Orphaned Credit Anomaly
    print("\n--- Test 3: Simulating Orphaned Credit ---")
    
    # Simulate orphaned webhook (sends webhook with non-existent order_id)
    status, _ = post_json(f"{BASE_URL}/api/simulate/webhook/orphaned")
    assert status == 200, "Failed to simulate orphaned webhook"
    
    # Trigger recon
    status, _ = post_json(f"{BASE_URL}/api/simulate/reconcile")
    assert status == 200
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find the orphaned credit anomaly
    cursor.execute("SELECT * FROM anomalies WHERE type = 'orphaned_credit' AND status = 'active'")
    anomaly = cursor.fetchone()
    assert anomaly is not None, "Orphaned credit anomaly was not detected"
    anomaly_id_orphaned = anomaly["anomaly_id"]
    print(f"Detected orphaned credit anomaly. Description: '{anomaly['description']}'")

    # Test Resolution: Create manual order
    status, res_data = post_json(f"{BASE_URL}/api/resolve/orphaned_credit", {"anomaly_id": anomaly_id_orphaned, "action": "create_order"})
    assert status == 200, f"Failed to resolve orphaned credit, got status {status}"
    
    # Verify that order was created
    entry_id = anomaly["reference_id"]
    cursor.execute("SELECT order_id FROM ledger_entries WHERE entry_id = ?", (entry_id,))
    order_id_orph = cursor.fetchone()["order_id"]
    
    cursor.execute("SELECT status FROM orders WHERE order_id = ?", (order_id_orph,))
    order_status = cursor.fetchone()["status"]
    assert order_status == "paid", f"Manual order status should be paid, got {order_status}"
    
    # Verify anomaly resolved
    cursor.execute("SELECT status, resolved_at FROM anomalies WHERE anomaly_id = ?", (anomaly_id_orphaned,))
    row = cursor.fetchone()
    assert row["status"] == "resolved", "Orphaned credit anomaly should be resolved"
    print(f"Verified orphaned credit resolved (Created manual order: {order_id_orph}, Anomaly status: {row['status']}).")
    conn.close()
    print("[5/6] Test 3 (Orphaned Credit & Manual Order Resolution) PASSED.")


    # 6. Test Balance Mismatch Anomaly
    print("\n--- Test 4: Simulating Balance Mismatch ---")
    
    # Corrupt balance
    status, _ = post_json(f"{BASE_URL}/api/simulate/corrupt_balance")
    assert status == 200
    print("Corrupted cached stored balance.")
    
    # Trigger recon
    status, _ = post_json(f"{BASE_URL}/api/simulate/reconcile")
    assert status == 200
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find balance mismatch anomaly
    cursor.execute("SELECT * FROM anomalies WHERE type = 'balance_mismatch' AND status = 'active'")
    anomaly = cursor.fetchone()
    assert anomaly is not None, "Balance mismatch anomaly was not detected"
    anomaly_id_mismatch = anomaly["anomaly_id"]
    print(f"Detected balance mismatch anomaly. Description: '{anomaly['description']}'")

    # Test Resolution: Force sync balance
    status, res_data = post_json(f"{BASE_URL}/api/resolve/balance_mismatch", {"anomaly_id": anomaly_id_mismatch})
    assert status == 200, f"Failed to resolve balance mismatch, got status {status}"
    
    # Verify anomaly resolved
    cursor.execute("SELECT status FROM anomalies WHERE anomaly_id = ?", (anomaly_id_mismatch,))
    status = cursor.fetchone()["status"]
    assert status == "resolved", "Balance mismatch anomaly should be resolved"
    print(f"Verified balance mismatch anomaly resolved. Anomaly status: {status}")
    conn.close()
    print("[6/6] Test 4 (Balance Mismatch & Force Sync Resolution) PASSED.")

    print("\n==================================================")
    print("ALL INTEGRATION TESTS COMPLETED SUCCESSFULLY!      ")
    print("==================================================")

if __name__ == "__main__":
    verify_all()
