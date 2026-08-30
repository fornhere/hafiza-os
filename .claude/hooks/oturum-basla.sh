#!/usr/bin/env bash
# SessionStart — dünü ve açık işleri bağlama enjekte eder, sayacı sıfırlar,
# önceki oturum ihmal edilmişse uyarı basar.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/ortak.sh"

SID=$(oturum_kimligi)
SDIR="$DURUM/$SID"
mkdir -p "$SDIR"
date +%s                > "$SDIR/baslangic"
date '+%Y-%m-%d %H:%M'  > "$SDIR/baslangic-okunur"
echo 0                  > "$SDIR/sayac"

# 7 günden eski oturum durumlarını temizle
find "$DURUM" -mindepth 1 -maxdepth 1 -type d -mtime +7 -exec rm -rf {} + 2>/dev/null

OUT=""

if [ -f "$IHMAL" ]; then
  OUT+="================================================================"$'\n'
  OUT+="  ⚠  ÖNCEKİ OTURUM HAFIZA GÜNCELLENMEDEN KAPANDI"$'\n'
  OUT+="================================================================"$'\n'
  OUT+="$(cat "$IHMAL")"$'\n'
  OUT+="Anayasa madde 4: yazılmayan oturum yaşanmamış sayılır."$'\n'
  OUT+="Bu oturumun ilk işi, o boşluğu kullanıcıya hatırlatmak ve"$'\n'
  OUT+="hatırlanabildiği kadarını son-oturum.md'ye geçirmektir."$'\n'
  OUT+="================================================================"$'\n\n'
  rm -f "$IHMAL"
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

printf '%s' "$OUT" | jq -Rs '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:.}}'
