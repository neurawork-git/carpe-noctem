"""Stop-Hook — der Motor der Nacht.

Ohne diesen Hook endet autonome Arbeit dort, wo das Modell sich für fertig hält. Hier
wird das Anhalten verweigert, solange die Nacht läuft, und der Fortsetzungsgrund wird
bei JEDEM Stop neu aus dem Ledger gebaut — er überlebt jede Kompaktierung.

Phasen, in dieser Reihenfolge:

1. **Arbeit** — offene Pakete, Risiko zuerst.
2. **Härtung** — alle Pakete zu oder wartend: eigene Fehler suchen (max. N Runden).
3. **Wache** — nur noch wartende Pakete und Restzeit: `cn.py wache` holt Nachrichten
   des Menschen und fährt die Trockenläufe der Grenzen nach — statt bei „alles
   blockiert" Feierabend zu machen und den Rest der Nacht zu verschenken.
4. **Abschluss** — Bericht erzwingen; schafft der Agent ihn nicht, schreibt ihn der Hook.

Ausstiege gegen die Endlosschleife: Deadline, `max_continuations`, Leerlauf (der
Fingerabdruck aus Git und Ledger bewegt sich STUCK_ABORT Runden nicht). Der Grund
wird im Ledger gespeichert und steht morgens im Bericht.

Neue Nachrichten des Menschen (Inbox, ntfy) stehen jedem Fortsetzungsgrund voran.
Exitet auf jedem Pfad 0; Fehler landen in `hook-fehler.log` und als Push.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cn  # noqa: E402
import cn_notify  # noqa: E402
import cn_report  # noqa: E402
import cn_state as ns  # noqa: E402

STUCK_WARN = 2
STUCK_ABORT = 4
REPORT_BLOCK_MAX = 3


def allow(message: str | None = None) -> NoReturn:
    if message:
        print(json.dumps({"systemMessage": message}))
    sys.exit(0)


def block(reason: str) -> NoReturn:
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


DENIAL_TAG = "[Klassifikator]"


def record_denials(root: Path, ledger: dict, transcript_path: str | None) -> list[dict]:
    """Klassifikator-Ablehnungen aus dem Transkript als Grenzen ins Ledger holen.

    Im Auto-Mode feuert kein PermissionRequest-Hook — ohne diesen Scan blieben Ablehnungen
    für Ledger und Bericht unsichtbar."""
    out = []
    for grund in ns.scan_transcript(ledger, transcript_path):
        item = ns.current_item(ledger) or {}
        g = {"id": ns.next_id(ledger["grenzen"], "G"), "paket": item.get("id", ""),
             "art": "permission", "was": "Auto-Mode-Klassifikator lehnte ab: %s" % grund,
             "probe": "", "status": "getroffen", "klaerung": "", "ersatz": "", "nachts": True,
             "klassifikator": True}
        ledger["grenzen"].append(g)
        ledger["klassifikator_ablehnungen"].append({"zeit": ns.iso(ns.now()), "grund": grund,
                                                    "paket": g["paket"], "grenze": g["id"]})
        ns.journal(root, "Klassifikator-Ablehnung (%s) bei Paket %s → Grenze %s"
                   % (grund, g["paket"] or "?", g["id"]))
        out.append(g)
    if out:  # ein Push je Stop, nicht je Fund — der Hook hat 30 s
        cn_notify.push("Carpe Noctem: Klassifikator lehnt ab (%d)" % len(out),
                       " · ".join("%s %s" % (g["id"], g["was"].split(": ", 1)[-1]) for g in out[:5]),
                       tags="lock", root=root, ledger=ledger)
    return out


def denial_notes(denials: list[dict]) -> list[str]:
    return ["%s %s lehnte eine Aktion ab (%s, Grenze %s). Dasselbe Ziel NICHT über ein anderes "
            "Werkzeug erzwingen. Gibt es einen freigegebenen Weg, nimm ihn; sonst `item wait %s "
            "--grenze %s --notiz \"…\"` und weiter." % (
                DENIAL_TAG, "Der Auto-Mode-Klassifikator", g["was"].split(": ", 1)[-1], g["id"],
                g["paket"] or "<ID>", g["id"]) for g in denials]


def inbox_block(msgs: list[str]) -> list[str]:
    if not msgs:
        return []
    human = [m for m in msgs if not m.startswith(DENIAL_TAG)]
    machine = [m for m in msgs if m.startswith(DENIAL_TAG)]
    out = []
    if machine:
        out += ["SPERRE SEIT DER LETZTEN RUNDE:", *["  » %s" % m[len(DENIAL_TAG):].strip() for m in machine], ""]
    if human:
        out += ["NACHRICHT VOM MENSCHEN (hat Vorrang vor dem Plan — umsetzen oder begründet "
                "als Entscheidung festhalten, `--quelle inbox`):", *["  » %s" % m for m in human], ""]
    return out


def head(ledger: dict, root: Path, rest_text: str, title: str) -> list[str]:
    return [
        title,
        "",
        "AUFTRAG: %s (%s)" % (ledger.get("titel") or "?", ns.mission_path(root).as_posix()),
        "STAND:   %s · Restzeit %s · Runde %d/%d" % (
            ns.progress_line(ledger), rest_text,
            ledger.get("continuations", 0), ledger.get("max_continuations", 0)),
        "",
    ]


def rules(cmd: str, ledger: dict) -> list[str]:
    out = ["REGELN DIESER NACHT", *["- " + r for r in cn_report.rules_text(cmd)]]
    if ledger.get("verbotene_aktionen"):
        out.append("- Ausdrücklich verboten: " + " · ".join(ledger["verbotene_aktionen"]))
    return out


def work_reason(ledger: dict, root: Path, rest_text: str, msgs: list[str]) -> str:
    cmd = ns.cli_cmd(ledger)
    parts = inbox_block(msgs) + head(ledger, root, rest_text,
                                     "CARPE NOCTEM — Anhalten verweigert, die Nacht läuft.")
    parts += ["Nimm das oberste STARTBARE Paket (Vorgänger erledigt; unter Gleichrangigen Risiko "
              "zuerst) und bring es bis zur Abnahme. Delegierst du an Subagenten: jedes vergebene "
              "Paket mit `%s item start <ID> --agent <name>` anmelden, Zwischenstände mit "
              "`progress \"…\" --id <ID>` — sonst kennt nach einer Kompaktierung niemand die "
              "Parallelarbeit." % cmd,
              "Stand aus dem Ledger lesen (`%s status`), nicht aus dem Gedächtnis." % cmd, "",
              "OFFENE PAKETE:"]
    offen = ns.open_items(ledger)
    for item in offen[:8]:
        fehlt = ns.missing_deps(ledger, item)
        marke = ("  <- läuft%s" % (" (%s)" % item["agent"] if item.get("agent") else "")
                 if item.get("status") == "doing" else
                 "  (wartet auf %s)" % ", ".join(fehlt) if fehlt else "")
        parts.append("  [%s] %s%s" % (item["id"], item.get("titel", ""), marke))
        if item.get("fertig_wenn"):
            parts.append("        fertig wenn: %s" % item["fertig_wenn"])
        for g in ns.grenzen_for(ledger, item["id"]):
            parts.append("        Grenze %s (%s, %s): %s%s" % (
                g["id"], g.get("art"), g.get("status"), g.get("was"),
                (" — Ersatz: %s" % g["ersatz"]) if g.get("ersatz") else ""))
        for line in ns.progress_lines(item):
            parts.append("        · %s" % line)
    if len(offen) > 8:
        parts.append("  … und %d weitere" % (len(offen) - 8))
    if ns.waiting_items(ledger):
        parts += ["", "WARTEN AUF DEN MENSCHEN: %s — nicht anfassen, außer eine Nachricht oder "
                  "ein grüner Trockenlauf gibt sie frei." % ", ".join(
                      "%s→%s" % (i["id"], i.get("wartet_auf", "?")) for i in ns.waiting_items(ledger))]
    streak = ledger.get("no_progress_streak", 0)
    if streak >= STUCK_WARN:
        parts += ["", "⚠ LEERLAUF seit %d Runden — weder Git noch Ledger bewegen sich. Anderes Paket, "
                  "anderer Ansatz, oder das Paket an seine Grenze hängen (`item wait`). Noch %d Runden, "
                  "dann wird die Nacht beendet." % (streak, max(0, STUCK_ABORT - streak))]
    parts += ["", *rules(cmd, ledger), "",
              "RUNDENABLAUF: Stand lesen → ein Paket → bauen → selbst widerlegen → frischer Lauf → "
              "committen → `item done`. Recherche an Subagenten, Gelerntes in Dateien.",
              "", "Arbeite jetzt am obersten offenen Paket weiter."]
    return "\n".join(parts)


def hardening_reason(ledger: dict, root: Path, rest_text: str, msgs: list[str]) -> str:
    cmd = ns.cli_cmd(ledger)
    parts = inbox_block(msgs) + head(
        ledger, root, rest_text,
        "CARPE NOCTEM — keine offenen Pakete, die Nacht läuft noch: Härtungsrunde %d von %d." % (
            ledger.get("hardening_rounds", 0) + 1, ledger.get("hardening_rounds_max", 0)))
    parts += [
        "Eigene Fehler suchen statt neuer Features:",
        "  1. `%s verify` — alle erledigten Pakete gegen Prüfbefehl und Richter-Schutz nachfahren." % cmd,
        "  2. Wartende Pakete: lässt sich mehr bis zur Grenze vorbereiten (Entwurf, Befehl, Branch)?",
        "  3. Randfälle, Fehlerpfade, fehlende Tests, Doku-Drift im berührten Bereich.",
    ]
    for entry in ledger.get("hardening_backlog") or []:
        parts.append("     - Backlog: %s" % entry)
    parts += ["", "Befund → `item add` und abarbeiten. Die Runde ist erst gezählt, wenn du sie "
              "protokollierst: `%s haertung \"<was geprüft>\" [--befund \"<was gefunden>\"]`, dann "
              "erneut anhalten." % cmd]
    haengen = ns.dep_stuck_items(ledger)
    if haengen:
        parts.append("Diese Pakete hängen an Vorgängern, die nicht vorankommen: %s — vorbereiten, "
                     "was ohne den Vorgänger geht; sonst `item wait <ID> --art extern --notiz \"wartet "
                     "auf <Vorgänger>\"` oder `item block`." % ", ".join(
                         "%s→%s" % (i["id"], ",".join(ns.missing_deps(ledger, i))) for i in haengen))
    streak = ledger.get("no_progress_streak", 0)
    if streak >= STUCK_WARN:
        parts.append("⚠ LEERLAUF seit %d Runden — ohne protokollierte Härtung, Commit oder Ledger-"
                     "Änderung endet die Nacht in %d Runden." % (streak, max(0, STUCK_ABORT - streak)))
    parts += ["", *rules(cmd, ledger)]
    return "\n".join(parts)


def wache_reason(ledger: dict, root: Path, rest_text: str, msgs: list[str]) -> str:
    cmd = ns.cli_cmd(ledger)
    parts = inbox_block(msgs) + head(
        ledger, root, rest_text, "CARPE NOCTEM — WACHE: nur noch Pakete, die auf einen Menschen warten.")
    for item in ns.waiting_items(ledger):
        g = ns.find_grenze(ledger, item.get("wartet_auf", "")) or {}
        parts.append("  [%s] wartet auf %s (%s): %s%s" % (
            item["id"], g.get("id", "?"), g.get("art", "?"), item.get("notiz", ""),
            "  · Trockenlauf: %s" % g["probe"] if g.get("probe") else ""))
    for item in ns.dep_stuck_items(ledger):
        parts.append("  [%s] hängt an Vorgänger %s" % (item["id"], ", ".join(ns.missing_deps(ledger, item))))
    parts += [
        "",
        "Starte jetzt `%s wache` (wartet bis zu 9 min, holt Nachrichten vom Handy und fährt die "
        "Trockenläufe nach; kehrt sofort zurück, wenn sich etwas bewegt)." % cmd,
        "- NACHRICHT → umsetzen; „G3 erledigt\" heißt: Trockenlauf fahren, Paket wieder aufnehmen.",
        "- FREI → das Paket ist wieder offen, weiterarbeiten.",
        "- ohne Ereignis → einfach erneut anhalten; die nächste Wache folgt bis zur Deadline.",
        "Keine neue Arbeit erfinden, um die Zeit zu füllen.",
    ]
    return "\n".join(parts)


def wrapup_reason(ledger: dict, root: Path, grund: str) -> str:
    cmd = ns.cli_cmd(ledger)
    return "\n".join([
        "CARPE NOCTEM — SCHICHTENDE (%s). Anhalten erst nach dem Bericht." % grund,
        "",
        "1. `%s report` schreibt das Gerüst nach %s — Kopf, Jetzt-du, Ergebnis und Grenzen "
        "kommen aus dem Ledger." % (cmd, ns.report_path(root).as_posix()),
        "2. Fülle NUR die Kurzfassung aus: drei Sätze — was erreicht ist, was nicht und warum, "
        "Zustand des Systems jetzt. Keine Wiederholung der Tabellen.",
        "3. Alles, was nur der Mensch darf, muss als `todo` mit erstem Schritt im Ledger stehen.",
        "4. Arbeit committen (pushen nur, wenn mission.md es ausdrücklich erlaubt — sonst To-Do), dann `%s finish`." % cmd,
    ])


def end_night(root: Path, ledger: dict, grund: str) -> NoReturn:
    """Abschlussphase: Bericht einfordern, nach REPORT_BLOCK_MAX Versuchen selbst schreiben."""
    ledger["ende_grund"] = ledger.get("ende_grund") or grund
    report = ns.report_path(root)
    report_ok = report.exists() and report.stat().st_size >= 200
    if report_ok and ledger.get("status") == "finished":
        ns.save(root, ledger)
        allow("Carpe Noctem beendet (%s). Bericht: %s" % (grund, report.as_posix()))

    ledger["report_blocks"] = ledger.get("report_blocks", 0) + 1
    if ledger["report_blocks"] > REPORT_BLOCK_MAX:
        cn.close_night(root, ledger, ledger["ende_grund"])
        if report_ok:
            cn_report.refresh(report, ledger, root)
        else:
            report.parent.mkdir(parents=True, exist_ok=True)
            with report.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(cn_report.render(ledger, root=root, auto=True))
        ns.journal(root, "Nacht zwangsbeendet (%s); Bericht %s." % (
            grund, "ergänzt" if report_ok else "maschinell erzeugt"))
        allow("Carpe Noctem zwangsbeendet (%s). Bericht: %s" % (grund, report.as_posix()))
    ns.save(root, ledger)
    block(wrapup_reason(ledger, root, grund))


def main(root_box: list) -> None:
    data = ns.read_hook_input()
    root = ns.find_root(data)
    root_box.append(root)
    session_id = data.get("session_id")

    ledger = ns.active_for_session(root, session_id)
    if ledger is None:
        allow()
    if ns.round_mode():
        ns.journal(root, "Runde beendet (Headless-Modus).")
        allow()

    ns.bind(root, ledger, session_id)

    mode = data.get("permission_mode") or ""
    if mode and mode != ledger.get("permission_mode"):
        ledger["permission_mode"] = mode
        ns.journal(root, "Permission-Modus der Nacht: %s%s" % (
            mode, " — Klassifikator-Ablehnungen werden per Transkript-Scan erfasst" if mode == "auto" else ""))

    msgs = cn_notify.new_messages(root, ledger)
    for text in msgs:
        ns.journal(root, "Nachricht vom Menschen: %s" % text)

    denials = record_denials(root, ledger, data.get("transcript_path"))

    msgs = denial_notes(denials) + msgs

    fp = ns.fingerprint(root, ledger)
    if fp == ledger.get("last_fingerprint") and not msgs:
        ledger["no_progress_streak"] = ledger.get("no_progress_streak", 0) + 1
    else:
        ledger["no_progress_streak"] = 0
    ledger["last_fingerprint"] = fp
    ledger["continuations"] = ledger.get("continuations", 0) + 1

    rest = ns.remaining(ledger.get("deadline"))
    rest_text = ns.human_delta(rest)
    time_left = rest is None or rest.total_seconds() > 0

    if not time_left:
        end_night(root, ledger, "Deadline erreicht")
    if ledger["continuations"] >= ledger.get("max_continuations", 200):
        end_night(root, ledger, "Fortsetzungs-Obergrenze erreicht")
    if ledger["no_progress_streak"] >= STUCK_ABORT:
        cn_notify.push("Carpe Noctem: Leerlauf", "%s dreht sich seit %d Runden im Kreis — Nacht wird "
                       "beendet." % (ledger.get("titel"), STUCK_ABORT), prio="high",
                       root=root, ledger=ledger)
        end_night(root, ledger, "Leerlauf — kein messbarer Fortschritt")

    # Gearbeitet wird nur an startbaren Paketen. Hängt ein Nachfolger an einem Vorgänger, der
    # selbst auf einen Menschen wartet, geht die Nacht in Härtung/Wache statt im Leerlauf zu enden.
    if ns.ready_items(ledger):
        ns.save(root, ledger)
        block(work_reason(ledger, root, rest_text, msgs))

    # Gezählt wird, was mit `cn.py haertung` protokolliert ist — auch ungefragte Härtung des
    # Agenten zählt so mit. Damit ein Agent, der das Protokoll vergisst, nicht vor der Wache
    # hängen bleibt, ist die Zahl der Mahnungen ebenfalls gedeckelt.
    max_h = ledger.get("hardening_rounds_max", 3)
    if ledger.get("hardening_rounds", 0) < max_h and ledger.get("haertung_mahnungen", 0) < max_h:
        ledger["haertung_mahnungen"] = ledger.get("haertung_mahnungen", 0) + 1
        ns.save(root, ledger)
        block(hardening_reason(ledger, root, rest_text, msgs))

    waiting = ns.waiting_items(ledger)
    # Wache nur, wenn sich nachts etwas bewegen KANN: ein Kanal zum Menschen oder ein
    # Trockenlauf, der von selbst grün werden kann. Sonst wäre es Warten auf niemanden.
    reachable = cn_notify.reachable(root, ledger) or any(
        (ns.find_grenze(ledger, i.get("wartet_auf", "")) or {}).get("probe") for i in waiting)
    if waiting and rest is not None and reachable:
        ns.save(root, ledger)
        block(wache_reason(ledger, root, rest_text, msgs))

    if not waiting and ns.dep_stuck_items(ledger):
        end_night(root, ledger, "Restpakete hängen an blockierten Vorgängern (%s)" % ", ".join(
            i["id"] for i in ns.dep_stuck_items(ledger)))
    if not waiting:
        end_night(root, ledger, "alle Pakete abgeschlossen")
    end_night(root, ledger, "nur noch wartende Pakete — %s" % (
        "keine Deadline für eine Wache" if rest is None else
        "kein Kanal erreicht den Menschen (ntfy oder `kanal_md:` außerhalb des Repos)"))


if __name__ == "__main__":
    box: list = []
    try:
        main(box)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 — ein Hook-Fehler darf keine Session festhalten
        ns.hook_error(box[0] if box else None, "stop-guard")
        sys.exit(0)
