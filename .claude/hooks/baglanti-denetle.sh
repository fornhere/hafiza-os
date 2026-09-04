#!/usr/bin/env bash
# Vault'taki çıkış bağlantısı olmayan ve başka bir nottan da bağlanmayan yetimleri listeler.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/ortak.sh"

HATA=0
while IFS= read -r -d '' DOSYA; do
  GORELI=${DOSYA#"$HAFIZA"/}
  case "$GORELI" in README.md|agents.md) continue ;; esac
  grep -Eq '\[\[[^]]+\]\]' "$DOSYA" && continue

  ANAHTAR=${GORELI%.md}
  TABAN=${ANAHTAR##*/}
  GELEN=$(grep -RFl --include='*.md' --exclude-dir=.git --exclude-dir=.claude \
    -e "[[$ANAHTAR" -e "[[$TABAN" "$HAFIZA" 2>/dev/null | grep -Fvx "$DOSYA" || true)
  [ -n "$GELEN" ] && continue

  printf '%s\n' "$GORELI"
  HATA=1
done < <(find "$HAFIZA" -path "$HAFIZA/.git" -prune -o -path "$HAFIZA/.claude" -prune \
  -o -type f -name '*.md' -print0)

exit "$HATA"
