import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, jsonify, request, render_template_string
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from bot.leads import get_all_leads, update_lead
from bot.lists import (get_whitelist, get_blacklist,
                       add_to_whitelist, remove_from_whitelist,
                       add_to_blacklist, remove_from_blacklist)
from bot.whatsapp import send_message

IST       = ZoneInfo("Asia/Kolkata")
dashboard = Blueprint("dashboard", __name__)
auth      = HTTPBasicAuth()

DASHBOARD_USER = os.environ.get("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.environ.get("DASHBOARD_PASS", "clinic123")
USERS = {DASHBOARD_USER: generate_password_hash(DASHBOARD_PASS)}


@auth.verify_password
def verify_password(username, password):
    if username in USERS and check_password_hash(USERS[username], password):
        return username


# ── Dashboard HTML ────────────────────────────────────────────────────────────
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Clinic Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: sans-serif; background: #f5f7fa; color: #333; }
  header { background: #2563eb; color: white; padding: 16px 24px;
           display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 20px; }
  nav { display: flex; gap: 8px; padding: 16px 24px; background: white;
        border-bottom: 1px solid #e5e7eb; flex-wrap: wrap; }
  nav button { padding: 8px 16px; border: none; border-radius: 6px;
               cursor: pointer; font-size: 14px; font-weight: 500;
               background: #f3f4f6; color: #374151; }
  nav button.active { background: #2563eb; color: white; }
  .section { display: none; padding: 24px; }
  .section.active { display: block; }
  table { width: 100%; border-collapse: collapse; background: white;
          border-radius: 10px; overflow: hidden;
          box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
  th { background: #f9fafb; padding: 12px 14px; text-align: left;
       font-size: 12px; color: #6b7280; text-transform: uppercase; }
  td { padding: 12px 14px; border-top: 1px solid #f3f4f6; font-size: 14px; }
  tr:hover td { background: #f9fafb; }
  .badge { padding: 3px 10px; border-radius: 20px; font-size: 12px;
           font-weight: 600; display: inline-block; }
  .badge.pending   { background: #fef3c7; color: #92400e; }
  .badge.confirmed { background: #d1fae5; color: #065f46; }
  .badge.cancelled { background: #fee2e2; color: #991b1b; }
  .badge.completed { background: #dbeafe; color: #1e40af; }
  .badge.noshow    { background: #f3f4f6; color: #6b7280; }
  .btn { padding: 6px 12px; border-radius: 6px; border: none;
         cursor: pointer; font-size: 13px; font-weight: 500; }
  .btn-green  { background: #d1fae5; color: #065f46; }
  .btn-red    { background: #fee2e2; color: #991b1b; }
  .btn-blue   { background: #dbeafe; color: #1e40af; }
  .btn-gray   { background: #f3f4f6; color: #374151; }
  .card { background: white; border-radius: 10px; padding: 20px;
          box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 16px; }
  .input-row { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  input[type=text] { padding: 8px 12px; border: 1px solid #d1d5db;
                     border-radius: 6px; font-size: 14px; flex: 1; min-width: 200px; }
  h2 { font-size: 18px; margin-bottom: 16px; color: #111; }
  .stats { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 24px; }
  .stat { background: white; border-radius: 10px; padding: 16px 20px;
          box-shadow: 0 1px 4px rgba(0,0,0,0.08); min-width: 120px; }
  .stat .num { font-size: 28px; font-weight: 700; color: #2563eb; }
  .stat .label { font-size: 13px; color: #6b7280; margin-top: 2px; }
  .empty { padding: 40px; text-align: center; color: #9ca3af; }
</style>
</head>
<body>

<header>
  <h1>🏥 Clinic Dashboard</h1>
  <span id="clock" style="font-size:14px;opacity:0.8"></span>
</header>

<nav>
  <button class="active" onclick="show('leads')">Leads</button>
  <button onclick="show('whitelist')">Whitelist</button>
  <button onclick="show('blacklist')">Blacklist</button>
</nav>

<!-- LEADS -->
<div id="leads" class="section active">
  <div class="stats" id="stats"></div>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Name</th><th>Phone</th><th>Problem</th>
        <th>Preferred Time</th><th>Confirmed Time</th>
        <th>Status</th><th>Received</th><th>Actions</th>
      </tr>
    </thead>
    <tbody id="leads-body">
      <tr><td colspan="9" class="empty">Loading...</td></tr>
    </tbody>
  </table>
</div>

<!-- WHITELIST -->
<div id="whitelist" class="section">
  <div class="card">
    <h2>Whitelist — Family / Staff (bot stays silent)</h2>
    <div class="input-row">
      <input type="text" id="wl-phone" placeholder="+91XXXXXXXXXX">
      <input type="text" id="wl-note"  placeholder="Note (optional)">
      <button class="btn btn-green" onclick="addToList('whitelist')">Add</button>
    </div>
    <table>
      <thead><tr><th>Phone</th><th>Note</th><th>Remove</th></tr></thead>
      <tbody id="wl-body"><tr><td colspan="3" class="empty">Loading...</td></tr></tbody>
    </table>
  </div>
</div>

<!-- BLACKLIST -->
<div id="blacklist" class="section">
  <div class="card">
    <h2>Blacklist — Spam / Unwanted (one message then silent)</h2>
    <div class="input-row">
      <input type="text" id="bl-phone" placeholder="+91XXXXXXXXXX">
      <input type="text" id="bl-note"  placeholder="Note (optional)">
      <button class="btn btn-red" onclick="addToList('blacklist')">Add</button>
    </div>
    <table>
      <thead><tr><th>Phone</th><th>Note</th><th>Remove</th></tr></thead>
      <tbody id="bl-body"><tr><td colspan="3" class="empty">Loading...</td></tr></tbody>
    </table>
  </div>
</div>

<script>
function show(id) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  event.target.classList.add('active');
  if (id === 'leads')     loadLeads();
  if (id === 'whitelist') loadList('whitelist');
  if (id === 'blacklist') loadList('blacklist');
}

// ── Clock ──────────────────────────────────────────────────────────────────
function updateClock() {
  document.getElementById('clock').textContent =
    new Date().toLocaleString('en-IN', {timeZone:'Asia/Kolkata'});
}
setInterval(updateClock, 1000);
updateClock();

// ── Leads ──────────────────────────────────────────────────────────────────
async function loadLeads() {
  const r    = await fetch('/api/leads');
  const data = await r.json();
  const body = document.getElementById('leads-body');

  // Stats
  const total     = data.length;
  const pending   = data.filter(l => l.status === 'pending').length;
  const confirmed = data.filter(l => l.status === 'confirmed').length;
  const completed = data.filter(l => l.status === 'completed').length;
  const noshow    = data.filter(l => l.status === 'noshow').length;

  document.getElementById('stats').innerHTML = `
    <div class="stat"><div class="num">${total}</div><div class="label">Total Leads</div></div>
    <div class="stat"><div class="num">${pending}</div><div class="label">Pending</div></div>
    <div class="stat"><div class="num">${confirmed}</div><div class="label">Confirmed</div></div>
    <div class="stat"><div class="num">${completed}</div><div class="label">Completed</div></div>
    <div class="stat"><div class="num">${noshow}</div><div class="label">No Shows</div></div>
  `;

  if (!data.length) {
    body.innerHTML = '<tr><td colspan="9" class="empty">No leads yet.</td></tr>';
    return;
  }

  body.innerHTML = [...data].reverse().map(l => `
    <tr>
      <td>${l.id}</td>
      <td><strong>${l.name || '—'}</strong></td>
      <td>${l.phone}</td>
      <td>${l.problem || '—'}</td>
      <td>${l.preferred_time || '—'}</td>
      <td>${l.confirmed_time || '—'}</td>
      <td><span class="badge ${l.status}">${l.status}</span></td>
      <td>${l.timestamp || '—'}</td>
      <td style="display:flex;gap:6px;flex-wrap:wrap">
        ${l.status === 'confirmed' ? `
          <button class="btn btn-blue"
            onclick="markCompleted('${l.phone}')">✅ Done</button>
          <button class="btn btn-red"
            onclick="markNoShow('${l.phone}')">❌ No Show</button>
        ` : ''}
        ${l.status === 'completed' && !l.followup_sent ? `
          <button class="btn btn-gray"
            onclick="sendFollowup('${l.phone}')">💬 Follow-up</button>
        ` : ''}
      </td>
    </tr>
  `).join('');
}

async function markCompleted(phone) {
  await fetch('/api/leads/complete', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({phone})
  });
  loadLeads();
}

async function markNoShow(phone) {
  await fetch('/api/leads/noshow', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({phone})
  });
  loadLeads();
}

async function sendFollowup(phone) {
  await fetch('/api/leads/followup', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({phone})
  });
  loadLeads();
}

// ── Lists ──────────────────────────────────────────────────────────────────
async function loadList(type) {
  const r    = await fetch(`/api/${type}`);
  const data = await r.json();
  const body = document.getElementById(`${type === 'whitelist' ? 'wl' : 'bl'}-body`);

  if (!data.length) {
    body.innerHTML = `<tr><td colspan="3" class="empty">No entries yet.</td></tr>`;
    return;
  }

  body.innerHTML = data.map(e => {
    const phone = typeof e === 'object' ? e.phone : e;
    const note  = typeof e === 'object' ? (e.note || '—') : '—';
    return `<tr>
      <td>${phone}</td>
      <td>${note}</td>
      <td>
        <button class="btn btn-red"
          onclick="removeFromList('${type}','${phone}')">Remove</button>
      </td>
    </tr>`;
  }).join('');
}

async function addToList(type) {
  const phoneId = type === 'whitelist' ? 'wl-phone' : 'bl-phone';
  const noteId  = type === 'whitelist' ? 'wl-note'  : 'bl-note';
  const phone   = document.getElementById(phoneId).value.trim();
  const note    = document.getElementById(noteId).value.trim();
  if (!phone) return alert('Phone number required.');
  await fetch(`/api/${type}`, {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({phone, note})
  });
  document.getElementById(phoneId).value = '';
  document.getElementById(noteId).value  = '';
  loadList(type);
}

async function removeFromList(type, phone) {
  await fetch(`/api/${type}/${encodeURIComponent(phone)}`,
    {method:'DELETE'});
  loadList(type);
}

// Auto-refresh leads every 30 seconds
loadLeads();
setInterval(loadLeads, 30000);
</script>
</body>
</html>
"""


# ── Routes ────────────────────────────────────────────────────────────────────
@dashboard.route("/")
@auth.login_required
def index():
    return render_template_string(DASHBOARD_HTML)


@dashboard.route("/api/leads")
@auth.login_required
def api_leads():
    return jsonify(get_all_leads())


@dashboard.route("/api/leads/complete", methods=["POST"])
@auth.login_required
def api_complete():
    phone = (request.get_json(silent=True) or {}).get("phone", "")
    if not phone:
        return jsonify({"error": "phone required"}), 400
    update_lead(phone, status="completed")
    return jsonify({"status": "updated"})


@dashboard.route("/api/leads/noshow", methods=["POST"])
@auth.login_required
def api_noshow():
    phone = (request.get_json(silent=True) or {}).get("phone", "")
    if not phone:
        return jsonify({"error": "phone required"}), 400

    lead = None
    from bot.leads import get_lead
    lead = get_lead(phone)
    name = lead.get("name", "there") if lead else "there"

    update_lead(phone, status="noshow", noshow_sent=True)

    owner_phone = os.environ.get("CLINIC_OWNER_PHONE", "")

    # Recovery message to patient
    send_message(phone,
        f"Hello {name}, we noticed you missed your appointment today.\n\n"
        f"We'd love to help you. Would you like to book another appointment? "
        f"Just reply *BOOK* and we'll get you scheduled. 🏥")

    return jsonify({"status": "updated"})


@dashboard.route("/api/leads/followup", methods=["POST"])
@auth.login_required
def api_followup():
    phone = (request.get_json(silent=True) or {}).get("phone", "")
    if not phone:
        return jsonify({"error": "phone required"}), 400

    from bot.leads import get_lead
    lead = get_lead(phone)
    name = lead.get("name", "there") if lead else "there"

    send_message(phone,
        f"Hello {name}! 😊\n\n"
        f"Hope your treatment went well.\n\n"
        f"Would you like to book a follow-up appointment? "
        f"Reply *BOOK* and we'll get you scheduled. 🏥")

    update_lead(phone, followup_sent=True)
    return jsonify({"status": "sent"})


# ── Whitelist routes ──────────────────────────────────────────────────────────
@dashboard.route("/api/whitelist")
@auth.login_required
def api_get_whitelist():
    return jsonify(get_whitelist())


@dashboard.route("/api/whitelist", methods=["POST"])
@auth.login_required
def api_add_whitelist():
    body  = request.get_json(silent=True) or {}
    phone = body.get("phone", "").strip()
    note  = body.get("note", "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400
    add_to_whitelist(phone, note)
    return jsonify({"status": "added"})


@dashboard.route("/api/whitelist/<path:phone>", methods=["DELETE"])
@auth.login_required
def api_remove_whitelist(phone):
    remove_from_whitelist(phone)
    return jsonify({"status": "removed"})


# ── Blacklist routes ──────────────────────────────────────────────────────────
@dashboard.route("/api/blacklist")
@auth.login_required
def api_get_blacklist():
    return jsonify(get_blacklist())


@dashboard.route("/api/blacklist", methods=["POST"])
@auth.login_required
def api_add_blacklist():
    body  = request.get_json(silent=True) or {}
    phone = body.get("phone", "").strip()
    note  = body.get("note", "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400
    add_to_blacklist(phone, note)
    return jsonify({"status": "added"})


@dashboard.route("/api/blacklist/<path:phone>", methods=["DELETE"])
@auth.login_required
def api_remove_blacklist(phone):
    remove_from_blacklist(phone)
    return jsonify({"status": "removed"})
