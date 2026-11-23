"""Safety layer 1: the WHITELIST. A fix must pass every rule here, or it is blocked."""
import re

ALLOWED_ACTIONS = {"pip_install"}
ALLOWED_FLAGS = {"--upgrade", "--force-reinstall", "--no-deps"}

# package name + optional ==version. No spaces, no ; & | ` $ or anything else.
PACKAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}(==[A-Za-z0-9.+!-]{1,40})?$")


def check_fix(fix, manifest):
    """Return (True, "ok") or (False, "reason it was blocked")."""
    if not isinstance(fix, dict):
        return False, "fix is not a JSON object"
    if set(fix) - {"action", "packages", "flags"}:
        return False, "fix has unexpected fields"
    if fix.get("action") not in ALLOWED_ACTIONS:
        return False, f"action '{fix.get('action')}' is not allowed"

    packages = fix.get("packages")
    if not isinstance(packages, list) or not 1 <= len(packages) <= 5:
        return False, "packages must be a list of 1 to 5 items"

    lab_packages = {p["dist"].lower() for p in manifest["packages"]}
    for spec in packages:
        if not isinstance(spec, str) or not PACKAGE_RE.match(spec):
            return False, f"'{spec}' is not a valid package spec"
        name = spec.split("==")[0].lower()
        if name not in lab_packages:
            return False, f"'{name}' is not in the lab manifest"

    for flag in fix.get("flags", []):
        if flag not in ALLOWED_FLAGS:
            return False, f"flag '{flag}' is not allowed"
    return True, "ok"


def describe(fix):
    """The fix as a readable command for the dashboard."""
    if not fix:
        return ""
    return " ".join(["pip install", *fix.get("flags", []), *fix["packages"]])