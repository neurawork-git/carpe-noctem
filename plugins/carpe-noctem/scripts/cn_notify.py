"""Kanal zwischen Schicht und Mensch — Meldungen hinaus, Inbox herein.

In der Praxis greift der Mensch nachts ohnehin ein (neue Anweisung, erneuter Login,
Freigabe) — ohne Kanal nur durch Tippen in die Session. Carpe Noctem gibt dem einen Weg,
mit wählbaren Ausspielungskanälen:

* **`md`** — jede Meldung wird an eine Markdown-Datei angehängt. Default
  `.claude/carpe-noctem/meldungen.md`; mit `kanal_md:` in mission.md (oder
  `CARPE_NOCTEM_MD`) ein eigener Pfad, z. B. in einem synchronisierten Ordner oder einem
  Obsidian-Vault, den man vom Handy liest. Antwort: eine Zeile `- …` in `inbox.md`.
* **`ntfy`** — Push aufs Handy (`CARPE_NOCTEM_NTFY` = vollständige Topic-URL, optional
  `CARPE_NOCTEM_NTFY_TOKEN`). Antwort: Nachricht an das Topic mit Suffix `-in`.

Auswahl: `kanal: md, ntfy` in mission.md oder `CARPE_NOCTEM_KANAL` (gewinnt). Ohne Angabe:
`md` immer, `ntfy` zusätzlich, wenn `CARPE_NOCTEM_NTFY` gesetzt ist. Gemeldet wird, was
einen Menschen braucht: Grenze nachts getroffen, P1-To-Do, Sperre, Hook-Fehler, Abbruch,
Schichtende. Keine Routine.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import cn_state as ns
from cn_judge import scrub

TIMEOUT_S = 6
PRIO = {"low": "2", "default": "3", "high": "4", "urgent": "5"}
KANAELE = ("md", "ntfy")
MD_NAME = "meldungen.md"


# ── Konfiguration ────────────────────────────────────────────────────────────

def ntfy_url() -> str:
    return os.environ.get("CARPE_NOCTEM_NTFY", "").strip().rstrip("/")


def parse_kanaele(value: str) -> list[str]:
    """`"md, ntfy"` → `["md", "ntfy"]`. Unbekannte Namen wirft der Aufrufer als Fehler."""
    return [k.strip().lower() for k in (value or "").replace(";", ",").split(",") if k.strip()]


def unknown_kanaele(value: str) -> list[str]:
    return [k for k in parse_kanaele(value) if k not in KANAELE]


def channels(ledger: dict | None) -> list[str]:
    """Aktive Kanäle: Umgebung > mission.md > Default (md, plus ntfy wenn URL gesetzt)."""
    explicit = os.environ.get("CARPE_NOCTEM_KANAL") or (ledger or {}).get("kanaele_roh") or ""
    if explicit:
        return [k for k in parse_kanaele(explicit) if k in KANAELE]
    return ["md", "ntfy"] if ntfy_url() else ["md"]


def explicit(ledger: dict | None) -> bool:
    return bool(os.environ.get("CARPE_NOCTEM_KANAL") or (ledger or {}).get("kanaele_roh"))


def md_path(root: Path | None, ledger: dict | None) -> Path | None:
    raw = os.environ.get("CARPE_NOCTEM_MD") or (ledger or {}).get("kanal_md") or ""
    if raw:
        p = Path(os.path.expanduser(raw))
        return p if p.is_absolute() or root is None else root / p
    return None if root is None else ns.cn_dir(root) / MD_NAME


def reachable(root: Path | None, ledger: dict | None) -> bool:
    """Kann die Nacht einen Menschen erreichen? ntfy ja; md nur, wenn bewusst gewählt —
    die Default-Datei im Repo liest nachts niemand."""
    chans = channels(ledger)
    if "ntfy" in chans and ntfy_url():
        return True
    return "md" in chans and explicit(ledger)


def describe(root: Path | None, ledger: dict | None) -> list[str]:
    """Zeilen für Preflight und Gate: welche Kanäle mit welchem Ziel."""
    out = []
    for k in channels(ledger):
        if k == "md":
            out.append("md → %s" % (md_path(root, ledger) or "?"))
        elif k == "ntfy":
            url = ntfy_url()
            out.append("ntfy → %s" % (url.rsplit("/", 1)[0] + "/…" if url else "⚠ CARPE_NOCTEM_NTFY fehlt"))
    return out


# ── Ausspielen ───────────────────────────────────────────────────────────────

def _send_ntfy(title: str, message: str, prio: str, tags: str) -> bool:
    url = ntfy_url()
    if not url:
        return False
    token = os.environ.get("CARPE_NOCTEM_NTFY_TOKEN", "").strip()
    headers = {"Title": title.encode("utf-8").decode("latin-1", "replace"),
               "Priority": PRIO.get(prio, "3")}
    if token:
        headers["Authorization"] = "Bearer %s" % token
    if tags:
        headers["Tags"] = tags
    req = urllib.request.Request(url, data=message.encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _write_md(path: Path | None, title: str, message: str, prio: str) -> bool:
    if path is None:
        return False
    try:
        new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            if new:
                fh.write("# Carpe Noctem — Meldungen\n\nNeueste unten. Antwort: eine Zeile `- …` in "
                         "`.claude/carpe-noctem/inbox.md` des Repos (oder per ntfy an das Topic mit `-in`).\n")
            marke = {"high": " ⚠", "urgent": " 🚨"}.get(prio, "")
            fh.write("\n## %s%s · %s\n\n%s\n" % (ns.now().strftime("%Y-%m-%d %H:%M"), marke, title,
                                               message.strip()))
        return True
    except OSError:
        return False


def push(title: str, message: str, prio: str = "default", tags: str = "", *,
         root: Path | None = None, ledger: dict | None = None) -> list[str]:
    """Meldung über alle aktiven Kanäle. Rückgabe: die Kanäle, die zugestellt haben.

    Meldungen enthalten Projektinhalt (Missionstitel, Paketnotizen, Befehlsauszüge). Secret-
    Muster werden deshalb vor jedem Kanal maskiert — auch vor der lokalen md-Datei, die in
    einem synchronisierten Ordner liegen kann."""
    title, message = scrub(title), scrub(message)
    done = []
    for k in channels(ledger):
        if k == "ntfy" and _send_ntfy(title, message, prio, tags):
            done.append("ntfy")
        elif k == "md" and _write_md(md_path(root, ledger), title, message, prio):
            done.append("md")
    return done


def receipt(done: list[str]) -> str:
    return ("Meldung über %s." % " + ".join(done)) if done else \
        "Meldung NICHT zugestellt (kein Kanal erreichbar) — steht im Bericht."


# ── Inbox ────────────────────────────────────────────────────────────────────

def _poll_ntfy(ledger: dict) -> list[str]:
    """Neue Nachrichten aus dem Rückkanal-Topic (`<topic>-in`) holen."""
    url = ntfy_url()
    if not url or "ntfy" not in channels(ledger):
        return []
    since = ledger.get("ntfy_since") or ""
    if not since:
        start = ns.parse_iso(ledger.get("nacht_beginn"))
        since = str(int(start.timestamp())) if start else "10m"
    headers = {}
    token = os.environ.get("CARPE_NOCTEM_NTFY_TOKEN", "").strip()
    if token:
        headers["Authorization"] = "Bearer %s" % token
    req = urllib.request.Request("%s-in/json?poll=1&since=%s" % (url, since), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return []
    out = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") != "message":
            continue
        ledger["ntfy_since"] = event.get("id") or ledger.get("ntfy_since")
        text = (event.get("message") or "").strip()
        if text:
            out.append(text)
    return out


def _inbox_entries(root: Path) -> list[str]:
    try:
        lines = ns.inbox_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line[2:].strip() for line in lines if line.startswith("- ") and line[2:].strip()]


def new_messages(root: Path, ledger: dict) -> list[str]:
    """Ungelesene Nachrichten des Menschen. Holt ntfy in die Inbox-Datei (damit alles an
    einem Ort steht) und rückt den Lesezeiger vor. Der Aufrufer speichert das Ledger."""
    fresh = _poll_ntfy(ledger)
    if fresh:
        path = ns.inbox_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            for text in fresh:
                fh.write("- %s (Handy) %s\n" % (ns.now().strftime("%H:%M"), text.replace("\n", " ")))
    entries = _inbox_entries(root)
    seen = int(ledger.get("inbox_gelesen", 0))
    if seen > len(entries):  # Datei wurde gekürzt — neu anfangen statt Nachrichten zu verlieren
        seen = 0
    ledger["inbox_gelesen"] = len(entries)
    return entries[seen:]
