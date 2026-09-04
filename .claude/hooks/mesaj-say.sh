#!/usr/bin/env bash
# UserPromptSubmit — sadece mesaj sayacını bir artırır.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/ortak.sh"

SID=$(oturum_kimligi)
SDIR="$DURUM/$SID"
mkdir -p "$SDIR"

N=$(cat "$SDIR/sayac" 2>/dev/null || echo 0)
case "$N" in ''|*[!0-9]*) N=0 ;; esac
echo $((N + 1)) > "$SDIR/sayac"
rm -f "$SDIR/zorlama-sayisi"
exit 0
