#!/usr/bin/env bash
# SessionEnd — 5'ten fazla mesajlı oturumun kendine ait makbuzu yoksa
# kalıcı eksik-oturum checklist'ine transcript yoluyla birlikte kaydeder.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/ortak.sh"

INPUT=$(cat 2>/dev/null || echo '{}')
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // "bilinmeyen"' 2>/dev/null || echo bilinmeyen)
TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // "bilinmiyor"' 2>/dev/null || echo bilinmiyor)
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // "bilinmiyor"' 2>/dev/null || echo bilinmiyor)
SDIR="$DURUM/$SID"

N=$(sayi_oku "$SDIR/sayac")
ETIKET=$(makbuz_etiketi "$SID" "$N")

if [ "$N" -gt 5 ] && { ! makbuz_var_mi "$ETIKET" || ! makbuz_baglantili_mi "$ETIKET"; }; then
  mkdir -p "$(dirname "$EKSIK_OTURUMLAR")"
  if [ ! -f "$EKSIK_OTURUMLAR" ]; then
    printf '# Eksik Oturum Makbuzları\n\nTamamlanan satırı `[x]` yap. [[Ana Sayfa]]\n\n' > "$EKSIK_OTURUMLAR"
  fi
  KIMLIK="<!-- eksik-session:$SID mesaj:$N -->"
  if ! grep -Fq "$KIMLIK" "$EKSIK_OTURUMLAR"; then
    printf -- '- [ ] %s · %s mesaj · `%s` · transcript: `%s` %s\n' \
      "$(date '+%Y-%m-%d %H:%M')" "$N" "$CWD" "$TRANSCRIPT" "$KIMLIK" >> "$EKSIK_OTURUMLAR"
  fi
fi

rm -rf "$SDIR" 2>/dev/null
exit 0
