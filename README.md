# Hafıza OS

**Ajanlar değişsin, hafızan aynı yerde kalsın.**

Hafıza OS; tercihlerini, kararlarını, işlerini ve kaynaklarını kendi Markdown
kasanda tutman için açık kaynak bir başlangıç sistemi. Claude Code, Codex ve
Antigravity aynı kasaya yönlendirilebilir. Dosya ve terminal erişimi olan diğer
ajanlara da ortak yönerge aktarabilirsin.

Dosyalar sende kalır; Obsidian onları gezmek için isteğe bağlı bir arayüzdür.
Kurulum, bütün sohbetlerini otomatik hatırlama garantisi değildir: yönerge
okuma, kaynaklı geri çağırma ve oturum kaydı farklı katmanlardır.

## Neler yapabilirsin?

- **Kaynağıyla hatırla:** göreve uygun küçük bağlam paketleri, kaynak yolu ve
  sürüm denetimiyle eski bilgiyi güncel karardan ayır.
- **Bilgileri bağla:** tercih, karar, ders ve örnekleri [bilgi ağında](BILGI-AGI.md)
  kapsamlarıyla birleştir; Obsidian'da kaynaklarına git.
- **Konu dosyaları oluştur:** [konu sentezi](KONU-SENTEZI.md) ile incelenmiş
  bilgileri birlikte gör. Bunlar kaynaklardan türetilen, yenilenebilir görünümlerdir.
- **İş ve çıktıları takip et:** [devam kapsülü, karar geçmişi ve çıktı
  takibi](CODEX.md) ile sonraki adımı ve doğrulanmış dosya sürümünü bul.
- **İstersen erişimi genişlet:** [Mem0](zihin/hafıza-sistemi.md) isteğe bağlı
  indeks, [Jev](JEV.md) varsayılan kapalı erişim/inceleme danışmanıdır.
  Kanonik kaynak yine yerel kasadır.

## Hangi ajanla?

| İstemci | Yönerge hedefi | İsteğe bağlı yerel runtime |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | Python exec hook, sessiz episodik aday |
| Codex | `~/.codex/AGENTS.md` | Mevcut adaptör ve ayrı konsolidasyon |
| Antigravity CLI (`agy`) | `~/.gemini/GEMINI.md` | PreInvocation/Stop, sessiz episodik aday |
| Diğer ajanlar | Seçilen Markdown | Yalnız yönerge aktarımı |

Linux yerel çekirdek kanıtı vardır; yeni değişikliğin kabulü bekliyor.
macOS/Windows yerel Python CI matrisi eklendi, koşum sonucu ve canlı istemci
kanıtı bekliyor. agy 1.1.27 altı insan girdisi ve başarılı Stop gözlendi;
Claude model denemesi 403 ile engellendi. Bunlar bütün istemcilerin her işletim
sisteminde doğrulandığı anlamına gelmez. [Ayrıntılı kurulum matrisi](ENTEGRASYONLAR.md).

## Hızlı başlangıç

Python 3.10+ ile kasa kökünde, Linux/macOS:

```sh
python3 -X utf8 araclar/ajan_kur.py --vault "$PWD" --agent all
python3 -X utf8 araclar/ajan_kur.py --vault "$PWD" --agent all --apply
```

Varsayılan yalnız yönerge köprüsüdür. Kayıt adaptörleri için `--with-hooks` ekle.
Eski aynı-kasa hook'larından geçiş ayrıca `--migrate-legacy` gerektirir. Kurucu
ilgisiz ayar ve trust değerlerini korur; jq/bash gerektirmez. Windows PowerShell,
istemci kabuğu, kaldırma ve yeniden başlatma: [entegrasyon rehberi](ENTEGRASYONLAR.md).

Yönerge köprüsü kayıt değildir; hook yakalaması da incelenmiş hafıza değildir.
Reviewer sağlayıcısını ayrıca yapılandır ve tek seferlik incelemeyi açıkça çalıştır.
İlk beş mesaj, kaydetmeme ve sır koruması sürer. Yeni native adaptörler yalnız
episodik aday üretir; kanonik terfi ve Codex konsolidasyonu ayrı süreçtir.
Paylaşılan kasadan kaynaklı recall, tam transcript senkronu değildir.
Kişisel profil şablonlarını kendin doldur; kurucu bunları güncellemez.

## Son eklenenler

- **19 Eylül:** üç istemci için ortak yönerge kurucusu ve genel Markdown aktarımı.
- **18 Eylül:** kaynaklı konu dosyaları, isteğe bağlı Jev danışmanı, bilgi ağı,
  karar/çıktı takibi ve hafızanın görünür kullanım bilgisi.

[Tüm güncelleme notları](GUNCELLEMELER.md) · [Kullanım doğrulama](KULLANIM-DOGRULAMA.md)
· [Fayda ölçümü](FAYDA-OLCUMU.md)

## Sınırlar ve gizlilik

Bu depo kişisel hafızanın kendisi değil, şablonudur. Kişisel kopyanı özel tut;
anahtar, parola ve özel yazışmaları kamu deposuna koyma. Görev ajanı doğrudan
kanonik kataloğa veya Mem0'a yazmaz; kaynaklı aday ayrı incelemeden geçer.
Mem0/Jev açıldığında belirli içerikler uzak servise gider; ilgili rehberleri oku.

Kaydın bulunması, cevabın doğruluğu ve işine faydası ayrı ölçülür. Konu
sentezinin kelime temelli yönlendirmesi bütün doğal dil sorularını çözmez;
Jev puanları da kullanıcı onayı değildir. İstemci izinleri, yönerge önceliği ve
bağlam sınırları nedeniyle bir dosyanın kurulmuş olması okunacağını kanıtlamaz.

<details>
<summary>Klasörler ve ileri kullanım</summary>

- `agents.md`: kasa kuralları ve çalışma biçimi.
- `zihin/`: kimlik, kaynaklı hafıza, son oturum ve açık işler.
- `komuta/`: öncelikler, ajan brief'i ve inceleme yönergeleri.
- `projeler/`, `günlük/`, `arşiv/`: süren işler, tarihli kayıtlar ve kapanmış işler.
- `gelen-kutusu/`: henüz ayıklanmamış girdiler.
- `araclar/`: yerel erişim ve bakım araçları; yalnız Mem0'a ait değildir.

Aşağıdaki örnekler POSIX kabuğu içindir; Windows'ta Python için `py -3 -X utf8` ve PowerShell yollarını kullan.

```sh
python3 araclar/hafiza.py --vault . validate
python3 araclar/hafiza.py --vault . context 'ilgili karar' --limit 5 --char-budget 1200
```

[Hafıza politikası](zihin/hafıza-sistemi.md), [konsolidasyon](komuta/hafıza-konsolidasyonu.md),
[görünürlük](HAFIZA-GORUNURLUGU.md) ve [yayın sınırları](YAYINLAMA.md).

</details>

## Lisans

MIT.
