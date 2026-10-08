---
name: carpe-noctem-vorbereitung
description: "Vorbereitung einer autonomen Carpe-Noctem-Nacht — Auftrag in messbare Pakete zerlegen, Pre-mortem, jede Stelle finden, an der die Nacht einen Menschen bräuchte (Permission, Login, Freigabe, Urteil, externer Dienst), sie per Trockenlauf berühren und klären, solange der Mensch wach ist, Fragen gebündelt stellen, nach Restrisiko ordnen und erst über das Gate starten. Zu verwenden, bevor ein Agent stundenlang unbeaufsichtigt arbeiten soll. Triggert bei: Carpe Noctem, Nachtschicht, über Nacht laufen lassen, autonom bis morgen, arbeite das alleine ab, mission.md, unbeaufsichtigt, Ralph-Loop."
---

# Carpe Noctem — Vorbereitung

**Risiko heißt hier nicht „technisch schwierig", sondern: die Wahrscheinlichkeit, dass ein
Paket nachts einen Menschen braucht.** Technische Probleme löst die Nacht selbst. Einen
Menschen findet sie nicht — und genau daran scheitern autonome Nächte typischerweise:
Pakete hängen an einem manuellen Start, ein Login läuft mitten in der Nacht ab, eine
Session hängt an einem Bestätigungsdialog.

Die Vorbereitung ist deshalb kein Formular, sondern eine **Jagd auf Grenzen**, solange der
Mensch wach ist. Fünf Schritte, in dieser Reihenfolge. Die Hooks sind in dieser Phase still,
Rückfragen sind erwünscht — gebündelt, als Multiple Choice.

`CN` steht unten für `python "${CLAUDE_PLUGIN_ROOT}/scripts/cn.py"`.

## 1. Auftrag und Pakete

- **Ziel** — woran erkennt der Mensch morgens, dass die Nacht etwas wert war?
- **Nicht-Ziele** — was ausdrücklich nicht angefasst wird.
- **Machbarkeit** — passt es in die Stunden? Sonst den Ausschnitt vorschlagen, der fertig wird.
- **Pakete** mit messbarem Fertig-Kriterium und möglichst einem `prüfen:`-Befehl (Exit 0 nur
  bei Erfüllung, ungepiped). Ein Paket ≈ eine Runde.
- **Abhängigkeiten** als `nach: A1` unter dem Paket. Die Nacht sortiert Vorgänger zuerst und
  unter Gleichrangigen nach Risiko — reine Risiko-Sortierung stellt sonst ein Paket vor das
  Fundament, gegen das es geprüft wird.
- **Pushen** ist nachts verboten, solange die Mission es nicht ausdrücklich erlaubt. Ist eine
  CI der Richter, muss gepusht werden — dann im Auftrag festhalten, wohin (Branch) und dass der
  Mensch das freigibt, und den Push als Grenze (`freigabe`) in der Vorbereitung klären.
- **Default-Richter** (`richter_default:` im Frontmatter): der Prüfbefehl für Pakete, die die
  Nacht selbst anlegt. Ohne ihn wählt der Agent seinen Richter selbst.
- **Feature-Pakete** brauchen einen Test je Funktion im Kriterium. „CI grün“ misst Kompilieren
  und vorhandene Tests, nicht die aufgezählten Funktionen.
- **Richter-Dateien** — welche Dateien entscheiden, ob ein Paket fertig ist (Tests,
  Prüfskripte, Fixtures)? Die kommen nach `geschuetzt:` und sind nachts schreibgeschützt.
  Gibt es für ein Paket noch keinen Test: **jetzt** schreiben (lassen), rot sehen, schützen —
  Red/Green beginnt in der Vorbereitung, nicht in der Nacht. Im geschützten Bereich darf
  die Nacht auch keine neuen Dateien anlegen. Soll sie selbst Tests schreiben, schütze
  gezielt die Richter-Dateien (`tests/test_auth.py`), nicht pauschal `tests/**`.

Ist ein Planning-Doc die Quelle (PRP, `docs/plan.md`, Notion, Issue): ganz lesen, übersetzen
statt importieren, Nummerierung übernehmen (`P1`…), Fertig-Kriterien ergänzen, `quelle:`
eintragen, dem Menschen das **Delta** zeigen.

## 2. Pre-mortem

