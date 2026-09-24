# Sistem haritası

Kod ve belge karşılaştırması: 2026-09-24. Bu sayfa giriş haritasıdır;
canlı sağlık, kullanıcı kabulü veya zamanlayıcının çalışması için kanıt değildir.

## Veri akışı — iki ayrı yakalama yolu

```text
Claude oturumu
  → client_hafiza.py (SessionStart / UserPromptSubmit: bağlam; Stop: yakalama)
  → client_sessions kuyruğu (.state) → packet → client_review / review
  → incelenmiş episodik makbuz + varsa semantik aday
                                                    ↘
                                                      hafıza-adayları.jsonl
                                                    ↗
Codex oturumu
  → codex_hafiza.py hook (açılış / kullanıcı bağlamı; Stop / Interrupt: boş dönüş)
  → konsolidasyon.py sessions (zamanlanmış kaynak taraması)
  → tamamlanan kaynak bölümü → codex_hafiza.py record → makbuz + semantik aday
  → checkpoint (incelenen kaynak sürümünün işlem sonucu)

semantik aday → kaynak + kalıcılık + kapsam + tekrar/çelişki incelemesi
  → konsolidasyon.py review → katalog → hafiza.py sync → Mem0 → audit / geri okuma
```

İstemci kuyruğu ile semantik aday kuyruğu farklıdır. Codex Stop olayının
tek başına makbuz/aday ürettiği varsayılmaz. Claude/Antigravity kaynak biçimleri
ve kurulum sınırları [entegrasyon rehberinde](ENTEGRASYONLAR.md), Codex kanıt
alanları [kaynak rehberinde](CODEX.md) açıklanır. Tam sohbet senkronu yapılmaz.
`review-pending --apply` danışmanlık makbuzu yazar; tek başına terfi yapmaz.

## Veri sahipliği

Yetki, tek yazıcı, gizlilik ve Mem0 politikasının tek kaynağı:
[zihin/hafıza-sistemi.md](zihin/hafıza-sistemi.md).

| Dosya / katman | Sahipliği ve rolü |
|---|---|
| `zihin/hafıza-kataloğu.jsonl` | İncelenmiş kalıcı iddiaların kanonik kaydı; kaynak bağıyla okunur. |
| `bilgi/` içindeki kaynaklı kartlar | Kendi proje/iş türü kapsamındaki incelenmiş bilgi; katalogdaki aynı iddianın bağımsız ikinci kopyası yapılmaz. |
| `zihin/is-durumu.jsonl`, `zihin/ders-durumu.jsonl` | Kaynaklı iş ve ders sürümlerinin kanonik defterleri. |
| `gelen-kutusu/hafıza-adayları.jsonl` | İnceleme bekleyen öneriler; onaylı gerçek değildir. |
| `gelen-kutusu/ajan-oturumlari/.state/` | Claude/Antigravity yakalama ve inceleme durumu; özgün transcript yerine geçmez. |
| `gelen-kutusu/codex-oturumları/`, `gelen-kutusu/ajan-oturumlari/` | Episodik makbuzlar; özgün kullanıcı beyanı ve güncel durumla karıştırılmaz. |
| `günlük/hafıza-olayları.jsonl`, kaynak sürümü ve inceleme makbuzları | İşlem/kanıt geçmişi; kaynak içeriğini veya insan kabulünü kanıtlamaz. |
| `zihin/açık-işler.md` | `is_ve_ders.py render` ile iş defterinden türetilir; elle ikinci liste tutulmaz. |
| `bilgi/konu-sentezleri/`, `.ozet.md` | Kaynaklardan türetilen erişim görünümleri. |
| `komuta/hafıza-raporu.md`, `komuta/hafıza-sagligi.md` | Ölçüm/sağlık çıktısı; üretim tarihi başarılı bakım zamanı değildir. |
| Mem0 | Katalogdan yeniden üretilebilir uzak erişim görünümü; yetki ve çelişki kuralı yukarıdaki kayıt sözleşmesinde. |

## Komut girişleri

