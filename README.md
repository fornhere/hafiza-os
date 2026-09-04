# Hafıza OS

![lisans](https://img.shields.io/badge/lisans-MIT-black)
![platform](https://img.shields.io/badge/platform-Linux%20%C2%B7%20macOS-black)
![bağımlılık](https://img.shields.io/badge/ba%C4%9F%C4%B1ml%C4%B1l%C4%B1k-git%20%C2%B7%20jq%20%C2%B7%20bash-black)
![dil](https://img.shields.io/badge/dil-T%C3%BCrk%C3%A7e-black)

**Claude Code'a süreklilik veren bir klasör yapısı.**

Yapay zekâya bir asistan gibi davranıyorsun ama o her sabah kapıdan girip
"merhaba, siz kimsiniz?" diyor. Dün anlattığın her şey, verdiğin kararlar,
"bir daha böyle yapma" dediğin hata — hepsi silinmiş. Bu depo o sorunu
markdown dosyaları ve beş hook ile çözüyor.

Her yeni oturumda kendini baştan anlatmak yerine, ajan oturum açılışında dünü
okur: ne konuşuldu, ne karar verildi, ne yarım kaldı. Kapanışta da yazmadan
gitmesin diye bir mekanizma var — iyi niyete değil, hook'a bağlı.

Sihir yok. Birkaç markdown dosyası, beş hook ve bir anayasa.

---

## Ne yapar

- **Açılışta hatırlar.** `SessionStart` hook'u son oturum notunu ve aktif iş
  başlıklarını ajanın bağlamına enjekte eder. Sen bir şey yazmadan önce bilir.
- **Kapanışı zorlar.** 5 mesajı geçen bir oturum, kimlikli ve `[[bağlantılı]]`
  bir makbuz yazmadan kapanamaz. `Stop`/`PreCompact` kontrolü önce yazmayı
  ister; son güvenlik ağı eksik oturumu transcript yolu ile listeye alır.
- **Grafiği bağlı tutar.** Bağlantı denetimi, Obsidian'da gelen veya giden
  bağlantısı olmayan kalıcı notları kapanışta yakalar.
- **Kural koyar.** `agents.md` bir anayasadır: neyi sormadan yapar, neyi
  asla onaysız yapmaz (para, dışarı çıkan mesaj, silme, gizli bilgi),
  ve her işin bir **makbuz** bırakma zorunluluğu.
- **Sırrı dışarıda tutar.** Sertleştirilmiş `.gitignore` + commit'e sır
  girmesini engelleyen bir `pre-commit` hook'u.
- **Kalıcı gerçekleri kimliklendirir.** *(isteğe bağlı)* Mem0 kurduysan
  `araclar/hafiza.py`, her kalıcı gerçeği kaynağına ve içerik hash'ine
  bağlayan bir kapı kurar: aday kuyruğu, çelişki kontrolü, okuyarak doğrulanan
  senkron, bütçeli bağlam paketi ve erişim regresyonu.

---

## Neden çalışıyor — beş kavram

Kurulumdan önce beş şeyi bilmek, sonradan neyi neden değiştireceğini de öğretir.

**1. Model neden unutuyor?** Modeller *durumsuz* çalışır: modelin kendisinde
hiçbir şey saklanmaz. Sen mesaj yazdığında, o ana kadarki konuşmanın tamamı
modele her seferinde baştan gönderilir. Model konuşmayı hatırlamıyor — her
mesajda konuşmanın tümünü yeniden okuyor. Oturum kapanınca o metin gider;
model senin için yeniden doğar, bomboş.

**2. Bağlam (context) nedir?** Modele her seferinde gönderilen o metin yığını.
Sınırlı bir alan — **bir masanın üstü** gibi. Masada ne varsa model bilir;
masada olmayan şey onun için dünyada yoktur. Bu sistemin tamamı tek bir soruya
verilmiş cevaptır: *her oturum başında masaya ne koyacağız?*

**3. Hook (kanca) nedir?** Claude Code'a "şu olay olduğunda şu script'i
çalıştır" diyebilirsin: oturum açılınca, mesaj gönderilince, oturum kapanınca.
Kritik nokta şu: **hook'u yapay zekâ çalıştırmıyor, program çalıştırıyor.**
Unutması mümkün değil. Hafızayı iyi niyete değil mekanizmaya bağlayan şey bu.

**4. Semantik hafıza ne demek?** Tek satırlık gerçekleri saklayan ve kelimeyle
değil **anlamla** arayan bir katman (bkz. Mem0). "Kullanıcı nasıl cevap sever?"
diye sorduğunda, içinde "cevap" kelimesi geçmese bile *"Kısa ve net yazılardan
hoşlanır"* kaydını bulur. Dosya gibi yüklenmez; ajan ihtiyaç duyunca sorar.

**5. Neden düz dosyalar?** Sen okuyabilirsin, sen düzeltebilirsin, git ile
geçmişi tutulur, hiçbir şirkete bağımlı değil. Arayüz gelir geçer; dosyalar kalır.

---

## Kurulum

```bash
git clone https://github.com/fornhere/hafiza-os ~/Hafıza
cd ~/Hafıza
./kur.sh
```

`kur.sh` şunları yapar:

- `jq` ve `git` var mı bakar,
- `~/.claude/settings.json` dosyasını **yedekler**, sonra beş hook'u bağlar
  (eski/çift kayıtları temizleyerek — tekrar çalıştırmak güvenlidir),
- global `~/.claude/CLAUDE.md` içine işaretli başlangıç talimatını ekler,
- `CLAUDE.md → agents.md` linkini kurar,
- şablondaki `<TARİH>` alanlarını bugüne çevirir,
- git deposunu ve sır kapanını hazırlar.

Klasörü `~/Hafıza` yerine başka bir yere klonlayabilirsin; hook'lar kendi
yerlerini bulur. Kaldırmak için: `./kur.sh --kaldir` (ayarları temizler,
dosyalarına dokunmaz).

**Gereksinimler:** Claude Code, `git`, `jq`, bash. Linux ve macOS'ta çalışır.

---

## Kurduktan sonraki ilk üç şey

1. Claude Code'u bu klasörde aç. `/hooks` ile beş hook'u, `/context` ile
   global Hafıza OS talimatını gördüğünü doğrula.
2. Ajana şunu söyle: **"`zihin/çekirdek.md` boş, bana mülakat yap."**
   Çekirdeği kendin doldurma. Kendi yazdığın tanıtım yazısı olur;
   mülakattan çıkan ise işletme talimatı.
3. `zihin/ruh.md` içinde varsayılan modunu seç (iş modu / sohbet modu) ve
   `komuta/bu-hafta.md`'ye ilk maddeni koy.

---

## Çalıştığını kanıtla — amnezi testi

Sistemi kurmak bir şey ifade etmez; **kanıtlaması** eder. En dürüst test şu:

1. Bir oturum boyunca gerçek bir iş yap. Bir karar ver, bir dosya değiştir.
2. Oturumu kapat. Ajana kapanış notunu yazdır (madde 4) — ya da yazdırma,
   hook'un seni yakalayıp yakalamadığını gör.
3. **Bilgisayarı kapat, yeniden aç.** Claude Code'u bu klasörde başlat.
4. Tek bir soru sor: **"Dün ne yapmıştık?"**

Kurulumdan önce alacağın cevap: *"Önceki konuşmalara erişimim yok."*
Kurulumdan sonra: dünkü kararlar, yarım kalan iş, sıradaki adım.

Aradaki fark bir model güncellemesi değil, daha pahalı bir abonelik de değil —
birkaç markdown dosyası ve beş script.

---

## Klasörler

| Klasör | Ne için |
|---|---|
| `gelen-kutusu/` | Ham giriş. Ayıklanmamış her şey önce buraya düşer. |
| `komuta/` | Yön. Bu hafta ne önemli, ajandan ne bekleniyor. |
| `projeler/` | Süren işler. Her projenin kendi `DURUM.md`'si. |
| `zihin/` | Kalıcı bellek. Ruh, çekirdek, açık işler, son oturum. |
| `günlük/` | Tarihli kayıtlar. Geriye dönük okunur, üzerine yazılmaz. |
| `arşiv/` | Bitmiş ve soğumuş olan. Silmek yerine buraya taşınır. |

Üç dosya sistemin bel kemiği:

- **`agents.md`** — anayasa. Sekiz madde. Her oturumun ilk okuduğu şey.
- **`zihin/çekirdek.md`** — kullanıcı hakkında değişmesi zor doğrular.
  Her maddenin altında *"bunun ajana yüklediği"* satırı vardır: o madde
  ajanın davranışını nasıl değiştiriyor. O satır yoksa madde süstür.
- **`zihin/son-oturum.md`** — dün ne oldu. Hook bunu okur.

`araclar/` klasörü Mem0 katmanının kapısıdır ve isteğe bağlıdır; Mem0
kurmadıysan silebilirsin.

---

## Hook'lar

| Script | Ne zaman | Ne yapar |
|---|---|---|
| `oturum-basla.sh` | oturum açılışında | Son oturum notunu ve aktif iş başlıklarını bağlama enjekte eder; resume sayacını korur; eksik makbuzları hatırlatır. |
| `mesaj-say.sh` | her kullanıcı mesajında | Mesaj sayacını bir artırır. |
| `hafiza-kontrol.sh` | `Stop` ve `PreCompact` öncesinde | Uzun oturumda kimlikli, bağlantılı makbuz yoksa kapanışı durdurur. |
| `baglanti-denetle.sh` | kontrolün içinde veya elle | Bağlantısız Markdown notlarını listeler. |
| `oturum-bitir.sh` | oturum kapanışında | Eksik makbuzu transcript yolu ile kalıcı kontrol listesine yazar. |

Hook'lar kullanıcı ayarlarına bağlanır, yani **hangi klasörde çalışırsan çalış**
devreye girerler. Oturum sayaçları `.claude/durum/` içinde tutulur ve git'e girmez.

---

## Üç katman

Sistem üç katmanda hatırlar. İkisi zorunlu değil ama neyin nerede durduğunu
bilmek işin yarısı:

| Katman | İnsandaki karşılığı | Ne tutar | Nerede |
|---|---|---|---|
| **Dosyalar** (zorunlu) | Epizodik — *"dün akşam ne yaptım?"* | Süreklilik, kararlar, süren işler | bu klasör |
| **Günlük → arşiv** (zorunlu) | Prosedürel — *"bisiklet sürmeyi bilmek"* | Damıtılmış dersler, kapanmış işler | `günlük/`, `arşiv/` |
| **Mem0** (isteğe bağlı) | Semantik — *"annemin doğum günü 3 Mayıs"* | Tek satırlık çıplak gerçekler | bulutta, indeks |
| **Obsidian** (isteğe bağlı) | — (arayüz, hafıza değil) | Aynı dosyaları gezme/okuma | yerelde |

Neden ayrı katmanlar? Her birinin **değişme hızı** ve **kullanılma biçimi**
farklı. Süreklilik her oturumda yüklenir → kısa kalmalı. Arşiv büyür ama
yalnızca gerektiğinde açılır. Semantik katman hiç yüklenmez → aranır.
Hepsini tek dosyaya yığarsan ya şişer ya da ajan okumaz.

> **Dosyalar düşünür, Mem0 hatırlar, Obsidian gösterir.**

Mem0 katmanını kurarsan bir kural daha eklenir: **dosyalar kanoniktir, Mem0
indekstir.** İkisi çelişirse dosyalar kazanır — Mem0 buradan yeniden
üretilebilir, tersi doğru değildir.

### Mem0 — kalıcı gerçekler katmanı *(isteğe bağlı)*

Anayasa madde 6 bunu tarif eder. Kurmadıysan o maddeyi sil; sistemin geri
kalanı Mem0'sız sorunsuz çalışır.

Ne işe yarar: `zihin/` dosyaları bir oturumun *hikâyesini* tutar, Mem0 ise
oturumdan bağımsız **tek cümlelik gerçekleri**. "Kısa kurgu sever",
"dosya adlarını Türkçe yazar" gibi. Bunlar altı ay sonra da doğrudur.

Tek kural: **kimlik geçer, haber geçemez.** Bir kayıt altı ay sonra da hem
doğru hem işe yarar olacaksa girer. "Bugün şunu yaptım" girmez — o
`zihin/son-oturum.md`'nin işi.

Kurulumu (API anahtarını [mem0.ai](https://mem0.ai) üzerinden alırsın):

```bash
claude mcp add mem0 --env MEM0_API_KEY=<anahtarın> -- npx -y @mem0/mcp-server
```

Anahtarı bu klasöre **yazma** — anayasa madde 6'nın kırmızı çizgisi budur.
`komuta/anahtarlar.md` sadece anahtarın nerede durduğunu söyler, değerini asla.

İki tuzak, ikisi de yaşanarak öğrenildi:

- Mem0 `"Memory added successfully"` dediği hâlde kaydı **sessizce düşürebilir.**
  Yazdıktan sonra depo okunup kaydın orada olduğu görülmeli.
- Mem0 yazdığın cümleyi **İngilizceye çevirip yeniden yazar.** Kaydı ararken
  birebir cümleyi değil kavramı ara.

#### Kapı: dosyalar kanonik, Mem0 indeks

Mem0'ı doğrudan kullanmak yerine `araclar/hafiza.py` üzerinden kullanman
önerilir. Sebep: Mem0'un güncel çıkarım yolu **eklemelidir** — düzeltmek için
`add` çağırırsan eski ve yeni gerçek yan yana yaşar ve ikisi de geri çağrılır.

Kapı bunu şöyle çözer. Her kalıcı gerçek `zihin/hafıza-kataloğu.jsonl` içinde
tek satırlık bir kayıt olur; kaydın kendi kimliği, kaynak dosyası, içerik
hash'i, geçerlilik aralığı ve karşılık geldiği `mem0_id` alanı vardır. Düzeltme
yeni kayıt eklemez, mevcut `mem0_id`'yi **günceller**.

```bash
export HAFIZA_MEM0_USER_ID=kullanici-adin

python3 araclar/hafiza.py --vault . validate      # şema + kaynak + hash, ağa çıkmaz
python3 araclar/hafiza.py --vault . sync          # farkı göster (dry-run)
python3 araclar/hafiza.py --vault . sync --apply  # uygula + okuyarak doğrula
python3 araclar/hafiza.py --vault . audit         # drift / yetim / tekrar
python3 araclar/hafiza.py --vault . context "…"   # bütçeli, kaynaklı bağlam
python3 araclar/hafiza.py --vault . eval          # erişim regresyonu
```

Getirdikleri:

| Sorun | Kapının cevabı |
|---|---|
| Aynı gerçeğin iki sürümü birlikte dönüyor | `mem0_id` eşlemesi; `add` değil `update` |
| Kaydın nereden geldiği belli değil | `source_path` + `source_anchor` + `source_hash` |
| Ajanın çıkarımı sessizce kalıcı oluyor | Aday kuyruğu; `reviewed_by` olmadan terfi yok |
| Çelişen gerçek eskisini siliyor | `superseded` + `supersedes`; tarihçe korunur |
| Eskimiş bilgi hâlâ geri çağrılıyor | `status` ve `valid_to`; `context` yalnız `active` verir |
| "Hafıza çalışıyor" ölçülemiyor | `araclar/hafıza-testleri.örnek.json` biçiminde regresyon |

Kendi test setini `araclar/hafıza-testleri.json` olarak yaz: her vaka bir soru,
beklenen `memory_id`'ler ve **yasaklı** `memory_id`'ler içerir. Yasaklı liste,
geçici bir durumun kalıcı gerçek gibi geri çağrılmasını yakalar.

Şema ve politikanın tamamı `zihin/hafıza-sistemi.md` içinde. Araç yalnız
standart kütüphane kullanır ve `python3 -m unittest test_hafiza.py` ile
`araclar/` içinde test edilir.

### Obsidian — okuma arayüzü *(isteğe bağlı)*

Bu klasör düz markdown olduğu için [Obsidian](https://obsidian.md) ile
**kasa (vault) olarak açılabilir.** Obsidian'ı aç → *Open folder as vault* →
bu klasörü seç. Dosya biçimi değişmez, hiçbir şey taşınmaz.

Ne kazandırır: dosyalar arası `[[bağlantı]]`lar tıklanabilir olur, grafik
görünümü hangi notun neye bağlandığını gösterir, arama tüm hafızayı tarar,
telefondan okuyabilirsin.

**Ne kazandırmaz — ve bu önemli:** ajan Obsidian'ı kullanmaz. O düz dosyaları
okur. Obsidian **senin** için bir pencere; sistemin çalışması ona bağlı değil.
Kurmasan da hiçbir şey eksilmez.

`.gitignore` içinde `.obsidian/workspace.json` gibi satırlar bu yüzden var:
Obsidian'ın pencere düzeni kişiseldir, hafızanın içeriği değildir — git'e girmez.

---

## Sorun giderme

**Hook'ların çalıştığını elle doğrula.** Hook'lar stdin'den JSON okur, yani
Claude Code olmadan da test edilirler:

```bash
printf '{"session_id":"test"}' | bash .claude/hooks/oturum-basla.sh
```

Geçerli bir JSON basmalı; içinde `## HAFIZA — Son Oturum` ve aktif iş
başlıkların görünür. Boş çıktı veya hata varsa `jq` kurulu değildir.

Kapanış kontrolünü denemek için: aynı `session_id` ile `mesaj-say.sh`'ı altı
kez çalıştır, `son-oturum.md`'ye dokunma, sonra aynı JSON'u
`hafiza-kontrol.sh`'a ver. `"decision":"block"` dönmeli. Dosyanın en üstüne
`<!-- hafiza-session:test mesaj:6 -->` işaretli ve `[[Ana Sayfa]]` bağlantılı
bir bölüm ekleyince aynı kontrol sessizce geçmelidir.

**Bilinen davranışlar:**

| Durum | Ne olur |
|---|---|
| `jq` kurulu değil | `kur.sh` durur, ayarlara dokunmaz, kurulum komutunu yazar |
| `settings.json` bozuk JSON | `kur.sh` durur, dosyayı **değiştirmez** |
| `kur.sh` ikinci kez çalıştırılır | Çift kayıt olmaz; eski kayıtlar temizlenip yeniden yazılır |
| `--kaldir` | Hafıza OS hook'ları ve işaretli global talimat bloğu çıkarılır; diğer ayarların korunur |
| Ayar dosyası kurulumdan önce yoktu | `--kaldir` geriye boş dosya bırakmaz, siler |

Her kurulum öncesi `settings.json` bir zaman damgalı yedeğe kopyalanır
(`settings.json.yedek-<tarih>`); bir şey ters giderse geri dönebilirsin.

**Platform:** Linux'ta test edildi. macOS'ta çalışacak şekilde yazıldı
(GNU/BSD `stat` farkı hook'ta ele alınıyor) ama macOS'ta gerçek bir oturumla
denenmedi. Windows için WSL gerekir.

---

## Kaçınılan tuzaklar

Bu yapı boş bir sayfadan çıkmadı; benzer bir sistemi bir yıl kullanıp
"sıfırdan kursam neyi farklı yapardım" diye soran birinin listesinden çıktı.
Şunlar bilerek böyle:

- **Bulut senkronu yok, git var.** Böyle bir klasörü iCloud/Drive üzerinde
  tutmak `X 2.md` tarzı çakışma kopyaları üretiyor — yüzlercesi. Yedek git ile
  alınır.
- **Klasör adlarında emoji ve numara yok.** Obsidian'da hoş duruyor,
  terminalde ve script'te baş ağrısı oluyor.
- **Kişisel veri ile sistem ayrı.** `zihin/çekirdek.md` gibi dosyalar bir kez
  git geçmişine girdiğinde kolay kolay çıkmaz. Bu depo **şablondur** — kişisel
  katman senin kendi (tercihen private) kopyanda yaşar.
- **İlk gün 6 klasör, 15 değil.** Kullanılmayan klasör, yapı değil gürültüdür.
  İhtiyaç doğunca eklersin.
- **Otomasyon ilk hafta yok.** Önce elle yaz, neyin tekrarlandığını gör,
  sonra script'e dök. Ters sırada yaparsan yanlış şeyi otomatikleştirirsin.
- **Ajan brief'i kısa.** `komuta/ajan-briefingi.md` şiştiği an okunmaz hâle
  gelir; o yüzden dosyanın kendi içinde "şişme" uyarısı var.

---

## Kendine göre değiştir

Bu bir çerçeve, kutsal metin değil. Klasör adları Türkçe çünkü Türkçe
düşünen biri için yazıldı — hepsini değiştirebilirsin. Değiştirirsen
`agents.md` madde 1'deki okuma sırasını ve hook'lardaki dosya yollarını da
güncelle.

Değiştirmeden bırakılması önerilen tek şey **makbuz kuralı**: iz bırakmayan
iş, olmamış iştir.

## Lisans

MIT.
