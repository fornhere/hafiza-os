#!/usr/bin/env bash
# SessionEnd — 5'ten fazla mesaj yazıldıysa ve son-oturum.md bu oturumda
# hiç değişmediyse, ihmal işaretini bırakır.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/ortak.sh"

SID=$(oturum_kimligi)
SDIR="$DURUM/$SID"

N=$(cat "$SDIR/sayac" 2>/dev/null || echo 0)
case "$N" in ''|*[!0-9]*) N=0 ;; esac
BAS=$(cat "$SDIR/baslangic" 2>/dev/null || echo 0)
case "$BAS" in ''|*[!0-9]*) BAS=0 ;; esac

if [ "$N" -gt 5 ] && [ -f "$SON_OTURUM" ]; then
  MTIME=$(dosya_zamani "$SON_OTURUM")
  if [ "$MTIME" -lt "$BAS" ]; then
    mkdir -p "$DURUM"
    {
      echo "Kapanış tarihi : $(date '+%Y-%m-%d %H:%M')"
      echo "Başlangıç      : $(cat "$SDIR/baslangic-okunur" 2>/dev/null || echo bilinmiyor)"
      echo "Mesaj sayısı   : $N"
      echo "Durum          : son-oturum.md bu oturum boyunca hiç değişmedi."
    } > "$IHMAL"
  fi
fi

rm -rf "$SDIR" 2>/dev/null
exit 0