Kasa kökünde `python3 araclar/ARAÇ.py --vault . KOMUT` biçimi kullanılır;
aşağıdaki istisnalar açıkça gösterilmiştir. Alt komutlar argparse kodundan doğrulandı.

| Araç | Gerçek alt komutlar / giriş |
|---|---|
| `hafiza.py` | `validate`, `candidate-add`, `candidate-assess`, `promote`, `bind-source`, `context`, `category-report`, `sync`, `audit`, `eval`, `forget` |
| `codex_hafiza.py` | `hook`, `latest-session`, `record` |
| `client_hafiza.py` | Alt komut yok; `--client`, `--event`; hook girdisi stdin JSON. |
| `client_sessions.py` | `pending`, `packet`, `review`, `recall` |
| `client_review.py` | Alt komut yok; `--reviewer-argv-json`, `--limit`, `--apply`; sağlayıcı ayrıca ayarlanır. |
| `konsolidasyon.py` | `status`, `pending`, `sessions`, `checkpoint`, `review`, `review-pending`, `health` |
| `is_ve_ders.py` | `task`, `lesson`, `brief`, `render`, `lessons` |
| `gorev_baglam.py` | `package`, `resume`, `validate-inputs` |
| `bilgi_agi.py` | `register`, `assess-source`, `context`, `review`, `review-candidate`, `status` |
| `hafiza_dongusu.py` | `review-pending`, `outcome`, `review-lesson`, `verify-answer`, `context` |
| `ozet.py` | `build`, `status`, `show`, `map` |
| `hafiza_rapor.py` | Alt komut yok; `--days 7`; `--write` rapor Markdown'ını yeniler. |
| `erisim_olc.py` | `collect`, `evaluate` (girdi ve çıktı dosyası seçenekleri aşağıda). |
| `ajan_kur.py` | Alt komut yok; `--agent`, `--with-hooks`, `--apply`, `--remove`. |

Yazma/uzak erişim seçenekleri için ilgili aracın `--help` çıktısını ve bakım
sözleşmesini oku. `sessions` tarama makbuzu, `checkpoint` olay kaydı yazar;
`health` sağlık dosyası ve izinli veri değişikliği varsa yerel Git commit'i üretir.
`health --check` de aynı yan etkilere sahiptir; salt okunur kontrol için `status`.
`sync`/`audit` uzak servise erişebilir. Bu haritadaki komutların yazılması
kurulum, kayıt, yayın veya dışa veri aktarımı yetkisi değildir.

## Zamanlanmış işler

Kurucu zamanlayıcı kurmaz. İsteğe bağlı saatlik bakımın sözleşmesi
[komuta/hafıza-konsolidasyonu.md](komuta/hafıza-konsolidasyonu.md) içindedir:
Codex için `sessions --scheduled`; native istemci kuyruğu için ayrıca
`client_review.py` gerekir. Projede bulunmayan kişisel zamanlayıcı kurulmuş
sayılmaz. Son başarılı tarama/audit zamanı `status.operational_health` ile
kontrol edilir. Uygulama kapalıyken kesintisiz çalışma garantisi yoktur.
Gelişim deneyleri ayrıca yapılandırılır; çekirdek yakalama için önkoşul değildir.

## H1–H7 ölçüm girişleri

