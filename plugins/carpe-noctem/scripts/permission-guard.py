"""PermissionRequest — ein Permission-Dialog um 2 Uhr hält die Nacht bis zum Morgen an.

Laut Claude-Code-Doku pausiert eine Session an einem Permission-Prompt, „until you
respond". Dieser Hook beantwortet den Dialog nachts selbst: **ablehnen**, die Grenze
ins Ledger schreiben (Art `permission`, Status `getroffen`) und den Agenten anweisen,
das Paket auf die Wartebank zu setzen und weiterzuarbeiten. Morgens steht im Bericht,
welche Allow-Regel gefehlt hat — die Vorbereitung lernt daraus.

Wichtig: `PermissionRequest` feuert nur in den Modi default/plan/acceptEdits. Im
Auto-Mode lehnt der Klassifikator still ab und die Nacht erfährt nichts davon —
deshalb empfiehlt `cn.py preflight` Default oder acceptEdits für die Nacht.

Außerhalb einer aktiven Nacht (und in der Vorbereitung) tut der Hook nichts — dann
sieht der Mensch den Dialog wie immer und genau das ist gewollt: in der Vorbereitung
SOLLEN die Dialoge kommen, solange jemand wach ist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cn_notify  # noqa: E402
import cn_state as ns  # noqa: E402


def _describe(tool: str, tool_input: dict) -> str:
    if tool == "Bash":
        return "Bash: %s" % str(tool_input.get("command", ""))[:160]
    for key in ("file_path", "path", "url", "pattern"):
        if tool_input.get(key):
            return "%s: %s" % (tool, str(tool_input[key])[:160])
    return tool


def main(box: list) -> None:
    data = ns.read_hook_input()
    root = ns.find_root(data)
    box.append(root)
    ledger = ns.active_for_session(root, data.get("session_id"))
    if ledger is None:
        sys.exit(0)

    cmd = ns.cli_cmd(ledger)
    was = _describe(data.get("tool_name", "?"), data.get("tool_input") or {})
    item = ns.current_item(ledger)
    g = {"id": ns.next_id(ledger["grenzen"], "G"), "paket": (item or {}).get("id", ""),
         "art": "permission", "was": "Permission fehlte: %s" % was, "probe": "",
         "status": "getroffen", "klaerung": "", "ersatz": "", "nachts": True}
    ledger["grenzen"].append(g)
    ns.save(root, ledger)
    ns.journal(root, "Permission-Dialog nachts abgelehnt (%s): %s" % (g["id"], was))
    cn_notify.push("Carpe Noctem: Permission fehlt", "%s\nPaket %s · Grenze %s" % (
        was, g["paket"] or "?", g["id"]), prio="default", tags="lock", root=root, ledger=ledger)

    message = (
        "CARPE NOCTEM: Permission-Dialog nachts abgelehnt — niemand kann ihn bestätigen "
        "(Grenze %s protokolliert). Gibt es einen freigegebenen Weg zum selben Ziel, nimm ihn. "
        "Sonst: bis hierher vorbereiten und `%s item wait %s --grenze %s --notiz \"Allow-Regel "
        "für <…> fehlt\"`, dann am nächsten Paket weiter. Versuch NICHT, die Sperre mit einem "
        "anderen Befehl zu umgehen." % (g["id"], cmd, g["paket"] or "<ID>", g["id"]))
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        "decision": {"behavior": "deny", "message": message},
    }}))
    sys.exit(0)


if __name__ == "__main__":
    box: list = []
    try:
        main(box)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        ns.hook_error(box[0] if box else None, "permission-guard")
        sys.exit(0)