Stell dir vor: **Es ist 7 Uhr, die Nacht ist gescheitert. Warum?** Mindestens drei
Szenarien, konkret, je Paket gedacht. Studien zum „prospektiven Zurückblicken“ (die
Grundlage von Gary Kleins Pre-mortem) berichten, dass man so deutlich mehr Ursachen findet
als mit der Frage „was könnte schiefgehen?“.

Typische Szenarien aus echten Nächten:
- Paket hing an einem Start/Merge/Deploy, den nur der Mensch auslöst.
- Token/Login lief mitten in der Nacht ab (`az`, `gh`, `claude` selbst).
- Ein Befehl stand nicht in der Allow-Liste → Permission-Dialog.
- Ein fachliches Urteil (Datenmodell, Benennung, Kundenwunsch) wurde stellvertretend falsch getroffen.
- Ein externer Dienst (CI, API, Kundensystem) war nicht erreichbar oder rate-limitiert.
- Der Prüfbefehl maß eine Nachbargröße („committet" statt „läuft").

`CN premortem "<Szenario>" [--grenze G3]`

## 3. Grenzen finden und berühren — der Trockenlauf

Für **jedes** Paket: Was ist der erste Schritt, der etwas außerhalb des eigenen Arbeitsbaums
anfasst — ein Login, ein externer Dienst, ein Befehl außerhalb der Allow-Liste, ein Push,
eine Freigabe? Das ist eine **Grenze**.

```
CN grenze add A3 --art login --was "Azure-CLI-Token für den Blob-Upload" --probe "az account show"
```

Arten: `permission` · `login` · `extern` (je Gewicht 2) · `urteil` · `freigabe` · `irreversibel` (je 3).

Dann **berühre jede Grenze jetzt selbst**, mit deinen eigenen Werkzeugen, so wie die Nacht
es tun wird — den ersten echten Schritt, nicht eine Beschreibung davon:

- Fragt Claude Code dabei nach einer Permission: **genau das ist der Zweck.** Der Mensch
  ist wach und kann „immer erlauben" wählen. Nachts würde derselbe Dialog die Session
  anhalten (oder, mit Carpe Noctem, abgelehnt werden).
- `CN grenze probe` fährt alle Trockenlauf-Befehle; ein Login-Probe prüft auch die
  **Laufzeit**: reicht das Token bis nach der Deadline?
- Was nur der Mensch kann (Freigabe, Urteil), wird **jetzt gefragt** — nicht nachts erraten.

Jede Grenze endet in einem von zwei Zuständen:

- **geklärt** — `CN grenze klaer G3 --wie "Allow-Regel Bash(az storage:*) ergänzt, Token bis 09:12"`
  (mit Trockenlauf: er muss frisch grün sein, sonst lässt das Gate nicht starten).
  Bei `urteil`/`freigabe`/`irreversibel` ist `--durch mensch|agent` Pflicht. `agent` heißt:
  du hast es aus einer Regel abgeleitet — erlaubt, steht aber morgen unter „Bitte prüfen“.
  Ist der Mensch da, frag ihn lieber.
- **Wartebank** — bewusst akzeptiert, weil es erst nachts entsteht (z. B. CI-Ergebnis, Review):
  `CN grenze wartebank G5 --ersatz "P7 vorbereiten bis zum PR, danach Härtungs-Backlog"`.
  Die Nacht meldet sich per Meldung (md/ntfy), wenn sie dort ankommt, und arbeitet derweil am Ersatz.

## 4. Fragen gebündelt klären

Sammle alle `urteil`-/`freigabe`-Grenzen und offenen Annahmen und stell sie **in einem
Rutsch** (`AskUserQuestion`, bis zu vier Fragen je Aufruf, Multiple Choice mit Empfehlung).
Jede Antwort wird eine Entscheidung mit Quelle „Mensch":

`CN decision "<Frage>" --wahl "<Antwort>" --warum "Vorgabe in der Vorbereitung" --quelle mensch`

`--quelle mensch` NUR für echte Antworten des Menschen — was du selbst ableitest, bleibt
`--quelle agent` (Default). Danach die zugehörige Grenze klären (`--durch mensch`). Was der Mensch nicht entscheiden will, geht auf die
Wartebank — mit Ersatzarbeit.

## 5. Restrisiko, Reihenfolge, Gate

```
CN risiko
```

zeigt je Paket das Restrisiko (offene Grenzen doppelt, Wartebank einfach, kein Prüfbefehl
+1), das Pre-mortem und den Gate-Stand. **Ziel ist Restrisiko 0 für alles außer der
bewusst gewählten Wartebank.**

