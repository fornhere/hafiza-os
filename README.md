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

| İstemci | Ortak yönerge hedefi | Oturum otomasyonu |
|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | Mevcut `kur.sh` ile ayrıca kurulan shell hook'ları |
| Codex | `~/.codex/AGENTS.md` veya `CODEX_HOME` | [Codex adaptörü ve ayrı konsolidasyon](CODEX.md) |
| Antigravity | `~/.gemini/GEMINI.md` | Bu depoda transcript/hook adaptörü yok |
| Diğer yerel ajanlar | Seçtiğin Markdown dosyası | İstemciye elle bağlanır; otomasyon yok |
| Tarayıcı sohbetleri | Elle seçilmiş içerik aktarımı | Yerel kasaya kendiliğinden erişmez |

Linux mevcut sistemin test edildiği platformdur. Yeni köprünün yerel kabul
kontrolleri ve her istemcide canlı smoke kontrolü ayrıca yapılmalıdır.
macOS canlı denenmedi. Yerel Windows köprüsü yalnız manuel, bütçeli dosya
okuma yönergesi üretir; kaynak doğrulamalı CLI erişimi sağlamaz. Erişim ve
konsolidasyon araçları POSIX `fcntl` bağımlılığı nedeniyle yerel Windows'ta
desteklenmez. Tam motor (CLI erişimi, konsolidasyon ve hook'lar) için WSL
içinde, WSL'den görünen kasa/istemci yollarıyla ayrı kurulum gerekir.
Windows canlı istemci oturumuyla doğrulanmış değildir. [Destek ve sınırların tamamı](ENTEGRASYONLAR.md).

## Hızlı başlangıç: aynı kasayı bağla

Python 3.10+ yeterli; köprü ek paket indirmez. Aşağıdaki POSIX örneği kasayı
indirir, önce planı gösterir, sonra üç istemcinin yönergesini günceller:

```sh
git clone https://github.com/fornhere/hafiza-os "$HOME/Hafıza"
cd "$HOME/Hafıza"
python3 araclar/ajan_kur.py --vault "$PWD" --agent all
python3 araclar/ajan_kur.py --vault "$PWD" --agent all --apply
```

Yalnız kullandığın ajan için `all` yerine `claude`, `codex` veya `antigravity`
yaz. Kurucu kendi işaretli bloğunu ekler, diğer metni korur; değişen mevcut
hedefi zaman damgalı yedekler. Hook, güven ayarı, Mem0 veya zamanlayıcı kurmaz.

Yeni bir ajan oturumunda kasa yolunu ve örnek bir bilginin kaynak dosyasını
sorarak kontrol et. Ardından `zihin/çekirdek.md`, `zihin/ruh.md` ve
`komuta/bu-hafta.md` şablonlarını kendine göre doldur. Henüz kaydedilmemiş bir
geçmişi sistem biliyormuş gibi bekleme.

[Windows/PowerShell, özel yollar, genel aktarım, kaldırma ve smoke kontrolü →](ENTEGRASYONLAR.md)

## Oturum kaydı da istiyorsan

Aşağıdakiler POSIX/WSL içindeki, ortak yönergelerden bağımsız kurulumlardır;
yerel Windows köprüsü oturum otomasyonu sağlamaz:

- **Claude Code:** kasa kökünde `bash kur.sh`. Git, jq ve bash gerektirir;
  ayarları ve shell hook'larını değiştirir. [Kurucuyu](kur.sh) ve
  [hook sözleşmesini](agents.md#7-hooklar) incele; yeni oturumda `/hooks` ile
  bağlantıları doğrula. Kaldırma: `bash kur.sh --kaldir`.
- **Codex:** [CODEX.md](CODEX.md) içindeki adaptör, etkinleştirme ve isteğe
  bağlı düzenli inceleme adımlarını uygula. Dosyaları indirmek zamanlanmış
  konsolidasyonu başlatmaz.

Var olan kurulumu koruyabilirsin. Köprü eski kurucuların bloklarını silmez;
aynı kasaya işaret ettiklerini kontrol et. Kasa taşıma ve kaldırma işlemlerinde
her kurulumun kendi yönergesini izle.

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

Aşağıdaki CLI komutları POSIX/WSL içindir; yerel Windows'ta çalışmaz.

```sh
python3 araclar/hafiza.py --vault . validate
python3 araclar/hafiza.py --vault . context 'ilgili karar' --limit 5 --char-budget 1200
```

[Hafıza politikası](zihin/hafıza-sistemi.md), [konsolidasyon](komuta/hafıza-konsolidasyonu.md),
[görünürlük](HAFIZA-GORUNURLUGU.md) ve [yayın sınırları](YAYINLAMA.md).

</details>

## Lisans

MIT.
