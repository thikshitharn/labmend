"""The brain: knowledge base (KB) first, local LLM (Ollama) for errors the KB doesn't know."""
import json
import re
import urllib.request

import config

KB = json.loads(config.KB_PATH.read_text(encoding="utf-8"))


def pin(pkg):
    """'tabulate' + version 0.9.0 -> 'tabulate==0.9.0'"""
    return f"{pkg['dist']}=={pkg['version']}" if pkg.get("version") else pkg["dist"]


def find_package(manifest, dist):
    for p in manifest["packages"]:
        if p["dist"].lower() == dist.lower():
            return p
    return {"dist": dist, "version": None}


def diagnose(finding, manifest):
    """Turn one finding into a diagnosis dict."""
    text = KB["explanations"]
    kind = finding["type"]

    if kind == "import":
        pkg = find_package(manifest, finding["dist"])
        error = finding.get("error", "")
        if "ModuleNotFoundError" in error and not finding.get("version"):
            return {"kind": "missing", "severity": "red", "signature": f"missing:{pkg['dist']}",
                    "error_text": error, "source": "kb",
                    "explanation": text["missing"].format(dist=pkg["dist"], module=finding["module"]),
                    "fix": {"action": "pip_install", "packages": [pin(pkg)]}}
        return {"kind": "broken", "severity": "red", "signature": f"broken:{pkg['dist']}",
                "error_text": error, "source": "kb",
                "explanation": text["broken"].format(dist=pkg["dist"]),
                "fix": {"action": "pip_install", "packages": [pin(pkg)], "flags": ["--force-reinstall"]}}

    if kind == "version":
        pkg = find_package(manifest, finding["dist"])
        return {"kind": "version", "severity": "amber", "signature": f"version:{pkg['dist']}",
                "error_text": f"{pkg['dist']} {finding['found']} installed, {finding['expected']} required",
                "source": "kb",
                "explanation": text["version"].format(dist=pkg["dist"], found=finding["found"],
                                                      expected=finding["expected"]),
                "fix": {"action": "pip_install", "packages": [pin(pkg)]}}

    if kind == "runtime":
        error = finding.get("error", "")
        match = re.search(r"No module named '([\w.]+)'", error)
        if match:
            module = match.group(1)
            top = module.split(".")[0]
            dist = KB["module_aliases"].get(module) or KB["module_aliases"].get(top) or top
            pkg = find_package(manifest, dist)
            return {"kind": "runtime", "severity": "red", "signature": f"crash:missing:{dist}",
                    "error_text": error, "source": "kb",
                    "explanation": text["runtime_missing"].format(module=module, dist=dist),
                    "fix": {"action": "pip_install", "packages": [pin(pkg)]}}
        last_line = error.strip().splitlines()[-1] if error.strip() else "unknown error"
        return {"kind": "runtime", "severity": "red", "signature": f"crash:{last_line[:80]}",
                "error_text": error, "source": "none", "fix": None, "needs_llm": True,
                "explanation": "Unknown error. Asking the local AI..."}

    return {"kind": "unknown", "severity": "amber", "signature": f"unknown:{kind}",
            "error_text": json.dumps(finding), "source": "none", "fix": None,
            "explanation": "LabMend does not recognise this finding."}


PROMPT = """You are a lab technician for Python computer labs.
A student's program crashed. Reply with ONLY this JSON:
{{"explanation": "<one or two simple sentences: what went wrong>",
  "packages": ["<package>==<version>"]}}
Rules:
- "packages" may ONLY use packages from this list: {allowed}
- If reinstalling one of them would fix the error, put it in "packages".
- If it is a bug in the student's own code, use "packages": [].
Error:
{error}
"""


def ask_llm(error_text, manifest):
    """Ask the local Ollama model. Returns (explanation, fix or None, ok)."""
    allowed = ", ".join(pin(p) for p in manifest["packages"])
    body = json.dumps({
        "model": config.OLLAMA_MODEL,
        "prompt": PROMPT.format(allowed=allowed, error=error_text[-2500:]),
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
    }).encode()
    request = urllib.request.Request(config.OLLAMA_URL + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT_S) as response:
            answer = json.loads(response.read())["response"]
        data = json.loads(re.search(r"\{.*\}", answer, re.S).group(0))
    except Exception as e:
        return f"Local AI not available ({type(e).__name__}). Please check manually.", None, False

    explanation = str(data.get("explanation", "")).strip()[:500] or "No explanation given."
    packages = [p for p in data.get("packages", []) if isinstance(p, str)]
    fix = {"action": "pip_install", "packages": packages, "flags": ["--force-reinstall"]} if packages else None
    return explanation, fix, True