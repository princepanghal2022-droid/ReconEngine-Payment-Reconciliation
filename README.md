[README.md](https://github.com/user-attachments/files/29394845/README.md)
# ReconEngine - Webhook Payment Verifier & Ledger

ReconEngine is a real-time payment verification and ledger auditing system. It ingests payment events via webhooks, logs entries in a double-entry ledger, and runs an automated reconciliation job to detect discrepancies between expected payments and actual ledger records. It features a premium, live-updating glassmorphism Admin Dashboard powered by Server-Sent Events (SSE).

## 🚀 Key Features

*   **Real-time Webhook Receiver**: Ingests payment events and records entries to the ledger immediately.
*   **60-Second Automated Auditor**: A background scheduler that detects three types of anomalies:
    1.  **Stalled Orders**: Pending checkouts that have timed out without receiving a webhook.
    2.  **Orphaned Credits**: Payment events recorded in the ledger referencing orders that do not exist.
    3.  **Balance Mismatches**: Deviations between the cached ledger balance and the calculated ledger sum.
*   **Dynamic Admin UI**: Real-time dashboard that displays active anomalies and live database table viewers without requiring manual browser refreshes.
*   **Suggested Actions Flow**: Interactive resolution panel allowing admins to cancel stalled orders, generate manual matching orders for orphaned payments, or sync corrupted ledger balances.
*   **Automated Verification Suite**: A self-contained script testing all application flows and state transitions.

## 🛠️ Technology Stack

*   **Backend**: Python 3, Flask (Web server & API), SQLite (Embedded relational database)
*   **Frontend**: HTML5, Vanilla CSS3 (Glassmorphism design system), JavaScript (Server-Sent Events connection)
*   **Threading**: Standard Python `threading` for background reconciliation scheduler

## 📁 Project Directory Structure

```text
├── app.py                  # Main Flask app (Server, APIs, & Scheduler)
├── db.py                   # SQLite database setup & seed data
├── reconciliation.py       # Core reconciliation audit checks & resolutions
├── verify_system.py        # Complete automated integration test suite
├── templates/
│   └── index.html          # Admin Dashboard layout
├── static/
│   ├── css/
│   │   └── style.css       # Premium dark mode stylesheet
│   └── js/
│       └── app.js          # Live UI logic & SSE receiver
└── requirements.txt        # Extracted DOCX text requirements summary
```

## ⚙️ How to Run Locally

### 1. Install Dependencies
Make sure Python 3 is installed. Then, install Flask:
```bash
pip install flask
```

### 2. Initialize the Database
Set up the SQLite database schema and seed mock transactions:
```bash
python db.py
```

### 3. Start the Web Server
Launch the Flask application locally:
```bash
python app.py
```
Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/) in your web browser to view the live dashboard.

### 4. Run Automated Integration Tests
In a separate terminal window, you can run the test suite to verify all functionalities:
```bash
python verify_system.py
```
