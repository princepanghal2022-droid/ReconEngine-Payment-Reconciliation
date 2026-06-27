import sqlite3
import os
from datetime import datetime, timedelta

import os

if os.environ.get("VERCEL"):
    DB_PATH = "/tmp/payment_system.db"
else:
    DB_PATH = "payment_system.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(force=False):
    # If DB exists and we are not forcing recreate, do not reset it
    if os.path.exists(DB_PATH) and not force:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending', 'paid', 'stalled', 'cancelled')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ledger_entries (
        entry_id TEXT PRIMARY KEY,
        order_id TEXT,
        account_id TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('credit', 'debit')),
        created_at TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ledger_balances (
        account_id TEXT PRIMARY KEY,
        stored_balance REAL NOT NULL,
        currency TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS anomalies (
        anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL CHECK(type IN ('orphaned_credit', 'stalled_order', 'balance_mismatch')),
        reference_id TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active', 'resolved')),
        suggested_action TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    );
    """)

    # Seed initial mock data
    now = datetime.now()
    
    # 1. Clear tables if they have data
    cursor.execute("DELETE FROM orders;")
    cursor.execute("DELETE FROM ledger_entries;")
    cursor.execute("DELETE FROM ledger_balances;")
    cursor.execute("DELETE FROM anomalies;")

    # 2. Add orders
    # Successful order
    cursor.execute(
        "INSERT INTO orders (order_id, amount, currency, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("ord_001", 250.00, "USD", "paid", (now - timedelta(minutes=5)).isoformat(), (now - timedelta(minutes=5)).isoformat())
    )
    # Stalled order (created 120 seconds ago, still pending)
    cursor.execute(
        "INSERT INTO orders (order_id, amount, currency, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("ord_002", 75.50, "USD", "pending", (now - timedelta(seconds=120)).isoformat(), (now - timedelta(seconds=120)).isoformat())
    )
    # Healthy pending order (created 5 seconds ago)
    cursor.execute(
        "INSERT INTO orders (order_id, amount, currency, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("ord_003", 120.00, "USD", "pending", (now - timedelta(seconds=5)).isoformat(), (now - timedelta(seconds=5)).isoformat())
    )

    # 3. Add Ledger Entries
    # Entry for ord_001 (successful credit)
    cursor.execute(
        "INSERT INTO ledger_entries (entry_id, order_id, account_id, amount, currency, direction, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("ent_001", "ord_001", "acc_main", 250.00, "USD", "credit", (now - timedelta(minutes=5)).isoformat())
    )

    # 4. Add Ledger Balances
    # Stored balance is correct: matching the sum of ledger entries (250.00)
    cursor.execute(
        "INSERT INTO ledger_balances (account_id, stored_balance, currency, updated_at) VALUES (?, ?, ? ,?)",
        ("acc_main", 250.00, "USD", now.isoformat())
    )

    conn.commit()
    conn.close()
    print("Database initialized and seeded.")

if __name__ == "__main__":
    init_db(force=True)
