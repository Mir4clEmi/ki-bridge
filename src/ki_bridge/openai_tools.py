"""OpenAI: generate_image und ask_chatgpt mit Kostenschätzung und Quota-Schutz.

Preise laut developers.openai.com/api/docs/pricing (Stand 2026-11-23).
"""

from __future__ import annotations

import base64
from pathlib import Path

from . import config, usage

# USD pro 1M Tokens: (text_in, image_in, image_out)
IMAGE_TOKEN_PRICES = {
    "gpt-image-2.6-flare": (5.0, 8.0, 30.0),
    "gpt-image-2.6-sunburst": (5.0, 8.0, 30.0),
    "gpt-image-2.5-flare": (5.0, 8.0, 30.0),
    "gpt-image-2.5-sunburst": (5.0, 8.0, 30.0),
    "gpt-image-2": (5.0, 8.0, 30.0),
    "gpt-image-1-mini": (2.0, 2.5, 8.0),
}
# Geschätzte Kosten pro Bild 1024x1024 (low, medium, high); Basis: gpt-image-2-Tabelle
IMAGE_PER_IMAGE = {
    "gpt-image-1.5": (0.009, 0.034, 0.133),
    "gpt-image-1-mini": (0.005, 0.011, 0.036),
    "_default": (0.006, 0.053, 0.211),
}
# USD pro 1M Tokens (input, output)
TEXT_PRICES = {
    "gpt-6-luna": (0.10, 0.50),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-6.2-sol": (2.0, 10.0),
    "gpt-6.2-astra": (8.0, 40.0),
}


def _client():
    from openai import OpenAI

    # max_retries=0: bei Fehlern (v. a. Quota) keine automatischen Wiederholungen
    return OpenAI(api_key=config.api_key("OPENAI_API_KEY"), max_retries=0, timeout=180)


def estimate_image_cost(model: str, quality: str, size: str, n: int) -> float:
    low, med, high = IMAGE_PER_IMAGE.get(model, IMAGE_PER_IMAGE["_default"])
    per = {"low": low, "medium": med, "high": high}[quality]
    if size in ("1024x1536", "1536x1024", "auto"):
        per *= 1.5
    return round(per * n + 0.001, 4)  # + Prompt-Tokens


def _actual_image_cost(model: str, resp, fallback: float) -> float:
    u = getattr(resp, "usage", None)
    prices = IMAGE_TOKEN_PRICES.get(model)
    if not u or not prices:
        return fallback
    try:
        details = getattr(u, "input_tokens_details", None)
        text_in = getattr(details, "text_tokens", None) if details else None
        img_in = getattr(details, "image_tokens", 0) if details else 0
        if text_in is None:
            text_in = u.input_tokens
        out_tokens = u.output_tokens
        return round((text_in * prices[0] + (img_in or 0) * prices[1] + out_tokens * prices[2]) / 1e6, 5)
    except Exception:
        return fallback


def _handle_error(tool: str, err: Exception) -> str:
    if usage.is_quota_error(err):
        usage.block_openai(f"{type(err).__name__}: {err}")
        usage.log(tool, "openai", "-", 0.0, f"QUOTA-FEHLER: {err}")
        return (
            "STOPP – OpenAI meldet ein Guthaben-/Quota-Problem (z. B. insufficient_quota). "
            "Ich wiederhole nichts und sperre weitere OpenAI-Aufrufe, bis du set_balance aufrufst.\n"
            f"Fehler: {err}\n"
            "Biete der Person an, die betroffene Aufgabe per handoff_to_me zu übernehmen "
            "(z. B. Bild in ChatGPT im Browser erzeugen)."
        )
    text = str(err)
    if "verif" in text.lower():
        return (
            "OpenAI verlangt evtl. eine Organisations-Verifizierung für Bildmodelle. "
            "Das muss die Person im OpenAI-Dashboard selbst erledigen (Handoff).\n" + text
        )
    return f"OpenAI-Fehler ({type(err).__name__}): {text}"


