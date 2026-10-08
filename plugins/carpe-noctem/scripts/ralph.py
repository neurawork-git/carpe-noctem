"""Headless-Rundenlauf — die Ralph-Variante von Carpe Noctem.

Der interaktive Modus hält EINE Session über Stunden am Leben; der Stop-Hook
verweigert das Anhalten. Das funktioniert, hat aber eine Schwäche: der Kontext
altert. Nach genug Kompaktierungen arbeitet der Agent an einem Bild der Lage,
das nur noch entfernt mit den Dateien übereinstimmt.

Hier läuft es umgekehrt — nach dem Ralph-Muster: eine dumme äußere Schleife
startet immer wieder `claude -p` mit demselben Rundenprompt. Jede Runde beginnt
mit frischem Kontext und holt sich den Stand aus dem Ledger. Die Intelligenz
liegt im Dateizustand (mission.md, ledger.json, journal.md), nicht im Verlauf.

Die Runden-Kinder laufen mit `CARPE_NOCTEM_ROUND=1`: dann hält sich der
Stop-Hook heraus (die Runde DARF enden) und SessionEnd markiert die Schicht
nicht als abgerissen. Motor ist diese Schleife.

    python scripts/ralph.py --rounds 40

Voraussetzung: `cn.py preflight` ist sauber. Im Print-Modus fragt Claude Code
nicht nach Erlaubnis, sondern verweigert nicht freigegebene Werkzeuge — eine
löchrige Allow-Liste lässt die Nacht also nicht hängen, sondern scheitern.
Deshalb: Allow-Liste vorher füllen, keinen Bypass verwenden.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cn_notify  # noqa: E402
import cn_report  # noqa: E402
import cn_state as ns  # noqa: E402

STUCK_ROUNDS = 4  # so viele Runden ohne messbaren Fortschritt, dann Abbruch
LIMIT_RE = re.compile(r"(session|usage|rate) limit", re.IGNORECASE)
RESET_RE = re.compile(r"resets?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE)
LIMIT_WAIT_DEFAULT = 1800  # Sekunden, wenn keine Reset-Zeit lesbar ist


def limit_wait_seconds(log: Path) -> int | None:
    """Erkennt eine vom Limit abgewiesene Runde ('You've hit your session limit · resets 4:50am')
    und liefert die Wartezeit bis zum Reset — sonst None.

    Ohne diese Prüfung verbrennt die Schleife Dutzende Runden in Minuten: jede Runde endet
    sofort mit Exit 1, und die Leerlauf-Erkennung greift nicht rechtzeitig.
    """
    try:
        head = log.read_text(encoding="utf-8", errors="replace")[:600]
    except OSError:
        return None
    if not LIMIT_RE.search(head):
        return None
    m = RESET_RE.search(head)
    if not m:
        return LIMIT_WAIT_DEFAULT
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int((target - now).total_seconds()) + 90


def run_round(root: Path, prompt: str, model: str | None, log: Path, timeout: int) -> int:
    cmd = ["claude", "-p", prompt]
    if model:
        cmd += ["--model", model]
    env = {**os.environ, "CARPE_NOCTEM_ROUND": "1", "CLAUDE_INVOKED_BY": "carpe-noctem"}
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8", newline="\n") as fh:
        try:
            proc = subprocess.run(cmd, cwd=str(root), env=env, stdout=fh,
                                  stderr=subprocess.STDOUT, timeout=timeout)
            return proc.returncode
        except subprocess.TimeoutExpired:
            fh.write("\n[ralph] Runde nach %ds abgebrochen (Timeout).\n" % timeout)
            return 124
        except OSError as exc:
            fh.write("\n[ralph] `claude` nicht startbar: %s\n" % exc)
            return 127


def main() -> int:
    ns.stdout_utf8()
    p = argparse.ArgumentParser(prog="ralph", description="Carpe Noctem im Rundenmodus")
    p.add_argument("--root", help="Repo-Wurzel (Default: automatisch)")
    p.add_argument("--rounds", type=int, default=40, help="Obergrenze an Runden")
    p.add_argument("--model", help="Modell für die Runden (Default: Sitzungs-Default)")
    p.add_argument("--timeout", type=int, default=1800, help="Sekunden pro Runde")
    p.add_argument("--pause", type=int, default=5, help="Sekunden zwischen den Runden")
    args = p.parse_args()

    root = Path(args.root).resolve() if args.root else ns.find_root()
    ledger = ns.load(root)
    if ledger is None:
        print("FEHLER: keine Schicht in %s." % ns.cn_dir(root).as_posix())
        return 1
    if ledger.get("status") != "active":
        print("FEHLER: Schicht steht auf `%s` — erst `cn.py resume`." % ledger.get("status"))
        return 1

    prompt_file = ns.cn_dir(root) / "prompt.md"
    if not prompt_file.exists():
        print("FEHLER: %s fehlt (wird von `cn.py start` geschrieben)." % prompt_file.as_posix())
        return 1
    # `{CN}` zeigt auf die CLI dieses Plugins — zur Laufzeit aufgelöst, damit ein
    # Versions-Bump den in prompt.md eingefrorenen Pfad nicht still totlegt.
    cn_cmd = 'python "%s"' % (Path(__file__).resolve().parent / "cn.py").as_posix()
    prompt = prompt_file.read_text(encoding="utf-8").replace("{CN}", cn_cmd)

    print("Carpe Noctem im Rundenmodus: %s" % ledger.get("titel"))
    print("  %s · Restzeit %s · max. %d Runden\n"
          % (ns.progress_line(ledger), ns.human_delta(ns.remaining(ledger.get("deadline"))),
             args.rounds))
    ns.journal(root, "Headless-Rundenlauf gestartet (max. %d Runden)." % args.rounds)

    last_fp = ns.fingerprint(root, ledger)
    stuck = 0

    round_no = 0
    ende = "Rundenobergrenze erreicht (%d)" % args.rounds
    while round_no < args.rounds:
        round_no += 1
        ledger = ns.load(root) or ledger
        if ledger.get("status") != "active":
            print("Schicht steht auf `%s` — Schleife endet." % ledger.get("status"))
            ende = None
            break
        rest = ns.remaining(ledger.get("deadline"))
        if rest is not None and rest.total_seconds() <= 0:
            print("Zeitlimit erreicht — Schleife endet.")
            ende = "Deadline erreicht"
            break

        log = ns.cn_dir(root) / "rounds" / ("round-%03d.log" % round_no)
        print("[Runde %d/%d] %s · Restzeit %s"
              % (round_no, args.rounds, ns.progress_line(ledger), ns.human_delta(rest)))
        code = run_round(root, prompt, args.model, log, args.timeout)
        print("            beendet (Exit %d) · Protokoll %s" % (code, log.as_posix()))
        if code == 127:
            ns.journal(root, "Rundenlauf abgebrochen: `claude` nicht startbar.")
            print("`claude` ließ sich nicht starten — Schleife endet.")
            cn_notify.push("Carpe Noctem: Rundenlauf abgebrochen", "`claude` nicht startbar.", prio="high",
                           root=root, ledger=ledger)
            return 1

        wait = limit_wait_seconds(log) if code != 0 else None
        if wait is not None:
            rest = ns.remaining(ledger.get("deadline"))
            if rest is not None and rest.total_seconds() <= wait:
                ns.journal(root, "Rundenlauf gestoppt: Nutzungslimit, Reset erst nach der Deadline.")
                print("Nutzungslimit erreicht, Reset liegt hinter der Deadline — Schleife endet.")
                ende = "Nutzungslimit, Reset nach der Deadline"
                break
            ns.journal(root, "Nutzungslimit erreicht — warte %d min bis zum Reset (Runde zählt nicht)."
                       % (wait // 60))
            print("            Nutzungslimit — warte %d min, dann weiter." % (wait // 60))
            time.sleep(wait)
            round_no -= 1
            continue

        ledger = ns.load(root) or ledger
        fp = ns.fingerprint(root, ledger)
        stuck = stuck + 1 if fp == last_fp else 0
        last_fp = fp
        if stuck >= STUCK_ROUNDS:
            ns.journal(root, "Rundenlauf gestoppt: %d Runden ohne messbaren Fortschritt." % stuck)
            print("%d Runden ohne Fortschritt — Schleife endet, damit die Nacht nicht "
                  "im Kreis läuft." % stuck)
            ende = "Leerlauf — %d Runden ohne Fortschritt" % stuck
            break
        if ns.open_items(ledger) or ledger.get("status") == "active":
            time.sleep(max(0, args.pause))

    ledger = ns.load(root) or ledger
    print("\nEnde. %s · Status %s" % (ns.progress_line(ledger), ledger.get("status")))
    report = ns.report_path(root)
    # Notbericht wie im interaktiven Modus — am Morgen liegt immer ein Bericht da.
    if ledger.get("status") == "active":
        if ende:
            ledger["ende_grund"] = ledger.get("ende_grund") or ende
        import cn  # noqa: PLC0415
        cn.close_night(root, ledger, ledger.get("ende_grund") or "Rundenlauf beendet")
        if report.exists() and report.stat().st_size >= 200:
            cn_report.refresh(report, ledger, root)
        else:
            with report.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(cn_report.render(ledger, root=root, auto=True))
    print("Bericht: %s" % report.as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