Die Nacht läuft **Risiko zuerst**: was trotz Vorbereitung am ehesten einen Menschen braucht,
kommt an den Anfang. Dann trifft es die Grenze um 23:30, nicht um 4 Uhr — die Meldung erreicht
vielleicht noch jemanden, und die Wartezeit überlappt mit der übrigen Arbeit.

Vor dem Start außerdem:

```
CN preflight --push-test
```

- `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` gesetzt — als Umgebungsvariable, in Repo- oder User-Settings
  (sonst endet die Nacht nach 8 Blocks). Fehlt er, setzt ihn **der Mensch**: Claude-Settings
  schreibt der Agent nicht (der Klassifikator blockt das als Self-Modification — und es per
  Write-Werkzeug zu umgehen, ist derselbe Verstoß).
- **Kanal zum Menschen** gewählt (`kanal:` in mission.md): `ntfy` (Push, braucht
  `CARPE_NOCTEM_NTFY`) und/oder `md` (Meldungsdatei; mit `kanal_md:` an einem Ort, den der
  Mensch nachts liest — die Default-Datei im Repo erreicht niemanden). Frag den Menschen,
  welcher Kanal ihn erreicht, und teste ihn mit `CN preflight --push-test`.
- Permission-Modus Default oder acceptEdits (dann lehnt der Hook nachts ab und protokolliert;
  im Auto-Mode lehnt der Klassifikator **still** ab). Niemals einen Bypass vorschlagen.
- Richter: `richter: jev` nur mit `datenschutz: intern` und gesetztem `TYPESAFE_API_KEY`.
  Dabei gehen Kriterium, Prüfausgabe und `git diff --stat` an einen externen Dienst —
  Verarbeitungsort und Auftragsverarbeitung vorab klären. Sonst: Prüfbefehl + Schreibschutz.

Zeig dem Menschen `CN risiko` und die `mission.md` — **das ist die letzte Freigabe**. Dann:

```
CN start
```

Das Gate verweigert den Start, solange Grenzen offen sind, Trockenläufe nicht frisch grün,
das Pre-mortem dünn oder der Block-Cap fehlt. `--force` übergeht es — die übergangenen
Punkte stehen dann oben im Morgenbericht. Danach gilt `carpe-noctem-nacht`.

## mission.md

Nach `<repo>/.claude/carpe-noctem/mission.md`, dann `CN init` (liest sie ein; Grenzen und
Pre-mortem können auch per CLI dazukommen):

```markdown
---
titel: Kurzer Name der Nacht
quelle: docs/plan-auth-umstellung.md
deadline: 07:00
geschuetzt: tests/gates/**, scripts/check_*.py
richter_default: bash tests/gates/ci-gruen.sh   # Prüfbefehl für nachts angelegte Pakete
kanal: md, ntfy              # Meldungen: md-Datei und/oder ntfy-Push
kanal_md: ~/OneDrive/Nacht/meldungen.md          # optional; Default .claude/carpe-noctem/meldungen.md
datenschutz: intern          # nur dann darf ein externer Richter (Jev) urteilen
richter: jev                 # optional
max_continuations: 200
hardening_rounds_max: 3
---

# Auftrag
Zwei bis fünf Sätze: was erreicht werden soll und warum.

# Nicht-Ziele
- …

# Arbeitspakete
- [ ] A1 — Titel :: fertig wenn: <messbares Kriterium, darf mehrzeilig sein>
      prüfen: pytest tests/test_auth.py -q
- [ ] A2 — Titel :: fertig wenn: …
      nach: A1
      prüfen: bash tests/gates/ci-gruen.sh

# Grenzen
- G1 [A1] login: Azure-CLI-Token für den Upload
      probe: az account show
- G2 [A3] urteil: Feldname für den Kundenschlüssel

# Pre-mortem
- Token läuft nachts ab → G1
- CI-Lauf braucht manuelle Freigabe

# Verbotene Aktionen
- Externe Kommunikation, Deploy, Löschen, --force

# Härtungs-Backlog
- Randfälle, Doku-Drift
```

## Was die Nacht nicht aufhebt

Kundenserver bleiben lesend. Senden, Deployen, Löschen, Geld, Verträge bleiben beim
Menschen — nachts bis zum Gate vorbereitet und als To-Do übergeben.
