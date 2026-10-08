"""SessionEnd — abgerissene Nacht kennzeichnen, Notbericht schreiben, Bescheid geben.

Stirbt die Session (Absturz, `/clear`, Login abgelaufen, Terminal zu), bliebe das
Ledger sonst auf `active` an eine tote Session gebunden, und die Nacht stünde bis zum
Morgen still, ohne dass es jemand erfährt. Deshalb: `interrupted`, Notbericht, Meldung.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cn_notify  # noqa: E402
import cn_report  # noqa: E402
import cn_state as ns  # noqa: E402


def main(box: list) -> None:
    data = ns.read_hook_input()
    if ns.round_mode():
        sys.exit(0)  # jede Headless-Runde endet planmäßig — kein Abriss
    root = ns.find_root(data)
    box.append(root)
    ledger = ns.active_for_session(root, data.get("session_id"))
    if ledger is None:
        sys.exit(0)

    grund = data.get("reason") or "?"
    ledger["status"] = "interrupted"
    ledger["bound_session"] = None
    ledger["unterbrochen"] = ns.iso(ns.now())
    ledger["ende_grund"] = "Session beendet (%s)" % grund
    ledger["beendet"] = ns.iso(ns.now())
    ns.save(root, ledger)

    report = ns.report_path(root)
    if not report.exists() or report.stat().st_size < 200:
        with report.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(cn_report.render(ledger, root=root, auto=True))
    ns.journal(root, "Session beendet (%s) — Nacht unterbrochen, %s" % (grund, ns.progress_line(ledger)))
    cn_notify.push("Carpe Noctem unterbrochen", "%s — Session beendet (%s). %s. Weiter mit `cn.py "
                   "resume` in einer neuen Session." % (ledger.get("titel"), grund,
                                                        ns.progress_line(ledger)), prio="high",
                   tags="warning", root=root, ledger=ledger)


if __name__ == "__main__":
    box: list = []
    try:
        main(box)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        ns.hook_error(box[0] if box else None, "session-end")
        sys.exit(0)
