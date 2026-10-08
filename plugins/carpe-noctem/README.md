# Carpe Noctem

> Autonome Nächte für Claude Code — vorbereitet entlang des einzigen Risikos, das eine
> Nacht nicht selbst lösen kann: **dass sie einen Menschen braucht.**

Ideen aus dem Feld: Karpathys autoresearch,
der Ralph-Loop, Claude Codes `/goal`, Jamon Holmgrens „Night Shift“, Anthropics Beiträge zu
Long-Running-Harnesses und der ImpossibleBench-Benchmark.

## Die Idee

Risiko heißt hier **nicht** technische Schwierigkeit. Die löst die Nacht selbst. Risiko ist
die Wahrscheinlichkeit, dass ein Paket einen Menschen braucht: eine fehlende Permission, ein
ablaufender Login, eine Freigabe, ein fachliches Urteil, ein externer Dienst, etwas
Irreversibles. Typische Gründe, warum autonome Nächte scheitern:

| Fehlschlag | Folge |
|---|---|
| Pakete hängen an einem manuellen Start | die Nacht bleibt großteils ungenutzt |
| ein Login läuft nachts ab, ein Dialog wartet auf Bestätigung | die Session steht bis zum Morgen |
| das Zustandsfile ist halb geschrieben | Hooks laufen still ins Leere, kein Bericht |
| die To-Dos stehen weit unten im Bericht | was der Mensch tun muss, wird übersehen |

Daraus folgen drei Bausteine:

1. **Vorbereitung als Jagd auf Grenzen**, solange der Mensch wach ist: Pre-mortem → jede
   Grenze per Trockenlauf selbst berühren → Fragen gebündelt klären → Restrisiko → Gate.
2. **Die Nacht arbeitet Risiko zuerst** und hängt Pakete an einer Grenze auf die
   **Wartebank** statt aufzuhören: Meldung über md-Datei oder ntfy-Push, Antwort über die Inbox, Wache bis zur Deadline.
3. **Der Morgen ist das Produkt**: Ampel, tatsächliche Laufzeit, Abbruchgrund und
   „Jetzt du" ganz oben; Abnahme durch Prüfbefehl, geschützte Richter-Dateien und optional
   einen unabhängigen Richter (Jev).

## Änderungen in 0.3 und 0.4 (aus dem ersten Praxislauf)

| Thema | Verhalten |
|---|---|
| Block-Cap | Das Gate liest ihn aus Umgebungsvariable, Repo- und User-Settings; Claude-Settings setzt der Mensch |
| Auto-Mode | Der Stop-Hook liest Klassifikator-Ablehnungen aus dem Transkript → Grenze, Meldung, „Bitte prüfen“; Regel: dasselbe Ziel nie über ein anderes Werkzeug erzwingen |
| Herkunft von Entscheidungen | `decision --quelle agent|mensch|inbox` (Default agent); Urteils-Grenzen nur mit `--durch` klärbar |
| Reihenfolge | `nach: A1` je Paket, topologisch sortiert, Risiko als Gleichstand-Brecher; `item start` prüft Vorgänger |
| Parallelarbeit | mehrere `doing` mit `--agent`, `progress` verlangt dann `--id` |
| Nachts angelegte Pakete | `richter_default:` in mission.md; eigener Prüfbefehl → „Bitte prüfen“ |
| Dringendes | `todo --prio P1` meldet sich sofort |
| Früher Abschluss | `finish` vor der Deadline verlangt protokollierte Härtung (`cn.py haertung`) oder `--grund` |
| Bericht | „Bitte prüfen“ zählt alle Fälle oben; Kopf zeigt Stop-Hook-Fortsetzungen, Härtung, Auto-Mode |
| Meldekanäle (0.4) | `md` und/oder `ntfy`, siehe unten |

## Ablauf

