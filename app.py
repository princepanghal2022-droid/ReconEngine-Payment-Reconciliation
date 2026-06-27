import os
import json
import time
import queue
import threading
from datetime import datetime
from flask import Flask, request, jsonify, render_template, Response, send_from_directory
from db import get_db_connection, init_db
from reconciliation import run_reconciliation

app = Flask(__name__, static_folder='static', template_folder='templates')
# Initialize database when app is imported by Vercel
try:
    init_db()
    run_reconciliation()
except Exception as e:
    print("Startup initialization error:", e)

# Queue system for Server-Sent Events (SSE)
sse_clients = []

def broadcast_state():
    """
    Fetches the latest state from the database and broadcasts it to all connected SSE clients.
    """
    state = get_system_state()
    data = json.dumps(state)
    for q in sse_clients[:]:
        try:
            q.put(f"data: {data}\n\n")
        except Exception:
            sse_clients.remove(q)

def get_system_state():
    """
    Fetches all tables from SQLite to represent the entire system state.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM orders ORDER BY created_at DESC;")
    orders = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM ledger_entries ORDER BY created_at DESC;")
    ledger_entries = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM ledger_balances ORDER BY updated_at DESC;")
    ledger_balances = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM anomalies ORDER BY status ASC, created_at DESC;")
    anomalies = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return {
        "orders": orders,
        "ledger_entries": ledger_entries,
        "ledger_balances": ledger_balances,
        "anomalies": anomalies
    }

# --- SSE ROUTE ---
@app.route('/api/events')
def events():
    """
    SSE stream endpoint. Sends the initial database state immediately upon connection,
    then listens to the broadcast queue to stream subsequent updates.
    """
    def event_stream():
        q = queue.Queue()
        sse_clients.append(q)
        
        # Send initial state immediately
        initial_state = json.dumps(get_system_state())
        yield f"data: {initial_state}\n\n"
        
        try:
            while True:
                msg = q.get()
                yield msg
        except GeneratorExit:
            sse_clients.remove(q)

    return Response(event_stream(), content_type='text/event-stream')

# --- STATIC & UI ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

# --- WEBHOOK RECEIVER ---
@app.route('/api/webhook', methods=['POST'])
def webhook():
    """
    Accepts incoming payment succeeded webhooks, inserts ledger entries,
    updates order status, and updates balances.
    """
    data = request.get_json() or {}
    event = data.get("event")
    event_data = data.get("data", {})
    
    if event != "payment.succeeded":
        return jsonify({"status": "error", "message": "Unknown event"}), 400
        
    order_id = event_data.get("order_id")
    amount = event_data.get("amount")
    currency = event_data.get("currency")
    payment_id = event_data.get("payment_id")
    
    if not order_id or amount is None or not currency:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    try:
        # Check if order exists
        cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        order = cursor.fetchone()
        
        # Create ledger entry
        entry_id = payment_id or f"ent_{int(time.time() * 1000)}"
        cursor.execute(
            "INSERT INTO ledger_entries (entry_id, order_id, account_id, amount, currency, direction, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_id, order_id, "acc_main", amount, currency, "credit", now)
        )
        
        # Update balance
        cursor.execute("SELECT stored_balance FROM ledger_balances WHERE account_id = ?", ("acc_main",))
        balance_row = cursor.fetchone()
        if balance_row:
            new_balance = balance_row['stored_balance'] + amount
            cursor.execute(
                "UPDATE ledger_balances SET stored_balance = ?, updated_at = ? WHERE account_id = ?",
                (new_balance, now, "acc_main")
            )
        else:
            cursor.execute(
                "INSERT INTO ledger_balances (account_id, stored_balance, currency, updated_at) VALUES (?, ?, ?, ?)",
                ("acc_main", amount, currency, now)
            )
            
        if order:
            cursor.execute(
                "UPDATE orders SET status = 'paid', updated_at = ? WHERE order_id = ?",
                (now, order_id)
            )
            message = "Webhook processed. Order marked as paid."
        else:
            # Order does not exist. Ledger entry is created, which will trigger an Orphaned Credit anomaly.
            message = "Webhook processed. Order not found. Orphaned ledger entry created."
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()
        
    broadcast_state()
    return jsonify({"status": "success", "message": message})

# --- SIMULATION ENDPOINTS ---
@app.route('/api/simulate/order', methods=['POST'])
def simulate_order():
    """
    Creates a new pending order to simulate a customer checkout.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    import random
    order_id = f"ord_{random.randint(100, 999)}"
    amount = round(random.uniform(10.0, 500.0), 2)
    currency = "USD"
    now = datetime.now().isoformat()
    
    cursor.execute(
        "INSERT INTO orders (order_id, amount, currency, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (order_id, amount, currency, "pending", now, now)
    )
    conn.commit()
    conn.close()
    
    broadcast_state()
    return jsonify({"status": "success", "order_id": order_id, "amount": amount})

