"""LabMend server: runs on the INSTRUCTOR's laptop.  Start:  python Server\\app.py"""
import json
import socket
import threading
import time
from functools import wraps

from flask import Flask, abort, jsonify, render_template, request

import config
import db
from diagnose import ask_llm, diagnose
from safety import check_fix, describe

app = Flask(__name__)


# =============== helpers ===============
def load_manifest():
    return json.loads(config.MANIFEST_PATH.read_text(encoding="utf-8"))


def agents_only(func):
    """Reject any request that doesn't carry the secret lab token."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if request.headers.get("X-Lab-Token") != config.LAB_TOKEN:
            abort(401)
        return func(*args, **kwargs)
    return wrapper


def instructor_only(func):
    """Approve/Reject only from the instructor's own laptop (or in online demo mode)."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not config.DEMO_MODE and request.remote_addr not in ("127.0.0.1", "::1"):
            abort(403)
        return func(*args, **kwargs)
    return wrapper


def store_diagnosis(node_id, d, manifest):
    """Save a diagnosis as an issue. Its fix must pass the whitelist (safety layer 1)."""
    if d.get("needs_llm"):
        state = "diagnosing" if config.USE_LLM else "manual"
        if not config.USE_LLM:
            d["explanation"] = "Unknown error and the local AI is switched off. Please check manually."
    elif d["fix"]:
        ok, reason = check_fix(d["fix"], manifest)
        state = "pending" if ok else "blocked"
        if not ok:
            d["explanation"] += f"  [Blocked by whitelist: {reason}]"
    else:
        state = "manual"

    issue_id = db.add_issue(node_id, d["signature"], d["kind"], d["severity"], d["error_text"],
                            d["explanation"], d["fix"], d["source"], state)
    if state == "diagnosing":   # the AI can take seconds, so run it in the background
        threading.Thread(target=llm_job, args=(issue_id, d["error_text"], manifest), daemon=True).start()
    return issue_id


def llm_job(issue_id, error_text, manifest):
    explanation, fix, ok = ask_llm(error_text, manifest)
    if fix:
        good, reason = check_fix(fix, manifest)
        if good:
            db.update_issue(issue_id, explanation=explanation, fix=fix, source="llm", state="pending")
        else:
            db.update_issue(issue_id, explanation=f"{explanation}  [Blocked by whitelist: {reason}]",
                            fix=fix, source="llm", state="blocked")
    else:
        db.update_issue(issue_id, explanation=explanation, source="llm" if ok else "none", state="manual")


def node_status(node_id):
    severities = {i["severity"] for i in db.open_issues(node_id)}
    return "red" if "red" in severities else "amber" if "amber" in severities else "green"


def process_report(node_id, hostname, python, findings):
    """The heart of LabMend: compare what the agent sees now with what we knew before."""
    manifest = load_manifest()
    seen = set()
    for finding in findings:
        d = diagnose(finding, manifest)
        seen.add(d["signature"])
        old = db.find_open_issue(node_id, d["signature"])
        if old is None:
            store_diagnosis(node_id, d, manifest)                 # new problem
        elif old["state"] == "applied":                           # fix ran, problem still there
            db.update_issue(old["id"], state="failed", result="Still broken after the fix.")
            store_diagnosis(node_id, d, manifest)

    for issue in db.open_issues(node_id):                         # problems that disappeared
        if issue["kind"] != "runtime" and issue["signature"] not in seen:
            note = "Verified by re-audit." if issue["state"] == "applied" else "No longer detected."
            db.update_issue(issue["id"], state="resolved", result=note)

    status = node_status(node_id)
    count = len(db.open_issues(node_id))
    summary = f"{count} problem(s)" if count else "All checks passed"
    db.save_node(node_id, hostname, python, status, summary)
    return status


