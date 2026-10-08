"""PreCompact — den Riss im Ledger markieren, bevor der Kontext zusammengefaltet wird.

Die Wiedereinspeisung macht `session-start.py` (SessionStart mit `source: "compact"`).
Hier wird festgehalten, an welcher Stelle der Nacht der Kontext riss, damit die nächste
Runde der Zusammenfassung entsprechend weniger traut.
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
    if ledger is None:
        sys.exit(0)

    trigger = data.get("trigger") or "?"
    item = ns.current_item(ledger)
    ledger["letzte_kompaktierung"] = {
        "zeit": ns.iso(ns.now()), "trigger": trigger,
        "paket": (item or {}).get("id", ""), "fortsetzung": ledger.get("continuations", 0),
    }
    if item is not None:
        ns.add_progress(item, "— Kontext an dieser Stelle kompaktiert (%s) —" % trigger)
    ns.save(root, ledger)
    ns.journal(root, "Kontext-Kompaktierung (%s) bei Runde %d, Paket %s"
               % (trigger, ledger.get("continuations", 0), (item or {}).get("id", "keins")))
    print(json.dumps({"systemMessage": (
        "Carpe Noctem: Kontext wird kompaktiert. Behalte das laufende Paket %s samt Erledigtem, die "
        "zuletzt gelaufenen Befehle mit Ergebnis und Messwerte im Wortlaut. Der Stand liegt im "
        "Ledger unter %s." % ((item or {}).get("id", "(keins)"), ns.cn_dir(root).as_posix()))}))


if __name__ == "__main__":
    box: list = []
    try:
        main(box)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        ns.hook_error(box[0] if box else None, "pre-compact")
        sys.exit(0)
