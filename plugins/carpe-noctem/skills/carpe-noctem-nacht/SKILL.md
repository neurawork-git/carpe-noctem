---
name: carpe-noctem-nacht
description: Arbeitsweise während einer laufenden Carpe-Noctem-Nacht — eine Runde ein Paket in Risiko-Reihenfolge, Stand aus dem Ledger, an Grenzen auf die Wartebank statt blockieren, Nachrichten des Menschen aus der Inbox umsetzen, Abnahme über Prüfbefehl und Richter statt Selbstlob, Wache statt Feierabend, Übergabe mit „Jetzt du“ oben. Zu verwenden, sobald eine Nacht aktiv ist oder der Stop-Hook zum Weiterarbeiten auffordert. Triggert bei: Carpe Noctem aktiv, Nachtschicht aktiv, Stop-Hook blockt, Rückfrage gesperrt, Permission abgelehnt, Wache, Schichtende, cn.py.
---

# Carpe Noctem — die Nacht

Es ist niemand da — aber jemand ist **erreichbar**. Was du entscheidest, muss morgen
nachvollziehbar und umkehrbar sein; was nur ein Mensch kann, meldest du sofort und
arbeitest woanders weiter.

`CN` = `python "${CLAUDE_PLUGIN_ROOT}/scripts/cn.py"`.

**Erst prüfen, ob überhaupt eine Nacht läuft:** meldet `CN status` „keine Schicht“ oder steht
sie auf `vorbereitung`, gilt der Skill `carpe-noctem-vorbereitung` — eine Nacht ohne Mission
und Gate gibt es nicht.

## Parallel arbeiten

Arbeitest du als Orchestrator mit Subagenten, melde **jedes** vergebene Paket an:
`CN item start <ID> --agent <name>` (mehrere `doing` sind erlaubt), Zwischenstände mit
`CN progress "…" --id <ID>`. Sonst zeigt das Ledger nur einen Bruchteil der echten
Parallelarbeit, und nach einer Kompaktierung ist die Koordination verloren.
`item start` verweigert Pakete, deren Vorgänger (`nach:`) noch offen sind.

## Die Runde

Eine Runde = **genau ein Paket**, das oberste offene (die Reihenfolge ist nach Risiko sortiert).

1. **Stand lesen** — `CN status`. Steht eine **NACHRICHT VOM MENSCHEN** im Fortsetzungsgrund,
   hat sie Vorrang: umsetzen, oder begründet als `decision` festhalten, warum nicht.
2. `CN item start <ID>`, bauen.
3. **Selbst widerlegen** — welcher Fall bricht es? Du hast Zeit, dein Ergebnis anzugreifen.
4. **Unabhängig gegenlesen** — ein unabhängiger Review-Subagent (z. B. ein eigens definierter `reviewer`) bekommt nur Diff + Fertig-Kriterium,
   nicht deine Begründung. Wer baut, benotet nicht.
5. **Abnahme** — `CN item done <ID> --beleg "<kurz>"`. Das fährt den Prüfbefehl (Git-Bash),
   prüft, dass keine Richter-Datei verändert ist, und — wenn konfiguriert — fragt Jev, ob der
   Beleg das Kriterium trägt. Abgelehnt heißt: nachbessern, nicht wegargumentieren.
6. Committen. Pushen nur, wenn mission.md es ausdrücklich erlaubt (etwa weil die CI der Richter ist) — sonst als To-Do für den Menschen. Zwischendurch nach jedem Schritt:
   `CN progress "<was jetzt gilt>" --id <ID>`.

## An einer Grenze

Eine Grenze ist alles, wofür es einen Menschen braucht: fehlende Permission, abgelaufener
Login, Freigabe, fachliches Urteil, externer Dienst, Irreversibles.

**Nicht blockieren, nicht raten, nicht umgehen.** Bis zur Grenze vorbereiten (Entwurf,
Befehl, Branch, PR), dann:

```
CN item wait <ID> --grenze G3 --notiz "Bitte az login; danach läuft der Upload von selbst"
CN item wait <ID> --art urteil --notiz "Feldname customer_id vs. account_id — beide Varianten liegen auf Branches"
```

Mit `--probe "<befehl>"` gibst du einen Trockenlauf mit, der grün wird, sobald es weitergeht —
dann gibt die Wache das Paket von selbst frei. Der Befehl schickt eine Meldung (md/ntfy); du nimmst das
nächste Paket.