def generate_image(prompt, output_path, filename, size, quality, transparent, n,
                   confirmed, low_balance_ok, project_dir=None) -> str:
    cfg = config.load()
    model = cfg["openai_image_model"]
    max_n = int(cfg["max_images_per_request"])
    if n < 1:
        return "n muss mindestens 1 sein."
    if n > max_n and not confirmed:
        return (
            f"RÜCKFRAGE NÖTIG: Maximal {max_n} Bilder pro Anfrage. Für {n} Bilder erst die "
            "Person fragen und dann confirmed=true setzen."
        )
    est = estimate_image_cost(model, quality, size, n)
    stop = usage.preflight_openai(est, confirmed, low_balance_ok)
    if stop:
        return stop

    # Zielpfad
    target_dir: Path
    fixed_file: Path | None = None
    if output_path:
        p = Path(output_path).expanduser()
        if p.suffix.lower() in (".png", ".webp", ".jpg", ".jpeg"):
            fixed_file, target_dir = p, p.parent
        else:
            target_dir = p
    else:
        try:
            project = config.resolve_project_dir(project_dir)
        except ValueError as e:
            return str(e)
        target_dir = project / "assets" / "images"
    target_dir.mkdir(parents=True, exist_ok=True)

    fmt = "png"
    kwargs = dict(model=model, prompt=prompt, size=size, quality=quality, n=n, output_format=fmt)
    if transparent:
        kwargs["background"] = "transparent"
    try:
        resp = _client().images.generate(**kwargs)
    except Exception as e:  # noqa: BLE001
        return _handle_error("generate_image", e)

    from .handoff import slug

    base = filename or slug(" ".join(prompt.split()[:6]))
    saved = []
    for i, img in enumerate(resp.data):
        if fixed_file and n == 1:
            out = fixed_file
        else:
            out = target_dir / (f"{base}.{fmt}" if n == 1 else f"{base}-{i + 1}.{fmt}")
        k = 2
        while out.exists() and not (fixed_file and out == fixed_file):
            out = target_dir / f"{base}-{k}.{fmt}"
            k += 1
        out.write_bytes(base64.b64decode(img.b64_json))
        saved.append(out)

    cost = _actual_image_cost(model, resp, est)
    bal = usage.charge_openai("generate_image", model, cost,
                              f"{n}x {quality} {size}{' transparent' if transparent else ''}: {prompt[:80]}")
    lines = [f"Gespeichert ({model}, {quality}, {size}{', transparent' if transparent else ''}):"]
    lines += [f"- {s}" for s in saved]
    lines.append(f"Kosten geschätzt: {cost:.4f} USD. " + usage.balance_hint(bal))
    return "\n".join(lines)


def estimate_text_cost(model: str, prompt: str, system: str | None, max_out: int) -> float:
    pin, pout = TEXT_PRICES.get(model, (2.0, 10.0))
    in_tokens = (len(prompt) + len(system or "")) / 3.5 + 20
    return round((in_tokens * pin + max_out * pout) / 1e6, 5)


def ask_chatgpt(prompt, system, model, max_output_tokens, confirmed, low_balance_ok) -> str:
    cfg = config.load()
    model = model or cfg["openai_text_model"]
    max_output_tokens = max(16, min(int(max_output_tokens), 16000))
    est = estimate_text_cost(model, prompt, system, max_output_tokens)
    stop = usage.preflight_openai(est, confirmed, low_balance_ok)
    if stop:
        return stop
    kwargs = dict(model=model, input=prompt, max_output_tokens=max_output_tokens)
    if system:
        kwargs["instructions"] = system
    try:
        resp = _client().responses.create(**kwargs)
    except Exception as e:  # noqa: BLE001
        return _handle_error("ask_chatgpt", e)
    pin, pout = TEXT_PRICES.get(model, (2.0, 10.0))
    u = getattr(resp, "usage", None)
    cost = round((u.input_tokens * pin + u.output_tokens * pout) / 1e6, 6) if u else est
    bal = usage.charge_openai("ask_chatgpt", model, cost, prompt[:80])
    text = resp.output_text or "(leere Antwort – evtl. max_output_tokens zu niedrig)"
    return f"{text}\n\n---\n[{model} · Kosten geschätzt {cost:.5f} USD · {usage.balance_hint(bal)}]"