```
/carpe-noctem "bring die Auth-Umstellung aus docs/plan.md durch"
  Vorbereitung  mission.md → cn.py init
                Pre-mortem          cn.py premortem "…"
                Grenzen berühren    cn.py grenze add|probe|klaer|wartebank
                Fragen gebündelt    AskUserQuestion (jetzt erwünscht)
                Restrisiko + Gate   cn.py risiko · cn.py preflight --push-test · cn.py start
  Nacht         Stop-Hook treibt, Risiko zuerst, eine Runde = ein Paket
                Grenze getroffen    cn.py item wait … → Meldung, nächstes Paket
                nur noch Wartende   cn.py wache (Inbox + Trockenläufe, ≤ 9 min)
  Morgen        .claude/carpe-noctem/REPORT.md
/carpe-noctem-status · /carpe-noctem-ende
```

## Hooks

| Hook | Rolle |
|---|---|
| **Stop** | Motor. Phasen Arbeit → Härtung → Wache → Abschluss. Grund wird bei jedem Stop neu aus dem Ledger gebaut, neue Nachrichten des Menschen stehen oben. Ausstiege: Deadline, `max_continuations`, Leerlauf. `ende_grund` landet im Ledger. |
| **PreToolUse** `AskUserQuestion\|ExitPlanMode` | Rückfrage-Sperre (auch in Subagenten), mit Ersatzverfahren; jede Sperre wird gezählt. |
| **PreToolUse** `Edit\|Write\|MultiEdit\|NotebookEdit` | Richter-Dateien (`geschuetzt:`) sind nachts schreibgeschützt. |
| **PermissionRequest** | Permission-Dialog nachts: ablehnen, als Grenze protokollieren, Meldung. Greift in Default/acceptEdits — **nicht im Auto-Mode**; dort liest der Stop-Hook die Klassifikator-Ablehnungen aus dem Transkript (`transcript_path`). |
| **SessionStart** | Lagebild nach Neustart/Kompaktierung; Hinweis auf laufende Vorbereitung oder unterbrochene Nacht. |
| **PreCompact** | Riss im Ledger markieren. |
| **SessionEnd** | Abriss → `interrupted`, Notbericht, Meldung. |

Alle Hooks feuern global, tun aber nichts, solange keine Nacht (`status: active`) an die
Session gebunden ist. In der Vorbereitung sind sie still. Hook-Fehler landen in
`hook-fehler.log` und als Meldung — still ist nichts mehr.

## Zustand im Ziel-Repo

`<repo>/.claude/carpe-noctem/`:

| Datei | Inhalt |
|---|---|
| `mission.md` | Auftrag, Pakete, Grenzen, Pre-mortem, Verbote, Backlog (Format im Skill `carpe-noctem-vorbereitung`) |
| `ledger.json` (+ `.bak`) | Maschinenzustand; nur über `cn.py` anfassen. Kaputtes Ledger → Sicherung wird zurückgespielt |
| `journal.md` | Append-only-Protokoll |
| `inbox.md` | Nachrichten an die laufende Nacht (`- …` je Zeile) |
| `meldungen.md` | Meldungen der Nacht (Kanal `md`, sofern kein eigener `kanal_md:`) |
| `REPORT.md` | Morgenbericht |
| `richter.jsonl` · `hook-fehler.log` · `prompt.md` · `rounds/` | Richter-Urteile, Hook-Fehler, Rundenprompt und -logs für `ralph.py` |

Laufzeitzustand im Ziel-Repo ignorieren:

```gitignore
.claude/carpe-noctem/ledger.json*
.claude/carpe-noctem/journal.md
.claude/carpe-noctem/inbox.md
.claude/carpe-noctem/meldungen.md
.claude/carpe-noctem/prompt.md
.claude/carpe-noctem/rounds/
.claude/carpe-noctem/*.log
.claude/carpe-noctem/richter.jsonl
```

## Kanäle zum Menschen

Meldungen (Grenze nachts getroffen, P1-To-Do, Klassifikator-Sperre, Hook-Fehler, Abbruch,
Schichtende) gehen über wählbare Kanäle:

| Kanal | hinaus | herein |
|---|---|---|
| `md` | Abschnitt je Meldung, angehängt an eine Markdown-Datei — Default `.claude/carpe-noctem/meldungen.md`, mit `kanal_md:` beliebiger Pfad (relativ zum Repo oder absolut, z. B. synchronisierter Ordner, Obsidian-Vault) | Zeile `- …` in `.claude/carpe-noctem/inbox.md` |
| `ntfy` | Push aufs Handy (`CARPE_NOCTEM_NTFY` = Topic-URL, optional `CARPE_NOCTEM_NTFY_TOKEN`) | Nachricht an `<topic>-in` — landet ebenfalls in `inbox.md` |

