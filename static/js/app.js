// SSE Connection State
let eventSource = null;

// Initialize when page loads
document.addEventListener("DOMContentLoaded", () => {
    initSSE();
});

// Setup Server-Sent Events (SSE) Connection
function initSSE() {
    const statusDot = document.querySelector(".status-dot");
    const statusLabel = document.querySelector(".status-label");
    const connectionStatus = document.getElementById("connection-status");

    eventSource = new EventSource("/api/events");

    eventSource.onopen = () => {
        statusDot.className = "status-dot pulsing";
        statusLabel.textContent = "LIVE SYNC ACTIVE";
        connectionStatus.className = "connection-status";
        console.log("SSE connected successfully.");
    };

    eventSource.onerror = (err) => {
        statusDot.className = "status-dot";
        statusLabel.textContent = "OFFLINE - RECONNECTING";
        connectionStatus.className = "connection-status offline";
        console.error("SSE connection lost. Reconnecting...", err);
    };

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateDashboard(data);
        } catch (e) {
            console.error("Error parsing SSE state update:", e);
        }
    };
}

// Update the Entire Dashboard State
function updateDashboard(state) {
    updateAnomalies(state.anomalies);
    updateOrdersTable(state.orders);
    updateEntriesTable(state.ledger_entries);
    updateBalancesTable(state.ledger_balances);
}

// 1. Render Anomalies list
function updateAnomalies(anomalies) {
    const listEl = document.getElementById("anomaly-list");
    const countEl = document.getElementById("anomaly-count");
    
    // Count active anomalies
    const activeCount = anomalies.filter(a => a.status === 'active').length;
    countEl.textContent = `${activeCount} Active`;
    if (activeCount === 0) {
        countEl.className = "anomaly-count-badge zero";
    } else {
        countEl.className = "anomaly-count-badge";
    }

    if (anomalies.length === 0) {
        listEl.innerHTML = `
            <div class="empty-state">
                <span class="empty-state-icon">🛡️</span>
                <h3>System Healthy</h3>
                <p>No anomalies found. All ledger balances and orders are in perfect alignment.</p>
            </div>
        `;
        return;
    }

    listEl.innerHTML = "";
    anomalies.forEach(anomaly => {
        const card = document.createElement("div");
        card.className = `anomaly-alert-card ${anomaly.type} ${anomaly.status === 'resolved' ? 'resolved' : ''}`;
        
        // Format dates
        const createdTime = formatDateTime(anomaly.created_at);
        const resolvedTime = anomaly.resolved_at ? formatDateTime(anomaly.resolved_at) : null;
        
        // Set Header Title
        let typeTitle = "";
        if (anomaly.type === 'orphaned_credit') typeTitle = "⚠️ Orphaned Credit";
        else if (anomaly.type === 'stalled_order') typeTitle = "⏳ Stalled Order";
        else if (anomaly.type === 'balance_mismatch') typeTitle = "❌ Balance Mismatch";

        // Set action buttons based on anomaly type
        let actionButtons = "";
        if (anomaly.status === 'active') {
            if (anomaly.type === 'orphaned_credit') {
                actionButtons = `
                    <div class="anomaly-actions">
                        <button class="btn btn-primary btn-sm" onclick="resolveOrphaned(${anomaly.anomaly_id}, 'create_order')">🛒 Create Manual Order</button>
                        <button class="btn btn-secondary btn-sm" onclick="resolveOrphaned(${anomaly.anomaly_id}, 'refund')">💸 Refund Credit</button>
                    </div>
                `;
            } else if (anomaly.type === 'stalled_order') {
                actionButtons = `
                    <div class="anomaly-actions">
                        <button class="btn btn-secondary btn-sm" onclick="resolveStalled(${anomaly.anomaly_id}, 'pay')">💵 Simulate Pay Webhook</button>
                        <button class="btn btn-danger btn-sm" onclick="resolveStalled(${anomaly.anomaly_id}, 'cancel')">🚫 Cancel Order</button>
                    </div>
                `;
            } else if (anomaly.type === 'balance_mismatch') {
                actionButtons = `
                    <div class="anomaly-actions">
                        <button class="btn btn-primary btn-sm" onclick="resolveBalance(${anomaly.anomaly_id})">⚙️ Force Sync Stored Balance</button>
                    </div>
                `;
            }
        } else {
            actionButtons = `
                <div class="anomaly-actions">
                    <span style="color: var(--color-success); font-size: 0.75rem; font-weight: 700;">
                        Resolved at ${resolvedTime}
                    </span>
                </div>
            `;
        }

        card.innerHTML = `
            <div class="anomaly-meta">
                <span class="anomaly-type-title">${typeTitle}</span>
                <span class="anomaly-time">${createdTime}</span>
            </div>
            <p class="anomaly-desc">${anomaly.description}</p>
            ${actionButtons}
        `;
        
        listEl.appendChild(card);
    });
}

// 2. Render Orders Table
function updateOrdersTable(orders) {
    const tbody = document.getElementById("table-orders-body");
    if (orders.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--color-text-muted);">No orders in database.</td></tr>`;
        return;
    }
    tbody.innerHTML = orders.map(order => `
        <tr>
            <td style="font-weight: 600;">${order.order_id}</td>
            <td>${order.amount.toFixed(2)}</td>
            <td>${order.currency}</td>
            <td><span class="badge badge-${order.status}">${order.status}</span></td>
            <td style="color: var(--color-text-muted);">${formatDateTime(order.created_at)}</td>
        </tr>
    `).join("");
}