def process_crash(node_id, hostname, script, error):
    manifest = load_manifest()
    d = diagnose({"type": "runtime", "error": error}, manifest)
    d["error_text"] = f"[{script}]\n{d['error_text']}"
    old = db.find_open_issue(node_id, d["signature"])
    issue_id = old["id"] if old else store_diagnosis(node_id, d, manifest)
    db.save_node(node_id, hostname, None, node_status(node_id), "Program crashed")
    return issue_id


# =============== agent API (needs the token) ===============
@app.get("/api/manifest")
@agents_only
def api_manifest():
    return jsonify(load_manifest())


@app.post("/api/report")
@agents_only
def api_report():
    data = request.get_json()
    status = process_report(data["node_id"], data.get("hostname"), data.get("python"),
                            data.get("findings", []))
    return jsonify({"status": status, "interval": config.AGENT_INTERVAL_S})


@app.post("/api/crash")
@agents_only
def api_crash():
    data = request.get_json()
    issue_id = process_crash(data["node_id"], data.get("hostname"), data.get("script", "?"),
                             data.get("error", ""))
    return jsonify({"issue_id": issue_id})


@app.get("/api/fixes")
@agents_only
def api_fixes():
    node_id = request.args["node_id"]
    return jsonify([{"issue_id": i["id"], "fix": i["fix"]}
                    for i in db.issues_with("approved", node_id=node_id)])


@app.post("/api/fix_result")
@agents_only
def api_fix_result():
    data = request.get_json()
    issue = db.get_issue(data["issue_id"]) or abort(404)
    output = (data.get("output") or "")[-1500:]
    if data.get("ok"):
        state = "resolved" if issue["kind"] == "runtime" else "applied"
        db.update_issue(issue["id"], state=state, result="Fix applied. Re-checking...")
    else:
        db.update_issue(issue["id"], state="failed", result=output)
    return jsonify({"ok": True})


# =============== dashboard ===============
@app.get("/")
def dashboard():
    return render_template("dashboard.html", lab=load_manifest()["lab_name"], demo=config.DEMO_MODE)


@app.get("/api/state")
def api_state():
    now = time.time()
    nodes = db.all_nodes()
    for n in nodes:
        n["online"] = now - n["last_seen"] < config.OFFLINE_AFTER_S
        n["seconds_ago"] = int(now - n["last_seen"])
    issues = db.recent_issues()
    for i in issues:
        i["fix_text"] = describe(i["fix"])
    return jsonify({"nodes": nodes, "issues": issues,
                    "ai": config.OLLAMA_MODEL if config.USE_LLM else None})


@app.post("/api/issues/<int:issue_id>/approve")
@instructor_only
def approve(issue_id):
    issue = db.get_issue(issue_id)
    if not issue or issue["state"] != "pending":
        abort(400)
    ok, reason = check_fix(issue["fix"], load_manifest())       # check again before approving
    if not ok:
        db.update_issue(issue_id, state="blocked", result=reason)
        return jsonify({"approved": 0, "reason": reason})
    same = db.issues_with("pending", signature=issue["signature"])   # one click, whole lab
    for i in same:
        db.update_issue(i["id"], state="approved", result="Approved. Waiting for the PC to apply it.")
    return jsonify({"approved": len(same)})


@app.post("/api/issues/<int:issue_id>/reject")
@instructor_only
def reject(issue_id):
    db.update_issue(issue_id, state="rejected", result="Rejected by the instructor.")
    return jsonify({"ok": True})


# =============== start ===============
db.init_db()
if config.DEMO_MODE:
    import demo
    demo.start(process_report, process_crash)


def my_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    print("\n  LabMend server is running")
    print("  Dashboard (this laptop):  http://localhost:5000")
    print(f"  Agents on other PCs use:  --server http://{my_lan_ip()}:5000")
    print(f"  Local AI: {config.OLLAMA_MODEL if config.USE_LLM else 'OFF'}\n")
    app.run(host="0.0.0.0", port=5000)