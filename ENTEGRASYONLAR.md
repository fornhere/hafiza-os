# Yerel istemci kurulumu

Aynı kasa paylaşılır; tam sohbet geçmişi istemciler arasında senkronize edilmez.
Yönerge köprüsü kayıt değildir. Hook yakalaması incelenmiş hafıza değildir.
Reviewer sağlayıcısı ayrıca ve açıkça yapılandırılır; hook model çağırmaz.

| İstemci | Yönerge | `--with-hooks` |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | `settings.json`: SessionStart, UserPromptSubmit, Stop |
| Codex | `~/.codex/AGENTS.md` | `hooks.json`: SessionStart, UserPromptSubmit, Stop, Interrupt |
| Antigravity CLI (`agy`) | `~/.gemini/GEMINI.md` | `config/hooks.json`: `hafiza-os` grubunda doğrudan PreInvocation ve Stop dizileri |
| generic | `--export` Markdown | Yok; hook seçeneği reddedilir |

| İşletim sistemi | Python motoru |
|---|---|
| Linux | 360 testlik paket başarılı |
| macOS | 360 testlik paket başarılı |
| Windows | 360 testlik paket başarılı; native kilit, UTF-8 ve cmd hook çalıştırma dahil |

Linux'ta agy 1.1.27 ile gerçek Stop → ayrı model incelemesi → farklı oturumda
doğru geri çağırma zinciri doğrulandı.

