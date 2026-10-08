"""Selbsttest für Carpe Noctem — Parser, Restrisiko, Schreibschutz und ein ganzer Lauf.

Der Lauf spielt in einem Wegwerf-Git-Repo: Vorbereitung → Gate verweigert → Grenzen
klären → Start → Abnahme scheitert/gelingt → Richter-Datei manipuliert → Wartebank →
Stop-Hook (Arbeit, Inbox-Nachricht, Wache) → Bericht → finish. Kein Netz: ntfy und
Jev bleiben aus.

    python scripts/test_cn.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cn_report  # noqa: E402
import cn_state as ns  # noqa: E402

MISSION = """---
titel: Testnacht
deadline: +6h   # Kommentar wird abgeschnitten
geschuetzt: tests/**
richter_default: test -f ok.txt
kanal: md
kanal_md: meldungen/nacht.md
---

# Arbeitspakete

- [ ] A1 — Erstes Paket :: fertig wenn: die Datei
      `ok.txt` existiert und jede Zeile
      trägt eine Begründung.
      prüfen: test -f ok.txt
- [ ] A2 — Zweites Paket :: fertig wenn: in
      `AGENTS.md` stehen vier Quellenarten.
      nach: A1
- [ ] A3 — Drittes Paket :: fertig wenn: Upload liegt im Blob

# Grenzen

- G1 [A3] login: Token für den Upload
      probe: true
- G2 [A2] urteil: Feldname kundennr oder debitor

# Pre-mortem

- Token läuft nachts ab
- Feldname falsch geraten

# Verbotene Aktionen

- Externe Kommunikation

# Härtungs-Backlog

- Randfälle
"""

ENV = {k: v for k, v in os.environ.items()
       if k not in ("CARPE_NOCTEM_NTFY", "TYPESAFE_API_KEY", "CLAUDE_PLUGIN_ROOT", "CARPE_NOCTEM_ROUND",
                    "CLAUDE_CODE_STOP_HOOK_BLOCK_CAP", "CARPE_NOCTEM_KANAL", "CARPE_NOCTEM_MD")}


def unit() -> None:
    parsed = ns.parse_mission(MISSION)
    items = {i["id"]: i for i in parsed["items"]}
    assert parsed["front"]["deadline"] == "+6h", parsed["front"]
    assert parsed["front"]["geschuetzt"] == "tests/**"
    assert "Begründung" in items["A1"]["fertig_wenn"], items["A1"]
    assert items["A2"]["fertig_wenn"] != "in", "Regression: Kriterium auf erste Zeile abgeschnitten"
    assert items["A1"]["pruefbefehl"] == "test -f ok.txt"
    assert items["A2"]["nach"] == ["A1"], items["A2"]
    assert "nach:" not in items["A2"]["fertig_wenn"], items["A2"]["fertig_wenn"]
    assert parsed["front"]["richter_default"] == "test -f ok.txt"
    g = {x["id"]: x for x in parsed["grenzen"]}
    assert g["G1"]["probe"] == "true" and g["G1"]["paket"] == "A3" and g["G1"]["art"] == "login"
    assert g["G2"]["art"] == "urteil" and g["G2"]["probe"] == ""
    assert len(parsed["premortem"]) == 2

    ledger = {"items": parsed["items"], "grenzen": parsed["grenzen"]}
    # G2 urteil offen: 2*3 + ohne Prüfbefehl 1 = 7 · G1 login offen: 2*2 + 1 = 5 · A1: 0
    assert ns.restrisiko(ledger, items["A2"]) == 7, ns.restrisiko(ledger, items["A2"])
    assert ns.restrisiko(ledger, items["A3"]) == 5
    assert ns.restrisiko(ledger, items["A1"]) == 0
    g["G2"]["status"] = "wartebank"
    assert ns.restrisiko(ledger, items["A2"]) == 4

    assert ns.matches_protected("tests/unit/test_x.py", ["tests/**"])
    assert ns.matches_protected("./scripts/check_a.py", ["scripts/check_*.py"])
    assert not ns.matches_protected("src/tests.py", ["tests/**"])

    # Abhängigkeiten vor Risiko: A2 (Risiko 4) kommt erst nach A1 (Risiko 0).
    order = [i["id"] for i in ns.topo_order(ledger)]
    assert order.index("A1") < order.index("A2"), order
    items["A1"]["nach"] = ["A2"]
    try:
        ns.topo_order(ledger)
        raise AssertionError("Zyklus nicht erkannt")
    except ValueError:
        pass
    items["A1"]["nach"] = []

    # `nach:` mit Zusatztext wird gemeldet, nicht still verworfen.
    p = ns.parse_mission("# Arbeitspakete\n- [ ] B1 — x :: fertig wenn: y\n      nach: A1 (Basis) und A4\n")
    assert p["items"][0]["nach"] == ["A1", "A4"], p["items"][0]
    assert p["items"][0]["nach_unklar"] == ["(Basis)"], p["items"][0]

    # Block-Cap aus der Umgebung zählt; 8 ist der Default und zählt nicht.
    old = os.environ.get("CLAUDE_CODE_STOP_HOOK_BLOCK_CAP")
    os.environ["CLAUDE_CODE_STOP_HOOK_BLOCK_CAP"] = "200"
    assert ns.block_cap(Path(".")) == ("Umgebungsvariable", "200")
    os.environ["CLAUDE_CODE_STOP_HOOK_BLOCK_CAP"] = "8"
    assert (ns.block_cap(Path(".")) or ("",))[0] != "Umgebungsvariable"
    if old is None:
        del os.environ["CLAUDE_CODE_STOP_HOOK_BLOCK_CAP"]
    else:
        os.environ["CLAUDE_CODE_STOP_HOOK_BLOCK_CAP"] = old

    # Kanäle: Default md (+ ntfy nur mit URL), explizite Wahl gewinnt, Unbekanntes wird gemeldet.
    import cn_notify  # noqa: PLC0415
    saved = {k: os.environ.pop(k, None) for k in ("CARPE_NOCTEM_KANAL", "CARPE_NOCTEM_NTFY", "CARPE_NOCTEM_MD")}
    assert cn_notify.channels({}) == ["md"]
    assert not cn_notify.reachable(Path("."), {}), "Default-md im Repo erreicht niemanden"
    os.environ["CARPE_NOCTEM_NTFY"] = "http://127.0.0.1:9/test"
    assert cn_notify.channels({}) == ["md", "ntfy"]
    assert cn_notify.channels({"kanaele_roh": "md"}) == ["md"]
    os.environ["CARPE_NOCTEM_KANAL"] = "ntfy"
    assert cn_notify.channels({"kanaele_roh": "md"}) == ["ntfy"], "Umgebung gewinnt"
    assert cn_notify.unknown_kanaele("md, telegram") == ["telegram"]
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v

    for n in range(ns.MAX_PROGRESS + 3):
        ns.add_progress(items["A1"], "schritt %d" % n)
    assert len(ns.progress_lines(items["A1"])) == ns.MAX_PROGRESS
    assert ns.progress_lines(None) == []


def cn(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(HERE / "cn.py"), "--root", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", env=ENV)
    return proc.returncode, proc.stdout + proc.stderr


def hook(root: Path, script: str, payload: dict) -> dict:
    proc = subprocess.run([sys.executable, str(HERE / script)], input=json.dumps(
        {"cwd": str(root), "session_id": "s1", **payload}), capture_output=True, text=True,
        encoding="utf-8", env=ENV)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def flow() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Eigenes Home: der Block-Cap aus ~/.claude/settings.json des Entwicklers darf den
        # Gate-Test nicht grün färben.
        ENV["USERPROFILE"] = ENV["HOME"] = tmp
        git(root, "init", "-q")
        git(root, "config", "--local", "user.email", "test@example.invalid")
        git(root, "config", "--local", "user.name", "Test")
        (root / "tests").mkdir()
        (root / "tests" / "test_a.py").write_text("assert True\n", encoding="utf-8")
        ns.cn_dir(root).mkdir(parents=True)
        ns.mission_path(root).write_text(MISSION, encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "basis")

        code, out = cn(root, "init")
        assert code == 0, out
        assert ns.load(root)["status"] == "vorbereitung"
        # Hooks sind in der Vorbereitung still.
        assert hook(root, "stop-guard.py", {}) == {}

        code, out = cn(root, "start")
        assert code == 1 and "Pre-mortem" in out and "G1" in out and "BLOCK_CAP" in out, out

        assert cn(root, "premortem", "Prüfbefehl misst Nachbargröße")[0] == 0
        assert cn(root, "grenze", "klaer", "G1", "--wie", "Token bis 09:00")[0] == 0
        # Urteils-Grenze ohne Angabe, wer geklärt hat: verweigert.
        code, out = cn(root, "grenze", "klaer", "G2", "--wie", "Regel aus CLAUDE.md")
        assert code == 1 and "--durch" in out, out
        # Entscheidung in der Vorbereitung ohne --quelle gilt als Agent, nicht als Mensch.
        assert cn(root, "decision", "Feldname?", "--wahl", "kundennr", "--warum", "Code gilt")[0] == 0
        assert ns.load(root)["entscheidungen"][0]["quelle"] == "Agent (Vorbereitung)"
        code, out = cn(root, "start", "--headless")
        assert code == 1 and "Trockenlauf" in out, out  # geklärt, aber Probe nicht gefahren
        assert cn(root, "grenze", "probe")[0] == 0
        assert cn(root, "grenze", "wartebank", "G2", "--ersatz", "A1 zuerst")[0] == 0
        (root / ".claude" / "settings.json").write_text(
            json.dumps({"env": {"CLAUDE_CODE_STOP_HOOK_BLOCK_CAP": "200"}}), encoding="utf-8")
        code, out = cn(root, "start")
        assert code == 0, out
        ledger = ns.load(root)
        order = [i["id"] for i in ns.ordered(ledger["items"])]
        # A2 hat das höchste Risiko, braucht aber A1 — Abhängigkeit vor Risiko. A3 (Risiko 1,
        # kein Prüfbefehl) läuft vor A1 (Risiko 0).
        assert order == ["A3", "A1", "A2"], order
        assert "tests/test_a.py" in ledger["geschuetzt_hashes"]
        code, out = cn(root, "item", "start", "A2")
        assert code == 1 and "braucht erst A1" in out, out

        # Orchestrator: mehrere Pakete parallel, progress verlangt dann --id.
        assert cn(root, "item", "start", "A1", "--agent", "bau-1")[0] == 0
        assert cn(root, "item", "start", "A3", "--agent", "bau-2")[0] == 0
        code, out = cn(root, "progress", "halb fertig")
        assert code == 1 and "--id" in out, out
        assert cn(root, "progress", "halb fertig", "--id", "A3")[0] == 0

        # Nachts angelegte Pakete erben den Default-Richter; ein eigener wird markiert.
        assert cn(root, "item", "add", "--titel", "Nachpaket", "--fertig-wenn", "x")[0] == 0
        assert cn(root, "item", "add", "--titel", "Eigenrichter", "--fertig-wenn", "y",
                  "--pruefbefehl", "true")[0] == 0
        ledger = ns.load(root)
        z1, z2 = ns.find_item(ledger, "Z4"), ns.find_item(ledger, "Z5")
        assert z1["pruefbefehl"] == "test -f ok.txt" and not z1["richter_vom_agent"], z1
        assert z2["richter_vom_agent"], z2
        assert cn(root, "item", "done", "Z5", "--beleg", "true")[0] == 0
        assert ns.find_item(ns.load(root), "Z5")["bitte_pruefen"]
        assert cn(root, "item", "drop", "Z4", "--notiz", "nur Test")[0] == 0
        # Nachfolger eines Pakets, das später auf einen Menschen wartet.
        assert cn(root, "item", "add", "--titel", "Folgepaket", "--fertig-wenn", "z", "--nach", "A2")[0] == 0
        code, out = cn(root, "item", "add", "--titel", "x", "--fertig-wenn", "x", "--nach", "A2 (bald)")
        assert code == 1 and "keine Paket-ID" in out, out

        # Abnahme: Prüfbefehl rot, dann grün (Git-Bash, nicht cmd.exe).
        code, out = cn(root, "item", "done", "A1", "--beleg", "geschrieben")
        assert code == 1 and "Exit" in out, out
        (root / "ok.txt").write_text("x\n", encoding="utf-8")
        code, out = cn(root, "item", "done", "A1", "--beleg", "ok.txt da")
        assert code == 0, out
        a1 = ns.find_item(ns.load(root), "A1")
        assert a1["abnahme"]["art"] == "pruefbefehl" and not a1["bitte_pruefen"]

        # Richter-Datei angefasst → keine Abnahme mehr, Edit-Hook lehnt ab.
        denied = hook(root, "guard-protected.py", {"tool_name": "Edit", "tool_input": {
            "file_path": str(root / "tests" / "test_a.py")}})
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
        (root / "tests" / "test_a.py").write_text("assert True or 1\n", encoding="utf-8")
        code, out = cn(root, "item", "done", "A3", "--beleg", "hochgeladen")
        assert code == 1 and "Richter-Dateien" in out, out
        git(root, "checkout", "--", "tests/test_a.py")

        # Rückfrage und Permission-Dialog nachts: abgelehnt und protokolliert.
        q = hook(root, "guard-no-questions.py", {"tool_name": "AskUserQuestion", "tool_input": {
            "questions": [{"question": "Welcher Feldname?"}]}})
        assert q["hookSpecificOutput"]["permissionDecision"] == "deny"
        p = hook(root, "permission-guard.py", {"tool_name": "Bash", "tool_input": {"command": "az storage blob upload"}})
        assert p["hookSpecificOutput"]["decision"]["behavior"] == "deny"
        assert any(g.get("nachts") for g in ns.load(root)["grenzen"])

        # Auto-Mode: Klassifikator-Ablehnung steht nur im Transkript — der Stop-Hook holt sie.
        transcript = root / "transcript.jsonl"
        denial = {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
                  "content": "Permission for this action was denied by the Claude Code auto mode "
                             "classifier. Reason: [Self-Modification]. If you have other tasks…"}]}}
        quote = {"type": "assistant", "message": {"content": [{"type": "text", "text":
                 "Zitat: denied by the Claude Code auto mode classifier. Reason: [Zitat]"}]}}
        # Falsch-positiv-Fallen: gelesene Datei mit dem Satz, Ablehnung vor der Nacht.
        cat = {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": False,
               "content": "Permission for this action was denied by the Claude Code auto mode "
                          "classifier. Reason: [AusDatei]"}]}}
        alt = dict(denial, timestamp="2000-01-01T00:00:00Z")
        alt["message"] = {"content": [{"type": "tool_result", "is_error": True, "content":
                          "Permission for this action was denied by the Claude Code auto mode "
                          "classifier. Reason: [Vorbereitung]"}]}
        transcript.write_text("\n".join(json.dumps(x) for x in (quote, cat, alt, denial)) + "\n",
                              encoding="utf-8")
        r = hook(root, "stop-guard.py", {"transcript_path": str(transcript), "permission_mode": "auto"})
        assert r["reason"].startswith("SPERRE SEIT DER LETZTEN RUNDE"), r["reason"][:200]
        ledger = ns.load(root)
        assert ledger["permission_mode"] == "auto"
        assert [d["grund"] for d in ledger["klassifikator_ablehnungen"]] == ["Self-Modification"]
        r = hook(root, "stop-guard.py", {"transcript_path": str(transcript)})
        assert "SPERRE" not in r["reason"], "Ablehnung darf nur einmal gemeldet werden"

        # Stop-Hook: Arbeit, mit Inbox-Nachricht oben.
        ns.inbox_path(root).write_text("- 23:41 nimm kundennr\n", encoding="utf-8")
        r = hook(root, "stop-guard.py", {})
        assert r["decision"] == "block" and r["reason"].startswith("NACHRICHT VOM MENSCHEN"), r
        assert "kundennr" in r["reason"]
        r = hook(root, "stop-guard.py", {})
        assert "NACHRICHT" not in r["reason"], "Nachricht darf nur einmal erscheinen"

        # Wartebank: Paket hängt, Rest geschlossen → Härtung, dann Wache (Trockenlauf vorhanden).
        assert cn(root, "item", "wait", "A2", "--grenze", "G2", "--notiz", "Feldname?",
                  "--probe", "test -f feld.txt")[0] == 0
        assert cn(root, "item", "block", "A3", "--notiz", "Upload-Ziel fehlt")[0] == 0
        ledger = ns.load(root)
        ledger["hardening_rounds"] = ledger["hardening_rounds_max"]
        ns.save(root, ledger)
        r = hook(root, "stop-guard.py", {})
        # Z6 ist offen, aber nicht startbar — die Nacht darf nicht in der Arbeitsphase festsitzen.
        assert "WACHE" in r["reason"] and "Z6] hängt an Vorgänger A2" in r["reason"], r["reason"][:600]
        (root / "feld.txt").write_text("kundennr\n", encoding="utf-8")
        code, out = cn(root, "wache", "--minuten", "1")
        assert code == 0 and "FREI: A2" in out, out
        assert ns.find_item(ns.load(root), "A2")["status"] == "open"

        # Bericht: Jetzt du vor Ergebnis, Laufzeit und Ampel im Kopf, Prosa überlebt finish.
        code, out = cn(root, "todo", "Upload-Ziel anlegen", "--prio", "P1", "--warum", "fehlt",
                       "--schritt", "az storage container create -n x", "--paket", "A3")
        assert code == 0 and "Meldung über md" in out, out
        # md-Kanal: Meldungen der Nacht stehen in der gewählten Datei (relativ zum Repo).
        meldungen = (root / "meldungen" / "nacht.md").read_text(encoding="utf-8")
        for erwartet in ("Carpe Noctem: Testnacht", "braucht dich: A2", "P1: Upload-Ziel anlegen",
                         "Klassifikator lehnt ab", "Permission fehlt"):
            assert erwartet in meldungen, erwartet
        # Secret-Muster verlassen keinen Kanal — auch nicht als Befehlsauszug einer Permission.
        token = "ghp_" + "A1b2C3d4" * 4
        hook(root, "permission-guard.py", {"tool_name": "Bash", "tool_input": {
            "command": "curl -H 'Authorization: token %s' https://api.example.invalid" % token}})
        meldungen = (root / "meldungen" / "nacht.md").read_text(encoding="utf-8")
        assert token not in meldungen and "[SECRET]" in meldungen, meldungen[-400:]
        assert cn(root, "report")[0] == 0
        report = ns.report_path(root)
        text = report.read_text(encoding="utf-8")
        assert text.index("## Jetzt du") < text.index("## Ergebnis") < text.index("## Anhang")
        assert "Lief " in text and ("🟡" in text or "🔴" in text)
        for erwartet in ("Klassifikator lehnte ab", "Vorbereitung vom Agenten entschieden",
                         "Prüfbefehl vom Agenten gewählt", "Auto-Mode"):
            assert erwartet in text, erwartet
        assert "G2** urteil-Grenze vom Agenten" not in text, "per Trockenlauf frei ≠ vom Agenten geklärt"
        report.write_text(text.replace("_Drei Sätze:", "MEINE PROSA. _Drei Sätze:"), encoding="utf-8")
        # Früher Abschluss ohne Härtung: verweigert, mit protokollierter Härtung: erlaubt.
        ledger = ns.load(root)
        ledger["hardening_rounds"] = 0
        ns.save(root, ledger)
        code, out = cn(root, "finish")
        assert code == 1 and "Härtungsrunde" in out, out
        assert cn(root, "haertung", "verify gefahren, Randfälle Feiertage")[0] == 0
        code, out = cn(root, "finish")
        assert code == 0, out
        final = report.read_text(encoding="utf-8")
        assert "MEINE PROSA" in final and "Ende: vom Agenten abgeschlossen" in final, final[:400]
        ledger = ns.load(root)
        assert ledger["status"] == "finished" and ledger["ende_grund"]
        assert any("A2" in (t.get("pakete") or []) for t in ledger["todos"]), "offenes A2 → To-Do"
        if os.environ.get("CN_TEST_REPORT"):  # Bericht zum Ansehen ablegen
            Path(os.environ["CN_TEST_REPORT"]).write_text(final, encoding="utf-8")

        # Kaputtes Ledger: Sicherung wird zurückgespielt statt still zu no-oppen.
        ns.ledger_path(root).write_text("{kaputt", encoding="utf-8")
        assert ns.load(root) is not None
        assert "zurückgespielt" in ns.journal_path(root).read_text(encoding="utf-8")

        assert cn_report.headline(ledger)


def main() -> int:
    ns.stdout_utf8()
    unit()
    flow()
    print("test_cn: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
