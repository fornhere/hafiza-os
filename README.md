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

Linux, macOS ve Windows'ta **360 testlik paket başarılı**: [gerçek OS koşumu](https://github.com/fornhere/hafiza-os/actions/runs/35442868256).
İşletim sistemine özgü bir test diğer platformda atlanır. Antigravity CLI 1.1.27
ile Linux'ta gerçek hook → inceleme → farklı oturumda hatırlama zinciri doğrulandı.
Claude Code 2.1.261 için adaptör testleri geçti.
[Kurulum ve destek matrisi](ENTEGRASYONLAR.md).

## İlk kez kullanıyorsan

1. Bu sayfanın üstündeki **Code → Download ZIP** ile indir ve arşivi aç.
   Klasörü kalıcı tutacağın bir yere taşı; örneğin kullanıcı klasöründe `Hafiza`.
   Bu klasör senin **kasan**: notların ve ayarların burada duracak.
2. Bilgisayarında **Python 3.10+** ve dosya/terminal erişimi olan bir ajan
   (Claude Code, Codex veya Antigravity CLI) olsun. Obsidian isteğe bağlıdır;
   kullanıyorsan bu klasörü **Open folder as vault** ile aç.
3. Terminali çıkardığın klasörde aç. İçinde `agents.md`, `araclar` ve `zihin`
   klasörlerini görmelisin. Aşağıdaki komutlarda `claude` yerine kullandığın
   ajana göre `codex` veya `antigravity` yaz.

**Linux / macOS:**

```sh
python3 --version
python3 -X utf8 araclar/ajan_kur.py --vault "$PWD" --agent claude
python3 -X utf8 araclar/ajan_kur.py --vault "$PWD" --agent claude --apply
```

**Windows PowerShell:**

```powershell
py -3 --version
py -3 -X utf8 .\araclar\ajan_kur.py --vault "$($PWD.Path)" --agent claude
py -3 -X utf8 .\araclar\ajan_kur.py --vault "$($PWD.Path)" --agent claude --apply
```

İlk kurulum komutu yapılacakları gösterir; `--apply` olan komut uygular.
Ajanı yeniden başlat ve kasa klasörünü aç. İlk mesaj olarak şunu gönder:

> Bu klasör benim hafıza kasam. Önce agents.md dosyasını oku ve oradaki
> açılış sırasını izle. Sonra zihin/çekirdek.md için bana kısa bir mülakat yap;
> soruları tek tek sor. Cevaplarımdan bir profil taslağı çıkar, onayladığım
> bilgileri dosyaya yaz. Boş alanları tahmin ederek doldurma.

Bu başlangıç ajana kasanın yerini ve çalışma yönergelerini tanıtır.
Sohbetlerin arka planda kaydı ayrıca kurulur.
**[Adım adım kullanım rehberi →](KULLANIM.md)**: günlük mesaj örnekleri,
yeni sohbette hatırlama denemesi ve isteğe bağlı kayıt kurulumu.

## Günlük kullanım

Ajana normal konuşarak ne yapmak istediğini söyle:

- **Kaldığın yerden devam:** “Bu projede son kararımız neydi? Kaynağını bul,
  açık kalan işi söyle ve oradan devam edelim.”
- **Tercihini kullan:** “Metni yazmadan önce kasadaki anlatım tercihlerimi oku.”
- **Bilgiyi düzelt:** “Bu not artık geçerli değil. Kaynağını bul ve değişiklik
  taslağını göster.”
- **Kayıt dışında tut:** “Bu konuşmayı hafızaya alma.”

Ajanın verdiği dosya yolunu açarak sonucu kontrol et. İlk kullanımda geçmiş
bilgi bulunmaması normaldir; kasa senin notlarınla dolacak. Kişisel kasanı
bu kamu deposuna yükleme.

## Son eklenenler

- **19 Eylül, 2026.09.19.1:** yerel Windows/macOS/Linux motoru; Claude/Antigravity
  oturum adaptörleri, ortak makbuz erişimi, güvenli hook kurulum/geçişi ve üç OS testi.
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
