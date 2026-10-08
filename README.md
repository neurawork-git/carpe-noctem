# Carpe Noctem

> Autonome Nächte für Claude Code — vorbereitet entlang des einzigen Risikos, das eine Nacht
> nicht selbst lösen kann: **dass sie einen Menschen braucht.**

Ein Claude-Code-Plugin für mehrstündige, unbeaufsichtigte Läufe („Nachtschichten“). Abends
wird ein Plan gemeinsam vorbereitet, nachts arbeitet der Agent ihn ab, morgens liegt ein
Bericht da, der mit dem beginnt, was der Mensch jetzt tun muss.

**Risiko** heißt hier nicht technische Schwierigkeit — die löst die Nacht selbst. Risiko ist
die Wahrscheinlichkeit, dass ein Paket nachts einen Menschen braucht: eine fehlende
Permission, ein ablaufender Login, eine Freigabe, ein fachliches Urteil, ein externer Dienst.
Diese **Grenzen** werden in der Vorbereitung gesucht, probeweise berührt und geklärt, solange
der Mensch wach ist.

## Installation

```
/plugin marketplace add neurawork-git/carpe-noctem
/plugin install carpe-noctem@carpe-noctem
```

Danach Claude Code neu starten. Voraussetzungen: Python ≥ 3.10, Git (unter Windows mit Git-Bash).

## In drei Schritten

```
/carpe-noctem "bring die Umstellung aus docs/plan.md durch"
```

1. **Vorbereitung** — Pakete mit messbarem Fertig-Kriterium und Prüfbefehl, Pre-mortem
   („Es ist 7 Uhr, die Nacht ist gescheitert — warum?“), jede Grenze per Trockenlauf
   berühren, Fragen gebündelt klären, Restrisiko ansehen, dann `cn.py start` als Gate.
2. **Nacht** — ein Stop-Hook hält die Session am Laufen, Pakete laufen Abhängigkeiten zuerst
   und Risiko zuerst. Trifft ein Paket eine Grenze, kommt es auf die Wartebank, eine Meldung
   geht raus (md-Datei oder ntfy), der Agent arbeitet am nächsten Paket weiter.
3. **Morgen** — `REPORT.md` mit Ampel, Laufzeit, Abbruchgrund, „Jetzt du“, „Bitte prüfen“,
   Ergebnis-Tabelle und allen Grenzen der Nacht.

Die vollständige Dokumentation — Hooks, Zustand im Repo, Kanäle, Datenschutz, Abnahme, CLI —
steht in [`plugins/carpe-noctem/README.md`](plugins/carpe-noctem/README.md).

## Datenschutz in einem Satz

Ohne Konfiguration geht **nichts** nach außen; ntfy-Meldungen, eine Meldungsdatei außerhalb
des Repos und der optionale externe Richter sind jeweils ausdrücklich einzuschalten — was
dabei übertragen wird, steht im Plugin-README.

## Lizenz

Apache License 2.0 — siehe [`LICENSE`](LICENSE). Copyright 2026 Neurawork GmbH.
