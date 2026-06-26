from datetime import datetime, timedelta
import sqlite3
from db import get_db_connection

def run_reconciliation():
    """
    Runs the reconciliation job, detecting orphaned credits, stalled orders, 
    and balance mismatches. It inserts new active anomalies and marks 
    previously active anomalies as resolved if their issues have been corrected.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    anomalies_detected = []

    try:
        # --- 1. RECONCILE: ORPHANED CREDITS ---
        # Find ledger entries that reference an order that does not exist in the orders table.
        cursor.execute("""
            SELECT le.entry_id, le.order_id, le.amount, le.currency 
            FROM ledger_entries le
            LEFT JOIN orders o ON le.order_id = o.order_id
            WHERE le.order_id IS NOT NULL AND o.order_id IS NULL;
        """)
        orphaned_entries = cursor.fetchall()
        active_orphaned_entry_ids = set()

        for entry in orphaned_entries:
            entry_id = entry['entry_id']
            order_id = entry['order_id']
            amount = entry['amount']
            currency = entry['currency']
            active_orphaned_entry_ids.add(entry_id)

            # Check if this orphaned credit is already flagged as active
            cursor.execute(
                "SELECT anomaly_id FROM anomalies WHERE type = 'orphaned_credit' AND reference_id = ? AND status = 'active'",
                (entry_id,)
            )
            if not cursor.fetchone():
                # Raise anomaly
                desc = f"Ledger entry '{entry_id}' (Amount: {amount} {currency}) references non-existent order '{order_id}'."
                cursor.execute(
                    "INSERT INTO anomalies (type, reference_id, description, status, suggested_action, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    ("orphaned_credit", entry_id, desc, "active", "Create manual order or refund credit", now)
                )
                anomalies_detected.append(f"Orphaned credit flagged: {entry_id}")

        # Resolve orphaned credits that are no longer orphaned (i.e. order was created or entry was removed)
        cursor.execute("SELECT anomaly_id, reference_id FROM anomalies WHERE type = 'orphaned_credit' AND status = 'active'")
        for anomaly in cursor.fetchall():
            ref_id = anomaly['reference_id']
            # If the entry is no longer in the orphaned set (either order was created or entry removed)
            if ref_id not in active_orphaned_entry_ids:
                cursor.execute(
                    "UPDATE anomalies SET status = 'resolved', resolved_at = ? WHERE anomaly_id = ?",
                    (now, anomaly['anomaly_id'])
                )
                anomalies_detected.append(f"Orphaned credit resolved: {ref_id}")


        # --- 2. RECONCILE: STALLED ORDERS ---
        # Find pending orders created more than 60 seconds ago.
        cutoff_time = (datetime.now() - timedelta(seconds=60)).isoformat()
        cursor.execute("""
            SELECT order_id, amount, currency, created_at 
            FROM orders 
            WHERE status = 'pending' AND created_at < ?;
        """, (cutoff_time,))
        stalled_orders = cursor.fetchall()
        active_stalled_order_ids = set()

        for order in stalled_orders:
            order_id = order['order_id']
            amount = order['amount']
            currency = order['currency']
            active_stalled_order_ids.add(order_id)

            # Check if this stalled order is already flagged as active
            cursor.execute(
                "SELECT anomaly_id FROM anomalies WHERE type = 'stalled_order' AND reference_id = ? AND status = 'active'",
                (order_id,)
            )
            if not cursor.fetchone():
                # Raise anomaly
                desc = f"Order '{order_id}' (Amount: {amount} {currency}) is stalled in pending state for over 60s."
                cursor.execute(
                    "INSERT INTO anomalies (type, reference_id, description, status, suggested_action, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    ("stalled_order", order_id, desc, "active", "Cancel stalled order or re-request webhook", now)
                )
                anomalies_detected.append(f"Stalled order flagged: {order_id}")

        # Resolve stalled orders that are no longer stalled (status changed from pending to paid/cancelled)
        cursor.execute("SELECT anomaly_id, reference_id FROM anomalies WHERE type = 'stalled_order' AND status = 'active'")
        for anomaly in cursor.fetchall():
            ref_id = anomaly['reference_id']
            # If the order is no longer in the stalled set (either status changed or order deleted)
            if ref_id not in active_stalled_order_ids:
                cursor.execute(
                    "UPDATE anomalies SET status = 'resolved', resolved_at = ? WHERE anomaly_id = ?",
                    (now, anomaly['anomaly_id'])
                )
                anomalies_detected.append(f"Stalled order resolved: {ref_id}")


        # --- 3. RECONCILE: BALANCE MISMATCH ---
        # Compare stored_balance in ledger_balances with the sum of ledger_entries for each account.
        cursor.execute("""
            SELECT lb.account_id, lb.stored_balance, lb.currency, COALESCE(calc.calculated_balance, 0.0) as calculated_balance
            FROM ledger_balances lb
            LEFT JOIN (
                SELECT account_id,
                       SUM(CASE WHEN direction = 'credit' THEN amount WHEN direction = 'debit' THEN -amount ELSE 0.0 END) as calculated_balance
                FROM ledger_entries
                GROUP BY account_id
            ) calc ON lb.account_id = calc.account_id;
        """)
        balances = cursor.fetchall()
        active_mismatched_accounts = set()

        for bal in balances:
            account_id = bal['account_id']
            stored_val = bal['stored_balance']
            calc_val = bal['calculated_balance']
            currency = bal['currency']

            # If there is a difference greater than a small threshold (e.g. 0.001)
            if abs(stored_val - calc_val) > 0.001:
                active_mismatched_accounts.add(account_id)

                # Check if this mismatch is already flagged as active
                cursor.execute(
                    "SELECT anomaly_id FROM anomalies WHERE type = 'balance_mismatch' AND reference_id = ? AND status = 'active'",
                    (account_id,)
                )
                if not cursor.fetchone():
                    # Raise anomaly
                    desc = f"Account '{account_id}' balance mismatch. Stored: {stored_val} {currency}, Calculated: {calc_val} {currency}."
                    cursor.execute(
                        "INSERT INTO anomalies (type, reference_id, description, status, suggested_action, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        ("balance_mismatch", account_id, desc, "active", "Force sync stored balance with ledger", now)
                    )
                    anomalies_detected.append(f"Balance mismatch flagged: {account_id}")

        # Resolve balance mismatches that have been corrected
        cursor.execute("SELECT anomaly_id, reference_id FROM anomalies WHERE type = 'balance_mismatch' AND status = 'active'")
        for anomaly in cursor.fetchall():
            ref_id = anomaly['reference_id']
            # If the account is no longer in the mismatch set (balance fixed)
            if ref_id not in active_mismatched_accounts:
                cursor.execute(
                    "UPDATE anomalies SET status = 'resolved', resolved_at = ? WHERE anomaly_id = ?",
                    (now, anomaly['anomaly_id'])
                )
                anomalies_detected.append(f"Balance mismatch resolved: {ref_id}")

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error in reconciliation job: {e}")
        raise e
    finally:
        conn.close()

    return anomalies_detected

if __name__ == "__main__":
    print("Running test reconciliation...")
    results = run_reconciliation()
    print("Reconciliation run output:")
    for r in results:
        print(f" - {r}")
