#!/usr/bin/env bash
# Hafıza OS — kurulum.
# Bu script bulunduğu klasörü senin hafızan olarak ayarlar:
# hook'ları Claude Code ayarlarına bağlar, git'i hazırlar, şablonu tarihler.
#
#   ./kur.sh            kur
#   ./kur.sh --kaldir   hook bağlantılarını ayarlardan çıkar (dosyalara dokunmaz)
set -euo pipefail

HAFIZA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AYAR="$HOME/.claude/settings.json"
BUGUN="$(date '+%Y-%m-%d')"

kirmizi() { printf '\033[31m%s\033[0m\n' "$*"; }
yesil()   { printf '\033[32m%s\033[0m\n' "$*"; }
gri()     { printf '\033[90m%s\033[0m\n' "$*"; }

# --- gereksinimler ---------------------------------------------------------
eksik=()
command -v jq  >/dev/null 2>&1 || eksik+=("jq")
command -v git >/dev/null 2>&1 || eksik+=("git")
if [ ${#eksik[@]} -gt 0 ]; then
  kirmizi "✖ Şunlar kurulu değil: ${eksik[*]}"
  echo "   Arch/Omarchy : sudo pacman -S ${eksik[*]}"
  echo "   Debian/Ubuntu: sudo apt install ${eksik[*]}"
  echo "   macOS        : brew install ${eksik[*]}"
  exit 1
fi

mkdir -p "$HOME/.claude"
AYAR_BIZDEN=0
if [ ! -f "$AYAR" ]; then
  echo '{}' > "$AYAR"
  AYAR_BIZDEN=1
fi
if ! jq -e . "$AYAR" >/dev/null 2>&1; then
  kirmizi "✖ $AYAR geçerli JSON değil. Önce onu düzelt."
  exit 1
fi

YEDEK="$AYAR.yedek-$(date '+%Y%m%d-%H%M%S')"
cp "$AYAR" "$YEDEK"
gri "Ayar yedeği: $YEDEK"

# --- eski/çift kayıtları temizle ------------------------------------------
# Hangi klasöre kurulmuş olursa olsun, Hafıza OS script'lerine işaret eden
# kayıtlar ayarlardan çıkarılır. Böylece tekrar çalıştırmak çiftlemez.
temizle() {
  jq '
    def sil:
      map(.hooks |= map(select((.command // "")
        | test("(oturum-basla|mesaj-say|hafiza-kontrol|oturum-bitir)\\.sh$") | not)))
      | map(select((.hooks | length) > 0));
    if .hooks then
      .hooks |= with_entries(.value |= sil)
      | .hooks |= with_entries(select((.value | length) > 0))
    else . end
    | if (.hooks // {}) == {} then del(.hooks) else . end
  ' "$AYAR" > "$AYAR.tmp" && mv "$AYAR.tmp" "$AYAR"
}

if [ "${1:-}" = "--kaldir" ]; then
  temizle
  GLOBAL_CLAUDE="$HOME/.claude/CLAUDE.md"
  if [ -f "$GLOBAL_CLAUDE" ]; then
    sed '/<!-- HAFIZA-OS:BAŞLA -->/,/<!-- HAFIZA-OS:BİTİR -->/d' \
      "$GLOBAL_CLAUDE" > "$GLOBAL_CLAUDE.tmp"
    mv "$GLOBAL_CLAUDE.tmp" "$GLOBAL_CLAUDE"
    grep -q '[^[:space:]]' "$GLOBAL_CLAUDE" || rm -f "$GLOBAL_CLAUDE"
  fi
  # Ayar dosyası bizden önce yoktu ve geriye boş bir kabuk kaldıysa, onu da
  # götür — kurulum öncesi hâl "boş dosya" değil, "dosya yok"tu.
  if [ "$(tr -d '[:space:]' < "$AYAR")" = "{}" ] && [ -f "$HAFIZA/.claude/durum/AYAR-BIZDEN" ]; then
    rm -f "$AYAR" "$HAFIZA/.claude/durum/AYAR-BIZDEN"
    gri "Boş ayar dosyası kaldırıldı (kurulumdan önce yoktu)."
  fi
  yesil "✔ Hook bağlantıları ayarlardan çıkarıldı. Dosyalarına dokunulmadı."
  echo "  Geri almak için: $HAFIZA/kur.sh"
  exit 0
fi

temizle

# --- hook'ları bağla -------------------------------------------------------
chmod +x "$HAFIZA/.claude/hooks/"*.sh
mkdir -p "$HAFIZA/.claude/durum"

jq --arg h "$HAFIZA" '
  .hooks //= {}
  | .hooks.SessionStart //= []
  | .hooks.UserPromptSubmit //= []
  | .hooks.Stop //= []
  | .hooks.PreCompact //= []
  | .hooks.SessionEnd //= []
  | .hooks.SessionStart += [{hooks:[{type:"command",
      command:($h + "/.claude/hooks/oturum-basla.sh"),
      timeout:15, statusMessage:"Hafıza okunuyor..."}]}]
  | .hooks.UserPromptSubmit += [{hooks:[{type:"command",
      command:($h + "/.claude/hooks/mesaj-say.sh"), timeout:10}]}]
  | .hooks.Stop += [{hooks:[{type:"command",
      command:($h + "/.claude/hooks/hafiza-kontrol.sh"), timeout:15}]}]
  | .hooks.PreCompact += [{hooks:[{type:"command",
      command:($h + "/.claude/hooks/hafiza-kontrol.sh"), timeout:15}]}]
  | .hooks.SessionEnd += [{hooks:[{type:"command",
      command:($h + "/.claude/hooks/oturum-bitir.sh"), timeout:15}]}]
' "$AYAR" > "$AYAR.tmp" && mv "$AYAR.tmp" "$AYAR"

yesil "✔ Hook'lar bağlandı ($AYAR)"
[ "$AYAR_BIZDEN" = 1 ] && : > "$HAFIZA/.claude/durum/AYAR-BIZDEN"

# --- CLAUDE.md sembolik linki ---------------------------------------------
if [ ! -e "$HAFIZA/CLAUDE.md" ]; then
  ln -s agents.md "$HAFIZA/CLAUDE.md"
fi

# --- global başlangıç talimatı ---------------------------------------------
# Claude başka bir projede açılsa bile hafıza anayasasının yüklenmesini sağlar.
# İşaretli blok tekrar kurulumda güvenle yenilenir; kullanıcının diğer global
# talimatları korunur.
GLOBAL_CLAUDE="$HOME/.claude/CLAUDE.md"
touch "$GLOBAL_CLAUDE"
sed '/<!-- HAFIZA-OS:BAŞLA -->/,/<!-- HAFIZA-OS:BİTİR -->/d' \
  "$GLOBAL_CLAUDE" > "$GLOBAL_CLAUDE.tmp"
cat >> "$GLOBAL_CLAUDE.tmp" <<BOOTSTRAP

<!-- HAFIZA-OS:BAŞLA -->
# Hafıza OS — global başlangıç

Her oturumda $HAFIZA/agents.md anayasasını ve oradaki açılış sırasını oku.
Uzun oturumun sonunda zihin/son-oturum.md içine hook'un verdiği oturum kimliği
ve mesaj sayısıyla bağlantılı bir makbuz bırak. Obsidian notlarını [[wikilink]]
ile Ana Sayfa veya ilgili proje merkezine bağla. Hook uyarılarını atlama.
<!-- HAFIZA-OS:BİTİR -->
BOOTSTRAP
mv "$GLOBAL_CLAUDE.tmp" "$GLOBAL_CLAUDE"
yesil "✔ Global başlangıç talimatı güncellendi ($GLOBAL_CLAUDE)"

# --- şablon tarihleri ------------------------------------------------------
# Yalnızca içerik klasörleri taranır. README.md ve agents.md dışarıda:
# ikisi de yer tutucuyu *anlatıyor*, kullanmıyor — tarih basılırsa
# kendi belgelerini bozar.
DEGISTI=0
while IFS= read -r -d '' f; do
  if grep -q '<TARİH>\|<YYYY-AA-GG>' "$f"; then
    sed -i.bak "s/<TARİH>/$BUGUN/g; s/<YYYY-AA-GG>/$BUGUN/g" "$f" && rm -f "$f.bak"
    DEGISTI=1
  fi
done < <(find "$HAFIZA/zihin" "$HAFIZA/komuta" "$HAFIZA/projeler" \
              "$HAFIZA/günlük" "$HAFIZA/arşiv" "$HAFIZA/gelen-kutusu" \
              -name '*.md' -print0 2>/dev/null)
[ "$DEGISTI" = 1 ] && gri "Şablondaki tarih alanları $BUGUN yapıldı."

# --- git -------------------------------------------------------------------
if [ ! -d "$HAFIZA/.git" ]; then
  git -C "$HAFIZA" init -q
  gri "git deposu açıldı."
fi
git -C "$HAFIZA" config core.hooksPath .githooks
yesil "✔ Sır kapanı devrede (.githooks/pre-commit)"

cat <<BITTI

$(yesil "Kurulum bitti.")  Hafıza: $HAFIZA

Sıradaki üç adım:

  1. Claude Code'u bu klasörde aç:   cd "$HAFIZA" && claude
     /hooks ile beş hook'u, /context ile global CLAUDE.md talimatını doğrula.

  2. Ajana şunu söyle:
       "zihin/çekirdek.md boş, bana mülakat yap"
     Çekirdeği sen değil, o doldursun. Fark burada.

  3. İlk commit'i at:
       git -C "$HAFIZA" add -A && git -C "$HAFIZA" commit -m "hafıza kuruldu"

Kaldırmak için: $HAFIZA/kur.sh --kaldir
BITTI
