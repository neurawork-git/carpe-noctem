"""SessionStart — Lagebild der laufenden Nacht wieder in den Kontext holen.

Feuert auch mit `source: "compact"`, direkt nach einer Kontext-Kompaktierung — der
Punkt, an dem eine Nacht sonst ihr Gedächtnis verliert. Das Lagebild wird aus dem
Ledger gebaut, nicht aus dem Gespräch.

Weitere Fälle: eine Vorbereitung ist angefangen (Hinweis, wo es weitergeht), eine
Nacht ist unterbrochen (`resume`/`abort` anbieten), eine Nacht gehört einer anderen
Session (melden, nicht adoptieren — außer ihre Deadline ist durch).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cn_report  # noqa: E402
import cn_state as ns  # noqa: E402


def emit(context: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }}))


def main(box: list) -> None:
    data = ns.read_hook_input()
    root = ns.find_root(data)
    box.append(root)
    ledger = ns.load(root)
    if ledger is None or ledger.get("status") not in ("active", "interrupted", "vorbereitung"):
        sys.exit(0)

    cmd = ns.cli_cmd(ledger)
    session_id = data.get("session_id")
    bound = ledger.get("bound_session")

    if ledger.get("status") == "vorbereitung":
        emit("CARPE NOCTEM in Vorbereitung: „%s“ (%d Pakete, %d Grenzen). Weiter mit dem Skill "
             "`carpe-noctem-vorbereitung`; Stand: `%s risiko`. Die Hooks sind still, bis `%s start` "
             "die Nacht beginnt." % (ledger.get("titel"), len(ledger.get("items", [])),
                                     len(ledger.get("grenzen", [])), cmd, cmd))
        sys.exit(0)

    if ledger.get("status") == "interrupted":
        emit("UNTERBROCHENE NACHT in diesem Repo: %s (%s). Fortsetzen mit `%s resume`, Stand mit "
             "`%s status`, endgültig schließen mit `%s abort --grund \"…\"`. Bis dahin sind die Hooks "
             "still." % (ledger.get("titel"), ns.progress_line(ledger), cmd, cmd, cmd))
        sys.exit(0)

    rest = ns.remaining(ledger.get("deadline"))
    if bound and session_id and bound != session_id and rest is not None and rest.total_seconds() <= 0:
        ledger["bound_session"] = None
        ledger["no_progress_streak"] = 0
        ledger["report_blocks"] = 0
        ns.save(root, ledger)
        ns.journal(root, "Bindung gelöst: Deadline abgelaufen, gebundene Session antwortet nicht "
                         "mehr — diese Session übernimmt den Abschluss.")
        emit("CARPE NOCTEM ÜBERFÄLLIG: „%s“ (%s). Deadline %s ist durch, die fahrende Session ist "
             "weg. Diese Session schließt ab: `%s report`, Kurzfassung ausfüllen, `%s finish`. Keine "
             "neuen Pakete." % (ledger.get("titel"), ns.progress_line(ledger), ledger.get("deadline"),
                                cmd, cmd))
        sys.exit(0)

    if bound and session_id and bound != session_id:
        emit("ACHTUNG: in diesem Repo läuft eine Carpe-Noctem-Nacht (%s, %s), die an eine ANDERE "
             "Session gebunden ist. Diese Session arbeitet normal; die Nacht-Hooks greifen hier nicht. "
             "Ist die andere Session tot: `%s resume`." % (ledger.get("titel"),
                                                           ns.progress_line(ledger), cmd))
        sys.exit(0)

    ns.journal(root, "Session-Start (%s) — Lagebild neu injiziert." % (data.get("source") or "?"))
    emit(cn_report.briefing(ledger, root, cmd))


if __name__ == "__main__":
    box: list = []
    try:
        main(box)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        ns.hook_error(box[0] if box else None, "session-start")
        sys.exit(0)
