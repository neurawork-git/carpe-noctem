"""PreToolUse(AskUserQuestion|ExitPlanMode) — Rückfragen-Sperre der Nacht.

Nachts ist eine Rückfrage kein Klärungsversuch, sondern ein Deadlock: die Session
steht bis zum Morgen. Deshalb wird das Werkzeug abgelehnt — und die Ablehnung liefert
das Ersatzverfahren mit. Feuert laut Claude-Code-Doku auch in Subagenten.

Jede Sperre wird gezählt und ins Journal geschrieben: wie oft die Nacht fragen wollte,
ist ein Maß dafür, was die Vorbereitung übersehen hat.

In der Vorbereitung (status `vorbereitung`) ist diese Sperre still — da sind Fragen
erwünscht.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cn_state as ns  # noqa: E402


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        "systemMessage": "Carpe Noctem: Rückfrage abgelehnt.",
    }))
    sys.exit(0)


def main(box: list) -> None:
    data = ns.read_hook_input()
    root = ns.find_root(data)
    box.append(root)
    ledger = ns.active_for_session(root, data.get("session_id"))
    if ledger is None:
        sys.exit(0)

    cmd = ns.cli_cmd(ledger)
    tool = data.get("tool_name", "")
    ledger["fragesperren"] = ledger.get("fragesperren", 0) + 1
    ns.save(root, ledger)

    if tool == "ExitPlanMode":
        ns.journal(root, "Planfreigabe abgelehnt (Nacht läuft).")
        deny("CARPE NOCTEM: Planfreigabe ist gesperrt — der Plan steht in %s und wurde in der "
             "Vorbereitung freigegeben. Arbeite am obersten offenen Paket weiter; neue Arbeit "
             "mit `%s item add --titel \"…\" --fertig-wenn \"…\"`."
             % (ns.mission_path(root).as_posix(), cmd))

    frage = ""
    for q in (data.get("tool_input") or {}).get("questions") or []:
        if isinstance(q, dict) and q.get("question"):
            frage = str(q["question"]).replace('"', "'")
            break
    ns.journal(root, "Rückfrage abgelehnt%s: %s" % (
        " (Subagent %s)" % data["agent_type"] if data.get("agent_type") else "", frage or "?"))

    deny("\n".join([
        "CARPE NOCTEM: Rückfragen sind gesperrt — niemand antwortet, die Session stünde bis morgen.",
        "",
        "Stattdessen, in dieser Reihenfolge:",
        "1. Selbst nachsehen: mission.md, README/CLAUDE.md, Code, vorhandene Projektdoku bzw. Wissensbasis.",
        "2. Ist es eine Geschmacks- oder Umsetzungsfrage: REVERSIBEL wählen und protokollieren:",
        '   %s decision "%s" --wahl "…" --warum "…" --reversibel "<wie zurück>"' % (cmd, frage or "<Frage>"),
        "3. Braucht es wirklich einen Menschen (Urteil, Freigabe, Login, Recht): das ist eine",
        "   GRENZE. Bis dorthin vorbereiten, dann",
        '   %s item wait <ID> --art urteil --notiz "<was der Mensch entscheiden muss>"' % cmd,
        "   — das schickt eine Meldung (md/ntfy), du arbeitest am nächsten Paket weiter.",
        "4. Weder entscheidbar noch an ein Paket gebunden: %s frage \"<Frage samt Kontext>\"." % cmd,
        "",
        "Danach ohne Unterbrechung weiterarbeiten. Frag nicht erneut.",
    ]))


if __name__ == "__main__":
    box: list = []
    try:
        main(box)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        ns.hook_error(box[0] if box else None, "guard-no-questions")
        sys.exit(0)
