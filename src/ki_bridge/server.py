"""MCP-Server "ki-bridge": verbindet Claude mit ChatGPT (OpenAI API), Gemini (Google API)
und dem Menschen (Handoffs)."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Literal

from mcp.server.mcpserver import MCPServer

from . import config, handoff, usage
from . import openai_tools, gemini_tools

for _n in ("httpx", "google_genai", "openai"):
    logging.getLogger(_n).setLevel(logging.WARNING)

mcp = MCPServer(
    "ki-bridge",
    instructions=(
        "Brücke zu ChatGPT (OpenAI API, kostenpflichtig, sparsam nutzen), Gemini (nur kostenlose Modelle) "
        "und zum Menschen (handoff_to_me). Antworten mit 'RÜCKFRAGE NÖTIG' bedeuten: erst die "
        "Person fragen, dann mit dem entsprechenden Bestätigungs-Flag erneut aufrufen. "
        "Antworten mit 'STOPP' bedeuten: keine Wiederholung, Person informieren, Handoff anbieten."
    ),
)


# ---------------------------------------------------------------- Guthaben

@mcp.tool()
def set_balance(balance_usd: float) -> str:
    """Setzt den aktuellen OpenAI-Guthabenstand (USD), z. B. nach dem Nachfüllen.
    Hebt eine evtl. bestehende Sperre nach einem Quota-Fehler auf."""
    if balance_usd < 0:
        return "Guthaben kann nicht negativ sein."
    config.update(
        openai_balance_usd=round(balance_usd, 4),
        balance_set_at=dt.datetime.now().isoformat(timespec="seconds"),
        openai_blocked=False,
        openai_blocked_reason=None,
    )
    usage.log("set_balance", "system", "-", 0.0, f"Guthaben auf {balance_usd:.2f} USD gesetzt")
    return f"Gespeichert: {balance_usd:.2f} USD. " + usage.balance_hint(balance_usd)


@mcp.tool()
def usage_report() -> str:
    """Zeigt geschätzten OpenAI-Reststand, Verbrauch diesen Monat und wofür."""
    return usage.report()


# ---------------------------------------------------------------- OpenAI

@mcp.tool()
def generate_image(
    prompt: str,
    output_path: str | None = None,
    filename: str | None = None,
    size: Literal["1024x1024", "1024x1536", "1536x1024", "auto"] = "1024x1024",
    quality: Literal["low", "medium", "high"] = "medium",
    transparent_background: bool = False,
    n: int = 1,
    confirmed: bool = False,
    low_balance_ok: bool = False,
    project_dir: str | None = None,
) -> str:
    """Erzeugt Bild(er) mit der OpenAI Images API und speichert sie als Datei.

    - output_path: Zielordner (Standard: <Projekt>/assets/images) ODER kompletter Dateipfad.
    - filename: Dateiname ohne Endung (Standard: aus dem Prompt abgeleitet).
    - quality: Standard "medium". "high" NUR auf ausdrücklichen Wunsch der Person.
    - transparent_background: true für Sprites/Charaktere (PNG mit Alpha).
    - n: Anzahl Bilder (Obergrenze pro Anfrage siehe config).
    - confirmed: erst true setzen, nachdem die Person Kosten über der Schwelle bestätigt hat.
    - low_balance_ok: erst true, nachdem die Person bei kritischem Kontostand zugestimmt hat.
    - project_dir: absoluter Projektpfad (für Standard-Zielordner assets/images).
    Vorher der Person kurz sagen, was erzeugt wird und in welcher Qualität.
    """
    return openai_tools.generate_image(
        prompt, output_path, filename, size, quality, transparent_background, n,
        confirmed, low_balance_ok, project_dir,
    )


@mcp.tool()
def ask_chatgpt(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    max_output_tokens: int = 1200,
    confirmed: bool = False,
    low_balance_ok: bool = False,
) -> str:
    """Fragt ChatGPT über die OpenAI API (Standard: günstiges Modell).
    Nur nutzen, wenn es echten Mehrwert bringt (Zweitmeinung, nachweisliche Stärke).
    Kostenpflichtig; Regeln wie bei generate_image (confirmed / low_balance_ok)."""
    return openai_tools.ask_chatgpt(prompt, system, model, max_output_tokens, confirmed, low_balance_ok)


# ---------------------------------------------------------------- Gemini

@mcp.tool()
def ask_gemini(
    prompt: str,
    files: list[str] | None = None,
    use_google_search: bool = False,
    system: str | None = None,
    model: str | None = None,
) -> str:
    """Fragt Gemini (nur kostenlose Modelle). Gut für Video-/Audio-Analyse, sehr lange
    Dokumente/PDFs, Bilder und Fragen mit Google-Suche (use_google_search=true).
    - files: absolute Pfade zu Bildern, PDFs, Audio, Video, Text.
    Achtung Datenschutz: Eingaben im kostenlosen API-Tarif kann Google zur Verbesserung nutzen. Keine
    vertraulichen/persönlichen Inhalte ohne Zustimmung der Person senden.
    Bei Limit (429 / limit: 0) wird automatisch ein anderes Free-Modell probiert, sonst
    kommt eine Wartezeit bzw. ein Handoff-Vorschlag zurück."""
    return gemini_tools.ask_gemini(prompt, files, use_google_search, system, model)


# ---------------------------------------------------------------- Handoff

@mcp.tool()
def handoff_to_me(
    title: str,
    steps: list[str],
    where: str,
    bring_back: str,
    urgency: Literal["blockiert sofort", "blockiert später", "nicht blockierend"],
    category: Literal[
        "ki-browser", "andere-app", "hardware", "physisch", "entscheidung", "zugangsdaten",
        "material", "sonstiges"
    ] = "sonstiges",
    why: str | None = None,
    copy_prompt: str | None = None,
    prompt_settings: str | None = None,
    hardware: list[dict] | None = None,
    expected_file_types: list[str] | None = None,
    target_subdir: str | None = None,
    target_name: str | None = None,
    max_files: int = 1,
    project_dir: str | None = None,
) -> str:
    """Erstellt eine Aufgabe für die Person (alles, was Claude/ChatGPT/Gemini nicht selbst
    können oder was Geld kosten würde) und trägt sie in <Projekt>/handoffs.md ein.

    - steps: konkrete Schritte. where: App/Website oder "offline/physisch".
    - bring_back: was zurückkommen soll (Datei, Text, Foto, Messwert, Bestätigung).
    - urgency: blockiert sofort / blockiert später / nicht blockierend.
    - copy_prompt + prompt_settings: fertiger Prompt für ChatGPT/Gemini im Browser und die
      richtige Einstellung (z. B. Modell, Modus, Länge).
    - hardware: Liste von {"name", "menge", "kosten_ca", "bezugsquelle"}.
    - expected_file_types: z. B. ["audio"] oder [".mp3", ".wav"]. Wenn gesetzt, wird der
      Download-Ordner bis zu 15 Minuten überwacht; nur NEUE passende Dateien werden umbenannt
      und nach target_subdir (Standard: assets/images|audio|other) verschoben.
    - project_dir: absoluter Projektpfad (Standard: aktuelles Projekt).
    Text, Fotos und Antworten gibt die Person direkt im Chat. Während sie arbeitet, mit
    allem weitermachen, was nicht davon abhängt.
    """
    try:
        project = config.resolve_project_dir(project_dir)
    except ValueError as e:
        return str(e)

    exts = handoff.normalize_types(expected_file_types or [])
    subdir = target_subdir or (handoff.default_subdir(exts) if exts else None)
    base_name = handoff.slug(target_name or title)
    minutes = float(config.load()["handoff_watch_minutes"])

    def build(hid: str) -> str:
        date = dt.date.today().isoformat()
        lines = [f"- [ ] **{hid}** {title} — _{urgency}_ · {where} · {date}"]
        for i, s in enumerate(steps, 1):
            lines.append(f"  {i}. {s}")
        lines.append(f"  - Zurückbringen: {bring_back}")
        if why:
            lines.append(f"  - Warum du: {why}")
        if hardware:
            for h in hardware:
                lines.append(
                    f"  - Hardware: {h.get('menge', 1)}× {h.get('name')} · ca. {h.get('kosten_ca', '?')}"
                    f" · {h.get('bezugsquelle', '?')}"
                )
        if copy_prompt:
            lines.append(f"  - Einstellung: {prompt_settings or '–'}")
            lines.append("  - Prompt:")
            lines.append("    ```text")
            lines.extend("    " + ln for ln in copy_prompt.splitlines())
            lines.append("    ```")
        if exts:
            lines.append(
                f"  - Datei landet automatisch in `{subdir}/` (Download-Ordner wird {minutes:g} Min. überwacht)"
            )
        return "\n".join(lines) + "\n\n"

    hid = handoff.add_entry(project, build)

    if exts:
        handoff.start_watch(hid, project, exts, subdir, base_name, minutes, max(1, max_files))

    out = [f"## Handoff {hid}: {title}", f"**Dringlichkeit:** {urgency}", f"**Wo:** {where}"]
    if why:
        out.append(f"**Warum du:** {why}")
    out.append("**Schritte:**")
    out += [f"{i}. {s}" for i, s in enumerate(steps, 1)]
    if hardware:
        out.append("**Hardware:**")
        out += [
            f"- {h.get('menge', 1)}× {h.get('name')} – ca. {h.get('kosten_ca', '?')} – {h.get('bezugsquelle', '?')}"
            for h in hardware
        ]
    if copy_prompt:
        out.append(f"**Einstellung:** {prompt_settings or '–'}")
        out.append("**Prompt zum Kopieren:**\n```text\n" + copy_prompt + "\n```")
    out.append(f"**Bring mir zurück:** {bring_back}")
    if exts:
        out.append(
            f"**Automatisch:** Ich überwache `{config.DOWNLOADS_DIR}` bis {handoff.WATCHERS[hid]['until']} Uhr "
            f"auf neue Dateien ({', '.join(sorted(exts))}) und verschiebe sie nach `{subdir}/{base_name}.*`. "
            "Andere Dateien werden nicht angefasst."
        )
    else:
        out.append("Antwort/Text/Foto bitte direkt im Chat schicken.")
    out.append(f"Eingetragen in `{project / handoff.HANDOFF_FILE}`.")
    return "\n".join(out)


@mcp.tool()
def handoff_status(handoff_id: str | None = None, wait_seconds: int = 0,
                   project_dir: str | None = None) -> str:
    """Status der Download-Überwachung eines Handoffs bzw. Liste offener Handoffs.
    wait_seconds (max. 600): so lange auf das Eintreffen der Datei warten."""
    if handoff_id:
        info = handoff.WATCHERS.get(handoff_id)
        if info and wait_seconds > 0:
            info = handoff.wait_for(handoff_id, min(wait_seconds, 600))
        if not info:
            return f"{handoff_id}: keine aktive Download-Überwachung in dieser Server-Sitzung."
        files = "\n".join(f"- {f}" for f in info["files"]) or "- (noch keine)"
        return f"{handoff_id}: {info['status']} (Typen {', '.join(info['types'])}, bis {info['until']})\n{files}"
    try:
        project = config.resolve_project_dir(project_dir)
    except ValueError as e:
        return str(e)
    entries = handoff.open_entries(project)
    if not entries:
        return "Keine offenen Handoffs."
    return "Offene Handoffs:\n" + "\n".join(f"- {e}" for e in entries)


@mcp.tool()
def complete_handoff(handoff_id: str, note: str = "", project_dir: str | None = None) -> str:
    """Hakt einen Handoff in handoffs.md ab (z. B. wenn die Person Text/Foto im Chat geliefert hat)."""
    try:
        project = config.resolve_project_dir(project_dir)
    except ValueError as e:
        return str(e)
    ok = handoff.mark_done(project, handoff_id, note)
    return f"{handoff_id} abgehakt." if ok else f"{handoff_id} nicht offen in {project / handoff.HANDOFF_FILE}."


def main() -> None:
    import logging as _lg
    _lg.getLogger().setLevel(_lg.WARNING)
    for _name in ("httpx", "google_genai", "openai", "mcp"):
        _lg.getLogger(_name).setLevel(_lg.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