```yaml
# mission.md
kanal: md, ntfy                 # oder nur md / nur ntfy
kanal_md: ~/OneDrive/Nacht/meldungen.md
```

`CARPE_NOCTEM_KANAL` (z. B. `md`) und `CARPE_NOCTEM_MD` überschreiben die Mission. Ohne Angabe:
`md` immer, `ntfy` zusätzlich, sobald `CARPE_NOCTEM_NTFY` gesetzt ist.

Ob die Nacht dich **erreicht**, prüft das Gate: ntfy zählt, `md` nur, wenn bewusst gewählt
(`kanal:`/`kanal_md:`) — die Default-Datei im Repo liest nachts niemand. Nur ein erreichbarer
Kanal (oder ein Trockenlauf, der von selbst grün werden kann) hält wartende Pakete in der Wache;
sonst endet die Nacht, wenn nur noch Wartendes übrig ist. Eine Antwort wie „G3 erledigt“ reicht —
die Wache fährt den Trockenlauf, das Paket läuft weiter. `cn.py preflight --push-test` schickt
eine Testmeldung über alle aktiven Kanäle.

## Datenschutz: was das Plugin nach außen gibt

Ohne Konfiguration **nichts**: alle Meldungen landen in einer Datei im Repo, es gibt keinen
Netzzugriff. Nach außen geht nur, was ausdrücklich eingeschaltet wird:

| Weg | was übertragen wird | Voraussetzung |
|---|---|---|
| `ntfy` | Meldungstexte: Missionstitel, Paket-IDs und Notizen, To-Do-Texte, Auszüge abgelehnter Befehle oder Dateipfade (bis 160 Zeichen), letzte Zeile eines Hook-Fehlers — an den konfigurierten ntfy-Server | `kanal: ntfy` bzw. `CARPE_NOCTEM_NTFY` |
| `md` außerhalb des Repos | dieselben Meldungstexte in eine Datei an einem selbst gewählten Ort (z. B. ein Cloud-synchronisierter Ordner) — damit verlassen Projektinhalte den Repo-Rahmen | `kanal_md:` mit Pfad außerhalb des Repos |
| Jev (TypeSafe) | Fertig-Kriterium, Prüfbefehl, dessen letzte Ausgabezeilen und `git diff --stat` (Dateipfade) an `api.typesafe.ai` | `richter: jev` **und** `datenschutz: intern` **und** `TYPESAFE_API_KEY` |

Secret-Muster (API-Keys, Tokens, `password=…`) werden vor jedem Versand maskiert; andere
Inhalte (Namen, Pfade, Hostnamen) nicht.

**ntfy sicher betreiben:** einen eigenen oder zugriffsgeschützten Server mit
`CARPE_NOCTEM_NTFY_TOKEN` verwenden. Auf einem öffentlichen Server ist ein Topic nur durch
seinen Namen geschützt — wer ihn kennt, liest die Meldungen mit. Der Rückkanal `<topic>-in`
wird als **Anweisung des Menschen** an den Agenten weitergegeben; er ist nur sicher, wenn
ausschließlich du dorthin schreiben kannst.

**Jev:** Ob die Übertragung an einen externen Dienst für ein Projekt zulässig ist
(Verarbeitungsort, Auftragsverarbeitung), vor dem Einschalten klären.

## Abnahme

1. **Prüfbefehl** (`prüfen:` in mission.md) läuft in Git-Bash — nie cmd.exe
   (`CARPE_NOCTEM_BASH` überschreibt den Pfad).
2. **Richter-Dateien** (`geschuetzt: tests/**, …`): SHA256 bei `start`; jede Änderung
   verweigert die Abnahme, der Edit-Hook blockt schon den Versuch. Vorbild: Karpathys
   read-only `prepare.py`, ImpossibleBench (Read-only-Tests stoppen Test-Manipulation).
