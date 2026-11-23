"""Gemini (nur kostenlose Modelle) mit automatischem Modell-Fallback und Handoff bei Limits.

Kostenlose Modelle laut aistudio.google.com/docs/pricing (Stand 2026-11-23).
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from . import config, usage

# Nur Modelle, die laut Pricing-Seite "Free of charge" sind. Paid-only-Modelle
# (gemini-4-carbon/-argon/-neon, gemini-3.1-pro-preview) werden abgelehnt.
FREE_MODELS = {
    "gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite",
}  # gemini-2.5-* laut API (2026-11-23) für neue Nutzer nicht mehr verfügbar
INLINE_LIMIT = 18 * 1024 * 1024  # sicher unter 20 MB Gesamtanfrage

EXTRA_MIME = {
    ".md": "text/markdown", ".py": "text/x-python", ".ts": "text/plain", ".js": "text/javascript",
    ".m4a": "audio/mp4", ".webm": "video/webm", ".heic": "image/heic",
}


def _client():
    from google import genai
    from google.genai import types

    # attempts=1: keine automatischen Wiederholungen, damit wir schnell auf das
    # nächste Free-Modell bzw. einen Handoff umschalten können.
    return genai.Client(
        api_key=config.api_key("GEMINI_API_KEY"),
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1), timeout=300_000),
    )


def _mime(p: Path) -> str:
    return EXTRA_MIME.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0] or "application/octet-stream"


def _retry_seconds(text: str) -> int | None:
    m = re.search(r"retry in ([\d.]+)\s*s", text, re.I) or re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+)", text)
    return int(float(m.group(1))) + 1 if m else None


def _classify(err: Exception) -> tuple[str, str]:
    """-> (art, kurzbeschreibung). art: 'limit0', 'rate', 'auth', 'other'"""
    code = getattr(err, "code", None)
    text = str(err)
    low = text.lower()
    if re.search(r"limit:\s*0\b", low) or "not available on the free tier" in low:
        return "limit0", "Modell ohne kostenloses Kontingent (limit: 0)"
    if code == 429 or "resource_exhausted" in low or "quota" in low:
        return "rate", "Limit erreicht (429)"
    if code in (400, 401, 403) and ("api key" in low or "permission" in low):
        return "auth", "API-Key ungültig oder ohne Berechtigung"
    if code == 404:
        return "notfound", "Modell nicht gefunden"
    if code in (500, 503, 504) or "unavailable" in low or "overloaded" in low:
        return "busy", "Modell gerade überlastet (503)"
    return "other", text[:300]


def ask_gemini(prompt: str, files: list[str] | None, use_google_search: bool,
               system: str | None, model: str | None) -> str:
    if not config.api_key("GEMINI_API_KEY"):
        return "GEMINI_API_KEY ist nicht gesetzt. Siehe README (Abschnitt API-Keys)."
    cfg = config.load()
    chain = [m for m in cfg["gemini_models"] if m in FREE_MODELS]
    if model:
        if model not in FREE_MODELS:
            return (f"'{model}' ist laut Doku nicht kostenlos nutzbar. Erlaubt: {', '.join(sorted(FREE_MODELS))}. "
                    "Kostenpflichtige Modelle werden nicht genutzt.")
        chain = [model] + [m for m in chain if m != model]

    from google.genai import types

    client = _client()

    # Dateien vorbereiten
    parts: list = []
    paths = [Path(f).expanduser() for f in (files or [])]
    for p in paths:
        if not p.is_file():
            return f"Datei nicht gefunden: {p}"
    total = sum(p.stat().st_size for p in paths)
    uploaded = []
    try:
        for p in paths:
            mt = _mime(p)
            if total <= INLINE_LIMIT:
                parts.append(types.Part.from_bytes(data=p.read_bytes(), mime_type=mt))
            else:
                f = client.files.upload(file=str(p), config=types.UploadFileConfig(mime_type=mt))
                uploaded.append(f)
                parts.append(f)
    except Exception as e:  # noqa: BLE001
        kind, msg = _classify(e)
        return f"Datei-Upload zu Gemini fehlgeschlagen: {msg}"
    # Videos brauchen nach dem Upload etwas Verarbeitungszeit
    if uploaded:
        import time
        for f in uploaded:
            for _ in range(60):
                st = client.files.get(name=f.name)
                if str(getattr(st, "state", "")).endswith("ACTIVE") or getattr(st, "state", None) is None:
                    break
                time.sleep(3)

    contents = parts + [prompt]

    def _cfg(search: bool):
        return types.GenerateContentConfig(
            system_instruction=system or None,
            tools=[types.Tool(google_search=types.GoogleSearch())] if search else None,
        )

    # Pässe: mit Google-Suche (falls gewünscht), danach ohne Suche, falls die Suche im
    # gesperrt oder erschöpft ist.
    passes = [True, False] if use_google_search else [False]
    attempts = []
    for search in passes:
        for m in chain:
            try:
                resp = client.models.generate_content(model=m, contents=contents, config=_cfg(search))
            except Exception as e:  # noqa: BLE001
                kind, msg = _classify(e)
                label = f"{m}{' +Suche' if search else ''}"
                attempts.append((label, kind, msg, _retry_seconds(str(e)), search))
                usage.log("ask_gemini", "gemini", m, 0.0, f"FEHLER {kind}{' (Suche)' if search else ''}: {msg}")
                if kind == "auth":
                    return f"Gemini: {msg}. Bitte GEMINI_API_KEY prüfen."
                if kind == "other":
                    return f"Gemini-Fehler ({m}): {msg}"
                continue  # limit0 / rate / notfound / busy -> nächstes Free-Modell
            text = resp.text or "(leere Antwort)"
            sources = ""
            try:
                gm = resp.candidates[0].grounding_metadata
                if gm and gm.grounding_chunks:
                    links = [f"- {c.web.title}: {c.web.uri}" for c in gm.grounding_chunks if c.web][:8]
                    sources = "\n\nQuellen (Google-Suche):\n" + "\n".join(links)
            except Exception:  # noqa: BLE001
                pass
            usage.log("ask_gemini", "gemini", m, 0.0,
                      f"{'search ' if search else ''}{len(paths)} Datei(en): {prompt[:60]}")
            warn = ""
            if use_google_search and not search:
                warn = ("WARNUNG: Google-Suche ist für deinen Key gerade gesperrt/erschöpft "
                        "(429). Antwort OHNE Websuche, kann veraltet sein. Für aktuelle Infos: später "
                        "erneut oder Handoff an gemini.google.com.\n\n")
            note = ""
            if attempts:
                note = "\n[Fallback: " + "; ".join(f"{a[0]} → {a[2]}" for a in attempts) + "]"
            return f"{warn}{text}{sources}\n\n---\n[{m}{' +Suche' if search else ''} · ohne Kosten]{note}"

    # Alle Free-Modelle ausgeschöpft -> Handoff statt Abbruch
    waits = [a[3] for a in attempts if a[3]]
    wait_txt = f"Frühestens in ca. {min(waits)} Sekunden erneut versuchen." if waits else \
        "Tageslimits werden um Mitternacht (US-Pazifikzeit) zurückgesetzt, Minutenlimits nach ~1 Minute."
    detail = "\n".join(f"- {a[0]}: {a[2]}" for a in attempts)
    if attempts and all(a[1] == "busy" for a in attempts):
        wait_txt = "Google-Server sind gerade überlastet (kein Limit-Problem). In 1–2 Minuten erneut versuchen."
    return (
        "GEMINI NICHT ERREICHBAR – nichts Kostenpflichtiges ausgelöst.\n"
        f"{detail}\n{wait_txt}\n\n"
        "HANDOFF-VORSCHLAG: Entweder später erneut versuchen oder die Person per handoff_to_me "
        "bitten, folgenden Prompt in gemini.google.com (im Browser) auszuführen"
        f"{' und die Dateien dort hochzuladen' if paths else ''}:\n"
        f"```text\n{prompt}\n```"
    )
