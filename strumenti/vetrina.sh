#!/usr/bin/env bash
set -euo pipefail

VERSIONE="${1:?versione}"
PESO="${2:?peso}"
: "${DEPOSITO_RILASCI:?}"
: "${TOKEN_RILASCI:?}"

PYTHON="${PYTHON:-python}"
RADICE="$(cd "$(dirname "$0")/.." && pwd)"
LAVORO="$(mktemp -d)"
CHIAVE="$(printf 'x-access-token:%s' "$TOKEN_RILASCI" | base64 | tr -d '\n')"
echo "::add-mask::$CHIAVE"
INTESTAZIONE="AUTHORIZATION: basic $CHIAVE"
[[ "$DEPOSITO_RILASCI" =~ ^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$ ]] || { echo "deposito non valido" >&2; exit 1; }
REMOTO="${VETRINA_REMOTO:-https://github.com/$DEPOSITO_RILASCI.git}"

for TENTATIVO in 1 2 3; do
  rm -rf "$LAVORO/pubblica"
  git -c "http.https://github.com/.extraheader=$INTESTAZIONE" clone --quiet --depth 1 -c core.autocrlf=false \
    "$REMOTO" "$LAVORO/pubblica"
  "$PYTHON" "$RADICE/strumenti/vetrina.py" --deposito "$DEPOSITO_RILASCI" \
    --versione "$VERSIONE" --peso "$PESO" --uscita "$LAVORO/pubblica" > /dev/null
  cd "$LAVORO/pubblica"
  git add -A
  if git diff --cached --quiet; then
    echo "la vetrina è già aggiornata alla $VERSIONE"
    exit 0
  fi
  git -c user.name="github-actions[bot]" \
      -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
      commit --quiet -m "Vetrina per la versione $VERSIONE"
  if git -c "http.https://github.com/.extraheader=$INTESTAZIONE" push --quiet origin HEAD; then
    echo "vetrina pubblicata per la $VERSIONE"
    exit 0
  fi
  cd "$RADICE"
  sleep $((TENTATIVO * 5))
done
echo "la vetrina non si è potuta pubblicare" >&2
exit 1
