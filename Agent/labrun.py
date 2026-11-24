"""labrun: students run programs through this, so crashes reach the instructor.

   python Agent\\labrun.py my_program.py
"""

import argparse, json, os, socket, subprocess, sys, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("program")
ap.add_argument("--server", default="http://127.0.0.1:5000")
ap.add_argument("--node-id", default=socket.gethostname())
ap.add_argument("--lab-python", default=sys.executable)
ap.add_argument("--token", default="twinspark-demo-token")
args = ap.parse_args()

# Run the student's program with the lab Python.
# Show errors live AND keep a copy.
p = subprocess.Popen(
    [args.lab_python, args.program],
    stderr=subprocess.PIPE,
    text=True
)

error_lines = []

for line in p.stderr:
    sys.stderr.write(line)
    error_lines.append(line)

code = p.wait()

error = "".join(error_lines)

if code != 0 and "Traceback" in error:
    body = {
        "node_id": args.node_id,
        "hostname": socket.gethostname(),
        "script": os.path.basename(args.program),
        "error": error[-3000:]
    }

    try:
        req = urllib.request.Request(
            args.server + "/api/crash",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Lab-Token": args.token
            }
        )

        urllib.request.urlopen(req, timeout=10)

        print("\n[LabMend] Error sent to your instructor's dashboard.")

    except Exception as e:
        print(f"\n[LabMend] Could not reach the LabMend server: {e}")

sys.exit(code)