// 3. Render Ledger Entries Table
function updateEntriesTable(entries) {
    const tbody = document.getElementById("table-entries-body");
    if (entries.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--color-text-muted);">No ledger entries in database.</td></tr>`;
        return;
    }
    tbody.innerHTML = entries.map(entry => `
        <tr>
            <td style="font-family: monospace;">${entry.entry_id}</td>
            <td>${entry.order_id || '<span style="color: var(--color-text-muted);">None (Orphaned)</span>'}</td>
            <td>${entry.account_id}</td>
            <td>${entry.amount.toFixed(2)} ${entry.currency}</td>
            <td><span class="badge badge-direction-${entry.direction}">${entry.direction}</span></td>
            <td style="color: var(--color-text-muted);">${formatDateTime(entry.created_at)}</td>
        </tr>
    `).join("");
}

// 4. Render Ledger Balances Table
function updateBalancesTable(balances) {
    const tbody = document.getElementById("table-balances-body");
    if (balances.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--color-text-muted);">No ledger balances in database.</td></tr>`;
        return;
    }
    tbody.innerHTML = balances.map(balance => `
        <tr>
            <td style="font-weight: 600;">${balance.account_id}</td>
            <td style="font-family: monospace; font-size: 0.95rem;">${balance.stored_balance.toFixed(2)}</td>
            <td>${balance.currency}</td>
            <td style="color: var(--color-text-muted);">${formatDateTime(balance.updated_at)}</td>
        </tr>
    `).join("");
}

// --- INTERACTION & RESOLUTION API CALLS ---

function simulateOrder() {
    postJSON("/api/simulate/order", {})
        .then(data => showToast(`Created pending order ${data.order_id} of $${data.amount.toFixed(2)}`))
        .catch(err => showToast(`Error simulating order: ${err.message}`));
}

function simulateWebhookValid() {
    postJSON("/api/simulate/webhook/valid", {})
        .then(data => showToast(`Valid Webhook Success: Paid order & posted ledger.`))
        .catch(err => showToast(`Simulation failed: ${err.message}`));
}

function simulateWebhookOrphaned() {
    postJSON("/api/simulate/webhook/orphaned", {})
        .then(data => showToast(`Orphaned Webhook sent. Ledger posted. Check active anomalies!`))
        .catch(err => showToast(`Simulation failed: ${err.message}`));
}

function simulateCorruptBalance() {
    postJSON("/api/simulate/corrupt_balance", {})
        .then(data => showToast(data.message))
        .catch(err => showToast(`Balance corruption failed: ${err.message}`));
}

function runReconciliationNow() {
    postJSON("/api/simulate/reconcile", {})
        .then(data => {
            const list = data.anomalies_detected;
            if (list.length === 0) {
                showToast("Reconciliation run: No new anomalies found.");
            } else {
                showToast(`Reconciliation run: ${list.length} update(s) detected.`);
            }
        })
        .catch(err => showToast(`Reconciliation error: ${err.message}`));
}

// Resolving Anomaly Calls
function resolveOrphaned(anomalyId, action) {
    postJSON("/api/resolve/orphaned_credit", { anomaly_id: anomalyId, action: action })
        .then(data => showToast(data.message))
        .catch(err => showToast(`Failed to resolve orphaned credit: ${err.message}`));
}

function resolveStalled(anomalyId, action) {
    postJSON("/api/resolve/stalled_order", { anomaly_id: anomalyId, action: action })
        .then(data => showToast(data.message))
        .catch(err => showToast(`Failed to resolve stalled order: ${err.message}`));
}

function resolveBalance(anomalyId) {
    postJSON("/api/resolve/balance_mismatch", { anomaly_id: anomalyId })
        .then(data => showToast(data.message))
        .catch(err => showToast(`Failed to resolve balance mismatch: ${err.message}`));
}

// --- UTILITY FUNCTIONS ---

// POST Request Helper
function postJSON(url, payload) {
    return fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    }).then(res => {
        if (!res.ok) {
            return res.json().then(data => { throw new Error(data.message || "Request failed"); });
        }
        return res.json();
    });
}

// Tab switcher
function switchTab(tabName) {
    // Switch active button classes
    const buttons = document.querySelectorAll(".tab-btn");
    buttons.forEach(btn => btn.classList.remove("active"));
    
    // Find active button and add class
    event.target.classList.add("active");

    // Hide all contents
    const contents = document.querySelectorAll(".tab-content");
    contents.forEach(c => c.classList.add("hidden"));

    // Show selected content
    document.getElementById(`tab-${tabName}`).classList.remove("hidden");
}

// Helper to format ISO timestamps nicely
function formatDateTime(isoString) {
    if (!isoString) return "";
    try {
        const date = new Date(isoString);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' ' + date.toLocaleDateString([], { month: 'short', day: 'numeric' });
    } catch (e) {
        return isoString;
    }
}

// Show Toast message
function showToast(message) {
    const toast = document.getElementById("toast");
    const toastMsg = document.getElementById("toast-message");
    
    toastMsg.textContent = message;
    toast.className = "toast"; // remove hidden

    // Clear previous timeouts if click is fast
    if (window.toastTimeout) {
        clearTimeout(window.toastTimeout);
    }

    window.toastTimeout = setTimeout(() => {
        toast.className = "toast hidden";
    }, 4000);
}
