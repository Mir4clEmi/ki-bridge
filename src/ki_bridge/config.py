"""Pfade, Konfiguration und gespeicherter Zustand (geschätzter Kontostand etc.).

API-Keys werden NUR aus Umgebungsvariablen gelesen (OPENAI_API_KEY, GEMINI_API_KEY)
und nie gespeichert.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

# Projektwurzel des Servers (…/AI Claude Verbindung Projekt)
SERVER_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path(os.environ.get("KI_BRIDGE_HOME", SERVER_ROOT / "state"))
CONFIG_FILE = STATE_DIR / "config.json"
USAGE_LOG = STATE_DIR / "usage_log.csv"
DOWNLOADS_DIR = Path(os.environ.get("KI_BRIDGE_DOWNLOADS", Path.home() / "Downloads"))

_lock = threading.Lock()

DEFAULTS: dict[str, Any] = {
    # Geschätzter OpenAI-Kontostand in USD (optional, wird mit set_balance gesetzt)
    "openai_balance_usd": None,
    "balance_set_at": None,
    # Wird gesetzt, wenn OpenAI "insufficient_quota" o. ä. meldet -> keine weiteren Aufrufe
    "openai_blocked": False,
    "openai_blocked_reason": None,
    # Kostenregeln (Standardwerte; eigene Werte in state/config.json eintragen)
    "confirm_threshold_usd": 0.25,
    "warn_low_usd": 2.00,
    "warn_critical_usd": 1.00,
    "max_images_per_request": 3,
    # Modelle (aus aktueller Doku, 2026-11-23; hier anpassbar)
    "openai_image_model": "gpt-image-2.5-flare",
    "openai_text_model": "gpt-6-luna",
    "openai_strong_model": "gpt-6.2-sol",
    # Kostenlos nutzbare Gemini-Modelle in Reihenfolge der Fallbacks
    "gemini_models": ["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.5-flash-lite"],
    # Wartezeit (Minuten) für Download-Überwachung bei Handoffs
    "handoff_watch_minutes": 15,
}


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict[str, Any]:
    with _lock:
        _ensure_dir()
        data: dict[str, Any] = {}
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text("utf-8"))
            except json.JSONDecodeError:
                data = {}
        merged = {**DEFAULTS, **data}
        return merged


def save(cfg: dict[str, Any]) -> None:
    with _lock:
        _ensure_dir()
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(CONFIG_FILE)


def update(**changes: Any) -> dict[str, Any]:
    cfg = load()
    cfg.update(changes)
    save(cfg)
    return cfg


def api_key(name: str) -> str | None:
    val = os.environ.get(name, "").strip()
    return val or None


def resolve_project_dir(project_dir: str | None) -> Path:
    """Projektordner bestimmen: Parameter > CLAUDE_PROJECT_DIR > aktuelles Verzeichnis."""
    if project_dir:
        p = Path(project_dir).expanduser()
    elif os.environ.get("CLAUDE_PROJECT_DIR"):
        p = Path(os.environ["CLAUDE_PROJECT_DIR"])
    else:
        p = Path.cwd()
    p = p.resolve()
    if p == Path("/") or p == Path.home():
        raise ValueError(
            "Kein sinnvoller Projektordner erkennbar. Bitte project_dir angeben "
            "(absoluter Pfad zum Projekt)."
        )
    return p
