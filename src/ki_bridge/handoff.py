"""handoff_to_me: Aufgaben für die Person, handoffs.md und Download-Überwachung."""

from __future__ import annotations

import datetime as dt
import re
import shutil
import threading
import time
from pathlib import Path

from . import config

HANDOFF_FILE = "handoffs.md"
_file_lock = threading.Lock()
# id -> Status der Überwachung
WATCHERS: dict[str, dict] = {}

# Endungen, die noch im Download sind
PARTIAL_SUFFIXES = {".crdownload", ".download", ".part", ".partial", ".tmp"}

TYPE_GROUPS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"},
    "video": {".mp4", ".mov", ".webm", ".mkv"},
    "document": {".pdf", ".docx", ".doc", ".txt", ".md", ".pptx", ".xlsx", ".csv"},
    "archive": {".zip"},
}


def normalize_types(expected: list[str]) -> set[str]:
    exts: set[str] = set()
    for t in expected:
        t = t.lower().strip()
        if t in TYPE_GROUPS:
            exts |= TYPE_GROUPS[t]
        elif t:
            exts.add(t if t.startswith(".") else f".{t}")
    return exts


def default_subdir(exts: set[str]) -> str:
    if exts and exts <= TYPE_GROUPS["image"]:
        return "assets/images"
    if exts and exts <= TYPE_GROUPS["audio"]:
        return "assets/audio"
    return "assets/other"


def slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß_-]+", "-", text.strip().lower()).strip("-")
    return s[:50] or "datei"


def _next_id(path: Path) -> str:
    if not path.exists():
        return "H-001"
    nums = [int(n) for n in re.findall(r"\bH-(\d{3,})\b", path.read_text("utf-8"))]
    return f"H-{(max(nums) + 1 if nums else 1):03d}"


def _header() -> str:
    return (
        "# Handoffs\n\n"
        "Aufgaben, die du selbst erledigen musst. Abgehakte Aufgaben sind erledigt.\n\n"
    )


def add_entry(project: Path, block_builder) -> str:
    path = project / HANDOFF_FILE
    with _file_lock:
        project.mkdir(parents=True, exist_ok=True)
        hid = _next_id(path)
        text = path.read_text("utf-8") if path.exists() else _header()
        if not text.endswith("\n"):
            text += "\n"
        text += block_builder(hid)
        path.write_text(text, "utf-8")
    return hid


def mark_done(project: Path, hid: str, note: str = "") -> bool:
    path = project / HANDOFF_FILE
    with _file_lock:
        if not path.exists():
            return False
        text = path.read_text("utf-8")
        pattern = re.compile(rf"^- \[ \] \*\*{re.escape(hid)}\*\*(.*)$", re.M)
        m = pattern.search(text)
        if not m:
            return False
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        extra = f" — erledigt {stamp}" + (f": {note}" if note else "")
        text = text[: m.start()] + f"- [x] **{hid}**{m.group(1)}{extra}" + text[m.end():]
        path.write_text(text, "utf-8")
        return True


def open_entries(project: Path) -> list[str]:
    path = project / HANDOFF_FILE
    if not path.exists():
        return []
    return re.findall(r"^- \[ \] (.*)$", path.read_text("utf-8"), re.M)


def _birth(p: Path) -> float:
    st = p.stat()
    return getattr(st, "st_birthtime", st.st_mtime)


def _watch(hid: str, project: Path, exts: set[str], subdir: str, base_name: str,
           start: float, minutes: float, max_files: int) -> None:
    info = WATCHERS[hid]
    dl = config.DOWNLOADS_DIR
    deadline = start + minutes * 60
    seen_sizes: dict[str, int] = {}
    moved: list[str] = []
    try:
        while time.time() < deadline and len(moved) < max_files:
            time.sleep(2)
            try:
                entries = list(dl.iterdir())
            except OSError as e:
                info["status"] = f"Fehler beim Lesen des Download-Ordners: {e}"
                return
            for p in entries:
                # Nur Dateinamen + Metadaten prüfen; fremde Dateien werden nie geöffnet.
                if not p.is_file() or p.name.startswith("."):
                    continue
                if p.suffix.lower() in PARTIAL_SUFFIXES or p.suffix.lower() not in exts:
                    continue
                try:
                    if _birth(p) < start - 1:
                        continue
                    size = p.stat().st_size
                except OSError:
                    continue
                # erst verschieben, wenn die Größe zwischen zwei Prüfungen stabil ist
                if size == 0 or seen_sizes.get(p.name) != size:
                    seen_sizes[p.name] = size
                    continue
                target_dir = project / subdir
                target_dir.mkdir(parents=True, exist_ok=True)
                n = len(moved) + 1
                name = base_name if max_files == 1 else f"{base_name}-{n}"
                target = target_dir / f"{name}{p.suffix.lower()}"
                i = 2
                while target.exists():
                    target = target_dir / f"{name}-{i}{p.suffix.lower()}"
                    i += 1
                shutil.move(str(p), str(target))
                moved.append(str(target))
                info["files"] = moved
                seen_sizes.pop(p.name, None)
        if moved:
            info["status"] = "erledigt"
            rel = ", ".join(str(Path(m).relative_to(project)) for m in moved)
            mark_done(project, hid, f"Datei(en) eingetroffen: {rel}")
        else:
            info["status"] = f"Zeitüberschreitung nach {minutes:g} Minuten – keine passende neue Datei"
    finally:
        info["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")


def start_watch(hid: str, project: Path, exts: set[str], subdir: str, base_name: str,
                minutes: float, max_files: int = 1) -> None:
    start = time.time()
    WATCHERS[hid] = {
        "status": "überwacht Downloads",
        "started_at": dt.datetime.now().isoformat(timespec="seconds"),
        "until": (dt.datetime.now() + dt.timedelta(minutes=minutes)).strftime("%H:%M"),
        "files": [],
        "project": str(project),
        "types": sorted(exts),
        "target": subdir,
    }
    t = threading.Thread(
        target=_watch,
        args=(hid, project, exts, subdir, base_name, start, minutes, max_files),
        daemon=True,
    )
    t.start()


def wait_for(hid: str, timeout_s: float) -> dict | None:
    end = time.time() + timeout_s
    while time.time() < end:
        info = WATCHERS.get(hid)
        if info is None or info.get("finished_at"):
            return info
        time.sleep(1)
    return WATCHERS.get(hid)
