#!/usr/bin/env bash
# SessionStart — dünü ve açık işleri bağlama enjekte eder. Yeni oturumda
# sayacı kurar; resume sırasında mevcut sayacı sıfırlamaz.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/ortak.sh"

INPUT=$(cat 2>/dev/null || echo '{}')
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // "bilinmeyen"' 2>/dev/null || echo bilinmeyen)
KAYNAK=$(printf '%s' "$INPUT" | jq -r '.source // "startup"' 2>/dev/null || echo startup)
SDIR="$DURUM/$SID"
mkdir -p "$SDIR"
if [ ! -f "$SDIR/baslangic" ]; then
  date +%s               > "$SDIR/baslangic"
  date '+%Y-%m-%d %H:%M' > "$SDIR/baslangic-okunur"
  echo 0                 > "$SDIR/sayac"
fi
printf '%s\n' "$KAYNAK" > "$SDIR/son-kaynak"

# 7 günden eski oturum durumlarını temizle
find "$DURUM" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} + 2>/dev/null

OUT=""

if [ -f "$EKSIK_OTURUMLAR" ] && grep -q '^- \[ \]' "$EKSIK_OTURUMLAR"; then
  OUT+="================================================================"$'\n'
  OUT+="  ⚠  HAFIZA MAKBUZU EKSİK OTURUMLAR VAR"$'\n'
  OUT+="================================================================"$'\n'
  OUT+="$(grep '^- \[ \]' "$EKSIK_OTURUMLAR" | tail -10)"$'\n'
  OUT+="Anayasa madde 4: yazılmayan oturum yaşanmamış sayılır."$'\n'
  OUT+="Eksikleri transcript yolundan geri doldur; tamamlanan kutuyu [x] yap."$'\n'
  OUT+="================================================================"$'\n\n'
fi

OUT+="## HAFIZA — Son Oturum (zihin/son-oturum.md)"$'\n\n'
if [ -f "$SON_OTURUM" ]; then
  BLOK=$(awk '/^## /{n++; if(n>1) exit} n==1{print}' "$SON_OTURUM")
  OUT+="${BLOK:-(henüz not yok)}"$'\n\n'
else
  OUT+="(son-oturum.md bulunamadı)"$'\n\n'
fi

OUT+="## HAFIZA — Aktif İşler (zihin/açık-işler.md)"$'\n\n'
if [ -f "$ACIK_ISLER" ]; then
  ISLER=$(awk '/^## Aktif İşler/{f=1;next} /^## /{f=0} f && /^### /{sub(/^### /,"- ");print}' "$ACIK_ISLER")
  OUT+="${ISLER:-(aktif iş yok)}"$'\n\n'
else
  OUT+="(açık-işler.md bulunamadı)"$'\n\n'
fi

OUT+="Açılış okuma sırasının tamamı için: $HAFIZA/agents.md"$'\n'
OUT+="Oturum kimliği: $SID. 6. mesajdan sonra Stop hook'unun istediği"$'\n'
OUT+="makbuz etiketini zihin/son-oturum.md notunda aynen kullan."$'\n'

printf '%s' "$OUT" | jq -Rs '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:.}}'
