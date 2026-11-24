"""lab.py: run a whole demo lab of several PCs on ONE laptop.

  python tools\\lab.py setup 6          create 6 student environments (labs\\pc-01 ... pc-06)
  python tools\\lab.py start 6          start 6 agents (PC-01 ... PC-06) in this one terminal
  python tools\\lab.py break PC-03 missing colorama
  python tools\\lab.py break PC-05 version tabulate 0.8.10
  python tools\\lab.py break all missing colorama      (every PC at once)

Start the server first (python Server\\app.py). Ctrl+C here stops every agent.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the Labmend folder
LABS = ROOT / "labs"
MANIFEST = ROOT / "Server" / "manifest.json"


def env_dir(n):
    return LABS / f"pc-{n:02d}"


def env_python(n):
    folder = env_dir(n)
    windows = folder / "Scripts" / "python.exe"
    return windows if windows.exists() else folder / "bin" / "python"


def node_number(name):
    """'PC-03' -> 3"""
    return int(name.upper().replace("PC-", ""))


def setup(count):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pins = [f"{p['dist']}=={p['version']}" if p.get("version") else p["dist"] for p in manifest["packages"]]
    LABS.mkdir(exist_ok=True)
    for n in range(1, count + 1):
        if env_python(n).exists():
            print(f"PC-{n:02d}: already exists")
            continue
        print(f"PC-{n:02d}: creating environment...")
        subprocess.run([sys.executable, "-m", "venv", str(env_dir(n))], check=True)
        subprocess.run([str(env_python(n)), "-m", "pip", "install", "-q", "--disable-pip-version-check", *pins],
                       check=True)
        print(f"PC-{n:02d}: ready with {', '.join(pins)}")
    print(f"\nDone. Now run:  python tools\\lab.py start {count}")


def start(count):
    agent = ROOT / "Agent" / "agent.py"
    processes = []
    for n in range(1, count + 1):
        if not env_python(n).exists():
            sys.exit(f"PC-{n:02d} has no environment. Run:  python tools\\lab.py setup {count}")
        log = open(LABS / f"pc-{n:02d}.log", "w", encoding="utf-8")
        p = subprocess.Popen([sys.executable, str(agent), "--node-id", f"PC-{n:02d}",
                              "--lab-python", str(env_python(n))], stdout=log, stderr=subprocess.STDOUT)
        processes.append(p)
        print(f"PC-{n:02d}: agent started (log: labs\\pc-{n:02d}.log)")
    print(f"\n{count} lab PCs are running. Open http://localhost:5000")
    print("Break one from ANOTHER terminal, e.g.:  python tools\\lab.py break PC-03 missing colorama")
    print("Press Ctrl+C here to stop all agents.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()
        print("\nAll agents stopped.")


def break_pc(target, kind, package, version=None):
    numbers = sorted(int(d.name[3:]) for d in LABS.glob("pc-*") if d.is_dir()) if target.lower() == "all" \
        else [node_number(target)]
    for n in numbers:
        py = str(env_python(n))
        if kind == "missing":
            cmd = [py, "-m", "pip", "uninstall", "-y", "-q", package]
        elif kind == "version":
            cmd = [py, "-m", "pip", "install", "-q", "--disable-pip-version-check", f"{package}=={version}"]
        else:
            sys.exit("kind must be 'missing' or 'version'")
        subprocess.run(cmd, check=True)
        print(f"PC-{n:02d}: broke {package} ({kind})")


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 1 and a[0] == "setup":
        setup(int(a[1]) if len(a) > 1 else 6)
    elif len(a) >= 1 and a[0] == "start":
        start(int(a[1]) if len(a) > 1 else 6)
    elif len(a) >= 4 and a[0] == "break":
        break_pc(a[1], a[2], a[3], a[4] if len(a) > 4 else None)
    else:
        print(__doc__)