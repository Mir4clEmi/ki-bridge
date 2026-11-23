"""Kosten-Tracking, Kostenprüfung und usage_log.csv."""

from __future__ import annotations

import csv
import datetime as dt
from collections import defaultdict

from . import config

FIELDS = ["datum", "tool", "anbieter", "modell", "geschaetzte_kosten_usd", "notiz"]


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def log(tool: str, provider: str, model: str, cost_usd: float, note: str = "") -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    new = not config.USAGE_LOG.exists()
    with config.USAGE_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(
            {
                "datum": now_iso(),
                "tool": tool,
                "anbieter": provider,
                "modell": model,
                "geschaetzte_kosten_usd": f"{cost_usd:.4f}",
                "notiz": note[:200].replace("\n", " "),
            }
        )


def charge_openai(tool: str, model: str, cost_usd: float, note: str = "") -> float | None:
    """Kosten loggen und vom gespeicherten Kontostand abziehen. Gibt neuen Stand zurück."""
    log(tool, "openai", model, cost_usd, note)
    cfg = config.load()
    bal = cfg.get("openai_balance_usd")
    if bal is None:
        return None
    new_bal = round(bal - cost_usd, 4)
    config.update(openai_balance_usd=new_bal)
    return new_bal


def balance_hint(balance: float | None) -> str:
    cfg = config.load()
    if balance is None:
        return "Hinweis: Kein OpenAI-Guthaben hinterlegt. Bitte mit set_balance setzen."
    if balance < cfg["warn_critical_usd"]:
        return (
            f"ACHTUNG: Geschätztes OpenAI-Guthaben nur noch {balance:.2f} USD. "
            "Willst du nachfüllen? (Danach set_balance aufrufen.)"
        )
    if balance < cfg["warn_low_usd"]:
        return f"Hinweis: Geschätztes OpenAI-Guthaben unter {cfg['warn_low_usd']:.2f} USD ({balance:.2f} USD)."
    return f"Geschätztes OpenAI-Guthaben: {balance:.2f} USD."


def preflight_openai(estimated_cost: float, confirmed: bool, low_balance_ok: bool) -> str | None:
    """Prüft vor einem OpenAI-Aufruf alle Regeln. Gibt eine Stopp-Meldung zurück oder None."""
    cfg = config.load()
    if cfg.get("openai_blocked"):
        return (
            "STOPP: OpenAI hat zuletzt einen Guthaben-/Quota-Fehler gemeldet "
            f"({cfg.get('openai_blocked_reason')}). Keine weiteren Aufrufe. "
            "Bitte Guthaben im OpenAI-Dashboard prüfen/nachfüllen und danach set_balance "
            "aufrufen. Alternativ die Aufgabe per handoff_to_me übernehmen."
        )
    if not config.api_key("OPENAI_API_KEY"):
        return "OPENAI_API_KEY ist nicht gesetzt. Siehe README (Abschnitt API-Keys)."
    bal = cfg.get("openai_balance_usd")
    if bal is not None and bal < cfg["warn_critical_usd"] and not low_balance_ok:
        return (
            f"RÜCKFRAGE NÖTIG: Geschätztes OpenAI-Guthaben nur {bal:.2f} USD (unter {cfg['warn_critical_usd']:.2f}). "
            "Frag die Person, ob sie nachfüllen will. Erst nach ihrem OK erneut mit "
            "low_balance_ok=true aufrufen."
        )
    if bal is not None and estimated_cost > bal:
        return (
            f"STOPP: Geschätzte Kosten {estimated_cost:.3f} USD übersteigen das geschätzte "
            f"Guthaben ({bal:.2f} USD). Bitte nachfüllen oder handoff_to_me nutzen."
        )
    if estimated_cost > cfg["confirm_threshold_usd"] and not confirmed:
        return (
            f"RÜCKFRAGE NÖTIG: Dieser Aufruf kostet geschätzt {estimated_cost:.3f} USD "
            f"(über {cfg['confirm_threshold_usd']:.2f} USD). Frag die Person vorher. "
            "Erst nach ihrem OK erneut mit confirmed=true aufrufen."
        )
    return None


QUOTA_MARKERS = (
    "insufficient_quota",
    "billing_hard_limit",
    "billing_not_active",
    "exceeded your current quota",
    "account_deactivated",
)


def is_quota_error(err: Exception) -> bool:
    text = f"{getattr(err, 'code', '')} {err}".lower()
    return any(m in text for m in QUOTA_MARKERS)


def block_openai(reason: str) -> None:
    config.update(openai_blocked=True, openai_blocked_reason=reason[:300])


def read_log() -> list[dict]:
    if not config.USAGE_LOG.exists():
        return []
    with config.USAGE_LOG.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def report() -> str:
    cfg = config.load()
    rows = read_log()
    month = dt.date.today().strftime("%Y-%m")
    this_month = [r for r in rows if r["datum"].startswith(month)]
    spent = sum(float(r["geschaetzte_kosten_usd"]) for r in this_month if r["anbieter"] == "openai")
    by_tool: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for r in this_month:
        if r["anbieter"] == "system":
            continue
        key = f"{r['tool']} ({r['modell']})"
        by_tool[key] += float(r["geschaetzte_kosten_usd"])
        count[key] += 1
    bal = cfg.get("openai_balance_usd")
    lines = [
        "## Usage-Report",
        f"- Geschätzter OpenAI-Reststand: {bal:.2f} USD" if bal is not None
        else "- Geschätzter OpenAI-Reststand: nicht gesetzt (set_balance)",
        f"  (Startwert gesetzt am {cfg.get('balance_set_at') or '–'})",
        f"- OpenAI-Verbrauch {month}: {spent:.4f} USD",
        f"- Gemini-Aufrufe {month}: {sum(1 for r in this_month if r['anbieter'] == 'gemini')} (ohne Kosten)",
    ]
    if cfg.get("openai_blocked"):
        lines.append(f"- OpenAI GESPERRT: {cfg.get('openai_blocked_reason')}")
    if by_tool:
        lines.append("\n| Tool (Modell) | Aufrufe | Kosten USD |\n|---|---|---|")
        for k in sorted(by_tool, key=lambda k: -by_tool[k]):
            lines.append(f"| {k} | {count[k]} | {by_tool[k]:.4f} |")
    recent = [r for r in this_month if r["anbieter"] == "openai"][-10:]
    if recent:
        lines.append("\nLetzte OpenAI-Ausgaben:")
        for r in recent:
            lines.append(f"- {r['datum']} {r['tool']}: {float(r['geschaetzte_kosten_usd']):.4f} USD – {r['notiz']}")
    lines.append("\n" + balance_hint(bal))
    lines.append("Hinweis: Alle Kosten sind Schätzungen. Maßgeblich ist das OpenAI-Dashboard.")
    return "\n".join(lines)
