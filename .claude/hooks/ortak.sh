#!/usr/bin/env bash
# Hafızanın kök klasörünü script'in kendi yerinden bulur.
# Böylece hafızanı nereye kurarsan kur, hook'lar çalışır.
HAFIZA="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DURUM="$HAFIZA/.claude/durum"
IHMAL="$DURUM/IHMAL-ISARETI"
SON_OTURUM="$HAFIZA/zihin/son-oturum.md"
ACIK_ISLER="$HAFIZA/zihin/açık-işler.md"

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

# Dosyanın değişme zamanı (epoch). GNU ve BSD/macOS farkını kapatır.
dosya_zamani() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0
}
