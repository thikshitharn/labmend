"""All settings in one place. Change them with environment variables, never by editing code."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = os.environ.get("LABMEND_DB", str(BASE_DIR / "labmend.db"))
MANIFEST_PATH = BASE_DIR / "manifest.json"
KB_PATH = BASE_DIR / "kb.json"

# Shared secret: agents must send this, or the server ignores them.
LAB_TOKEN = os.environ.get("LABMEND_TOKEN", "twinspark-demo-token")

# How often agents report, and when a silent PC counts as offline.
AGENT_INTERVAL_S = 5
OFFLINE_AFTER_S = 30

# Local AI (Ollama). If Ollama isn't running, LabMend still works with the knowledge base.
USE_LLM = os.environ.get("LABMEND_USE_LLM", "1") == "1"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")
LLM_TIMEOUT_S = 90

# Demo mode: simulated lab PCs, for the online demo link only.
DEMO_MODE = os.environ.get("LABMEND_DEMO", "0") == "1"