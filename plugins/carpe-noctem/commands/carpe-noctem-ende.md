---
description: Carpe-Noctem-Nacht abschließen — Bericht mit „Jetzt du" oben, dann die Hooks freigeben
allowed-tools: Read, Write, Edit, Grep, Glob, Bash
---

# Carpe Noctem — Abschluss

`CN` = `python "${CLAUDE_PLUGIN_ROOT}/scripts/cn.py"`

1. `CN status` — Stand ansehen.
2. Offene Pakete ehrlich schließen: `item done` nur mit Abnahme, an einer Grenze
   `item wait`, sonst `item block --notiz "<was fehlt>"`.
3. Liegt `.claude/carpe-noctem/REPORT.md` schon ausgefüllt vor: **ergänzen, nicht
   überschreiben**. Sonst `CN report`.
4. Nur die **Kurzfassung** schreiben (drei Sätze). Kopf, Jetzt du, Ergebnis, Grenzen und
   Anhang kommen aus dem Ledger.
5. Arbeit committen (pushen nur, wenn mission.md es ausdrücklich erlaubt — sonst als To-Do), dann `CN finish` — zieht die
   maschinellen Blöcke aus dem Endstand nach und schickt die Schlussmeldung.

Soll die Nacht stattdessen abgebrochen werden: `CN abort --grund "…"`, danach trotzdem 3–5.
