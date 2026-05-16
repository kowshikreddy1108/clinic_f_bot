from flask import Blueprint, jsonify, request, render_template
from bot.lists import (
    get_whitelist, get_blacklist,
    add_to_whitelist, remove_from_whitelist,
    add_to_blacklist, remove_from_blacklist,
)
from bot.qa import get_all_leads

dashboard = Blueprint("dashboard", __name__)


@dashboard.route("/")
def index():
    return render_template("dashboard.html")


# ── Leads ────────────────────────────────────────────────────────────────────

@dashboard.route("/api/leads")
def api_leads():
    return jsonify(get_all_leads())


# ── Whitelist ────────────────────────────────────────────────────────────────

@dashboard.route("/api/whitelist")
def api_get_whitelist():
    return jsonify(get_whitelist())


@dashboard.route("/api/whitelist", methods=["POST"])
def api_add_whitelist():
    body = request.get_json(silent=True) or {}
    phone = (body.get("phone") or "").strip()
    note  = (body.get("note")  or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400
    add_to_whitelist(phone, note)
    return jsonify({"status": "added"})


@dashboard.route("/api/whitelist/<path:phone>", methods=["DELETE"])
def api_remove_whitelist(phone):
    remove_from_whitelist(phone)
    return jsonify({"status": "removed"})


# ── Blacklist ────────────────────────────────────────────────────────────────

@dashboard.route("/api/blacklist")
def api_get_blacklist():
    return jsonify(get_blacklist())


@dashboard.route("/api/blacklist", methods=["POST"])
def api_add_blacklist():
    body = request.get_json(silent=True) or {}
    phone = (body.get("phone") or "").strip()
    note  = (body.get("note")  or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400
    add_to_blacklist(phone, note)
    return jsonify({"status": "added"})


@dashboard.route("/api/blacklist/<path:phone>", methods=["DELETE"])
def api_remove_blacklist(phone):
    remove_from_blacklist(phone)
    return jsonify({"status": "removed"})