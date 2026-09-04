#!/usr/bin/env bash
# Hafızanın kök klasörünü script'in kendi yerinden bulur.
# Böylece hafızanı nereye kurarsan kur, hook'lar çalışır.
HAFIZA="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DURUM="$HAFIZA/.claude/durum"
SON_OTURUM="$HAFIZA/zihin/son-oturum.md"
ACIK_ISLER="$HAFIZA/zihin/açık-işler.md"
EKSIK_OTURUMLAR="$HAFIZA/gelen-kutusu/oturum-eksikleri.md"

# Claude'un gönderdiği JSON'dan oturum kimliğini çıkarır.
oturum_kimligi() {
  local girdi
  girdi=$(cat 2>/dev/null || echo '{}')
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$girdi" | jq -r '.session_id // "bilinmeyen"' 2>/dev/null || echo bilinmeyen
  else
    echo bilinmeyen
  fi
}

sayi_oku() {
  local deger
  deger=$(cat "$1" 2>/dev/null || echo 0)
  case "$deger" in ''|*[!0-9]*) echo 0 ;; *) echo "$deger" ;; esac
}

makbuz_etiketi() {
  printf '<!-- hafiza-session:%s mesaj:%s -->' "$1" "$2"
}

makbuz_var_mi() {
  local etiket=$1
  [ -f "$SON_OTURUM" ] && grep -Fq "$etiket" "$SON_OTURUM"
}

makbuz_baglantili_mi() {
  local etiket=$1
  [ -f "$SON_OTURUM" ] || return 1
  awk -v etiket="$etiket" '
    index($0, etiket) { icerde=1; next }
    icerde && /^## / { exit }
    icerde && /\[\[[^]]+\]\]/ { bulundu=1 }
    END { exit(bulundu ? 0 : 1) }
  ' "$SON_OTURUM"
}

# Dosyanın değişme zamanı (epoch). GNU ve BSD/macOS farkını kapatır.
dosya_zamani() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0
}
