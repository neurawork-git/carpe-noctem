---
description: Carpe Noctem — eine autonome Nacht vorbereiten (Grenzen jagen, solange du wach bist) und über das Gate starten
argument-hint: "[grober Auftrag oder Pfad zum Plan, optional]"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash, Skill, AskUserQuestion, TodoWrite
---

# Carpe Noctem — Vorbereitung

Auftrag des Menschen: $ARGUMENTS

**Lade zuerst den Skill `carpe-noctem-vorbereitung`** und arbeite ihn ab. Kern:

> Risiko ist die Wahrscheinlichkeit, dass ein Paket nachts einen Menschen braucht.
> Jede solche Grenze wird jetzt gefunden, berührt und geklärt — nicht um 2 Uhr entdeckt.

1. **Auftrag und Pakete** — Ziel, Nicht-Ziele, messbare Fertig-Kriterien, Prüfbefehle,
   Richter-Dateien (`geschuetzt:`). `mission.md` schreiben, `cn.py init`.
2. **Pre-mortem** — „Es ist 7 Uhr, die Nacht ist gescheitert. Warum?" (≥ 3 Szenarien).
3. **Grenzen finden und berühren** — je Paket den ersten Schritt, der etwas außerhalb des
   Arbeitsbaums anfasst, JETZT selbst ausführen. Permission-Dialoge sind jetzt erwünscht.
   `cn.py grenze add|probe|klaer|wartebank`.
4. **Fragen gebündelt** — alle Urteils- und Freigabefragen in einem Rutsch, Multiple Choice.
5. **`cn.py risiko`, `cn.py preflight --push-test`**, Freigabe des Menschen, dann `cn.py start`.

Erst nach `start` beginnt die Nacht; ab dann gilt der Skill `carpe-noctem-nacht`.