@app.route('/api/simulate/webhook/valid', methods=['POST'])
def simulate_webhook_valid():
    """
    Finds the most recent pending order and sends a webhook to pay it.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE status = 'pending' ORDER BY created_at DESC LIMIT 1;")
    order = cursor.fetchone()
    conn.close()
    
    if not order:
        return jsonify({"status": "error", "message": "No pending orders found. Create one first."}), 400
        
    import random
    payment_id = f"pay_{random.randint(1000, 9999)}"
    payload = {
        "event": "payment.succeeded",
        "data": {
            "order_id": order['order_id'],
            "amount": order['amount'],
            "currency": order['currency'],
            "payment_id": payment_id
        }
    }
    
    # Send internally using the Flask test client
    with app.test_client() as client:
        res = client.post('/api/webhook', json=payload)
        return res.data, res.status_code

@app.route('/api/simulate/webhook/orphaned', methods=['POST'])
def simulate_webhook_orphaned():
    """
    Simulates a webhook event with a non-existent order_id, causing an orphaned credit entry.
    """
    import random
    fake_order_id = f"ord_fake_{random.randint(1000, 9999)}"
    amount = round(random.uniform(50.0, 300.0), 2)
    payment_id = f"pay_orph_{random.randint(1000, 9999)}"
    
    payload = {
        "event": "payment.succeeded",
        "data": {
            "order_id": fake_order_id,
            "amount": amount,
            "currency": "USD",
            "payment_id": payment_id
        }
    }
    
    with app.test_client() as client:
        res = client.post('/api/webhook', json=payload)
        return res.data, res.status_code

@app.route('/api/simulate/corrupt_balance', methods=['POST'])
def simulate_corrupt_balance():
    """
    Intentionally corrupts the cached ledger balance to test the balance mismatch logic.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    cursor.execute("SELECT * FROM ledger_balances WHERE account_id = ?;", ("acc_main",))
    row = cursor.fetchone()
    
    if row:
        import random
        offset = round(random.choice([-100.0, 50.0, 100.0]), 2)
        new_balance = row['stored_balance'] + offset
        cursor.execute(
            "UPDATE ledger_balances SET stored_balance = ?, updated_at = ? WHERE account_id = ?",
            (new_balance, now, "acc_main")
        )
        msg = f"Corrupted stored balance. Changed by {offset} to {new_balance}."
    else:
        cursor.execute(
            "INSERT INTO ledger_balances (account_id, stored_balance, currency, updated_at) VALUES (?, ?, ?, ?)",
            ("acc_main", 500.00, "USD", now)
        )
        msg = "Created balance cache with 500.00 (no ledger entries exist, mismatch created)."
        
    conn.commit()
    conn.close()
    broadcast_state()
    return jsonify({"status": "success", "message": msg})

