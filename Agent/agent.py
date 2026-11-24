"""LabMend agent: runs on every LAB PC.

  python Agent\\agent.py --node-id PC-01 --lab-python lab_env\\Scripts\\python.exe
  (other laptop:  add  --server http://<instructor-ip>:5000)

Loop: 1 audit the lab environment -> 2 report -> 3 run approved fixes safely -> repeat.
Uses only Python's built-in libraries, so nothing has to be installed on lab PCs.
"""
import argparse, json, os, re, shutil, socket, subprocess, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

# ---- Safety layer 2: the agent re-checks every fix itself (never trust the network) ----
ALLOWED_FLAGS = {"--upgrade", "--force-reinstall", "--no-deps"}
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}(==[A-Za-z0-9.+!-]{1,40})?$")

# This small program runs INSIDE the lab environment and reports what it finds.
PROBE = r'''
import json, sys, importlib, traceback
from importlib import metadata
packages = json.loads(sys.argv[1])
out = {"python": sys.version.split()[0], "packages": []}
for p in packages:
    r = {"dist": p["dist"], "module": p["module"]}
    try:
        importlib.import_module(p["module"])
        r["import_ok"] = True
    except BaseException:
        r["import_ok"] = False
        r["error"] = traceback.format_exc(limit=2)[-1500:]
    try:
        r["version"] = metadata.version(p["dist"])
    except metadata.PackageNotFoundError:
        r["version"] = None
    out["packages"].append(r)
print("LABMEND_JSON" + json.dumps(out))
'''


def call(args, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(args.server + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "X-Lab-Token": args.token})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


# ---------------- 1. audit ----------------
def audit(lab_python, manifest):
    packages = manifest["packages"]
    result = subprocess.run([lab_python, "-c", PROBE, json.dumps(packages)],
                            capture_output=True, text=True, timeout=120)
    m = re.search(r"LABMEND_JSON(.*)", result.stdout)
    if not m:
        raise RuntimeError("probe failed: " + result.stderr[-500:])
    probe = json.loads(m.group(1))

    findings = []
    wanted = {p["dist"]: p for p in packages}
    for r in probe["packages"]:
        if not r["import_ok"]:
            findings.append({"type": "import", "dist": r["dist"], "module": r["module"],
                             "error": r["error"], "version": r["version"]})
        else:
            expected = wanted[r["dist"]].get("version")
            if expected and r["version"] != expected:
                findings.append({"type": "version", "dist": r["dist"],
                                 "expected": expected, "found": r["version"]})
    return probe["python"], findings


# ---------------- 1b. system checks (beyond Python) ----------------
# A FIXED list of checks built into the agent. The server can only NAME a tool from this list;
# it can never send a command to run. So this can't be misused to run anything on a student PC.
TOOL_CHECKS = {
    "git":  ["git", "--version"],     # git version 2.43.0.windows.1
    "node": ["node", "--version"],    # v20.11.0
    "java": ["java", "-version"],     # openjdk version "21.0.2"  (Java prints this to stderr)
}


def version_tuple(text):
    # "git version 2.43.0", 'openjdk version "21.0.2"', "v20.11.0"
    m = (re.search(r'(?:version\s*"?|\bv)(\d+)(?:\.(\d+))?(?:\.(\d+))?', text or "", re.I)
         or re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", text or ""))        # plain "18.0"
    return tuple(int(x or 0) for x in m.groups()) if m else None


def system_audit(lab_python, manifest):
    findings = []
    for tool in manifest.get("tools", []):
        name = tool["name"]
        if name not in TOOL_CHECKS:
            continue                                   # unknown names are ignored, never executed
        try:
            p = subprocess.run(TOOL_CHECKS[name], capture_output=True, text=True, timeout=15)
            found = version_tuple(p.stdout + p.stderr) if p.returncode == 0 else None
            installed = p.returncode == 0
        except (OSError, subprocess.TimeoutExpired):   # command not found
            installed, found = False, None
        if not installed:
            findings.append({"type": "tool", "name": name, "found": None, "min": tool.get("min")})
        elif tool.get("min") and found and version_tuple(tool["min"]) and found < version_tuple(tool["min"]):
            findings.append({"type": "tool", "name": name, "found": ".".join(map(str, found)), "min": tool["min"]})

    if manifest.get("min_disk_gb"):
        drive = Path(lab_python).resolve().anchor or "/"
        free_gb = shutil.disk_usage(drive).free / 1e9
        if free_gb < manifest["min_disk_gb"]:
            findings.append({"type": "disk", "free_gb": round(free_gb, 1), "min_gb": manifest["min_disk_gb"]})

    for var in manifest.get("env_vars", []):
        if not os.environ.get(var):
            findings.append({"type": "env", "name": var})
    return findings


# ---------------- 3. fix ----------------
def build_command(lab_python, fix):
    """Rebuild the pip command from scratch. Refuse anything unexpected."""
    if not isinstance(fix, dict) or fix.get("action") != "pip_install":
        raise ValueError("action not allowed")
    packages = fix.get("packages") or []
    if not 1 <= len(packages) <= 5 or not all(isinstance(p, str) and PACKAGE_RE.match(p) for p in packages):
        raise ValueError(f"bad packages: {packages}")
    flags = fix.get("flags") or []
    if any(f not in ALLOWED_FLAGS for f in flags):
        raise ValueError(f"bad flags: {flags}")
    # Safety layer 2 (sandbox): pip of the LAB environment only, as a list (no shell).
    return [lab_python, "-m", "pip", "install", "--disable-pip-version-check", *flags, *packages]


def apply_fixes(args):
    fixes = call(args, "GET", "/api/fixes?node_id=" + urllib.parse.quote(args.node_id))
    for item in fixes:
        try:
            cmd = build_command(args.lab_python, item["fix"])
            print("   applying fix:", " ".join(cmd[2:]))
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            ok, output = p.returncode == 0, p.stdout + p.stderr
        except Exception as e:
            ok, output = False, f"Refused or failed on the agent: {e}"
        print("   fix", "OK" if ok else "FAILED")
        call(args, "POST", "/api/fix_result", {"issue_id": item["issue_id"], "ok": ok, "output": output[-1500:]})
    return len(fixes) > 0


# ---------------- main loop ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://127.0.0.1:5000")
    ap.add_argument("--node-id", default=socket.gethostname())
    ap.add_argument("--lab-python", required=True, help="python.exe of the lab environment to watch")
    ap.add_argument("--token", default="twinspark-demo-token")
    args = ap.parse_args()
    print(f"LabMend agent {args.node_id} -> {args.server}")

    while True:
        interval = 5
        try:
            manifest = call(args, "GET", "/api/manifest")
            python_version, findings = audit(args.lab_python, manifest)                  # 1
            findings += system_audit(args.lab_python, manifest)                           # 1b
            reply = call(args, "POST", "/api/report", {"node_id": args.node_id,          # 2
                         "hostname": socket.gethostname(), "python": python_version,
                         "findings": findings})
            print(f"{time.strftime('%H:%M:%S')} status {reply['status'].upper():5} | {len(findings)} finding(s)")
            interval = reply.get("interval", 5)
            if apply_fixes(args):                                                         # 3
                continue          # re-audit straight away = verify the fix worked
        except urllib.error.HTTPError as e:
            print("server refused:", e.code, "(401 = wrong token)")
        except Exception as e:
            print("problem:", e)
        time.sleep(interval)


if __name__ == "__main__":
    main()
