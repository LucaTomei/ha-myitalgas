#!/usr/bin/env bash
# Pubblica una nuova versione dell'integrazione.
#
#   scripts/rilascia.sh 1.2.0
#
# Aggiorna la versione nel manifest, crea il commit, prepara la bozza della
# release su GitHub (con le note generate dai commit) e avvia il workflow
# "Rilascio", che esegue tutti i controlli, allega myitalgas.zip e pubblica.
set -euo pipefail

errore() { echo "Errore: $*" >&2; exit 1; }

VERSIONE="${1:-}"
[[ "$VERSIONE" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || errore "uso: $0 X.Y.Z (es. $0 1.2.0)"
TAG="v$VERSIONE"
MANIFEST="custom_components/myitalgas/manifest.json"

command -v gh >/dev/null || errore "serve GitHub CLI (https://cli.github.com)"
gh auth status >/dev/null 2>&1 || errore "esegui prima: gh auth login"
cd "$(git rev-parse --show-toplevel)"
[[ "$(git branch --show-current)" == "main" ]] || errore "passa al branch main"
[[ -z "$(git status --porcelain)" ]] || errore "ci sono modifiche non salvate in un commit"
git pull --ff-only --quiet
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && errore "il tag $TAG esiste già"
gh release view "$TAG" >/dev/null 2>&1 && errore "la release $TAG esiste già"

python3 - "$MANIFEST" "$VERSIONE" <<'PY'
import json, sys
percorso, versione = sys.argv[1], sys.argv[2]
with open(percorso, encoding="utf-8") as f:
    manifest = json.load(f)
manifest["version"] = versione
with open(percorso, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY

if ! git diff --quiet -- "$MANIFEST"; then
  git commit --quiet -m "Versione $VERSIONE" -- "$MANIFEST"
fi
git push --quiet
gh release create "$TAG" --draft --target "$(git rev-parse HEAD)" --title "$TAG" --generate-notes
gh workflow run rilascio.yml -f versione="$VERSIONE"

echo
echo "Bozza $TAG creata e workflow di rilascio avviato."
echo "Segui l'avanzamento con:  gh run watch"
