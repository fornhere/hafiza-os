#!/usr/bin/env bash
# Stop/PreCompact — uzun oturumun oturuma özgü, bağlantılı makbuzu olmadan
# durmasını veya sıkıştırılmasını engeller. İki başarısız zorlamadan sonra
# SessionEnd'in kalıcı eksik checklist'ine düşebilmesi için güvenli biçimde açılır.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/ortak.sh"

INPUT=$(cat 2>/dev/null || echo '{}')
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // "bilinmeyen"' 2>/dev/null || echo bilinmeyen)
OLAY=$(printf '%s' "$INPUT" | jq -r '.hook_event_name // "Stop"' 2>/dev/null || echo Stop)
SDIR="$DURUM/$SID"
N=$(sayi_oku "$SDIR/sayac")
[ "$N" -gt 5 ] || exit 0

ETIKET=$(makbuz_etiketi "$SID" "$N")
YETIMLER=$(bash "$(dirname "${BASH_SOURCE[0]}")/baglanti-denetle.sh" 2>/dev/null || true)
if makbuz_var_mi "$ETIKET" && makbuz_baglantili_mi "$ETIKET" && [ -z "$YETIMLER" ]; then
  rm -f "$SDIR/zorlama-sayisi"
  exit 0
fi

ZORLAMA=$(sayi_oku "$SDIR/zorlama-sayisi")
if [ "$ZORLAMA" -ge 2 ]; then
  exit 0
fi
echo $((ZORLAMA + 1)) > "$SDIR/zorlama-sayisi"

SEBEP="Hafıza makbuzu eksik. zihin/son-oturum.md dosyasının EN ÜSTÜNDE bu oturuma ait bölümü oluştur veya güncelle. Başlığın hemen altına şu etiketi aynen koy: $ETIKET . Bölümde en az bir ilgili Obsidian bağlantısı ([[Ana Sayfa]] veya proje hub'ı) bulunsun. Kararlar, ne oldu, yarım kalanlar ve sonraki adımları güncelle; yeni bir proje/not doğduysa Ana Sayfa'dan da bağla."
if [ -n "$YETIMLER" ]; then
  SEBEP="$SEBEP Ayrıca bağlantısız notlar var; Ana Sayfa veya ilgili hub'dan bağla: $(printf '%s' "$YETIMLER" | tr '\n' ' ')"
fi

jq -n --arg olay "$OLAY" --arg sebep "$SEBEP" '
  if $olay == "Stop" then {decision:"block", reason:$sebep}
  else {decision:"block", reason:$sebep}
  end'
