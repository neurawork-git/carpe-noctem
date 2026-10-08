"""Lagebild, Rundenprompt und Morgenbericht von Carpe Noctem.

Der Morgen ist das Produkt der Nacht — gemessen an der Entscheidungsqualität am
Morgen, nicht an Tokens oder Zeilen. Deshalb steht oben, was der Mensch JETZT tun
muss, und unten, was er nachlesen kann. Belege erscheinen in der Tabelle gekürzt,
vollständig im Anhang.

Frühere Berichte hatten die To-Dos weit unten hinter langen Erledigt-Listen, Belege mit
Hunderten Zeichen pro Zeile, keinen Abbruchgrund und keine tatsächliche Laufzeit. Diese
Fassung dreht die Reihenfolge um.

Maschinelle Blöcke stehen zwischen `<!-- cn:… -->`-Markern. `refresh()` zieht sie beim
`finish` aus dem Endstand nach und lässt alles andere — die Prosa des Agenten — stehen.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import cn_state as ns

PRIO_ORDER = {"P1": 0, "P2": 1, "P3": 2}
SHORT = 90


# ── Lagebild und Rundenprompt ────────────────────────────────────────────────

def rules_text(cmd: str) -> list[str]:
    return [
        "Rückfragen sind gesperrt. Unklar? Erst mission.md, Repo-Doku (README/CLAUDE.md), Code "
        "und vorhandene Projektdoku bzw. Wissensbasis. "
        "Bleibt es offen: die REVERSIBLE Variante wählen und "
        '`%s decision "<Frage>" --wahl "…" --warum "…" --reversibel "<wie zurück>"`.' % cmd,
        "Trifft ein Paket eine Grenze (fehlende Permission, Login, Freigabe, menschliches Urteil, "
        "externer Dienst): NICHT blockieren, sondern bis zur Grenze vorbereiten und "
        '`%s item wait <ID> --grenze <GID> --notiz "<was der Mensch tun muss>"` (ohne bekannte '
        "Grenze: `--art <art>`, mit `--probe \"<cmd>\"`, das grün wird, sobald es weitergeht). "
        "Das schickt eine Meldung (md/ntfy); du arbeitest am nächsten Paket weiter." % cmd,
        "Was nur der Mensch darf (senden, deployen, löschen, Geld, Kundensysteme schreiben): bis "
        'zum Gate vorbereiten, dann `%s todo "<Titel>" --prio P1 --warum "…" --schritt "<erster '
        'Schritt>" --paket <ID>`. Nie selbst auslösen.' % cmd,
        "Fertig heißt abgenommen: `%s item done <ID> --beleg \"<kurz>\"` fährt Prüfbefehl und "
        "Richter. Richter-Dateien (Tests, Prüfskripte) sind schreibgeschützt — gegen veränderte "
        "Tests gibt es keine Abnahme." % cmd,
        "Nach JEDEM Schritt, der etwas bewegt hat: `%s progress \"<was jetzt gilt>\" --id <ID>`. "
        "Der Kontext überlebt die Kompaktierung nicht, das Ledger schon. Arbeiten Subagenten "
        "parallel: jedes Paket mit `item start <ID> --agent <name>` anmelden." % cmd,
        "Neue Arbeit: `%s item add --titel \"…\" --fertig-wenn \"<messbar, VOR der Arbeit formuliert>\" "
        "[--nach A1]`. Den Prüfbefehl liefert der Default-Richter der Mission; einen eigenen "
        "(`--pruefbefehl`) markiert der Bericht als „vom Agenten gewählt“." % cmd,
        "Lehnt ein Hook oder der Auto-Mode-Klassifikator eine Aktion ab, erzwinge dasselbe Ziel NIE "
        "über ein anderes Werkzeug (Bash geblockt → Write ist derselbe Verstoß). Freigegebenen Weg "
        "nehmen oder `item wait`.",
        "Entscheidungen tragen ihre Quelle: `--quelle agent` (Default) — `inbox`, wenn der Mensch "
        "per Inbox geantwortet hat. Härtung, auch ungefragte, zählt nur protokolliert: "
        "`%s haertung \"<was geprüft>\" [--befund \"…\"]`." % cmd,
    ]


def briefing(ledger: dict, root, cmd: str) -> str:
    """Kurzes Lagebild für Session-Start und Kompaktierung — ohne Gesprächsgedächtnis lesbar."""
    lines = [
        "CARPE NOCTEM — die Nacht läuft, autonomer Modus.",
        "Auftrag: %s (%s)" % (ledger.get("titel") or "?", ns.mission_path(root).as_posix()),
        "Stand: %s · Restzeit %s · Fortsetzung %d/%d" % (
            ns.progress_line(ledger), ns.human_delta(ns.remaining(ledger.get("deadline"))),
            ledger.get("continuations", 0), ledger.get("max_continuations", 0)),
        "Nächste Pakete (Risiko zuerst): %s" % (", ".join(
            "%s (%s)" % (i["id"], i.get("titel", "")) for i in ns.open_items(ledger)[:6]) or "keine"),
        "Wartend: %s" % (", ".join("%s→%s" % (i["id"], i.get("wartet_auf", "?"))
                                   for i in ns.waiting_items(ledger)) or "nichts"),
        *rules_text(cmd),
        "Werkzeug: %s status|item|progress|verify|wache|inbox|decision|todo|frage|note|report|finish"
        % cmd,
    ]
    laufend = ns.current_item(ledger)
    fortschritt = ns.progress_lines(laufend)
    if fortschritt:
        lines.append("Laufendes Paket %s — Zwischenstände: %s"
                     % (laufend["id"], " ;; ".join(fortschritt)))
    riss = ledger.get("letzte_kompaktierung") or {}
    if riss:
        lines.append("ACHTUNG: Kontext zuletzt %s mitten in Paket %s kompaktiert. Erst `%s status` "
                     "lesen, dann weiterbauen." % (riss.get("zeit", "?"), riss.get("paket") or "?", cmd))
    return " | ".join(lines)


def round_prompt(root, cmd: str) -> str:
    """Fester Rundenprompt (Ralph-Muster) für `ralph.py` — zustandslos, der Stand liegt im Ledger."""
    return "\n".join([
        "Du arbeitest eine Runde einer laufenden Carpe-Noctem-Nacht. Rückfragen sind gesperrt.",
        "",
        "1. Stand holen: `%s status` und `%s inbox`. Auftrag: %s" % (cmd, cmd, ns.mission_path(root).as_posix()),
        "   Eine Nachricht vom Menschen hat Vorrang vor dem Plan.",
        "2. GENAU EIN offenes Paket — das oberste (die Reihenfolge ist nach Risiko sortiert).",
        "   Sind nur wartende Pakete übrig: Härtungs-Backlog oder `%s wache`." % cmd,
        "3. Umsetzen, mit einem frischen Lauf belegen, committen.",
        "4. Abnahme NICHT selbst erteilen: unabhängiger Review-Subagent mit nur Diff + Fertig-Kriterium",
        "   gegenlesen lassen, dann `%s item done <ID> --beleg \"<kurz>\"` (fährt Prüfbefehl und Richter)." % cmd,
        "",
        *["- " + r for r in rules_text(cmd)],
        "",
        "Sind alle Pakete zu und die Zeit um: `%s report`, Kurzfassung ausfüllen, `%s finish`." % (cmd, cmd),
    ]) + "\n"


# ── Bericht ──────────────────────────────────────────────────────────────────

def _short(text: str, limit: int = SHORT) -> str:
    text = " ".join(str(text or "").split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _laufzeit(ledger: dict) -> str:
    start = ns.parse_iso(ledger.get("nacht_beginn"))
    if not start:
        return "nicht gestartet"
    end = ns.parse_iso(ledger.get("beendet")) or ns.now()
    lief = end - start
    soll = (ns.parse_iso(ledger.get("deadline")) - start) if ledger.get("deadline") else None
    text = "%s → %s (%s" % (start.strftime("%d.%m. %H:%M"), end.strftime("%H:%M"), ns.human_delta(lief))
    if soll and soll.total_seconds() > 0:
        text += " von %s, %d %%" % (ns.human_delta(soll), round(100 * lief / soll))
    return text + ")"


def ampel(ledger: dict) -> tuple[str, str]:
    items = [i for i in ledger.get("items", []) if i.get("status") != "dropped"]
    done = ns.items_by_state(ledger, "done")
    pruefen = [i for i in done if i.get("bitte_pruefen")]
    p1 = [t for t in ledger.get("todos", []) if str(t.get("prio")).upper() == "P1"]
    grund = str(ledger.get("ende_grund") or "")
    if ledger.get("status") in ("interrupted", "aborted") or "Leerlauf" in grund \
            or "Obergrenze" in grund or (items and len(done) < len(items) / 2):
        return "🔴", "Nacht hat ihr Ziel verfehlt"
    if len(done) == len(items) and not pruefen and not p1 and not ns.waiting_items(ledger) \
            and not _pruefen(ledger, None):
        return "🟢", "alles erledigt und abgenommen"
    return "🟡", "Ergebnis steht, braucht dich noch"


def headline(ledger: dict) -> str:
    farbe, satz = ampel(ledger)
    done = ns.items_by_state(ledger, "done")
    return "%s %s · %d/%d erledigt · %d warten auf dich · %d bitte prüfen · Ende: %s" % (
        farbe, satz, len(done), len(ledger.get("items", [])), len(ns.waiting_items(ledger)),
        len(_pruefen(ledger, None)), ledger.get("ende_grund") or "läuft")


def _kopf(ledger: dict, auto: bool) -> list[str]:
    out = ["**%s**" % headline(ledger), "",
           "Lief %s · %d× vom Stop-Hook fortgesetzt · %d Härtungsrunden · %d Wachen%s" % (
               _laufzeit(ledger), ledger.get("continuations", 0), ledger.get("hardening_rounds", 0),
               ledger.get("wachen", 0),
               (" · Quelle: %s" % ledger["quelle"]) if ledger.get("quelle") else "")]
    if ledger.get("permission_mode") == "auto":
        out += ["", "⚠ **Nacht lief im Auto-Mode** — Ablehnungen des Klassifikators wurden aus dem "
                    "Transkript gelesen (%d), nicht vom PermissionRequest-Hook."
                % len(ledger.get("klassifikator_ablehnungen") or [])]
    if ledger.get("gate_uebergangen"):
        out += ["", "⚠ **Gate beim Start übergangen:** " + " · ".join(ledger["gate_uebergangen"])]
    if auto:
        out += ["", "⚠ **Automatisch aus dem Ledger erzeugt** — die Nacht endete, bevor der Agent "
                    "den Bericht schreiben konnte. Die Kurzfassung fehlt, die Fakten stimmen."]
    return out


def _jetzt(ledger: dict) -> list[str]:
    todos = sorted(ledger.get("todos", []),
                   key=lambda t: PRIO_ORDER.get(str(t.get("prio", "P3")).upper(), 3))
    covered = {p.lower() for t in todos for p in (t.get("pakete") or [])}
    out = []
    n = 0
    for item in ns.waiting_items(ledger):
        if item["id"].lower() in covered:
            continue
        g = ns.find_grenze(ledger, item.get("wartet_auf", "")) or {}
        n += 1
        out.append("%d. **[P1] %s wartet auf dich** (%s, %s) — %s" % (
            n, item["id"], g.get("id", "?"), g.get("art", "?"), _short(item.get("notiz") or g.get("was"), 160)))
    for t in todos:
        n += 1
        link = (" _(%s)_" % ", ".join(t["pakete"])) if t.get("pakete") else ""
        out.append("%d. **[%s] %s**%s — %s" % (n, t.get("prio", "P3"), t.get("titel", ""), link,
                                               _short(t.get("warum"), 160)))
        if t.get("erster_schritt"):
            out.append("   → %s" % t["erster_schritt"])
    fragen = ledger.get("offene_fragen", [])
    if fragen:
        out += ["", "Fragen, die die Nacht nicht entscheiden konnte:"]
        out += ["- %s" % (f.get("text") if isinstance(f, dict) else f) for f in fragen]
    return out or ["Nichts — die Nacht braucht dich nicht."]


def _pruefen(ledger: dict, root) -> list[str]:
    out = []
    for item in ns.items_by_state(ledger, "done"):
        if not item.get("bitte_pruefen"):
            continue
        ab = item.get("abnahme") or {}
        urteil = ab.get("richter") or {}
        if item.get("richter_vom_agent"):
            why = "Prüfbefehl vom Agenten gewählt (`%s`)" % _short(item.get("pruefbefehl"), 80)
        elif urteil:
            why = "Richter unsicher (%s %.2f)" % (urteil.get("verdict"), urteil.get("confidence") or 0) \
                if urteil.get("verdict") != "fehler" else "Richter nicht erreichbar"
        else:
            why = "ohne Prüfbefehl — nur die Aussage des Agenten"
        out.append("- **%s** %s — %s · Kriterium: %s" % (item["id"], item.get("titel", ""), why,
                                                        _short(item.get("fertig_wenn"), 120)))
    for g in ledger.get("grenzen", []):
        if g.get("art") in ns.HUMAN_ONLY and g.get("status") == "geklaert" \
                and g.get("durch") not in ("mensch", "trockenlauf"):
            out.append("- **%s** %s-Grenze vom Agenten geklärt: %s — %s" % (
                g["id"], g["art"], _short(g.get("was"), 80), _short(g.get("klaerung"), 100)))
    for e in ledger.get("entscheidungen", []):
        if e.get("vom_agent") and not e.get("ersetzt_durch") and "Vorbereitung" in str(e.get("quelle")):
            out.append("- **%s** in der Vorbereitung vom Agenten entschieden, nicht vom Menschen: %s → %s"
                       % (e["id"], _short(e.get("frage"), 80), _short(e.get("wahl"), 60)))
    for d in ledger.get("klassifikator_ablehnungen") or []:
        out.append("- **%s** Klassifikator lehnte ab (%s) bei Paket %s — prüfen, ob das Ziel danach "
                   "auf anderem Weg erreicht wurde" % (d.get("grenze"), d.get("grund"), d.get("paket") or "?"))
    if root is not None:
        drift = ns.protected_drift(Path(root), ledger) if ledger.get("geschuetzt_hashes") else []
        if drift:
            out.append("- ⚠ **Richter-Dateien in der Nacht verändert:** %s" % ", ".join(drift[:8]))
    return out


def _ergebnis(ledger: dict) -> list[str]:
    label = {"done": "✓ erledigt", "waiting": "… wartet", "blocked": "✗ blockiert",
             "dropped": "~ verworfen", "open": "offen", "doing": "läuft"}
    out = ["| ID | Paket | Status | Abnahme | Beleg / Grund |", "|---|---|---|---|---|"]
    for item in ns.ordered(ledger.get("items", [])):
        ab = item.get("abnahme") or {}
        art = ab.get("art", "—") if item.get("status") == "done" else "—"
        if item.get("bitte_pruefen"):
            art += " ⚠"
        text = item.get("beleg") if item.get("status") == "done" else item.get("notiz")
        out.append("| %s | %s | %s | %s | %s |" % (item["id"], _short(item.get("titel"), 50),
                                                  label.get(item.get("status"), item.get("status")),
                                                  art, _short(text)))
    return out


def _entscheidungen(ledger: dict) -> list[str]:
    aktuell = [e for e in ledger.get("entscheidungen", []) if not e.get("ersetzt_durch")]
    ersetzt = len(ledger.get("entscheidungen", [])) - len(aktuell)
    out = []
    for e in aktuell:
        out.append("- **%s** %s → **%s** _(%s)_ — %s · zurück: %s" % (
            e.get("id", "?"), _short(e.get("frage"), 100), _short(e.get("wahl"), 80),
            e.get("quelle", "?"), _short(e.get("warum"), 100),
            _short(e.get("reversibel") or "unklar — bitte prüfen", 80)))
    if ersetzt:
        out.append("_%d frühere Entscheidung(en) wurden in der Nacht ersetzt — Verlauf im Ledger._" % ersetzt)
    return out or ["- (keine)"]


def _grenzen(ledger: dict) -> list[str]:
    if not ledger.get("grenzen"):
        return ["- (keine inventarisiert)"]
    ausgang = {"geklaert": "vorab geklärt", "wartebank": "Wartebank", "getroffen": "nachts getroffen",
               "offen": "offen"}
    out = ["| G | Paket | Art | Was | Ausgang |", "|---|---|---|---|---|"]
    for g in ledger["grenzen"]:
        detail = g.get("klaerung") or g.get("ersatz") or ""
        out.append("| %s | %s | %s | %s | %s%s |" % (
            g["id"], g.get("paket"), g.get("art"), _short(g.get("was"), 70),
            ausgang.get(g.get("status"), g.get("status")) + (" (nachts neu)" if g.get("nachts") else ""),
            (": " + _short(detail, 60)) if detail else ""))
    return out


def _artefakte(ledger: dict, root) -> list[str]:
    out = []
    if root is not None and ledger.get("nacht_commit"):
        try:
            log = subprocess.run(["git", "-C", str(root), "log", "--oneline",
                                  "%s..HEAD" % ledger["nacht_commit"]],
                                 capture_output=True, text=True, timeout=20, encoding="utf-8").stdout
            commits = [line for line in log.splitlines() if line.strip()]
        except (OSError, subprocess.SubprocessError):
            commits = []
        out.append("Commits der Nacht: %d" % len(commits))
        out += ["- `%s`" % c for c in commits[:40]]
    if root is not None:
        out.append("")
        # repo-relativ: REPORT.md wird committet und darf keine lokalen Benutzerpfade tragen
        out.append("Journal: `%s/%s` · Ledger: `%s/%s`" % (ns.DIRNAME, ns.JOURNAL_NAME, ns.DIRNAME, ns.LEDGER_NAME))
    return out


def _block(name: str, lines: list[str]) -> list[str]:
    return ["<!-- cn:%s -->" % name, *lines, "<!-- /cn:%s -->" % name]


def render(ledger: dict, root=None, auto: bool = False) -> str:
    titel = ledger.get("titel") or "Carpe Noctem"
    pruefen = _pruefen(ledger, root)
    lines = ["# Carpe Noctem — %s" % titel, ""]
    lines += _block("kopf", _kopf(ledger, auto))
    lines += ["", "## Kurzfassung", ""]
    lines += ["_(nicht geschrieben — Notbericht)_" if auto else
              "_Drei Sätze: was erreicht ist, was nicht und warum, in welchem Zustand das System jetzt ist._"]
    lines += ["", "## Jetzt du", ""]
    lines += _block("jetzt", _jetzt(ledger))
    lines += ["", "## Bitte prüfen", ""]
    lines += _block("pruefen", pruefen or ["Nichts — jede Abnahme lief über Prüfbefehl bzw. Richter."])
    lines += ["", "## Ergebnis", ""]
    lines += _block("ergebnis", _ergebnis(ledger))
    lines += ["", "## Entscheidungen", ""]
    lines += _block("entscheidungen", _entscheidungen(ledger))
    lines += ["", "## Grenzen — wo die Nacht einen Menschen brauchte", ""]
    lines += _block("grenzen", _grenzen(ledger))
    lines += ["", "---", "", "## Anhang", "", "### Belege vollständig", ""]
    belege = []
    for item in ns.items_by_state(ledger, "done"):
        ab = item.get("abnahme") or {}
        belege.append("- **%s** %s" % (item["id"], item.get("beleg", "")))
        if ab.get("ausgabe"):
            belege.append("  - Prüfbefehl `%s` → %s" % (item.get("pruefbefehl"), ab["ausgabe"]))
        if ab.get("richter"):
            r = ab["richter"]
            belege.append("  - Richter: %s (%s) %s" % (r.get("verdict"), r.get("confidence"),
                                                       r.get("modell", "")))
    lines += _block("belege", belege or ["- (keine)"])
    lines += ["", "### Härtung", ""]
    lines += _block("haertung", ["- %s %s%s" % (
        str(h.get("zeit", ""))[11:16], h.get("geprueft", ""),
        (" — **Befund:** %s" % h["befund"]) if h.get("befund") else " — ohne Befund")
        for h in ledger.get("haertung") or []] or ["- (keine protokolliert)"])
    lines += ["", "### Pre-mortem der Vorbereitung", ""]
    lines += _block("premortem", ["- %s %s%s" % (m.get("id"), m.get("szenario"),
                                                 (" → %s" % m["grenze"]) if m.get("grenze") else "")
                                  for m in ledger.get("premortem", [])] or ["- (keins)"])
    lines += ["", "### Artefakte", ""]
    lines += _block("artefakte", _artefakte(ledger, root))
    return "\n".join(lines) + "\n"


def refresh(report: Path, ledger: dict, root) -> None:
    """Maschinelle Blöcke im bestehenden Bericht aus dem Endstand neu setzen; Prosa bleibt."""
    try:
        text = report.read_text(encoding="utf-8")
    except OSError:
        return
    fresh = render(ledger, root=root, auto=False)
    for name in re.findall(r"<!-- cn:([a-z]+) -->", fresh):
        pat = re.compile(r"<!-- cn:%s -->.*?<!-- /cn:%s -->" % (name, name), re.DOTALL)
        new = pat.search(fresh)
        if new and pat.search(text):
            text = pat.sub(lambda _m: new.group(0), text, count=1)
    with report.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