@app.route('/api/simulate/reconcile', methods=['POST'])
def simulate_reconcile():
    """
    Triggers the reconciliation job manually so the user does not have to wait 60s.
    """
    try:
        anomalies = run_reconciliation()
        broadcast_state()
        return jsonify({"status": "success", "anomalies_detected": anomalies})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- RESOLUTION ENDPOINTS ---
@app.route('/api/resolve/orphaned_credit', methods=['POST'])
def resolve_orphaned_credit():
    """
    Resolves an orphaned credit anomaly.
    Actions:
    - create_order: Creates a paid order in the database matching the orphaned ledger entry.
    - refund: Creates a debit entry to offset the ledger entry and adjusts the balance.
    """
    data = request.get_json() or {}
    anomaly_id = data.get("anomaly_id")
    action = data.get("action")
    
    if not anomaly_id or not action:
        return jsonify({"status": "error", "message": "Missing anomaly_id or action"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM anomalies WHERE anomaly_id = ? AND status = 'active';", (anomaly_id,))
        anomaly = cursor.fetchone()
        if not anomaly or anomaly['type'] != 'orphaned_credit':
            return jsonify({"status": "error", "message": "Active orphaned credit anomaly not found"}), 404
            
        entry_id = anomaly['reference_id']
        cursor.execute("SELECT * FROM ledger_entries WHERE entry_id = ?;", (entry_id,))
        entry = cursor.fetchone()
        if not entry:
            return jsonify({"status": "error", "message": "Ledger entry not found"}), 404
            
        now = datetime.now().isoformat()
        
        if action == "create_order":
            cursor.execute(
                "INSERT INTO orders (order_id, amount, currency, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (entry['order_id'], entry['amount'], entry['currency'], "paid", now, now)
            )
            msg = f"Created order '{entry['order_id']}' to match orphaned credit."
        elif action == "refund":
            import random
            refund_id = f"ent_ref_{random.randint(1000, 9999)}"
            # Insert debit entry
            cursor.execute(
                "INSERT INTO ledger_entries (entry_id, order_id, account_id, amount, currency, direction, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (refund_id, entry['order_id'], entry['account_id'], entry['amount'], entry['currency'], "debit", now)
            )
            # Reduce balance
            cursor.execute("SELECT stored_balance FROM ledger_balances WHERE account_id = ?;", (entry['account_id'],))
            bal_row = cursor.fetchone()
            if bal_row:
                new_bal = bal_row['stored_balance'] - entry['amount']
                cursor.execute(
                    "UPDATE ledger_balances SET stored_balance = ?, updated_at = ? WHERE account_id = ?;",
                    (new_bal, now, entry['account_id'])
                )
            # Detach entry order_id to clear orphan
            cursor.execute("UPDATE ledger_entries SET order_id = NULL WHERE entry_id = ?;", (entry_id,))
            msg = f"Refunded ledger entry {entry_id} via debit entry {refund_id}."
        else:
            return jsonify({"status": "error", "message": "Invalid action"}), 400
            
        conn.commit()
        # Trigger reconciliation to auto-resolve
        run_reconciliation()
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()
        
    broadcast_state()
    return jsonify({"status": "success", "message": msg})

@app.route('/api/resolve/stalled_order', methods=['POST'])
def resolve_stalled_order():
    """
    Resolves a stalled order anomaly.
    Actions:
    - cancel: Cancels the stalled order.
    - pay: Force-pays the stalled order.
    """
    data = request.get_json() or {}
    anomaly_id = data.get("anomaly_id")
    action = data.get("action")
    
    if not anomaly_id or not action:
        return jsonify({"status": "error", "message": "Missing anomaly_id or action"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM anomalies WHERE anomaly_id = ? AND status = 'active';", (anomaly_id,))
        anomaly = cursor.fetchone()
        if not anomaly or anomaly['type'] != 'stalled_order':
            return jsonify({"status": "error", "message": "Active stalled order anomaly not found"}), 404
            
        order_id = anomaly['reference_id']
        now = datetime.now().isoformat()
        
        if action == "cancel":
            cursor.execute(
                "UPDATE orders SET status = 'cancelled', updated_at = ? WHERE order_id = ?;",
                (now, order_id)
            )
            msg = f"Order '{order_id}' has been cancelled."
            conn.commit()
            run_reconciliation()
        elif action == "pay":
            cursor.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
            order = cursor.fetchone()
            if not order:
                return jsonify({"status": "error", "message": "Order not found"}), 404
            
            conn.commit() # release write lock
            
            import random
            payment_id = f"pay_{random.randint(1000, 9999)}"
            payload = {
                "event": "payment.succeeded",
                "data": {
                    "order_id": order['order_id'],
                    "amount": order['amount'],
                    "currency": order['currency'],
                    "payment_id": payment_id
                }
            }
            
            with app.test_client() as client:
                res = client.post('/api/webhook', json=payload)
                if res.status_code != 200:
                    return res.data, res.status_code
                    
            # Run recon
            run_reconciliation()
            msg = f"Order '{order_id}' marked as paid via webhook simulation."
        else:
            return jsonify({"status": "error", "message": "Invalid action"}), 400
            
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()
        
    broadcast_state()
    return jsonify({"status": "success", "message": msg})

@app.route('/api/resolve/balance_mismatch', methods=['POST'])
def resolve_balance_mismatch():
    """
    Resolves a balance mismatch anomaly by recalculating the ledger sum.
    """
    data = request.get_json() or {}
    anomaly_id = data.get("anomaly_id")
    
    if not anomaly_id:
        return jsonify({"status": "error", "message": "Missing anomaly_id"}), 400
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM anomalies WHERE anomaly_id = ? AND status = 'active';", (anomaly_id,))
        anomaly = cursor.fetchone()
        if not anomaly or anomaly['type'] != 'balance_mismatch':
            return jsonify({"status": "error", "message": "Active balance mismatch anomaly not found"}), 404
            
        account_id = anomaly['reference_id']
        now = datetime.now().isoformat()
        
        # Calculate matching sum of entries
        cursor.execute("""
            SELECT SUM(CASE WHEN direction = 'credit' THEN amount WHEN direction = 'debit' THEN -amount ELSE 0.0 END) as calculated_balance
            FROM ledger_entries
            WHERE account_id = ?;
        """, (account_id,))
        calc_row = cursor.fetchone()
        calculated_balance = calc_row['calculated_balance'] if calc_row and calc_row['calculated_balance'] is not None else 0.0
        
        # Update stored_balance to match calculated
        cursor.execute(
            "UPDATE ledger_balances SET stored_balance = ?, updated_at = ? WHERE account_id = ?;",
            (calculated_balance, now, account_id)
        )
        msg = f"Synced balance of '{account_id}' to correct value of {calculated_balance}."
        
        conn.commit()
        run_reconciliation()
    except Exception as e:
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        conn.close()
        
    broadcast_state()
    return jsonify({"status": "success", "message": msg})

# --- SCHEDULER FOR RECONCILIATION ---
def start_reconciliation_scheduler():
    def run_scheduler():
        print("Reconciliation scheduler thread started.")
        while True:
            try:
                time.sleep(60)
                print("Running scheduled 60-second reconciliation...")
                anomalies = run_reconciliation()
                if anomalies:
                    print(f"Scheduled reconciliation found anomalies: {anomalies}")
                broadcast_state()
            except Exception as e:
                print(f"Error in scheduled reconciliation: {e}")
                time.sleep(10)

    thread = threading.Thread(target=run_scheduler, daemon=True)
    thread.start()

if __name__ == '__main__':
    # Initialize DB (creates database and seeds mock data if they don't exist)
    init_db()
    
    # Run initial reconciliation on start to catch seed anomalies
    run_reconciliation()
    
    # Start the background thread for scheduled 60s reconciliation
    start_reconciliation_scheduler()
    
    # Start the Flask app
    app.run(host='127.0.0.1', port=5000, debug=False)