3. **Jev** (optional, `richter: jev` + `datenschutz: intern` + `TYPESAFE_API_KEY`):
   Choice *belegt / widerlegt / sagt_nichts* über Kriterium, Prüfbefehl-Ausgabe und
   `git diff --stat` — nie über die Prosa des Agenten. Ab 0,8 belegt → ok, ab 0,8
   widerlegt → abgelehnt, sonst „bitte prüfen" im Bericht. Modell gepinnt (`JEV_MODEL`,
   Default `jev-1.13.0`). Was dabei übertragen wird: Abschnitt „Datenschutz“.

## Betriebsarten

**Interaktiv** (Default): eine Session, der Stop-Hook hält sie am Leben. Braucht
`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` (z. B. 200) als Umgebungsvariable oder unter `env` in den
Repo- bzw. User-Settings — sonst beendet Claude Code die Nacht nach 8 Blocks (das Gate prüft das).

**Rundenmodus** (`start --headless`, dann `python scripts/ralph.py --rounds 40`): frische
`claude -p`-Runden mit `CARPE_NOCTEM_ROUND=1`, Nutzungslimit-Wartelogik, Notbericht und Meldung
am Ende. Im Print-Modus werden nicht freigegebene Werkzeuge verweigert, nicht gefragt.

## CLI

```
Vorbereitung   init · premortem "…" [--grenze G] · grenze add <P> --art … --was … [--probe …]
               grenze probe [G] · grenze klaer <G> --wie … [--durch mensch|agent]
               grenze wartebank <G> --ersatz … · risiko · preflight [--push-test]
               start [--deadline] [--headless] [--force]
Nacht          status · item add [--nach A1] [--pruefbefehl] · item start <ID> [--agent name]
               item done|block|drop|wait · progress "…" [--id] · verify · haertung "…" [--befund]
               wache [--minuten] · inbox · decision "…" --wahl --warum [--reversibel] [--ersetzt E]
               [--quelle agent|mensch|inbox] · todo "…" --warum --schritt [--prio] [--paket A1,A2]
               frage · note
Abschluss      report [--stdout|--force] · finish [--grund] · abort · resume
```

mission.md-Frontmatter: `titel`, `quelle`, `deadline`, `geschuetzt`, `richter_default`,
`kanal`, `kanal_md`, `datenschutz`, `richter`, `max_continuations`, `hardening_rounds_max`. Je Paket eingerückt:
`prüfen:` und `nach:`.

## Tests

```
python scripts/test_cn.py
```

Parser, Restrisiko, Schreibschutz und ein ganzer Lauf in einem Wegwerf-Git-Repo
(Gate, Abnahme, Richter-Drift, Rückfrage- und Permission-Sperre, Inbox, Wartebank, Wache,
Bericht, finish, Ledger-Wiederherstellung). Kein Netz.

## Installation

Über den öffentlichen Marketplace [`neurawork-git/carpe-noctem`](https://github.com/neurawork-git/carpe-noctem):

```
/plugin marketplace add neurawork-git/carpe-noctem
/plugin install carpe-noctem@carpe-noctem
```

Danach Claude Code neu starten. `update` vergleicht die **Version** in
`.claude-plugin/plugin.json` — nach jeder Änderung hochsetzen. Voraussetzungen: Python ≥ 3.10,
Git (unter Windows mit Git-Bash).

## Grenzen des Plugins

- Im Auto-Mode werden Klassifikator-Ablehnungen erst beim nächsten Stop aus dem Transkript gelesen,
  nicht im Moment der Ablehnung; und ob der Agent das Ziel danach auf anderem Weg erreicht hat,
  kann nur der Mensch im Bericht prüfen.
- Ob die Nacht nachts tatsächlich Textfragen stellt (statt des Tools), ist nicht abgefangen;
  der Stop-Hook schickt sie nur weiter.
- Ein Jev-Urteil ist so gut wie der Beleg: es prüft Kriterium ↔ Ausgabe, nicht den Code.

## Lizenz

Apache License 2.0 — siehe `LICENSE`. Copyright 2026 Neurawork GmbH.
