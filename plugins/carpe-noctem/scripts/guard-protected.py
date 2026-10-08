"""PreToolUse(Edit|Write|MultiEdit|NotebookEdit) — Richter-Dateien sind nachts schreibgeschützt.

Agenten neigen dazu, Tests aufzuweichen, statt den Code zu reparieren; Benchmarks wie
ImpossibleBench messen schreibgeschützte Tests als Gegenmaßnahme. Karpathys autoresearch
macht es baulich: die Datei mit der Bewertung ist read-only, nur die Trainingsdatei ist frei.

Hier dasselbe für die Nacht: was in mission.md unter `geschuetzt:` steht, darf der
Agent nicht editieren. Schreibwege an diesem Hook vorbei (Bash, sed, git checkout)
fängt die Hash-Prüfung in `cn.py item done`/`verify` — sie verweigert die Abnahme.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cn_state as ns  # noqa: E402


def main(box: list) -> None:
    data = ns.read_hook_input()
    root = ns.find_root(data)
    box.append(root)
    ledger = ns.active_for_session(root, data.get("session_id"))
    if ledger is None or not ledger.get("geschuetzt"):
        sys.exit(0)

    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    rel = ns.relative_to_root(root, target) if target else None
    if not rel or not ns.matches_protected(rel, ledger["geschuetzt"]):
        sys.exit(0)

    ns.journal(root, "Schreibversuch auf Richter-Datei abgelehnt: %s" % rel)
    cmd = ns.cli_cmd(ledger)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            "CARPE NOCTEM: `%s` ist eine Richter-Datei (geschützt in mission.md) — gegen sie wird "
            "abgenommen, deshalb ändert die Nacht sie nicht. Bring den Code dazu, den Test zu "
            "bestehen. Hältst du den Test für falsch: `%s todo \"Test %s prüfen\" --prio P1 --warum "
            "\"<Begründung>\" --schritt \"<vorgeschlagene Änderung>\"` und das Paket an die Grenze "
            "hängen (`item wait <ID> --art urteil`)." % (rel, cmd, rel)),
    }}))
    sys.exit(0)


if __name__ == "__main__":
    box: list = []
    try:
        main(box)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        ns.hook_error(box[0] if box else None, "guard-protected")
        sys.exit(0)