| Hedef | Komut / ölçüm | Yorum sınırı |
|---|---|---|
| H1 Yakalama | `python3 araclar/konsolidasyon.py --vault . status`; `python3 araclar/client_sessions.py --vault . pending` | İstemci kuyruğu ve `capture`/kaynak durumu birlikte incelenir; boş kuyruk tek başına yakalama başarısı değildir. |
| H2 İnceleme | `python3 araclar/hafiza_rapor.py --vault . --days 7`; `python3 araclar/konsolidasyon.py --vault . pending` | Aday sayısı ve en yaşlı bekleyen ölçülür. `defer` hâlâ pending sayılır; ilk inceleme süresiyle engel yaşı aynı değildir. |
| H3 Erişim | Aşağıdaki `erisim_olc.py evaluate` | Gerçek, etiketli istemler gerekir; precision/recall, FP/FN ve karakter ölçümü maliyet veya insan faydası değildir. |
| H4 Süreklilik | `python3 araclar/codex_hafiza.py --vault . latest-session`; `python3 araclar/is_ve_ders.py --vault . brief` | Son oturum çıktısının kaynak/tarihini ve işlerin son teyidini kontrol et; otomatik işçi açılışında çalıştırılmaz. |
| H5 Haftalık ölçüm | `python3 araclar/hafiza_rapor.py --vault . --days 7` | JSON rapor; `--write` eklenirse haftalık Markdown görünümü yenilenir. Eksik veri başarı değildir. |
| H6 Sadelik | Aşağıdaki belge sayısı/satır/bayt sayacı; değiştirilmiş belgelerde bağlantı denetimi | Arşiv ayrı tutulur; küçülme tek başına anlaşılabilirliği kanıtlamaz. |
| H7 Güvence | `python3 -m unittest discover -s araclar -p 'test_*.py' </dev/null`; `python3 araclar/konsolidasyon.py --vault . status` | Yerel test, üç işletim sisteminin CI sonucu veya kamu gizlilik kabulü yerine geçmez. |

```sh
# Önceden hazırlanmış ve etiketlenmiş değerlendirme seti gerekir.
python3 araclar/erisim_olc.py --vault . evaluate \
  --set ISTEMLER.jsonl --labels ETIKETLER.json --out-dir SONUC_DIZINI
# İsteğe bağlı collect ham kaynaklardan arındırılmış istem seti yazar;
# --claude-root / --codex-root / --days / --limit / --out seçeneklerini kullanır.
# evaluate de JSON ve Markdown çıktı yazar; salt okunur değildir.
```

```sh
# Kök + komuta altındaki Markdown belgeleri; arşiv hariç, symlink çift sayılmaz.
python3 - <<'COUNT'
from pathlib import Path
root = Path('.')
files = sorted({p.resolve() for p in [*root.glob('*.md'), *root.glob('komuta/**/*.md')]})
print({'belge': len(files), 'satir': sum(len(p.read_bytes().splitlines()) for p in files),
       'bayt': sum(p.stat().st_size for p in files)})
COUNT
```

`konsolidasyon.py --vault . health --check` bakım yetkisi olan koşuda görünümü
yeniler ve healthy=0, failed=1, stale=2, unknown=3 döndürür. Commit yasaksa
çalıştırılmaz. H7 kamu içeriği ve yayın sınırı [YAYINLAMA.md](YAYINLAMA.md)
içindedir; `yayinla.py --apply` ölçüm komutu değildir, yayın yapar.

## Belge yolları

- Açılış: [agents.md](agents.md); merkez: [Ana Sayfa](<Ana Sayfa.md>).
- İşletim/bakım: [ajan işletimi](komuta/ajan-isletimi.md), [konsolidasyon](komuta/hafıza-konsolidasyonu.md).
- Erişim/bilgi: [BILGI-AGI](BILGI-AGI.md); türetilmiş konu görünümü [KONU-SENTEZI](KONU-SENTEZI.md); bildirim [HAFIZA-GORUNURLUGU](HAFIZA-GORUNURLUGU.md).
- Koşullu ders ve cevap kontrolü: [HAFIZA-DONGUSU](HAFIZA-DONGUSU.md).
- Ayrı deney/migrasyon: [GOREV-PLANI](GOREV-PLANI.md), [GELISIM-DONGUSU](GELISIM-DONGUSU.md), [KAYIT-UZLASTIRMA](KAYIT-UZLASTIRMA.md).
- Geliştirme ve test: [CONTRIBUTING](CONTRIBUTING.md); genel başlangıç: [README](README.md).

## Hook bağlamında uzak danışman

Claude ve Codex hook'ları görev paketini yerel kurar; uzak semantik danışman
(Jev) hook yolunda kapalıdır. Gerçek istemlerle ölçümde (`erisim_olc.py`)
uzak danışman doğruluğu düşürdü ve gecikme ekledi. İsteyen `HAFIZA_HOOK_JEV=1`
ile hook'ta yeniden açabilir; açık CLI kullanımı etkilenmez.
