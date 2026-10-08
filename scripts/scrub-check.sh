#!/usr/bin/env bash
# Gate vor jedem Push in ein öffentliches Repo: nichts Internes im Baum.
#
#   scripts/scrub-check.sh kundenname anderer-kunde ...
#   scripts/scrub-check.sh                 # nimmt die Begriffe aus .scrub-terms
#
# Die Begriffe stehen bewusst NICHT in diesem Skript: eine gepflegte Kundenliste
# im öffentlichen Repo wäre genau das Leck, das dieses Gate verhindern soll.
# .scrub-terms ist gitignored — eine Zeile je Begriff, # als Kommentar.
# Exit 0 = sauber, 1 = Treffer, 2 = keine Begriffe angegeben.
set -u

GEHEIM="BEGIN [A-Z ]*PRIVATE KEY|xox[baprs]-|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}"

if [ $# -gt 0 ]; then
  begriffe=("$@")
elif [ -f .scrub-terms ]; then
  mapfile -t begriffe < <(grep -vE '^\s*(#|$)' .scrub-terms)
else
  echo "Keine Begriffe. Übergib sie als Argumente oder lege .scrub-terms an." >&2
  exit 2
fi
[ ${#begriffe[@]} -eq 0 ] && { echo "Begriffsliste ist leer." >&2; exit 2; }

# Metazeichen entschärfen: Begriffe sind Namen, keine Regexe.
BEGRIFFE=$(printf '%s\n' "${begriffe[@]}" | sed 's/[][\.^$*+?(){}|\]/\&/g' | paste -sd'|' -)

treffer=0
while IFS= read -r datei; do
  [ "$datei" = "scripts/scrub-check.sh" ] && continue
  # Ausgabe erst einfangen, dann prüfen: der Exit-Code einer Pipe wäre der
  # des LETZTEN Befehls (sed/cut) und damit immer 0.
  fund=$(grep -niE "$BEGRIFFE" "$datei" 2>/dev/null || true)
  if [ -n "$fund" ]; then printf 'BEGRIFF %s\n' "$datei"; printf '%s\n' "$fund" | cut -c1-100; treffer=1; fi
  fund=$(grep -niE "$GEHEIM" "$datei" 2>/dev/null || true)
  if [ -n "$fund" ]; then printf 'SECRET  %s (Zeilen unterdrueckt)\n' "$datei"; treffer=1; fi
done < <(git ls-files)

if [ "$treffer" -eq 0 ]; then
  echo "sauber — $(git ls-files | wc -l) Dateien gegen ${#begriffe[@]} Begriff(e) geprüft"
  exit 0
fi
echo
echo "Treffer gefunden. Nicht pushen, bevor sie weg sind."
exit 1