[Üç işletim sisteminin CI sonucu](https://github.com/fornhere/hafiza-os/actions/runs/35442868256) — 19 Eylül 2026.
Her koşumda karşı işletim sistemine özgü bir test atlanır; örneğin junction testi
Windows'ta, POSIX flock uyumu macOS/Linux'ta çalışır. Bu testler model hesabı
veya GUI istemci desteği iddiası değildir. Python 3.10+ gerekir; CI 3.12 kullanır.

Modern kurucu jq veya bash gerektirmez. İstemcinin bulunması, hook desteği ve
komut kabuğu işletim sistemi desteğinden ayrı koşullardır.

## Kur ve denetle

Linux/macOS, kasa kökünde (ilk komut yalnız plan):

```sh
python3 -X utf8 araclar/ajan_kur.py --vault "$PWD" --agent all --with-hooks
python3 -X utf8 araclar/ajan_kur.py --vault "$PWD" --agent all --with-hooks --apply
```

`--with-hooks` verilmezse yalnız yönerge kurulur. Yalnız kullandığın istemciyi
`--agent claude`, `codex` veya `antigravity` ile seçebilirsin.
Windows PowerShell, gerçek Python kurulumu ile:

```powershell
py -3 -X utf8 .\araclar\ajan_kur.py --vault 'C:\Hafıza' --agent claude --with-hooks
py -3 -X utf8 .\araclar\ajan_kur.py --vault 'C:\Hafıza' --agent claude --with-hooks --apply
```

Claude için güncel exec-form desteği gerekir: gerçek Python executable `command`,
ayrı `args` dizisiyle doğrudan başlatılır; shell quoting kullanılmaz.
[Claude hook sözleşmesi](https://code.claude.com/docs/en/hooks#exec-form-and-shell-form).
Codex/Antigravity yalnız komut metni kullanır. Windows'ta istemcinin gerçekten
kullandığı kabuğu doğrulayıp `--hook-shell cmd` veya `--hook-shell posix` ver.
Kurucu kabuk tahmini yapmaz; cmd genişletme/metakarakteri içeren yolları reddeder.
PowerShell'den kurucuyu başlatmak hook'un PowerShell kullandığını göstermez.
Antigravity Windows kabuğu bu projede canlı doğrulanmış değildir.

`--home` istemci ev dizinini değiştirir. Codex hedef sırası: `--codex-home`,
`CODEX_HOME`, `--home/.codex`. Symlink hedefler kabul edilmez; macOS'ta geçici
örnekler için gerçek çözülmüş yolu kullan. `--agent generic --export /tam/yol/ajan.md`
yalnız kasa dışında Markdown üretir.

Kurucu bütün hedefleri önce denetler, değişen dosyaları zaman damgalı yedekler,
ilgisiz ayar/hook ve trust değerlerini korur. Sahiplik `.hafiza-os.json` yan
dosyasında tutulur; bu dosyayı ayarlardan ayrı silme. Düzenlenmiş sahiplik
çatışmasında işlem durur. Eşzamanlı hedef değişimi reddedilir; istemcileri
kapatıp kurulum yap. Dosyalar arası işletim sistemi işlemi atomik değildir;
yazma sırasında disk hatası olursa raporu/yedekleri inceleyip yeniden çalıştır.

Eski aynı-kasa Claude shell hook'ları veya `codex_kur.py` komutu bulunursa
kurulum çatışma bildirir. Geçişi incelemek için aynı komuta `--migrate-legacy`,
uygulamak için ayrıca `--apply` ekle. Yalnız tam bilinen aynı-kasa komutları
çıkarılır; başka kasaların ve kullanıcı hook'larının komutları korunur.
Eski Claude yollarının ham ve `shlex.quote` ile tırnaklanmış biçimleri tanınır;
`bash ...` gibi kullanıcı sarmalayıcıları otomatik sahiplenilmez.
`kur.sh` eski, isteğe bağlı POSIX yoludur; yeni sessiz kurulumla birlikte yeniden
çalıştırma. Eski dosyalar ve kişisel yönergeler otomatik silinmez; kullanıcıya
ait eski kapanış zorlamalarını ayrıca gözden geçir.

İstemciyi yeniden başlat; Claude/Codex `/hooks` ekranından bağlantıları incele.
Codex'te kullanıcı etkinleştirme/trust kararı ayrıca gerekir; kurucu güven açmaz.
Antigravity'de global grup kullanılır: güvenilmeyen workspace hook'ları
okunmayabilir. Hook cwd'si workspace olmayabilir ve `workspacePaths=[]` geçerlidir;
adaptör oturum kimliği ve transcript dosyasıyla bağ kurar.

## Pending → packet → review → recall

İlk beş gerçek kullanıcı girdisi kayıt üretmez. Sonraki anlamlı tamamlanmış iş
aday olur. Kaydetmeme, sır, alt ajan, eksik/başarısız terminal ve bilinmeyen
kanıt biçimleri güvenli biçimde dışlanır. Araç, sistem ve düşünce metinleri
kanıta alınmaz. Geçmiş hata ilerideki başarılı Stop'u kalıcı olarak engellemez.
PreInvocation ile eklenen bilinen `SYSTEM_SDK/EPHEMERAL_MESSAGE` satırı da
kullanıcı sayısına veya inceleme kanıtına katılmaz; bilinmeyen biçimler reddedilir.
Hook Stop'u engellemez ve kanonik dosyalara yazmaz.

Linux/macOS örnekleri; `<id>` yerine pending sonucunu kullan:

```sh
python3 -X utf8 araclar/client_sessions.py --vault "$PWD" pending
python3 -X utf8 araclar/client_sessions.py --vault "$PWD" packet --id '<id>'
python3 -X utf8 araclar/client_sessions.py --vault "$PWD" recall
python3 -X utf8 araclar/client_review.py --vault "$PWD" --reviewer-argv-json '["/absolute/path/to/your-reviewer"]'
python3 -X utf8 araclar/client_review.py --vault "$PWD" --reviewer-argv-json '["/absolute/path/to/your-reviewer"]' --apply
```

Windows PowerShell tek seferlik inceleme (kendi gerçek sağlayıcınla değiştir):

```powershell
py -3 -X utf8 .\araclar\client_sessions.py --vault 'C:\Hafıza' pending
py -3 -X utf8 .\araclar\client_sessions.py --vault 'C:\Hafıza' packet --id '<id>'
py -3 -X utf8 .\araclar\client_review.py --vault 'C:\Hafıza' --reviewer-argv-json '["C:\\Tools\\your-reviewer.exe"]'
py -3 -X utf8 .\araclar\client_review.py --vault 'C:\Hafıza' --reviewer-argv-json '["C:\\Tools\\your-reviewer.exe"]' --apply
py -3 -X utf8 .\araclar\client_sessions.py --vault 'C:\Hafıza' recall
```

Antigravity CLI ile Linux'ta canlı denenmiş inceleyici örneği (CLI oturumu açık olmalı):

```sh
python3 -X utf8 araclar/client_review.py --vault "$PWD" --reviewer-argv-json '["agy","--mode","plan","--print-timeout","60s","--output-format","text","--print","Araç kullanma; yalnız verilen paketi JSON sözleşmesine göre incele. {prompt}"]' --timeout 80 --apply
```

Bu tek seferlik çalıştırmadır; düzenli inceleme istenirse kendi zamanlayıcına
bağlanır. Kurucu kendiliğinden arka plan zamanlayıcısı kurmaz.

Reviewer varsayılan olarak istemi stdin'den okur, stdout'a sözleşmedeki JSON
kararını yazar. İstenirse argv'de tek `{prompt}` kullanılabilir; Windows toplam
komut sınırı aşılırsa `command_limit`, istem sınırı aşılırsa `prompt_limit`
verilir. Büyük paketlerde stdin tercih et. Dry-run süreç başlatmaz. Sağlayıcıyı
kullanıcı kurar; otomasyon veya API anahtarı kurulmaz. Elle üretilmiş karar için
`client_sessions.py ... review --id '<id>' --input-json karar.json` plan gösterir;
`--apply` incelenmiş episodik makbuzu yazar. Basit soru reviewer tarafından skip olur.
`--input-json` UTF-8 karar dosyasının göreli veya tam yolunu ya da doğrudan JSON
nesnesi metnini kabul eder. Dosyalar en fazla 128000 bayt olabilir.

Claude/Antigravity ve Codex bağlamı kaynak doğrulamalı incelenmiş makbuzları
bütçeli çağırabilir. Bu, kullanıcı profilini değiştirmez; semantik çıkarım ve
kanonik terfi ayrı mevcut inceleme/yazıcı sürecidir. Orijinal transcript'i silmek,
taşımak veya kanıt önekini değiştirmek recall'u geçersiz kılar. Yedek ve saklama
politikanı buna göre seç; makbuz transcript kopyası değildir.

## Kaldır

Aynı `--vault`, istemci/ev ve kabuk seçeneklerine `--remove --with-hooks` ekleyip
planı incele, sonra `--apply` ekle. Yalnız sahip olunan birebir girdiler çıkarılır;
kullanıcı ayarları ve trust korunur. Yalnız yönerge kaldırmak için `--with-hooks`
kullanma. Kasayı taşımadan önce eski konumdan kaldır, yeni konumda yeniden kur.

## İstemciler arasında ortak öğrenme döngüsü

Claude, Codex ve Antigravity aynı kasa araçlarını kullanır. Senkron hook model
çağrısı eklemeden, mevcut kaynak inceleme görevi sonunda
`konsolidasyon.py --vault KASA review-pending --limit 5 --apply` çalıştırılır.
Proje adayları için `--project-id` verilir. Yeni kurulumda ayrıca bakım görevi
ayarlanmalıdır; komutun kurulması zamanlayıcının çalıştığını kanıtlamaz.
Sonuçtan ders ve cevap atıf doğrulama sözleşmeleri [HAFIZA-DONGUSU.md](HAFIZA-DONGUSU.md).
