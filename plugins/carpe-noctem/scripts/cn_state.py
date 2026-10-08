"""Gemeinsamer Zustand von Carpe Noctem.

Eine Schicht lebt komplett in `<repo>/.claude/carpe-noctem/`:

    mission.md       vom Menschen freigegebener Auftrag (Quelle der Pakete und Grenzen)
    ledger.json      Maschinenzustand: Phase, Pakete, Grenzen, Entscheidungen, To-Dos
    ledger.json.bak  letzter gültiger Stand (vor jedem Schreiben gezogen)
    journal.md       Append-only-Protokoll
    inbox.md         Nachrichten des Menschen an die laufende Schicht
    REPORT.md        das Arbeitsergebnis für den Menschen
    hook-fehler.log  Tracebacks der Hooks — ein Hook-Fehler ist nie mehr still

Zwei Phasen:

* `vorbereitung` — der Mensch ist wach. Grenzen (alles, wofür die Schicht einen
  Menschen brauchen könnte) werden inventarisiert, probeweise berührt und geklärt.
  Die Hooks sind still; Rückfragen sind ausdrücklich erwünscht.
* `active` (die Nacht) — die Hooks treiben die Schicht, Rückfragen sind gesperrt.

**Risiko heißt hier: die Wahrscheinlichkeit, dass ein Paket einen Menschen braucht**
(Permission, Login, Freigabe, Urteil, externer Start, Irreversibles) — nicht technische
Schwierigkeit. Technische Probleme löst die Nacht selbst; einen Menschen findet sie nicht.

Reines stdlib, Python 3.10-kompatibel. Hooks fangen breit, protokollieren über
`hook_error()` und exiten 0.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

DIRNAME = ".claude/carpe-noctem"
LEDGER_NAME = "ledger.json"
MISSION_NAME = "mission.md"
JOURNAL_NAME = "journal.md"
REPORT_NAME = "REPORT.md"
INBOX_NAME = "inbox.md"
HOOK_ERROR_NAME = "hook-fehler.log"

MAX_PROGRESS = 8  # so viele Zwischenstände hält ein Paket; ältere fallen raus

LEDGER_VERSION = 2

OPEN_STATES = ("open", "doing")
# `waiting` ist weder offen noch zu: das Paket hängt an einer Grenze, die nur ein
# Mensch auflöst. Es hält die Nacht am Leben (Wache), wird aber nicht bearbeitet.
WAITING_STATES = ("waiting",)
CLOSED_STATES = ("done", "blocked", "dropped")

# Grenzarten und ihr Gewicht im Restrisiko. Hoch = braucht ein menschliches Urteil
# oder ist nicht umkehrbar; mittel = braucht eine Handlung, die vorab erledigt werden kann.
GRENZ_GEWICHT = {
    "urteil": 3,        # fachliche Entscheidung, die der Agent nicht stellvertretend treffen darf
    "freigabe": 3,      # Merge/Deploy/Senden/Geld — nur der Mensch löst aus
    "irreversibel": 3,  # Löschen, Migration ohne Rückweg, Schreiben auf Kundensysteme
    "permission": 2,    # Werkzeug/Befehl, der in der Allow-Liste fehlt
    "login": 2,         # Credential/Token, der ablaufen oder fehlen kann
    "extern": 2,        # Dienst/Prozess/Person außerhalb des Repos muss etwas tun
}
GRENZ_ARTEN = tuple(GRENZ_GEWICHT)
GRENZ_STATUS = ("offen", "geklaert", "wartebank", "getroffen")

PROBE_MAX_AGE = timedelta(hours=3)  # ein grüner Trockenlauf gilt so lange als frisch
# Prüfbefehle warten oft auf eine externe CI (gern 20 min und mehr). Das Bash-Werkzeug
# schiebt lange Aufrufe nach 10 min in den Hintergrund, bricht sie aber nicht ab.
CHECK_TIMEOUT = 1800
# Urteils-Grenzen, die ein Agent nicht mit eigener Autorität klären darf.
HUMAN_ONLY = ("urteil", "freigabe", "irreversibel")


# ── Pfade ────────────────────────────────────────────────────────────────────

def find_root(hook_input: dict | None = None) -> Path:
    """Repo-Wurzel bestimmen: Hook-Input > CLAUDE_PROJECT_DIR > Aufstieg von cwd."""
    for candidate in (
        (hook_input or {}).get("cwd"),
        os.environ.get("CLAUDE_PROJECT_DIR"),
    ):
        if candidate:
            p = Path(candidate)
            if p.exists():
                return _climb(p)
    return _climb(Path.cwd())


def _climb(start: Path) -> Path:
    """Von `start` aufsteigen bis zu einer Schicht bzw. .git; sonst start."""
    start = start.resolve()
    for p in (start, *start.parents):
        if (p / DIRNAME / LEDGER_NAME).exists():
            return p
        if (p / ".git").exists():
            return p
    return start


def cn_dir(root: Path) -> Path:
    return root / DIRNAME


def ledger_path(root: Path) -> Path:
    return cn_dir(root) / LEDGER_NAME


def mission_path(root: Path) -> Path:
    return cn_dir(root) / MISSION_NAME


def journal_path(root: Path) -> Path:
    return cn_dir(root) / JOURNAL_NAME


def report_path(root: Path) -> Path:
    return cn_dir(root) / REPORT_NAME


def inbox_path(root: Path) -> Path:
    return cn_dir(root) / INBOX_NAME


# ── Zeit ─────────────────────────────────────────────────────────────────────

def now() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.astimezone()


def parse_deadline(value: str | None, base: datetime | None = None) -> str | None:
    """Akzeptiert ISO-Zeitstempel, `+8h`/`+90m`/`+2d` oder `HH:MM` (nächstes Auftreten)."""
    if not value:
        return None
    value = value.strip()
    base = base or now()
    rel = re.fullmatch(r"\+(\d+(?:[.,]\d+)?)\s*([mhd])", value, re.IGNORECASE)
    if rel:
        amount = float(rel.group(1).replace(",", "."))
        unit = rel.group(2).lower()
        delta = {"m": timedelta(minutes=amount),
                 "h": timedelta(hours=amount),
                 "d": timedelta(days=amount)}[unit]
        return iso(base + delta)
    clock = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if clock:
        target = base.replace(hour=int(clock.group(1)), minute=int(clock.group(2)),
                              second=0, microsecond=0)
        if target <= base:
            target += timedelta(days=1)
        return iso(target)
    dt = parse_iso(value)
    return iso(dt) if dt else None


def remaining(deadline: str | None) -> timedelta | None:
    dt = parse_iso(deadline)
    return None if dt is None else dt - now()


def human_delta(delta: timedelta | None) -> str:
    if delta is None:
        return "kein Zeitlimit"
    total = int(delta.total_seconds())
    if total <= 0:
        return "abgelaufen"
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    if hours:
        return "%dh%02dm" % (hours, minutes)
    return "%dm" % minutes


# ── Ledger ───────────────────────────────────────────────────────────────────

def new_ledger(title: str) -> dict:
    return {
        "version": LEDGER_VERSION,
        # vorbereitung -> active -> finished | aborted | interrupted
        "status": "vorbereitung",
        "titel": title,
        "quelle": "",
        "erstellt": iso(now()),
        "nacht_beginn": None,
        "beendet": None,
        "ende_grund": None,
        "bound_session": None,
        "deadline": None,
        "max_continuations": 200,
        "continuations": 0,
        "hardening_rounds_max": 3,
        "hardening_rounds": 0,
        "report_blocks": 0,
        "no_progress_streak": 0,
        "last_fingerprint": None,
        "wachen": 0,
        "datenschutz": "",      # `intern` erlaubt einen externen Richter (Jev)
        "richter": "",          # "" | "jev"
        # Prüfbefehl für nachts angelegte Pakete — sonst wählt der Täter seinen Richter selbst.
        "richter_default": "",
        "permission_mode": "",  # aus dem Hook-Input; `auto` macht Ablehnungen unsichtbar
        "transcript_pos": 0,    # bis hierhin ist das Transkript auf Klassifikator-Ablehnungen gelesen
        "klassifikator_ablehnungen": [],
        "haertung": [],         # protokollierte Härtungsrunden (Hook oder `cn.py haertung`)
        "geschuetzt": [],       # Globs der Richter-Dateien (Tests, Prüfskripte)
        "geschuetzt_hashes": {},
        "verbotene_aktionen": [],
        "hardening_backlog": [],
        "premortem": [],
        "grenzen": [],
        "items": [],
        "entscheidungen": [],
        "todos": [],
        "offene_fragen": [],
        "inbox_gelesen": 0,
        "ntfy_since": "",
        "kanaele_roh": "",      # `kanal:` aus mission.md, z. B. "md, ntfy" — leer = Default
        "kanal_md": "",         # `kanal_md:` — Pfad der Meldungsdatei (relativ zum Repo oder absolut)
    }


def _read_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load(root: Path) -> dict | None:
    """Ledger laden. Ist es kaputt, die Sicherung aber heil, wird die Sicherung
    zurückgespielt — laut, mit Journaleintrag. Ohne das lässt ein halb geschriebenes
    Ledger alle Hooks still no-oppen, und die Nacht endet lautlos."""
    path = ledger_path(root)
    data = _read_json(path)
    if data is None and path.exists():
        backup = path.with_suffix(".json.bak")
        data = _read_json(backup)
        if data is not None:
            try:
                shutil.copyfile(backup, path)
                journal(root, "⚠ ledger.json war unlesbar — letzter gültiger Stand aus "
                              "ledger.json.bak zurückgespielt.")
            except OSError:
                pass
        else:
            hook_error(root, "ledger.json und ledger.json.bak sind unlesbar")
    if data is None:
        return None
    base = new_ledger(data.get("titel", ""))
    base.update(data)
    return base


def save(root: Path, ledger: dict) -> None:
    d = cn_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    path = ledger_path(root)
    if _read_json(path) is not None:
        shutil.copyfile(path, path.with_suffix(".json.bak"))
    tmp = path.with_suffix(".json.tmp")
    text = json.dumps(ledger, ensure_ascii=False, indent=2) + "\n"
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def round_mode() -> bool:
    """Läuft dieser Prozess als eine Runde des Headless-Laufs (`ralph.py`)?

    Im Rundenmodus ist die äußere Schleife der Motor: jede Runde bekommt frischen
    Kontext und DARF anhalten. Der Stop-Hook hält sich heraus, SessionEnd markiert
    die Schicht nicht als abgerissen, die Session-Bindung entfällt.
    """
    return os.environ.get("CARPE_NOCTEM_ROUND") == "1"


def active_for_session(root: Path, session_id: str | None) -> dict | None:
    """Ledger nur zurückgeben, wenn die Nacht läuft UND zu dieser Session gehört."""
    ledger = load(root)
    if not ledger or ledger.get("status") != "active":
        return None
    if round_mode():
        return ledger
    bound = ledger.get("bound_session")
    if bound and session_id and bound != session_id:
        return None
    return ledger


def bind(root: Path, ledger: dict, session_id: str | None) -> dict:
    if round_mode():
        return ledger
    if session_id and not ledger.get("bound_session"):
        ledger["bound_session"] = session_id
        save(root, ledger)
    return ledger


# ── Arbeitspakete ────────────────────────────────────────────────────────────

def items_by_state(ledger: dict, *states: str) -> list[dict]:
    return [i for i in ledger.get("items", []) if i.get("status") in states]


def _id_num(item: dict) -> int:
    m = re.search(r"(\d+)$", str(item.get("id", "")))
    return int(m.group(1)) if m else 0


def ordered(items: list[dict]) -> list[dict]:
    """Pakete in der Nachtreihenfolge (`rang`, gesetzt bei `cn.py start`)."""
    return sorted(items, key=lambda i: (i.get("rang", 10_000), _id_num(i)))


def open_items(ledger: dict) -> list[dict]:
    return ordered(items_by_state(ledger, *OPEN_STATES))


def missing_deps(ledger: dict, item: dict) -> list[str]:
    """Vorgänger (`nach:`), die noch nicht erledigt sind."""
    out = []
    for dep in item.get("nach") or []:
        other = find_item(ledger, dep)
        if other is None or other.get("status") not in ("done", "dropped"):
            out.append(dep)
    return out


def ready_items(ledger: dict) -> list[dict]:
    """Pakete, an denen jetzt gearbeitet werden kann: laufende und offene mit erledigten
    Vorgängern. Hängt ein Vorgänger an einer Grenze (`waiting`/`blocked`), ist sein
    Nachfolger NICHT startbar — dann darf die Nacht nicht in der Arbeitsphase festsitzen."""
    return [i for i in open_items(ledger)
            if i.get("status") == "doing" or not missing_deps(ledger, i)]


def dep_stuck_items(ledger: dict) -> list[dict]:
    """Offene Pakete, die nur auf Vorgänger warten."""
    ready = {id(i) for i in ready_items(ledger)}
    return [i for i in open_items(ledger) if id(i) not in ready]


def topo_order(ledger: dict) -> list[dict]:
    """Nachtreihenfolge: Abhängigkeiten zuerst, unter Gleichrangigen Risiko zuerst.

    Reine Risiko-Sortierung stellt sonst ein Paket vor das Fundament, gegen das es geprüft
    wird (z. B. vor das CI-Gerüst). Wirft ValueError bei Zyklus oder unbekanntem Vorgänger.
    """
    items = ledger.get("items", [])
    ids = {str(i["id"]).lower() for i in items}
    for item in items:
        unknown = [d for d in item.get("nach") or [] if d.lower() not in ids]
        if unknown:
            raise ValueError("Paket %s: unbekannte Vorgänger %s" % (item["id"], ", ".join(unknown)))
    done: list[dict] = []
    placed: set[str] = set()
    pending = list(items)
    while pending:
        ready = [i for i in pending
                 if all(d.lower() in placed for d in i.get("nach") or [])]
        if not ready:
            raise ValueError("Zyklus in den Abhängigkeiten: %s"
                             % ", ".join(i["id"] for i in pending))
        best = sorted(ready, key=lambda i: (-restrisiko(ledger, i), _id_num(i)))[0]
        done.append(best)
        placed.add(str(best["id"]).lower())
        pending.remove(best)
    return done


def waiting_items(ledger: dict) -> list[dict]:
    return ordered(items_by_state(ledger, *WAITING_STATES))


def progress_line(ledger: dict) -> str:
    items = ledger.get("items", [])
    return "%d/%d erledigt, %d warten, %d blockiert, %d verworfen, %d offen" % (
        len(items_by_state(ledger, "done")), len(items),
        len(waiting_items(ledger)), len(items_by_state(ledger, "blocked")),
        len(items_by_state(ledger, "dropped")), len(open_items(ledger)))


def current_item(ledger: dict) -> dict | None:
    """Das Paket, an dem gerade gearbeitet wird (`doing`), sonst das erste startbare.

    Mehrere `doing` sind erlaubt (Orchestrator mit Subagenten) — dann ist das erste
    gemeint; wer eindeutig sein muss (`progress`), verlangt `--id`."""
    doing = items_by_state(ledger, "doing")
    if doing:
        return doing[0]
    offen = ready_items(ledger) or open_items(ledger)
    return offen[0] if offen else None


def find_item(ledger: dict, item_id: str) -> dict | None:
    for item in ledger.get("items", []):
        if str(item.get("id", "")).lower() == str(item_id).lower():
            return item
    return None


def add_progress(item: dict, text: str) -> None:
    """Zwischenstand an ein Paket hängen — der Teil, den eine Kompaktierung frisst."""
    entries = item.setdefault("fortschritt", [])
    entries.append({"zeit": now().strftime("%H:%M"), "text": text.replace("\n", " ").strip()})
    del entries[:-MAX_PROGRESS]


def progress_lines(item: dict | None, limit: int = MAX_PROGRESS) -> list[str]:
    if not item:
        return []
    return ["%s %s" % (e.get("zeit", "??:??"), e.get("text", ""))
            for e in (item.get("fortschritt") or [])[-limit:]]


def next_id(entries: list[dict], prefix: str) -> str:
    nums = []
    for entry in entries:
        m = re.fullmatch(r"[A-Za-z]+(\d+)", str(entry.get("id", "")))
        if m:
            nums.append(int(m.group(1)))
    return "%s%d" % (prefix, (max(nums) + 1) if nums else 1)


# ── Grenzen und Restrisiko ───────────────────────────────────────────────────

def grenzen_for(ledger: dict, item_id: str) -> list[dict]:
    return [g for g in ledger.get("grenzen", [])
            if str(g.get("paket", "")).lower() == str(item_id).lower()]


def find_grenze(ledger: dict, gid: str) -> dict | None:
    for g in ledger.get("grenzen", []):
        if str(g.get("id", "")).lower() == str(gid).lower():
            return g
    return None


def restrisiko(ledger: dict, item: dict) -> int:
    """Wie wahrscheinlich braucht dieses Paket nachts einen Menschen?

    Offene und nachts getroffene Grenzen zählen doppelt, Wartebank-Grenzen einfach
    (bewusst akzeptiert, mit Ersatzarbeit), geklärte nicht. Ein Paket ohne Prüfbefehl
    bekommt einen Punkt: morgens muss ein Mensch es abnehmen.
    """
    score = 0
    for g in grenzen_for(ledger, item.get("id", "")):
        weight = GRENZ_GEWICHT.get(g.get("art", ""), 2)
        if g.get("status") in ("offen", "getroffen"):
            score += 2 * weight
        elif g.get("status") == "wartebank":
            score += weight
    if not item.get("pruefbefehl"):
        score += 1
    return score


def probe_fresh(grenze: dict) -> bool:
    run = grenze.get("probe_lauf") or {}
    ran = parse_iso(run.get("zeit"))
    return bool(ran and (now() - ran) <= PROBE_MAX_AGE and run.get("exit") == 0)


# ── Befehle ausführen (Prüfbefehle, Trockenläufe) ────────────────────────────

def bash_exe() -> str:
    """Die Shell für Prüfbefehle. Unter Windows Git-Bash — nie cmd.exe.

    Mit `shell=True` liefe ein Prüfbefehl unter Windows über cmd.exe, und POSIX-Befehle
    aus mission.md scheiterten falsch-rot. Ein Weg: `CARPE_NOCTEM_BASH` oder die
    Git-Installation neben `git`.
    `bash` aus dem PATH wäre unter Windows oft WSL — deshalb nicht.
    """
    explicit = os.environ.get("CARPE_NOCTEM_BASH")
    if explicit:
        if not Path(explicit).exists():
            raise RuntimeError("CARPE_NOCTEM_BASH zeigt auf %s — existiert nicht" % explicit)
        return explicit
    if os.name != "nt":
        found = shutil.which("bash")
        if not found:
            raise RuntimeError("bash nicht gefunden")
        return found
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git nicht im PATH — Git-Bash nicht auffindbar; CARPE_NOCTEM_BASH setzen")
    # git.exe liegt je nach PATH unter …/Git/cmd/ oder …/Git/mingw64/bin/ — die
    # Git-Wurzel ist der erste Elternordner mit bin/bash.exe.
    for parent in Path(git).resolve().parents:
        bash = parent / "bin" / "bash.exe"
        if bash.exists():
            return str(bash)
    raise RuntimeError("Git-Bash oberhalb von %s nicht gefunden — CARPE_NOCTEM_BASH setzen" % git)


def run_cmd(root: Path, cmd: str, timeout: int = CHECK_TIMEOUT) -> tuple[int, str]:
    """Befehl in (Git-)Bash im Repo ausführen. Rückgabe: (Exit-Code, letzte Zeilen)."""
    try:
        shell = bash_exe()
    except RuntimeError as exc:
        return 127, "Shell nicht startbar: %s" % exc
    try:
        proc = subprocess.run([shell, "-c", cmd], cwd=str(root), capture_output=True,
                              text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return 124, "nach %ds abgebrochen" % timeout
    except OSError as exc:
        return 127, "nicht startbar: %s" % exc
    out = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
    return proc.returncode, " / ".join(out[-3:])[:400]


# ── Richter-Dateien (Schreibschutz) ──────────────────────────────────────────

def _git_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
                             capture_output=True, text=True, timeout=30, encoding="utf-8")
        return [line.strip() for line in out.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def matches_protected(rel_path: str, globs: list[str]) -> bool:
    """`tests/**` trifft alles unter tests/, sonst fnmatch auf den Repo-Pfad."""
    rel = rel_path.replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    for pattern in globs:
        pat = pattern.strip().replace("\\", "/")
        while pat.startswith("./"):
            pat = pat[2:]
        if not pat:
            continue
        if pat.endswith("/**") and (rel == pat[:-3] or rel.startswith(pat[:-2])):
            return True
        if fnmatch.fnmatch(rel, pat):
            return True
    return False


def protected_hashes(root: Path, globs: list[str]) -> dict[str, str]:
    """SHA256 jeder Richter-Datei. Der Richter liegt außerhalb der Reichweite des Täters —
    Karpathys `prepare.py` ist read-only, ImpossibleBench misst genau diesen Schutz."""
    hashes = {}
    for rel in _git_files(root):
        if matches_protected(rel, globs):
            try:
                hashes[rel] = hashlib.sha256((root / rel).read_bytes()).hexdigest()
            except OSError:
                continue
    return hashes


def protected_drift(root: Path, ledger: dict) -> list[str]:
    """Richter-Dateien, die seit Nachtbeginn geändert, gelöscht oder neu sind.

    Neue Dateien zählen mit: eine nachts angelegte `conftest.py`, die Tests überspringt,
    ist genau die Manipulation, gegen die der Schutz steht. Neue Tests gehören in die
    Vorbereitung (Red/Green beginnt dort) oder in einen nicht geschützten Pfad."""
    globs = ledger.get("geschuetzt") or []
    if not globs or not ledger.get("nacht_beginn"):
        return []
    before = ledger.get("geschuetzt_hashes") or {}
    after = protected_hashes(root, globs)
    changed = [p for p in before if after.get(p) != before[p]]
    added = [p for p in after if p not in before]
    return sorted(changed + added)


def relative_to_root(root: Path, file_path: str) -> str | None:
    try:
        return Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


# ── Journal, Fehlerprotokoll ─────────────────────────────────────────────────

def journal(root: Path, text: str) -> None:
    path = journal_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = "- %s — %s\n" % (now().strftime("%Y-%m-%d %H:%M"), text.replace("\n", " ").strip())
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)


def hook_error(root: Path | None, where: str) -> None:
    """Hook-Fehler protokollieren und melden. Der Hook exitet danach trotzdem 0 —
    aber still ist er nicht mehr."""
    tb = traceback.format_exc()
    last = tb.strip().splitlines()[-1] if tb.strip() and "NoneType: None" not in tb else where
    try:
        if root is not None and cn_dir(root).exists():
            with (cn_dir(root) / HOOK_ERROR_NAME).open("a", encoding="utf-8", newline="\n") as fh:
                fh.write("=== %s · %s\n%s\n" % (iso(now()), where, tb))
    except OSError:
        pass
    try:
        import cn_notify  # noqa: PLC0415 — Importzyklus vermeiden
        ledger = _read_json(ledger_path(root)) if root is not None else None
        cn_notify.push("Carpe Noctem: Hook-Fehler", "%s — %s" % (where, last), prio="high",
                       root=root, ledger=ledger)
    except Exception:  # noqa: BLE001
        pass


# ── Fortschritts-Fingerabdruck (Wachhund gegen Endlosschleifen) ──────────────

def fingerprint(root: Path, ledger: dict) -> str:
    """Abdruck aus Git-Zustand und Ledger-Zählern.

    Die Journalgröße zählt bewusst NICHT: jeder Hook schreibt ins Journal, damit sah
    jede Runde nach Fortschritt aus und die Leerlauf-Erkennung griff nie. Eine Wache
    zählt als Fortschritt —
    Warten auf den Menschen ist kein Leerlauf.
    """
    parts = [
        str(len(items_by_state(ledger, "done"))),
        str(len(items_by_state(ledger, "blocked"))),
        str(len(waiting_items(ledger))),
        str(len(ledger.get("items", []))),
        str(len(ledger.get("entscheidungen", []))),
        str(len(ledger.get("todos", []))),
        str(ledger.get("wachen", 0)),
        str(len(ledger.get("haertung") or [])),
        str(len(ledger.get("klassifikator_ablehnungen") or [])),
        str(ledger.get("inbox_gelesen", 0)),
        str(sum(len(i.get("fortschritt") or []) for i in ledger.get("items", []))),
    ]
    for cmd in (["rev-parse", "HEAD"], ["status", "--porcelain"]):
        try:
            out = subprocess.run(["git", "-C", str(root), *cmd],
                                 capture_output=True, text=True, timeout=8)
            parts.append(out.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            parts.append("")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


# ── mission.md parsen ────────────────────────────────────────────────────────

_ITEM_RE = re.compile(
    r"^\s*[-*]\s*\[[^\]]?\]\s*(?P<id>[A-Za-z]{1,3}\d+)\s*[-—:.]\s*(?P<rest>.+)$"
)
_CHECK_RE = re.compile(r"^\s*(?:prüfen|pruefen|check|pruefbefehl)\s*:\s*(?P<cmd>.+?)\s*$",
                       re.IGNORECASE)
# `- G1 [A2] login: Azure-CLI-Token für den Upload` (+ eingerückt `probe: <befehl>`)
_GRENZE_RE = re.compile(
    r"^\s*[-*]\s*(?:\[[^\]]?\]\s*)?(?P<id>G\d+)\s*\[(?P<paket>[A-Za-z]{1,3}\d+)\]\s*"
    r"(?P<art>[a-zäöü]+)\s*:\s*(?P<was>.+)$", re.IGNORECASE)
_PROBE_RE = re.compile(r"^\s*(?:probe|trockenlauf)\s*:\s*(?P<cmd>.+?)\s*$", re.IGNORECASE)
# Vorgänger eines Pakets: eingerückte Folgezeile `nach: A1, A4`.
_NACH_RE = re.compile(r"^\s*(?:nach|after|braucht)\s*:\s*(?P<ids>.+?)\s*$", re.IGNORECASE)
_ID_RE = re.compile(r"[A-Za-z]{1,3}\d+")
_FUELLWOERTER = {"", "und", "and", "sowie", "&"}


def split_ids(value: str) -> list[str]:
    return [p for p in re.split(r"[\s,;]+", value or "") if _ID_RE.fullmatch(p)]


def unclear_tokens(value: str) -> list[str]:
    """Teile einer `nach:`-Angabe, die keine Paket-ID sind — gemeldet, nicht verschluckt."""
    return [p for p in re.split(r"[\s,;]+", value or "")
            if not _ID_RE.fullmatch(p) and p.lower() not in _FUELLWOERTER]


def parse_mission(text: str) -> dict:
    """mission.md -> {front, items, grenzen, premortem, verbotene_aktionen, hardening_backlog}.

    Format siehe skills/carpe-noctem-vorbereitung/SKILL.md. Tolerant: was der Parser
    nicht versteht, ignoriert er — was fehlt, meldet der Aufrufer, statt es zu erfinden.
    """
    front: dict[str, str] = {}
    body = text
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if fm:
        for line in fm.group(1).splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition(":")
                value = re.sub(r"\s+#.*$", "", value)
                front[key.strip().lower()] = value.strip().strip('"').strip("'")
        body = fm.group(2)

    sections: dict[str, list[str]] = {}
    current = ""
    for line in body.splitlines():
        head = re.match(r"^#{1,6}\s+(.*)$", line)
        if head:
            current = head.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    def section(*needles: str) -> list[str]:
        for name, lines in sections.items():
            if any(n in name for n in needles):
                return lines
        return []

    def blocks(lines: list[str], head_re: re.Pattern) -> list[tuple[re.Match, list[str]]]:
        # Ein Eintrag ist ein Block: eingerückte Folgezeilen gehören dazu. Wer nur die
        # erste Zeile nimmt, schreibt Fragmente wie `fertig_wenn: "in"` ins Ledger.
        out: list[tuple[re.Match, list[str]]] = []
        for line in lines:
            m = head_re.match(line)
            if m:
                out.append((m, []))
            elif out and line.strip() and line[:1].isspace():
                out[-1][1].append(line.strip())
        return out

    items = []
    for m, follow in blocks(section("arbeitspaket", "pakete", "aufgaben"), _ITEM_RE):
        check = ""
        nach: list[str] = []
        unklar: list[str] = []
        body_lines = [m.group("rest").strip()]
        for part in follow:
            cm = _CHECK_RE.match(part)
            dm = _NACH_RE.match(part)
            if cm:
                check = cm.group("cmd").strip().strip("`")
            elif dm:
                nach += split_ids(dm.group("ids"))
                unklar += unclear_tokens(dm.group("ids"))
            else:
                body_lines.append(part)
        rest = " ".join(body_lines).strip()
        title, done_when = rest, ""
        for sep in ("::", "|", " — fertig wenn:", " fertig wenn:"):
            if sep in rest:
                title, _, done_when = rest.partition(sep)
                break
        done_when = re.sub(r"^\s*(fertig wenn|dod|done when)\s*:\s*", "",
                           done_when.strip(), flags=re.IGNORECASE)
        items.append({
            "id": m.group("id"),
            "titel": title.strip(" -—:|"),
            "fertig_wenn": done_when.strip(),
            "pruefbefehl": check,
            "nach": nach,
            "nach_unklar": unklar,
            "status": "open",
            "beleg": "",
            "notiz": "",
        })

    grenzen = []
    for m, follow in blocks(section("grenzen"), _GRENZE_RE):
        probe = ""
        extra = []
        for part in follow:
            pm = _PROBE_RE.match(part)
            if pm:
                probe = pm.group("cmd").strip().strip("`")
            else:
                extra.append(part)
        grenzen.append({
            "id": m.group("id").upper(),
            "paket": m.group("paket"),
            "art": m.group("art").lower(),
            "was": " ".join([m.group("was").strip(), *extra]).strip(),
            "probe": probe,
            "status": "offen",
            "klaerung": "",
            "ersatz": "",
        })

    def bullets(lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            b = re.match(r"^\s*[-*]\s+(.*\S)\s*$", line)
            if b:
                out.append(re.sub(r"^\[[^\]]?\]\s*", "", b.group(1)).strip())
        return out

    return {
        "front": front,
        "items": items,
        "grenzen": grenzen,
        "premortem": bullets(section("pre-mortem", "premortem")),
        "verbotene_aktionen": bullets(section("verboten", "nur der mensch", "tabu")),
        # `haertung` als Eingabe-Toleranz: wer ohne Umlaut tippt, wird trotzdem gefunden.
        "hardening_backlog": bullets(section("härtung", "haertung", "hardening", "backlog")),
    }


def split_globs(value: str) -> list[str]:
    return [g.strip() for g in re.split(r"[,;]", value or "") if g.strip()]


# ── Umgebung der Session ─────────────────────────────────────────────────────

def block_cap(root: Path) -> tuple[str, str] | None:
    """Wo ist CLAUDE_CODE_STOP_HOOK_BLOCK_CAP gesetzt? (Quelle, Wert) oder None.

    Der Wert kann als Umgebungsvariable, in den Repo- oder in den User-Settings stehen.
    Wer nur eine Quelle liest, meldet fälschlich „fehlt“.
    """
    def tragfaehig(value) -> bool:  # 8 ist der Default — darunter oder gleich hilft nichts
        try:
            return int(str(value).strip()) > 8
        except ValueError:
            return False

    if tragfaehig(os.environ.get("CLAUDE_CODE_STOP_HOOK_BLOCK_CAP")):
        return "Umgebungsvariable", os.environ["CLAUDE_CODE_STOP_HOOK_BLOCK_CAP"]
    for path in (root / ".claude" / "settings.json", root / ".claude" / "settings.local.json",
                 Path.home() / ".claude" / "settings.json"):
        try:
            env = json.loads(path.read_text(encoding="utf-8")).get("env") or {}
        except (OSError, ValueError):
            continue
        if tragfaehig(env.get("CLAUDE_CODE_STOP_HOOK_BLOCK_CAP")):
            return path.as_posix(), str(env["CLAUDE_CODE_STOP_HOOK_BLOCK_CAP"])
    return None


_DENIAL_RE = re.compile(r"^\s*Permission for this action was denied by the Claude Code auto mode "
                        r"classifier\. Reason: \[(?P<grund>[^\]]+)\]")


def _tool_error_texts(entry: dict) -> list[str]:
    """Texte der fehlgeschlagenen Tool-Ergebnisse eines Transkript-Eintrags."""
    if entry.get("type") != "user":
        return []
    content = (entry.get("message") or {}).get("content")
    out = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_result" or not block.get("is_error"):
            continue
        body = block.get("content")
        if isinstance(body, list):
            body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
        out.append(str(body or ""))
    return out


def scan_transcript(ledger: dict, transcript_path: str | None) -> list[str]:
    """Neue Ablehnungen des Auto-Mode-Klassifikators seit dem letzten Aufruf.

    Im Auto-Mode feuert kein PermissionRequest-Hook — der Klassifikator lehnt ab, der
    Agent arbeitet weiter, und ohne diesen Scan erfährt weder Ledger noch Bericht davon.

    Gezählt wird nur ein fehlgeschlagenes Tool-Ergebnis, das MIT der Klassifikator-Meldung
    beginnt — kein Zitat, keine gelesene Datei, die den Satz enthält. Nur Einträge ab
    Nachtbeginn (Ablehnungen der Vorbereitung sind dort schon behandelt). Der Offset
    rückt nur bis zur letzten vollständigen Zeile vor, damit nichts doppelt oder halb zählt.
    """
    if not transcript_path:
        return []
    path = Path(transcript_path)
    try:
        start = int(ledger.get("transcript_pos") or 0)
        if start > path.stat().st_size:
            start = 0
        with path.open("rb") as fh:
            fh.seek(start)
            raw = fh.read()
    except OSError:
        return []
    cut = raw.rfind(b"\n")
    if cut < 0:
        return []
    ledger["transcript_pos"] = start + cut + 1
    beginn = parse_iso(ledger.get("nacht_beginn"))
    found = []
    for line in raw[:cut].decode("utf-8", "replace").splitlines():
        if "auto mode classifier" not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        stamp = parse_iso(str(entry.get("timestamp") or "").replace("Z", "+00:00"))
        if beginn and stamp and stamp < beginn:
            continue
        for text in _tool_error_texts(entry):
            m = _DENIAL_RE.match(text)
            if m:
                found.append(m.group("grund"))
    return found


# ── Ausgabe ──────────────────────────────────────────────────────────────────

def stdout_utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


def read_hook_input() -> dict:
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def cli_cmd(ledger: dict | None = None) -> str:
    """Aufrufform der CLI, wie sie in Hook-Texten und Prompts steht.

    Die Umgebung gewinnt vor dem Ledger: der im Ledger gemerkte Pfad trägt die
    Plugin-Version im Namen und zeigt nach dem nächsten Bump ins Leere."""
    root = (os.environ.get("CLAUDE_PLUGIN_ROOT", "") or (ledger or {}).get("cn_cmd") or ""
            ).replace("\\", "/").rstrip("/")
    if root:
        return 'python "%s/scripts/cn.py"' % root
    return 'python "%s"' % (Path(__file__).resolve().parent / "cn.py").as_posix()
