"""Carpe-Noctem-CLI — das Ledger wird ausschließlich hierüber angefasst.

Warum eine CLI statt Hand-Edits am JSON: nachts läuft niemand mit, der ein kaputtes
Ledger bemerkt. Die CLI schreibt atomar (mit Sicherung), validiert Pflichtfelder und
ist das einzige Werkzeug, das der Agent für die Buchhaltung braucht.

Ablauf:

    Vorbereitung (Mensch wach)          Nacht (Hooks aktiv)
    ─────────────────────────           ───────────────────
    init        mission.md einlesen     status · item … · progress
    premortem   „Warum ist sie          item wait   Grenze getroffen → Wartebank
                gescheitert?"           wache       auf Mensch/Grenze warten
    grenze …    inventarisieren,        inbox       Nachrichten des Menschen
                probieren, klären       verify · decision · todo · frage · note
    risiko      Restrisiko je Paket     report · finish · abort · resume
    start       Gate → die Nacht beginnt
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cn_judge
import cn_notify
import cn_report
import cn_state as ns

PREMORTEM_MIN = 3
WACHE_MAX_MIN = 9      # das Bash-Werkzeug bricht nach 10 Minuten ab
WACHE_TAKT_S = 60


def _fail(msg: str) -> int:
    print("FEHLER: %s" % msg)
    return 1


def _require(root: Path, *states: str):
    ledger = ns.load(root)
    if ledger is None:
        print("FEHLER: keine Schicht in %s — erst `mission.md` schreiben und `cn.py init`."
              % ns.cn_dir(root).as_posix())
        return None
    if states and ledger.get("status") not in states:
        print("FEHLER: Schicht steht auf `%s` — dieser Befehl gilt nur in: %s."
              % (ledger.get("status"), ", ".join(states)))
        return None
    return ledger


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                             text=True, timeout=20, encoding="utf-8")
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ── Vorbereitung ─────────────────────────────────────────────────────────────

def cmd_init(root: Path, args) -> int:
    mission = ns.mission_path(root)
    if not mission.exists():
        return _fail("%s fehlt. Erst den Auftrag schreiben." % mission.as_posix())
    existing = ns.load(root)
    if existing and existing.get("status") == "active" and not args.force:
        return _fail("Es läuft bereits eine Nacht (%s). `--force` überschreibt sie."
                     % existing.get("titel"))

    parsed = ns.parse_mission(mission.read_text(encoding="utf-8"))
    front = parsed["front"]
    if not parsed["items"]:
        return _fail("mission.md enthält keine Arbeitspakete im Format "
                     "`- [ ] A1 — Titel :: fertig wenn: <messbares Kriterium>`.")
    ohne_dod = [i["id"] for i in parsed["items"] if not i["fertig_wenn"]]
    if ohne_dod:
        return _fail("Diese Pakete haben kein messbares Fertig-Kriterium: %s." % ", ".join(ohne_dod))
    unklar = ["%s: %s" % (i["id"], " ".join(i["nach_unklar"])) for i in parsed["items"] if i.get("nach_unklar")]
    if unklar:
        return _fail("`nach:` enthält Teile, die keine Paket-ID sind (%s) — schreib nur IDs, z. B. "
                     "`nach: A1, A4`. Eine verworfene Abhängigkeit wäre still falsch." % "; ".join(unklar))
    ids = {i["id"].lower() for i in parsed["items"]}
    lose = [g["id"] for g in parsed["grenzen"] if g["paket"].lower() not in ids]
    if lose:
        return _fail("Grenzen verweisen auf unbekannte Pakete: %s." % ", ".join(lose))
    unbekannt = [g["id"] for g in parsed["grenzen"] if g["art"] not in ns.GRENZ_ARTEN]
    if unbekannt:
        return _fail("Unbekannte Grenzart bei %s — erlaubt: %s."
                     % (", ".join(unbekannt), ", ".join(ns.GRENZ_ARTEN)))

    ledger = ns.new_ledger(front.get("titel") or front.get("title") or "Carpe Noctem")
    ledger["quelle"] = front.get("quelle") or front.get("source") or ""
    ledger["items"] = parsed["items"]
    ledger["grenzen"] = parsed["grenzen"]
    ledger["premortem"] = [{"id": "M%d" % n, "szenario": s, "grenze": ""}
                           for n, s in enumerate(parsed["premortem"], 1)]
    ledger["verbotene_aktionen"] = parsed["verbotene_aktionen"]
    ledger["hardening_backlog"] = parsed["hardening_backlog"]
    ledger["deadline_roh"] = front.get("deadline") or ""
    ledger["datenschutz"] = (front.get("datenschutz") or "").lower()
    ledger["richter"] = (front.get("richter") or "").lower()
    ledger["richter_default"] = front.get("richter_default") or ""
    ledger["kanaele_roh"] = front.get("kanal") or front.get("kanaele") or ""
    ledger["kanal_md"] = front.get("kanal_md") or ""
    falsch = cn_notify.unknown_kanaele(ledger["kanaele_roh"])
    if falsch:
        return _fail("Unbekannte Kanäle in `kanal:`: %s — erlaubt: %s."
                     % (", ".join(falsch), ", ".join(cn_notify.KANAELE)))
    ledger["geschuetzt"] = ns.split_globs(front.get("geschuetzt", ""))
    try:
        ns.topo_order(ledger)
    except ValueError as exc:
        return _fail("Abhängigkeiten (`nach:`) in mission.md: %s." % exc)
    for key in ("max_continuations", "hardening_rounds_max"):
        if front.get(key, "").isdigit():
            ledger[key] = int(front[key])
    ledger["cn_cmd"] = str(Path(__file__).resolve().parent.parent)
    ns.save(root, ledger)
    ns.journal(root, "Vorbereitung begonnen: %s (%d Pakete, %d Grenzen aus mission.md)"
               % (ledger["titel"], len(ledger["items"]), len(ledger["grenzen"])))
    print("Vorbereitung: %s" % ledger["titel"])
    print("  Pakete: %d · Grenzen: %d · Pre-mortem: %d" % (
        len(ledger["items"]), len(ledger["grenzen"]), len(ledger["premortem"])))
    print("\nNächste Schritte: Pre-mortem (`premortem`), Grenzen inventarisieren und berühren "
          "(`grenze add|probe|klaer|wartebank`), Restrisiko ansehen (`risiko`), dann `start`.")
    return 0


def cmd_premortem(root: Path, args) -> int:
    ledger = _require(root, "vorbereitung")
    if ledger is None:
        return 1
    if args.grenze and not ns.find_grenze(ledger, args.grenze):
        return _fail("Grenze %s unbekannt." % args.grenze)
    entry = {"id": ns.next_id(ledger["premortem"], "M"), "szenario": args.szenario,
             "grenze": (args.grenze or "").upper()}
    ledger["premortem"].append(entry)
    ns.save(root, ledger)
    print("%s aufgenommen. Führt es auf einen Menschen zurück, gehört eine Grenze dazu "
          "(`grenze add … `, dann `premortem` mit `--grenze`)." % entry["id"])
    return 0


def cmd_grenze(root: Path, args) -> int:
    ledger = _require(root, "vorbereitung", "active")
    if ledger is None:
        return 1

    if args.action == "add":
        if not args.ziel or not ns.find_item(ledger, args.ziel):
            return _fail("`grenze add <PAKET>` — Paket %s unbekannt." % args.ziel)
        if args.art not in ns.GRENZ_ARTEN:
            return _fail("--art muss eins sein von: %s." % ", ".join(ns.GRENZ_ARTEN))
        if not args.was:
            return _fail("--was fehlt: welcher Mensch, welche Handlung, welches Recht?")
        g = {"id": ns.next_id(ledger["grenzen"], "G"), "paket": ns.find_item(ledger, args.ziel)["id"],
             "art": args.art, "was": args.was, "probe": args.probe or "",
             "status": "offen" if ledger["status"] == "vorbereitung" else "getroffen",
             "klaerung": "", "ersatz": ""}
        ledger["grenzen"].append(g)
        ns.save(root, ledger)
        print("%s [%s] %s: %s — Status %s" % (g["id"], g["paket"], g["art"], g["was"], g["status"]))
        return 0

    targets = ledger["grenzen"]
    if args.ziel:
        g = ns.find_grenze(ledger, args.ziel)
        if g is None:
            return _fail("Grenze %s unbekannt." % args.ziel)
        targets = [g]

    if args.action == "probe":
        ran = 0
        for g in targets:
            if not g.get("probe"):
                if args.ziel:
                    return _fail("%s hat keinen Trockenlauf-Befehl (`--probe` bei `grenze add` "
                                 "oder `probe:` in mission.md)." % g["id"])
                continue
            code, tail = ns.run_cmd(root, g["probe"], timeout=180)
            g["probe_lauf"] = {"zeit": ns.iso(ns.now()), "exit": code, "ausgabe": tail}
            ran += 1
            print("  [%s] %-4s %s → Exit %d: %s" % ("x" if code == 0 else "!", g["id"],
                                                   g["probe"], code, tail))
        ns.save(root, ledger)
        print("%d Trockenläufe." % ran)
        return 0

    if not args.ziel:
        return _fail("`grenze %s <GID>` braucht eine Grenze." % args.action)
    g = targets[0]
    if args.action == "klaer":
        if not args.wie:
            return _fail("--wie fehlt: wodurch ist die Grenze geklärt (Allow-Regel, Login bis "
                         "HH:MM, Entscheidung des Menschen …)?")
        # Eine Urteils-Grenze, die der Agent selbst aus einer Repo-Regel ableitet, darf im
        # Bericht nicht wie eine Vorgabe des Menschen aussehen. Wer geklärt hat, wird genannt.
        if g.get("art") in ns.HUMAN_ONLY and not args.durch:
            return _fail("%s ist eine %s-Grenze — wer hat sie geklärt? `--durch mensch` (der Mensch hat "
                         "entschieden) oder `--durch agent` (abgeleitet; steht morgen unter „Bitte prüfen“)."
                         % (g["id"], g["art"]))
        g["status"] = "geklaert"
        g["klaerung"] = args.wie
        g["durch"] = args.durch or "agent"
        ns.journal(root, "Grenze %s geklärt (%s): %s" % (g["id"], g["durch"], args.wie))
    elif args.action == "wartebank":
        if not args.ersatz:
            return _fail("--ersatz fehlt: woran arbeitet die Nacht, solange %s wartet?" % g["id"])
        g["status"] = "wartebank"
        g["ersatz"] = args.ersatz
        ns.journal(root, "Grenze %s auf die Wartebank (Ersatz: %s)" % (g["id"], args.ersatz))
    ns.save(root, ledger)
    print("%s → %s" % (g["id"], g["status"]))
    return 0


def _gate(root: Path, ledger: dict, headless: bool) -> tuple[list[str], list[str]]:
    """(Fehler, Warnungen) vor dem Start der Nacht."""
    errors, warnings = [], []
    if len(ledger.get("premortem", [])) < PREMORTEM_MIN:
        errors.append("Pre-mortem hat %d Szenarien, mindestens %d: „Es ist 7 Uhr, die Nacht ist "
                      "gescheitert — warum?\"" % (len(ledger.get("premortem", [])), PREMORTEM_MIN))
    offen = [g["id"] for g in ledger["grenzen"] if g.get("status") == "offen"]
    if offen:
        errors.append("Grenzen noch offen: %s — klären oder bewusst auf die Wartebank."
                      % ", ".join(offen))
    ohne_ersatz = [g["id"] for g in ledger["grenzen"]
                   if g.get("status") == "wartebank" and not g.get("ersatz")]
    if ohne_ersatz:
        errors.append("Wartebank ohne Ersatzarbeit: %s." % ", ".join(ohne_ersatz))
    unprobiert = [g["id"] for g in ledger["grenzen"]
                  if g.get("status") == "geklaert" and g.get("probe") and not ns.probe_fresh(g)]
    if unprobiert:
        errors.append("Geklärte Grenzen ohne frischen grünen Trockenlauf (≤ %dh): %s — "
                      "`grenze probe`." % (int(ns.PROBE_MAX_AGE.total_seconds() // 3600),
                                           ", ".join(unprobiert)))
    if ledger.get("richter") == "jev":
        why = cn_judge.allowed(ledger)
        if why:
            errors.append("Richter Jev nicht zulässig: %s." % why)
    if not headless and not ns.block_cap(root):
        errors.append("CLAUDE_CODE_STOP_HOOK_BLOCK_CAP ist nirgends gesetzt (Umgebung, Repo- oder "
                      "User-Settings) — Claude Code beendet die Nacht sonst nach 8 Blocks. Der Mensch "
                      "setzt ihn (Settings-Dateien schreibt der Agent nicht), oder `start --headless`.")
    try:
        ns.topo_order(ledger)
    except ValueError as exc:
        errors.append("Abhängigkeiten: %s." % exc)
    agent_urteile = [g["id"] for g in ledger["grenzen"]
                     if g.get("art") in ns.HUMAN_ONLY and g.get("status") == "geklaert"
                     and g.get("durch") != "mensch"]
    if agent_urteile:
        warnings.append("Vom Agenten geklärte Urteils-/Freigabe-Grenzen: %s — besser jetzt den "
                        "Menschen fragen; sonst stehen sie morgen unter „Bitte prüfen“."
                        % ", ".join(agent_urteile))
    if not ledger.get("richter_default"):
        warnings.append("Kein `richter_default:` in mission.md — nachts angelegte Pakete bringen "
                        "ihren Prüfbefehl selbst mit (der Täter wählt den Richter).")
    try:
        ns.bash_exe()
    except RuntimeError as exc:
        errors.append("Prüfbefehle laufen nicht: %s." % exc)
    chans = cn_notify.channels(ledger)
    if "ntfy" in chans and not cn_notify.ntfy_url():
        errors.append("Kanal `ntfy` gewählt, aber CARPE_NOCTEM_NTFY ist nicht gesetzt.")
    falsch = cn_notify.unknown_kanaele(os.environ.get("CARPE_NOCTEM_KANAL", ""))
    if falsch:
        errors.append("CARPE_NOCTEM_KANAL enthält unbekannte Kanäle: %s." % ", ".join(falsch))
    if not cn_notify.reachable(root, ledger):
        warnings.append("Kein Kanal erreicht dich nachts (%s) — Meldungen landen nur in der Datei "
                        "im Repo, Wartebank-Pakete warten bis morgen. `kanal_md:` auf einen Ordner, "
                        "den du vom Handy liest, oder `kanal: ntfy`." % "; ".join(
                            cn_notify.describe(root, ledger)))
    ohne_pruef = [i["id"] for i in ledger["items"] if not i.get("pruefbefehl")]
    if ohne_pruef:
        warnings.append("Ohne Prüfbefehl (morgen Handabnahme): %s." % ", ".join(ohne_pruef))
    if not ledger.get("geschuetzt"):
        warnings.append("Keine Richter-Dateien geschützt (`geschuetzt:` in mission.md) — der "
                        "Agent kann Tests ändern, gegen die er geprüft wird.")
    if not ledger.get("deadline_roh"):
        warnings.append("Keine Deadline — die Nacht endet, wenn alles zu ist.")
    return errors, warnings


def cmd_risiko(root: Path, args) -> int:
    ledger = _require(root)
    if ledger is None:
        return 1
    print("Restrisiko = Wahrscheinlichkeit, dass ein Paket nachts einen Menschen braucht.\n")
    rows = sorted(ledger["items"], key=lambda i: -ns.restrisiko(ledger, i))
    for item in rows:
        print("  %-4s Risiko %2d  %s" % (item["id"], ns.restrisiko(ledger, item), item.get("titel", "")))
        for g in ns.grenzen_for(ledger, item["id"]):
            probe = g.get("probe_lauf") or {}
            pmark = ("probe ✓" if ns.probe_fresh(g) else
                     "probe ✗ Exit %s" % probe.get("exit") if probe else
                     "probe —" if g.get("probe") else "")
            print("        %-4s %-12s %-10s %s %s" % (g["id"], g["art"], g["status"], g["was"],
                                                       ("[%s]" % pmark) if pmark else ""))
    errors, warnings = _gate(root, ledger, headless=args.headless)
    print("\nPre-mortem: %d Szenarien" % len(ledger.get("premortem", [])))
    for m in ledger.get("premortem", []):
        print("  %-4s %s%s" % (m["id"], m["szenario"], ("  → %s" % m["grenze"]) if m.get("grenze") else ""))
    print("\nGate: %s" % ("frei" if not errors else "%d Hindernis(se)" % len(errors)))
    for e in errors:
        print("  ✗ %s" % e)
    for w in warnings:
        print("  ⚠ %s" % w)
    return 0


def cmd_start(root: Path, args) -> int:
    ledger = _require(root, "vorbereitung")
    if ledger is None:
        return 1
    errors, warnings = _gate(root, ledger, headless=args.headless)
    for w in warnings:
        print("⚠ %s" % w)
    if errors and not args.force:
        for e in errors:
            print("✗ %s" % e)
        return _fail("Die Nacht startet erst, wenn die Vorbereitung trägt (`--force` übergeht das "
                     "Gate und landet im Bericht).")
    if errors:
        ledger["gate_uebergangen"] = errors

    # Abhängigkeiten zuerst, unter Gleichrangigen Risiko zuerst: was am ehesten einen Menschen
    # braucht, läuft früh — dann trifft die Grenze um 23:30 statt um 4 Uhr.
    try:
        reihenfolge = ns.topo_order(ledger)
    except ValueError as exc:
        return _fail("Abhängigkeiten: %s." % exc)
    for rang, item in enumerate(reihenfolge, 1):
        item["rang"] = rang
    start = ns.now()
    ledger["status"] = "active"
    ledger["nacht_beginn"] = ns.iso(start)
    ledger["nacht_commit"] = _git(root, "rev-parse", "HEAD")
    ledger["deadline"] = ns.parse_deadline(args.deadline or ledger.get("deadline_roh"), start)
    ledger["geschuetzt_hashes"] = ns.protected_hashes(root, ledger.get("geschuetzt") or [])
    ledger["bound_session"] = None
    ledger["cn_cmd"] = str(Path(__file__).resolve().parent.parent)
    ns.save(root, ledger)

    prompt = ns.cn_dir(root) / "prompt.md"
    with prompt.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(cn_report.round_prompt(root, "{CN}"))

    ns.journal(root, "Nacht beginnt: %s (%d Pakete, Ende %s, %d Richter-Dateien geschützt)"
               % (ledger["titel"], len(ledger["items"]), ledger["deadline"] or "offen",
                  len(ledger["geschuetzt_hashes"])))
    cn_notify.push("Carpe Noctem: %s" % ledger["titel"],
                   "Nacht läuft bis %s · %d Pakete · Antworten: Zeile in inbox.md oder an das "
                   "ntfy-Topic mit -in" % ((ledger["deadline"] or "offen")[11:16], len(ledger["items"])),
                   tags="crescent_moon", root=root, ledger=ledger)
    print("Carpe Noctem — die Nacht beginnt: %s" % ledger["titel"])
    print("  Reihenfolge (Risiko zuerst): %s" % " → ".join(
        i["id"] for i in ns.ordered(ledger["items"])))
    print("  Ende: %s" % (ledger["deadline"] or "wenn alles zu ist"))
    print("  Richter-Dateien geschützt: %d" % len(ledger["geschuetzt_hashes"]))
    print("\nDie Nacht bindet sich an die Session, deren Stop-Hook als nächstes feuert.")
    return 0


# ── Nacht ────────────────────────────────────────────────────────────────────

def cmd_status(root: Path, args) -> int:
    ledger = _require(root)
    if ledger is None:
        return 1
    if args.json:
        print(json.dumps(ledger, ensure_ascii=False, indent=2))
        return 0
    print("Carpe Noctem: %s  [%s]" % (ledger.get("titel"), ledger.get("status")))
    print("  Fortschritt:   %s" % ns.progress_line(ledger))
    print("  Restzeit:      %s" % ns.human_delta(ns.remaining(ledger.get("deadline"))))
    print("  Fortsetzungen: %d / %d · Leerlauf %d · Härtung %d/%d · Wachen %d" % (
        ledger.get("continuations", 0), ledger.get("max_continuations", 0),
        ledger.get("no_progress_streak", 0), ledger.get("hardening_rounds", 0),
        ledger.get("hardening_rounds_max", 0), ledger.get("wachen", 0)))
    print("  Entscheidungen %d · To-Dos %d · Fragen %d · Grenzen %d" % (
        len(ledger.get("entscheidungen", [])), len(ledger.get("todos", [])),
        len(ledger.get("offene_fragen", [])), len(ledger.get("grenzen", []))))
    print()
    mark = {"done": "x", "blocked": "!", "dropped": "~", "doing": ">", "waiting": "…"}
    for item in ns.ordered(ledger.get("items", [])):
        extra = []
        if item.get("agent") and item["status"] == "doing":
            extra.append("Agent %s" % item["agent"])
        fehlt = ns.missing_deps(ledger, item) if item["status"] in ns.OPEN_STATES else []
        if fehlt:
            extra.append("wartet auf %s" % ", ".join(fehlt))
        print("  [%s] %-4s %s%s" % (mark.get(item["status"], " "), item["id"], item.get("titel", ""),
                                    ("  (%s)" % "; ".join(extra)) if extra else ""))
        if item["status"] == "done":
            ab = item.get("abnahme") or {}
            print("          Abnahme: %s%s" % (ab.get("art", "?"),
                                               " · BITTE PRÜFEN" if item.get("bitte_pruefen") else ""))
        if item["status"] in ("blocked", "dropped", "waiting") and item.get("notiz"):
            print("          Grund: %s" % item["notiz"])
        for line in ns.progress_lines(item if item["status"] in ns.OPEN_STATES else None):
            print("          · %s" % line)
    return 0


def _accept(root: Path, ledger: dict, item: dict) -> tuple[bool, str]:
    """Abnahme eines Pakets. (ok, Meldung). Setzt item['abnahme'] und ggf. 'bitte_pruefen'."""
    drift = ns.protected_drift(root, ledger)
    if drift:
        ns.journal(root, "Paket %s: Richter-Dateien verändert (%s) — Abnahme verweigert"
                   % (item["id"], ", ".join(drift[:5])))
        return False, ("Richter-Dateien seit Nachtbeginn verändert: %s. Gegen veränderte Tests "
                       "gibt es keine Abnahme. Änderung zurücknehmen (`git checkout <nacht_commit> -- "
                       "<datei>`) oder — wenn der Test wirklich falsch ist — `todo` für den Menschen "
                       "und das Paket blockieren." % ", ".join(drift[:5]))
    check = item.get("pruefbefehl") or ""
    out = ""
    abnahme = {"art": "keine", "zeit": ns.iso(ns.now())}
    if check:
        print("Prüfbefehl läuft: %s" % check)
        code, out = ns.run_cmd(root, check)
        if code != 0:
            ns.journal(root, "Paket %s NICHT abgenommen — Prüfbefehl Exit %d: %s"
                       % (item["id"], code, out))
            return False, "Prüfbefehl endete mit Exit %d — das Paket bleibt offen.\n  %s" % (code, out)
        abnahme = {"art": "pruefbefehl", "exit": 0, "ausgabe": out, "zeit": ns.iso(ns.now())}

    if cn_judge.allowed(ledger) is None:
        try:
            urteil = cn_judge.judge(root, ledger, item, out)
        except cn_judge.JudgeError as exc:
            urteil = {"gate": "unsicher", "verdict": "fehler", "fehler": str(exc)}
            ns.journal(root, "Richter für %s nicht erreichbar: %s" % (item["id"], exc))
        abnahme["richter"] = urteil
        if urteil["gate"] == "abgelehnt":
            ns.journal(root, "Paket %s: Richter widerspricht (%.2f) — bleibt offen"
                       % (item["id"], urteil.get("confidence", 0)))
            return False, ("Richter (Jev) sieht das Kriterium als NICHT erfüllt (Konfidenz %.2f). "
                           "Der Beleg trägt nicht — Kriterium erneut lesen, nachbessern."
                           % urteil.get("confidence", 0))
        abnahme["art"] = "pruefbefehl+jev" if check else "jev"
        item["bitte_pruefen"] = urteil["gate"] != "ok"
    else:
        item["bitte_pruefen"] = not check
    if item.get("richter_vom_agent"):
        item["bitte_pruefen"] = True
    item["abnahme"] = abnahme
    return True, ""


def cmd_item(root: Path, args) -> int:
    ledger = _require(root, "active", "vorbereitung")
    if ledger is None:
        return 1

    if args.action == "add":
        item_id = args.id or ns.next_id(ledger["items"], "Z")
        if ns.find_item(ledger, item_id):
            return _fail("Paket %s gibt es schon." % item_id)
        if not args.fertig_wenn:
            return _fail("Neue Pakete brauchen `--fertig-wenn`.")
        nach = ns.split_ids(args.nach)
        if ns.unclear_tokens(args.nach):
            return _fail("`--nach` enthält Teile, die keine Paket-ID sind: %s."
                         % " ".join(ns.unclear_tokens(args.nach)))
        unknown = [d for d in nach if not ns.find_item(ledger, d)]
        if unknown:
            return _fail("Unbekannte Vorgänger: %s." % ", ".join(unknown))
        nachts = ledger["status"] == "active"
        default = ledger.get("richter_default") or ""
        pruef = args.pruefbefehl or (default if nachts else "")
        # Sonst nimmt der Agent sein eigenes Paket gegen eine selbst gewählte Prüfung ab (etwa
        # eine Job-Auswahl ohne den roten Job). Nachts gilt der Default-Richter; wer davon
        # abweicht, landet morgen unter „Bitte prüfen“.
        vom_agent = nachts and bool(args.pruefbefehl) and args.pruefbefehl != default
        ledger["items"].append({"id": item_id, "titel": args.titel, "fertig_wenn": args.fertig_wenn,
                                "pruefbefehl": pruef, "nach": nach, "status": "open",
                                "beleg": "", "notiz": "", "rang": 9_000, "nachts": nachts,
                                "richter_vom_agent": vom_agent})
        ns.journal(root, "Paket %s aufgenommen%s: %s" % (
            item_id, " (Prüfbefehl vom Agenten gewählt)" if vom_agent else "", args.titel))
        ns.save(root, ledger)
        print("Paket %s aufgenommen%s." % (
            item_id, " — Prüfbefehl weicht vom Default-Richter ab und steht morgen unter „Bitte prüfen“"
            if vom_agent else ""))
        return 0

    item = ns.find_item(ledger, args.id or "")
    if item is None:
        return _fail("Paket %s nicht gefunden." % args.id)

    if args.action == "start":
        fehlt = ns.missing_deps(ledger, item)
        if fehlt:
            return _fail("Paket %s braucht erst %s." % (item["id"], ", ".join(fehlt)))
        # Mehrere `doing` sind erlaubt: ein Orchestrator meldet jedes an einen Subagenten
        # vergebene Paket an — sonst zeigt das Ledger einen Bruchteil der echten Parallelarbeit.
        item["status"] = "doing"
        if args.agent:
            item["agent"] = args.agent
        ns.journal(root, "Paket %s begonnen%s." % (item["id"], " (%s)" % args.agent if args.agent else ""))
    elif args.action == "done":
        if not args.beleg:
            return _fail("`done` ohne `--beleg` ist eine Behauptung.")
        ok, msg = _accept(root, ledger, item)
        if not ok:
            ns.save(root, ledger)
            return _fail(msg)
        item["beleg"] = args.beleg
        item["status"] = "done"
        ns.journal(root, "Paket %s erledigt (%s%s) — %s" % (
            item["id"], item["abnahme"]["art"], ", bitte prüfen" if item.get("bitte_pruefen") else "",
            args.beleg))
    elif args.action == "block":
        if not args.notiz:
            return _fail("`block` ohne `--notiz` hilft morgens niemandem.")
        item["status"] = "blocked"
        item["notiz"] = args.notiz
        ns.journal(root, "Paket %s blockiert: %s" % (item["id"], args.notiz))
    elif args.action == "drop":
        if not args.notiz:
            return _fail("`drop` ohne `--notiz` ist stilles Weglassen.")
        item["status"] = "dropped"
        item["notiz"] = args.notiz
        ns.journal(root, "Paket %s verworfen: %s" % (item["id"], args.notiz))
    elif args.action == "wait":
        # Die Grenze ist nachts getroffen: das Paket wartet auf einen Menschen, die Nacht
        # arbeitet woanders weiter und meldet sich JETZT — nicht erst im Morgenbericht.
        if not args.notiz:
            return _fail("`wait` braucht `--notiz`: was genau muss der Mensch tun?")
        g = ns.find_grenze(ledger, args.grenze) if args.grenze else None
        if args.grenze and g is None:
            return _fail("Grenze %s unbekannt." % args.grenze)
        if g is None:
            if args.art not in ns.GRENZ_ARTEN:
                return _fail("Ohne `--grenze` braucht `wait` eine `--art` (%s)." % ", ".join(ns.GRENZ_ARTEN))
            g = {"id": ns.next_id(ledger["grenzen"], "G"), "paket": item["id"], "art": args.art,
                 "was": args.notiz, "probe": args.probe or "", "status": "getroffen",
                 "klaerung": "", "ersatz": "", "nachts": True}
            ledger["grenzen"].append(g)
        else:
            g["status"] = "getroffen"
            if args.probe:
                g["probe"] = args.probe
        item["status"] = "waiting"
        item["notiz"] = args.notiz
        item["wartet_auf"] = g["id"]
        ns.journal(root, "Paket %s wartet auf %s (%s): %s" % (item["id"], g["id"], g["art"], args.notiz))
        sent = cn_notify.push("Carpe Noctem braucht dich: %s" % item["id"],
                              "%s — %s\nAntwort (inbox.md oder ntfy-Topic mit -in), z. B. \"%s erledigt\""
                              % (g["art"], args.notiz, g["id"]), prio="high", tags="raising_hand",
                              root=root, ledger=ledger)
        print(cn_notify.receipt(sent))
    ns.save(root, ledger)
    print("Paket %s -> %s" % (item["id"], item["status"]))
    return 0


def cmd_progress(root: Path, args) -> int:
    ledger = _require(root, "active")
    if ledger is None:
        return 1
    if not args.id and len(ns.items_by_state(ledger, "doing")) > 1:
        return _fail("Mehrere Pakete laufen (%s) — `--id` angeben." % ", ".join(
            i["id"] for i in ns.items_by_state(ledger, "doing")))
    item = ns.find_item(ledger, args.id) if args.id else ns.current_item(ledger)
    if item is None:
        return _fail("kein Paket gefunden%s." % (" (%s)" % args.id if args.id else " — alle zu"))
    ns.add_progress(item, args.text)
    ns.save(root, ledger)
    print("Zwischenstand an %s: %s" % (item["id"], args.text))
    return 0


def cmd_verify(root: Path, args) -> int:
    ledger = _require(root, "active")
    if ledger is None:
        return 1
    targets = [i for i in ledger["items"] if i.get("status") == "done"]
    if args.id:
        targets = [i for i in targets if i["id"].lower() == args.id.lower()]
        if not targets:
            return _fail("Paket %s ist nicht auf `done`." % args.id)
    drift = ns.protected_drift(root, ledger)
    if drift:
        print("⚠ Richter-Dateien seit Nachtbeginn verändert: %s — alle Abnahmen stehen in Frage."
              % ", ".join(drift[:8]))
    gefallen = ohne = 0
    for item in targets:
        check = item.get("pruefbefehl") or ""
        if not check:
            ohne += 1
            print("  [?] %-4s kein Prüfbefehl — Beleg bleibt eine Behauptung" % item["id"])
            continue
        code, tail = ns.run_cmd(root, check)
        if code == 0 and not drift:
            print("  [x] %-4s hält: %s" % (item["id"], tail))
            continue
        gefallen += 1
        item["status"] = "open"
        item["notiz"] = "Nachprüfung %s: Exit %d%s — %s" % (
            ns.now().strftime("%H:%M"), code, ", Richter-Dateien verändert" if drift else "", tail)
        print("  [!] %-4s FÄLLT DURCH — wieder offen" % item["id"])
        ns.journal(root, "Nachprüfung: %s fällt durch (Exit %d) — wieder offen" % (item["id"], code))
    ns.save(root, ledger)
    print("\n%d geprüft, %d ohne Prüfbefehl, %d wieder geöffnet." % (len(targets) - ohne, ohne, gefallen))
    return 1 if gefallen else 0


def cmd_wache(root: Path, args) -> int:
    """Warten, ohne die Nacht zu verbrennen: Inbox und Trockenläufe der wartenden Pakete
    jede Minute prüfen, bei Bewegung sofort zurück. Eine Wache kostet einen Turn statt
    neun Minuten Leerlauf-Blocks."""
    ledger = _require(root, "active")
    if ledger is None:
        return 1
    minutes = max(1, min(args.minuten, WACHE_MAX_MIN))
    end = time.monotonic() + minutes * 60
    print("Wache für bis zu %d min — %s" % (minutes, ns.progress_line(ledger)))
    while True:
        ledger = ns.load(root) or ledger
        msgs = cn_notify.new_messages(root, ledger)
        freed = []
        for item in ns.waiting_items(ledger):
            g = ns.find_grenze(ledger, item.get("wartet_auf", ""))
            if g and g.get("probe"):
                code, tail = ns.run_cmd(root, g["probe"], timeout=120)
                g["probe_lauf"] = {"zeit": ns.iso(ns.now()), "exit": code, "ausgabe": tail}
                if code == 0:
                    g["status"] = "geklaert"
                    g["durch"] = "trockenlauf"  # grün geworden = jemand hat gehandelt, nicht der Agent
                    g["klaerung"] = "Trockenlauf nachts grün (%s)" % ns.now().strftime("%H:%M")
                    item["status"] = "open"
                    freed.append(item["id"])
        rest = ns.remaining(ledger.get("deadline"))
        done = msgs or freed or time.monotonic() >= end or (rest is not None and rest.total_seconds() <= 0)
        if done:
            ledger["wachen"] = ledger.get("wachen", 0) + 1
            ns.save(root, ledger)
            break
        ns.save(root, ledger)
        time.sleep(WACHE_TAKT_S)
    for text in msgs:
        print("NACHRICHT VOM MENSCHEN: %s" % text)
        ns.journal(root, "Nachricht vom Menschen (Wache): %s" % text)
    for item_id in freed:
        print("FREI: %s — Grenze ist jetzt passierbar, Paket wieder offen." % item_id)
        ns.journal(root, "Wache: %s wieder offen (Trockenlauf grün)" % item_id)
    if not msgs and not freed:
        print("Wache ohne Ereignis (%s)." % ns.progress_line(ledger))
    return 0


def cmd_inbox(root: Path, args) -> int:
    ledger = _require(root)
    if ledger is None:
        return 1
    msgs = cn_notify.new_messages(root, ledger)
    ns.save(root, ledger)
    for text in msgs:
        print("NACHRICHT VOM MENSCHEN: %s" % text)
    if not msgs:
        print("Keine neuen Nachrichten.")
    return 0


def cmd_decision(root: Path, args) -> int:
    ledger = _require(root, "active", "vorbereitung")
    if ledger is None:
        return 1
    if args.ersetzt:
        old = next((e for e in ledger["entscheidungen"] if e.get("id", "").lower() == args.ersetzt.lower()), None)
        if old is None:
            return _fail("Entscheidung %s unbekannt." % args.ersetzt)
    # Die Quelle wird genannt, nicht aus der Phase geraten: in der Vorbereitung entscheidet
    # auch der Agent, und seine Entscheidung darf nicht als Vorgabe des Menschen erscheinen.
    if args.quelle == "mensch" and ledger["status"] != "vorbereitung":
        return _fail("Nachts entscheidet kein Mensch — eine Antwort aus der Inbox ist `--quelle inbox`.")
    phase = "Vorbereitung" if ledger["status"] == "vorbereitung" else "Nacht"
    entry = {"id": ns.next_id(ledger["entscheidungen"], "E"), "frage": args.frage, "wahl": args.wahl,
             "warum": args.warum, "reversibel": args.reversibel or "",
             "quelle": "%s (%s)" % ({"mensch": "Mensch", "inbox": "Mensch per Inbox"}.get(
                 args.quelle, "Agent"), phase),
             "vom_agent": args.quelle == "agent",
             "zeit": ns.iso(ns.now())}
    ledger["entscheidungen"].append(entry)
    if args.ersetzt:
        old["ersetzt_durch"] = entry["id"]
    ns.save(root, ledger)
    ns.journal(root, "Entscheidung %s: %s -> %s" % (entry["id"], args.frage, args.wahl))
    print("Entscheidung %s protokolliert." % entry["id"])
    return 0


def cmd_todo(root: Path, args) -> int:
    ledger = _require(root, "active", "vorbereitung")
    if ledger is None:
        return 1
    pakete = [p.strip() for p in (args.paket or "").split(",") if p.strip()]
    unknown = [p for p in pakete if not ns.find_item(ledger, p)]
    if unknown:
        return _fail("Unbekannte Pakete: %s." % ", ".join(unknown))
    entry = {"id": ns.next_id(ledger["todos"], "T"), "prio": args.prio.upper(), "titel": args.titel,
             "warum": args.warum, "erster_schritt": args.schritt, "aufwand": args.aufwand or "",
             "pakete": pakete, "zeit": ns.iso(ns.now())}
    ledger["todos"].append(entry)
    ns.save(root, ledger)
    ns.journal(root, "To-Do %s [%s]: %s" % (entry["id"], entry["prio"], args.titel))
    print("To-Do %s aufgenommen." % entry["id"])
    # Ein P1 (z. B. ein Sicherheitsbefund) soll den Menschen nicht erst morgens erreichen.
    if entry["prio"] == "P1" and ledger["status"] == "active":
        sent = cn_notify.push("Carpe Noctem P1: %s" % args.titel,
                              "%s\nErster Schritt: %s" % (args.warum, args.schritt),
                              prio="high", tags="rotating_light", root=root, ledger=ledger)
        print(cn_notify.receipt(sent))
    return 0


def cmd_haertung(root: Path, args) -> int:
    """Eine Härtungsrunde protokollieren — auch eine, die der Agent ungefragt fährt.

    Härtet der Agent aus eigenem Antrieb, soll der Stop-Hook nicht zusätzlich Runden
    erzwingen — gezählt wird jede protokollierte Runde, egal wer sie angestoßen hat."""
    ledger = _require(root, "active")
    if ledger is None:
        return 1
    ledger["haertung"].append({"zeit": ns.iso(ns.now()), "geprueft": args.geprueft,
                               "befund": args.befund or "", "quelle": "agent"})
    ledger["hardening_rounds"] = ledger.get("hardening_rounds", 0) + 1
    ns.save(root, ledger)
    ns.journal(root, "Härtung %d: %s%s" % (ledger["hardening_rounds"], args.geprueft,
                                           (" — Befund: %s" % args.befund) if args.befund else " — ohne Befund"))
    print("Härtungsrunde %d/%d protokolliert." % (ledger["hardening_rounds"], ledger["hardening_rounds_max"]))
    return 0


def cmd_frage(root: Path, args) -> int:
    ledger = _require(root, "active")
    if ledger is None:
        return 1
    ledger["offene_fragen"].append({"text": args.text, "zeit": ns.iso(ns.now())})
    ns.save(root, ledger)
    ns.journal(root, "Offene Frage an den Menschen: %s" % args.text)
    print("Frage vorgemerkt — sie landet im Bericht, nicht in einem Prompt.")
    return 0


def cmd_note(root: Path, args) -> int:
    if ns.load(root) is None:
        return _fail("keine Schicht in diesem Repo.")
    ns.journal(root, args.text)
    print("notiert.")
    return 0


def cmd_report(root: Path, args) -> int:
    ledger = _require(root)
    if ledger is None:
        return 1
    text = cn_report.render(ledger, root=root, auto=False)
    if args.stdout:
        print(text)
        return 0
    path = ns.report_path(root)
    if path.exists() and path.stat().st_size >= 200 and not args.force:
        return _fail("%s existiert schon und ist ausgefüllt — ergänzen statt überschreiben "
                     "(`--stdout` zeigt das frische Gerüst, `--force` ersetzt)." % path.as_posix())
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("Gerüst geschrieben: %s — jetzt die Kurzfassung (drei Sätze) ausfüllen." % path.as_posix())
    return 0


def close_night(root: Path, ledger: dict, grund: str) -> None:
    """Nacht abschließen: Reste zu To-Dos, Status, Laufzeit, Push. Von `finish` und vom
    Stop-Hook (Notabschluss) gemeinsam genutzt."""
    for item in ns.open_items(ledger):
        stand = ns.progress_lines(item, 1)
        ledger["todos"].append({
            "id": ns.next_id(ledger["todos"], "T"), "prio": "P2",
            "titel": "Nicht erreicht: %s" % item.get("titel", ""),
            "warum": "Paket %s bei Schichtende offen (%s). Ziel: %s" % (
                item["id"], grund, item.get("fertig_wenn", "")),
            "erster_schritt": ("Weiter ab: %s" % stand[0]) if stand else
                              "nächste Nacht oder von Hand — Stand: `cn.py status`",
            "aufwand": "", "pakete": [item["id"]], "zeit": ns.iso(ns.now())})
        item["status"] = "blocked"
        item["notiz"] = (item.get("notiz") or "nicht erreicht") + " [bei Schichtende offen]"
    for item in ns.waiting_items(ledger):
        g = ns.find_grenze(ledger, item.get("wartet_auf", "")) or {}
        ledger["todos"].append({
            "id": ns.next_id(ledger["todos"], "T"), "prio": "P1",
            "titel": "%s wartet auf dich: %s" % (item["id"], g.get("was") or item.get("notiz", "")),
            "warum": "Grenze %s (%s) — danach kann das Paket weiterlaufen." % (g.get("id", "?"), g.get("art", "?")),
            "erster_schritt": item.get("notiz") or g.get("was", ""),
            "aufwand": "", "pakete": [item["id"]], "zeit": ns.iso(ns.now())})
    ledger["status"] = "finished"
    ledger["beendet"] = ns.iso(ns.now())
    ledger["ende_grund"] = ledger.get("ende_grund") or grund
    ns.save(root, ledger)
    ns.journal(root, "Nacht beendet (%s). %s" % (ledger["ende_grund"], ns.progress_line(ledger)))
    cn_notify.push("Carpe Noctem fertig: %s" % ledger.get("titel"),
                   cn_report.headline(ledger), tags="sunrise", root=root, ledger=ledger)


def cmd_finish(root: Path, args) -> int:
    ledger = _require(root, "active", "interrupted")
    if ledger is None:
        return 1
    report = ns.report_path(root)
    if not report.exists() or report.stat().st_size < 200:
        return _fail("%s fehlt oder ist leer. Die Nacht endet erst mit einem Bericht." % report.as_posix())
    # Früher Abschluss ist erlaubt, aber nicht ungeprüft: vor der Deadline braucht es
    # mindestens eine Härtungsrunde oder eine Begründung — sonst übergeht ein frühes `finish`
    # die Härtungsphase des Stop-Hooks.
    rest = ns.remaining(ledger.get("deadline"))
    frueh = rest is not None and rest.total_seconds() > 0 and ledger.get("status") == "active"
    # Hat der Stop-Hook das Ende schon entschieden (Leerlauf, Obergrenze, kein Kanal), gilt
    # der Guard nicht — er betrifft nur den Abschluss, den der Agent selbst wählt.
    hook_ende = bool(ledger.get("ende_grund"))
    if frueh and not hook_ende and not ledger.get("hardening_rounds") and not args.grund:
        return _fail("Noch %s bis zur Deadline und keine Härtungsrunde. Erst härten (`cn.py haertung "
                     "\"<was geprüft>\"`) oder begründen: `cn.py finish --grund \"…\"`."
                     % ns.human_delta(rest))
    grund = ledger.get("ende_grund") or (
        "vorzeitig abgeschlossen: %s" % args.grund if frueh and args.grund else
        "vom Agenten abgeschlossen, %s vor der Deadline" % ns.human_delta(rest) if frueh else
        "vom Agenten abgeschlossen")
    close_night(root, ledger, grund)
    # Kopf und Jetzt-du-Block aus dem Endstand nachziehen — die Prosa des Agenten bleibt.
    cn_report.refresh(report, ledger, root)
    print("Nacht beendet. Bericht: %s" % report.as_posix())
    return 0


def cmd_abort(root: Path, args) -> int:
    ledger = _require(root)
    if ledger is None:
        return 1
    ledger["status"] = "aborted"
    ledger["beendet"] = ns.iso(ns.now())
    ledger["ende_grund"] = "abgebrochen: %s" % (args.grund or "ohne Angabe")
    ns.save(root, ledger)
    ns.journal(root, "Schicht abgebrochen: %s" % (args.grund or "ohne Angabe"))
    print("Schicht abgebrochen. Hooks sind ab sofort still.")
    return 0


def cmd_resume(root: Path, args) -> int:
    ledger = _require(root, "active", "interrupted")
    if ledger is None:
        return 1
    ledger["status"] = "active"
    ledger["bound_session"] = None
    ledger["no_progress_streak"] = 0
    ledger["report_blocks"] = 0
    if args.deadline:
        ledger["deadline"] = ns.parse_deadline(args.deadline)
    ns.save(root, ledger)
    ns.journal(root, "Nacht fortgesetzt (neue Session adoptiert).")
    print("Nacht wieder aktiv: %s · %s · Restzeit %s" % (
        ledger.get("titel"), ns.progress_line(ledger), ns.human_delta(ns.remaining(ledger.get("deadline")))))
    return 0


def cmd_preflight(root: Path, args) -> int:
    print("Preflight für %s\n" % root.as_posix())
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        path = root / rel
        if not path.exists():
            print("  %-30s fehlt" % rel)
            continue
        try:
            perms = json.loads(path.read_text(encoding="utf-8")).get("permissions") or {}
        except (OSError, ValueError) as exc:
            print("  %-30s unlesbar (%s)" % (rel, exc))
            continue
        print("  %-30s allow %d · ask %d · deny %d · defaultMode %s" % (
            rel, len(perms.get("allow") or []), len(perms.get("ask") or []),
            len(perms.get("deny") or []), perms.get("defaultMode") or "—"))
        for rule in (perms.get("ask") or [])[:20]:
            print("      ⚠ ask: %s — fragt nachts; der PermissionRequest-Hook lehnt ab" % rule)
    cap = ns.block_cap(root)
    print("\n  Stop-Hook-Block-Cap: %s" % ("%s (%s)" % (cap[1], cap[0]) if cap
                                          else "⚠ nicht gesetzt — Nacht endet nach 8 Blocks"))
    try:
        print("  Shell für Prüfbefehle: %s" % ns.bash_exe())
    except RuntimeError as exc:
        print("  ✗ Shell für Prüfbefehle: %s" % exc)
    ledger = ns.load(root)
    print("  Kanäle: %s%s" % (" · ".join(cn_notify.describe(root, ledger)),
                              "" if cn_notify.reachable(root, ledger) else
                              "  ⚠ erreicht dich nachts nicht (md im Repo liest niemand)"))
    if args.push_test:
        print("    Testmeldung: %s" % cn_notify.receipt(cn_notify.push(
            "Carpe Noctem Preflight", "Kanal steht.", tags="white_check_mark", root=root, ledger=ledger)))
    print("\n  Permission-Modus der Nacht: Default oder acceptEdits. Dann feuert der")
    print("  PermissionRequest-Hook, lehnt nachts ab und legt die Grenze ins Ledger.")
    print("  Im Auto-Mode lehnt der Klassifikator STILL ab — die Nacht merkt es nicht.")
    print("  Nie bypassPermissions verwenden oder vorschlagen.")
    return 0


# ── Argumente ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cn", description="Carpe Noctem — Ledger")
    p.add_argument("--root", help="Repo-Wurzel (Default: automatisch)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="Vorbereitung aus mission.md beginnen")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("premortem", help="Szenario: warum ist die Nacht gescheitert?")
    sp.add_argument("szenario")
    sp.add_argument("--grenze", help="Grenze, auf die das Szenario zurückführt")
    sp.set_defaults(fn=cmd_premortem)

    sp = sub.add_parser("grenze", help="Grenzen inventarisieren, probieren, klären")
    sp.add_argument("action", choices=["add", "probe", "klaer", "wartebank"])
    sp.add_argument("ziel", nargs="?", help="add: Paket-ID · sonst: Grenz-ID (probe: optional)")
    sp.add_argument("--art", choices=list(ns.GRENZ_ARTEN))
    sp.add_argument("--was", default="")
    sp.add_argument("--probe", default="", help="Trockenlauf-Befehl, Exit 0 = Grenze passierbar")
    sp.add_argument("--wie", default="", help="klaer: wodurch geklärt")
    sp.add_argument("--durch", choices=["mensch", "agent"],
                    help="klaer: wer geklärt hat (Pflicht bei urteil/freigabe/irreversibel)")
    sp.add_argument("--ersatz", default="", help="wartebank: Ersatzarbeit, solange gewartet wird")
    sp.set_defaults(fn=cmd_grenze)

    sp = sub.add_parser("risiko", help="Restrisiko je Paket und Gate-Stand")
    sp.add_argument("--headless", action="store_true")
    sp.set_defaults(fn=cmd_risiko)

    sp = sub.add_parser("start", help="Gate prüfen und die Nacht beginnen")
    sp.add_argument("--deadline", help="ISO, +8h, +90m oder HH:MM (Default: mission.md)")
    sp.add_argument("--headless", action="store_true", help="Lauf über ralph.py (kein Block-Cap nötig)")
    sp.add_argument("--force", action="store_true", help="Gate übergehen (steht im Bericht)")
    sp.set_defaults(fn=cmd_start)

    sp = sub.add_parser("status", help="Stand zeigen")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("item", help="Arbeitspaket fortschreiben")
    sp.add_argument("action", choices=["add", "start", "done", "block", "drop", "wait"])
    sp.add_argument("id", nargs="?", help="Paket-ID (bei `add` optional)")
    sp.add_argument("--titel", default="")
    sp.add_argument("--fertig-wenn", dest="fertig_wenn", default="")
    sp.add_argument("--pruefbefehl", default="")
    sp.add_argument("--beleg", default="")
    sp.add_argument("--notiz", default="")
    sp.add_argument("--grenze", default="", help="wait: getroffene Grenze aus der Vorbereitung")
    sp.add_argument("--art", default="", help="wait ohne --grenze: Art der neuen Grenze")
    sp.add_argument("--probe", default="", help="wait: Befehl, der grün wird, sobald die Grenze passierbar ist")
    sp.add_argument("--nach", default="", help="add: Vorgänger, kommagetrennt")
    sp.add_argument("--agent", default="", help="start: welcher Subagent das Paket bearbeitet")
    sp.set_defaults(fn=cmd_item)

    sp = sub.add_parser("progress", help="Zwischenstand am laufenden Paket festhalten")
    sp.add_argument("text")
    sp.add_argument("--id", help="Paket (Default: das laufende bzw. erste offene)")
    sp.set_defaults(fn=cmd_progress)

    sp = sub.add_parser("verify", help="alle `done`-Pakete nachfahren, Durchfaller öffnen")
    sp.add_argument("id", nargs="?")
    sp.set_defaults(fn=cmd_verify)

    sp = sub.add_parser("wache", help="auf Mensch/Grenze warten (Inbox + Trockenläufe)")
    sp.add_argument("--minuten", type=int, default=WACHE_MAX_MIN)
    sp.set_defaults(fn=cmd_wache)

    sp = sub.add_parser("inbox", help="neue Nachrichten des Menschen lesen")
    sp.set_defaults(fn=cmd_inbox)

    sp = sub.add_parser("decision", help="Entscheidung protokollieren")
    sp.add_argument("frage")
    sp.add_argument("--wahl", required=True)
    sp.add_argument("--warum", required=True)
    sp.add_argument("--reversibel", help="wie der Mensch das rückgängig macht")
    sp.add_argument("--ersetzt", help="ID einer früheren Entscheidung, die hiermit überholt ist")
    sp.add_argument("--quelle", choices=["agent", "mensch", "inbox"], default="agent",
                    help="wer entschieden hat (Default agent; mensch nur in der Vorbereitung)")
    sp.set_defaults(fn=cmd_decision)

    sp = sub.add_parser("haertung", help="Härtungsrunde protokollieren")
    sp.add_argument("geprueft", help="was geprüft wurde")
    sp.add_argument("--befund", help="was gefunden wurde (leer = ohne Befund)")
    sp.set_defaults(fn=cmd_haertung)

    sp = sub.add_parser("todo", help="To-Do für den Menschen")
    sp.add_argument("titel")
    sp.add_argument("--prio", default="P2", choices=["P1", "P2", "P3", "p1", "p2", "p3"])
    sp.add_argument("--warum", required=True)
    sp.add_argument("--schritt", required=True, help="konkreter erster Schritt (Befehl/Link)")
    sp.add_argument("--aufwand")
    sp.add_argument("--paket", help="betroffene Pakete, kommagetrennt")
    sp.set_defaults(fn=cmd_todo)

    sp = sub.add_parser("frage", help="unbeantwortbare Frage in den Bericht")
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_frage)

    sp = sub.add_parser("note", help="Journaleintrag")
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_note)

    sp = sub.add_parser("report", help="Berichtsgerüst aus dem Ledger")
    sp.add_argument("--stdout", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_report)

    sp = sub.add_parser("finish", help="Nacht beenden (verlangt den Bericht)")
    sp.add_argument("--grund", help="Begründung für einen Abschluss vor der Deadline ohne Härtung")
    sp.set_defaults(fn=cmd_finish)

    sp = sub.add_parser("abort", help="Schicht abbrechen")
    sp.add_argument("--grund")
    sp.set_defaults(fn=cmd_abort)

    sp = sub.add_parser("resume", help="unterbrochene Nacht in dieser Session fortsetzen")
    sp.add_argument("--deadline")
    sp.set_defaults(fn=cmd_resume)

    sp = sub.add_parser("preflight", help="Umgebung für die Nacht prüfen")
    sp.add_argument("--push-test", action="store_true", help="Testmeldung über alle aktiven Kanäle")
    sp.set_defaults(fn=cmd_preflight)
    return p


def main() -> int:
    ns.stdout_utf8()
    args = build_parser().parse_args()
    root = Path(args.root).resolve() if args.root else ns.find_root()
    return args.fn(root, args)


if __name__ == "__main__":
    sys.exit(main())