Ein **Permission-Dialog** wird nachts automatisch abgelehnt und als Grenze protokolliert; im
Auto-Mode liest der Stop-Hook die Ablehnungen des Klassifikators aus dem Transkript. Gibt es
einen *freigegebenen* Weg zum selben Ziel, nimm ihn; sonst `item wait`. **Dasselbe Ziel über
ein anderes Werkzeug zu erzwingen, ist derselbe Verstoß** — die Klassifikator-Meldung „you may
attempt … using other tools“ gilt nicht für Ziele, die abgelehnt wurden, weil sie selbst
unzulässig sind (Claude-Settings schreiben, Self-Modification, Kundensysteme).

**Richter-Dateien** (Tests, Prüfskripte unter `geschuetzt:`) sind schreibgeschützt. Ist ein
Test wirklich falsch: `CN todo … --prio P1` mit der vorgeschlagenen Änderung und das Paket an
die Grenze (`--art urteil`).

## Statt zu fragen

`AskUserQuestion` ist gesperrt (auch in Subagenten). Reihenfolge:

1. Selbst nachsehen — mission.md, README/CLAUDE.md, Code, vorhandene Projektdoku bzw. Wissensbasis.
2. Umsetzungs- oder Geschmacksfrage → reversibel wählen, ggf. beide Varianten bauen:
   `CN decision "<Frage>" --wahl "…" --warum "…" --reversibel "<wie zurück>"`.
   Überholt eine spätere Entscheidung eine frühere: `--ersetzt E2`.
3. Braucht es einen Menschen → das ist eine Grenze, siehe oben.
4. Weder noch → `CN frage "<Frage samt Kontext>"`.

## Wache statt Feierabend

Sind nur noch wartende Pakete übrig und die Härtungsrunden durch, fordert der Stop-Hook eine
**Wache**: `CN wache` wartet bis zu 9 Minuten, holt Nachrichten vom Handy (ntfy-Topic mit
`-in`, oder `inbox.md`) und fährt die Trockenläufe der Grenzen nach. Kommt etwas, kehrt sie
sofort zurück — „G3 erledigt" heißt: Trockenlauf fahren, Paket aufnehmen. Ohne Ereignis
einfach erneut anhalten. **Keine Arbeit erfinden, um Zeit zu füllen.**

## Neue Pakete

Was du nachts entdeckst, wird ein Paket — mit Fertig-Kriterium, das du **vor** der Arbeit
formulierst (nicht „9 Befunde behoben“ nach dem Befund). Den Prüfbefehl liefert
`richter_default` aus der Mission; ein eigener `--pruefbefehl` (z. B. eine Job-Auswahl, die
einen roten Job auslässt) ist erlaubt, steht aber morgen unter „Bitte prüfen“.

## Härtungsrunden

Keine offenen Pakete, aber Restzeit: `CN verify` (alle Abnahmen frisch nachfahren),
wartende Pakete weiter bis zur Grenze vorbereiten, Randfälle, Tests, Doku-Drift,
Härtungs-Backlog. Befund → `item add`. Jede Runde — auch eine, die du ungefragt fährst —
protokollieren: `CN haertung "<was geprüft>" [--befund "<was gefunden>"]`. Gezählt wird nur,
was so protokolliert ist.

## Was die Nacht nicht aufhebt

Kundenserver lesend. Kein Senden, Deployen, Löschen, `--force`, keine Secrets in Dateien.
Verbotene Aktionen aus mission.md sind tabu. Alles davon: vorbereiten, als To-Do übergeben.

## Die Übergabe

```
CN report      # Gerüst: Ampel, Laufzeit, Ende-Grund, Jetzt du, Ergebnis, Grenzen — aus dem Ledger
               # du schreibst NUR die Kurzfassung (drei Sätze)
CN finish      # schließt ab, zieht Kopf und Jetzt-du aus dem Endstand nach, schickt die Schlussmeldung
```

Vor der Deadline verlangt `finish` mindestens eine protokollierte Härtungsrunde oder eine
Begründung (`--grund "…"`). Früh fertig ist gut — ungeprüft früh fertig nicht.

Sicherheitsbefunde und alles andere, was nicht bis morgen warten sollte: `todo --prio P1` —
das schickt nachts eine Meldung.

Jedes To-Do braucht einen ersten Schritt zum Kopieren (Befehle in Backticks) und `--paket`, damit der Mensch sieht,
was es freischaltet. Der Bericht wird morgens von oben gelesen: was jetzt zu tun ist, was zu
prüfen ist, dann das Ergebnis. Keine Prosa-Wiederholung der Tabellen.

Wird der Mensch wach und will abbrechen: `CN abort --grund "…"`, dann trotzdem Bericht.
