#!/usr/bin/env bash
set -euo pipefail

COPIA="${1:?cartella della repo dei rilasci}"
ZITTO="${2:-}"
RAMO=prove
FUORI=(sviluppo .claude .github/workflows/vetrina.yml)

RADICE="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
CODICE="$(git -C "$RADICE" rev-parse HEAD)"
OGGETTO="$(git -C "$RADICE" log -1 --format=%s)"
CORPO="$(git -C "$RADICE" log -1 --format=%b)"

if [ "$ZITTO" = "zitto" ]; then OGGETTO="$OGGETTO [skip actions]"; fi

cd "$COPIA"
if git ls-remote --exit-code --heads origin "$RAMO" > /dev/null; then
  git fetch --quiet --depth 1 origin "+$RAMO:refs/remotes/origin/$RAMO"
  git checkout --quiet -B "$RAMO" "origin/$RAMO"
else
  git checkout --quiet --orphan "$RAMO"
fi
git rm -r -q -f --ignore-unmatch . > /dev/null
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -r -f {} +

git -C "$RADICE" archive --format=tar "$CODICE" | tar -x -f - -C .
for VIA in "${FUORI[@]}"; do rm -r -f "./$VIA"; done

if grep -rIl --exclude-dir=.git -e "@gmail[.]com" -e "hf_[A-Za-z0-9]\{30\}" -e "gh[p]_" -e "github[_]pat[_]" -e "gh[o]_" -e "BEGIN .*PRIVATE[ ]KEY" -e "AKIA[0-9A-Z]\{16\}" . > /dev/null; then
  echo "nella copia c'è un'email o una chiave: non la mando" >&2
  exit 1
fi
git add -A
python3 "$RADICE/strumenti/blocco_commit.py"
if git diff --cached --quiet; then
  echo "il ramo $RAMO ha già il codice $CODICE"
  exit 0
fi
MESSAGGIO=(-m "$OGGETTO" -m "Copia del codice ${CODICE:0:12}.")
if [ -n "$CORPO" ]; then MESSAGGIO+=(-m "$CORPO"); fi
git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit --quiet "${MESSAGGIO[@]}"

for ATTESA in 2 4 8 16 0; do
  if git push --quiet -u origin "$RAMO"; then
    echo "mandato al ramo $RAMO: $(git rev-parse --short HEAD) = codice ${CODICE:0:12}"
    exit 0
  fi
  [ "$ATTESA" -gt 0 ] && sleep "$ATTESA"
done
echo "non sono riuscito a mandare il ramo $RAMO" >&2
exit 1
