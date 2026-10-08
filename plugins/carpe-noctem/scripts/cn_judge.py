"""Unabhängiger Richter: Jev (TypeSafe System One) urteilt über Kriterium ↔ Beleg.

Warum ein zweiter Richter neben dem Prüfbefehl: der Prüfbefehl misst, was er misst —
oft eine Nachbargröße („committet" statt „gelaufen"). Und wer baut, benotet zu milde
(ein bekanntes Muster: Agenten loben die eigene Arbeit zu bereitwillig). Jev ist ein anderes
Modell eines anderen Herstellers, führt keinen Dialog und liefert eine
Wahrscheinlichkeit statt eines Selbstlobs.

Muster: der Zitat-Prüfer aus der Jev-Doku (`citation_check`). Eine Choice-Frage
*belegt / widerlegt / sagt_nichts*, Auto-Accept ab 0,8, darunter geht das Paket als
„bitte prüfen" in den Morgenbericht.

Die Belege sammelt CODE, nicht der Agent: Fertig-Kriterium, Prüfbefehl, dessen
Ausgabe, `git diff --stat` seit Nachtbeginn. Die Prosa-Begründung des Agenten
kommt bewusst NICHT in den State — sonst bewertet der Richter die Selbstauskunft.

Datenschutz: der State (Kriterium, Prüfbefehl, dessen letzte Ausgabezeilen und
`git diff --stat` mit Dateipfaden) geht an `api.typesafe.ai`. Ob das für ein Projekt
zulässig ist (Verarbeitungsort, Auftragsverarbeitung), ist vorab zu klären — deshalb nur
mit `datenschutz: intern` in mission.md. Secret-Muster werden vor dem Versand maskiert.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import cn_state as ns

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("JEV_MODEL", "jev-1.13.0")  # gepinnt: die API kennt weder Seed noch Temperatur
TIMEOUT_S = 30
RETRIES = 3
AUTO_ACCEPT = 0.8

QUESTION = {"verdict": {
    "type": "choice",
    "instructions": ("A coding agent claims that the work package is done. Judge only from "
                     "`check_output` and `diff_stat` whether `criterion` is met. The check "
                     "command `check_command` was run by the harness, not by the agent."),
    "criteria": {
        "belegt": "the check output and the diff demonstrate that the criterion is met",
        "widerlegt": "the check output or the diff show that the criterion is NOT met",
        "sagt_nichts": "the evidence neither confirms nor refutes the criterion "
                       "(it measures something else, or is too thin)",
    },
}}

_SECRETS = [re.compile(p) for p in (
    r"(?<![A-Za-z0-9])sk-(?:proj-|ant-[a-z0-9]+-)?[A-Za-z0-9_]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"xox[baprs]-[A-Za-z0-9-]{10,}",
    r"ntn_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
    r"eyJhbGciOi[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]+)?",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
)]
_KEYVALUE = re.compile(r"(?i)((?:password|passwort|secret|token|api[_-]?key)[\"']?\s*[:=]\s*[\"']?)"
                       r"[^\s\"'`]{12,}")


def scrub(text: str) -> str:
    for p in _SECRETS:
        text = p.sub("[SECRET]", text)
    return _KEYVALUE.sub(r"\1[SECRET]", text)


class JudgeError(Exception):
    pass


def allowed(ledger: dict) -> str | None:
    """None, wenn Jev richten darf — sonst der Grund, warum nicht."""
    if (ledger.get("richter") or "") != "jev":
        return "kein externer Richter konfiguriert"
    if (ledger.get("datenschutz") or "").lower() != "intern":
        return ("Jev nur bei `datenschutz: intern` (Daten gehen an einen externen Dienst — "
                "Verarbeitungsort und Auftragsverarbeitung vorab klären)")
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        return "TYPESAFE_API_KEY fehlt"
    return None


def _diff_stat(root: Path, since: str | None) -> str:
    args = ["git", "-C", str(root), "diff", "--stat"]
    if since:
        args.append(since)
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=20, encoding="utf-8")
        return out.stdout.strip()[-2500:]
    except (OSError, subprocess.SubprocessError):
        return ""


def _ask(state: dict) -> dict:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    body = json.dumps({"model": MODEL, "state": state, "questions": QUESTION},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Authorization": "Bearer %s" % key, "Content-Type": "application/json"})
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))["answers"]["verdict"]
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 520, 529) and attempt < RETRIES:
                time.sleep(0.5 * 2 ** attempt)
                continue
            raise JudgeError("Jev HTTP %s: %s" % (exc.code, exc.read()[:200])) from exc
        except (TimeoutError, urllib.error.URLError, KeyError, ValueError) as exc:
            if attempt < RETRIES:
                time.sleep(0.5 * 2 ** attempt)
                continue
            raise JudgeError("Jev nicht erreichbar: %s" % exc) from exc
    raise JudgeError("Jev: keine Antwort")


def judge(root: Path, ledger: dict, item: dict, check_out: str) -> dict:
    """Urteil über ein Paket. Rückgabe: {verdict, confidence, probabilities, gate}.

    gate: `ok` (belegt ≥ 0,8) · `abgelehnt` (widerlegt ≥ 0,8) · `unsicher` (alles andere).
    """
    state = {
        "criterion": scrub(item.get("fertig_wenn", "")),
        "check_command": scrub(item.get("pruefbefehl", "")),
        "check_output": scrub(check_out or "(kein Prüfbefehl — keine Ausgabe)"),
        "diff_stat": scrub(_diff_stat(root, ledger.get("nacht_commit"))),
    }
    answer = _ask(state)
    verdict = answer.get("choice")
    conf = float(answer.get("confidence") or 0.0)
    if verdict == "belegt" and conf >= AUTO_ACCEPT:
        gate = "ok"
    elif verdict == "widerlegt" and conf >= AUTO_ACCEPT:
        gate = "abgelehnt"
    else:
        gate = "unsicher"
    result = {"verdict": verdict, "confidence": round(conf, 3),
              "probabilities": answer.get("probabilities"), "gate": gate,
              "modell": MODEL, "zeit": ns.iso(ns.now())}
    # Rohprotokoll der Urteile — ohne State, der bleibt im Repo.
    with (ns.cn_dir(root) / "richter.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"paket": item.get("id"), **result}, ensure_ascii=False) + "\n")
    return result
