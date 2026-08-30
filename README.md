# Hafıza OS

Claude Code'a **süreklilik** veren bir klasör yapısı.

Her yeni oturumda kendini baştan anlatmak yerine, ajan oturum açılışında dünü
okur: ne konuşuldu, ne karar verildi, ne yarım kaldı. Kapanışta da yazmadan
gitmesin diye bir mekanizma var — iyi niyete değil, hook'a bağlı.

Sihir yok. Birkaç markdown dosyası, üç hook ve bir anayasa.

---

## Ne yapar

- **Açılışta hatırlar.** `SessionStart` hook'u son oturum notunu ve aktif iş
  başlıklarını ajanın bağlamına enjekte eder. Sen bir şey yazmadan önce bilir.
- **Kapanışı zorlar.** 5 mesajı geçen bir oturum, hafızaya hiç dokunmadan
  kapanırsa bir "ihmal işareti" bırakılır; bir sonraki açılışta ajan bunu
  yüzüne söyler ve önce o boşluğu doldurur.
- **Kural koyar.** `agents.md` bir anayasadır: neyi sormadan yapar, neyi
  asla onaysız yapmaz (para, dışarı çıkan mesaj, silme, gizli bilgi),
  ve her işin bir **makbuz** bırakma zorunluluğu.
- **Sırrı dışarıda tutar.** Sertleştirilmiş `.gitignore` + commit'e sır
  girmesini engelleyen bir `pre-commit` hook'u.

---

## Kurulum

```bash
git clone https://github.com/fornhere/hafiza-os ~/Hafıza
cd ~/Hafıza
./kur.sh
```

`kur.sh` şunları yapar:

- `jq` ve `git` var mı bakar,
- `~/.claude/settings.json` dosyasını **yedekler**, sonra üç hook'u bağlar
  (eski/çift kayıtları temizleyerek — tekrar çalıştırmak güvenlidir),
- `CLAUDE.md → agents.md` linkini kurar,
- şablondaki `<TARİH>` alanlarını bugüne çevirir,
- git deposunu ve sır kapanını hazırlar.

Klasörü `~/Hafıza` yerine başka bir yere klonlayabilirsin; hook'lar kendi
yerlerini bulur. Kaldırmak için: `./kur.sh --kaldir` (ayarları temizler,
dosyalarına dokunmaz).

**Gereksinimler:** Claude Code, `git`, `jq`, bash. Linux ve macOS'ta çalışır.

---

## Kurduktan sonraki ilk üç şey

1. Claude Code'u bu klasörde aç. Açılışta **"Hafıza okunuyor..."** görüyorsan
   hook'lar devrede.
2. Ajana şunu söyle: **"`zihin/çekirdek.md` boş, bana mülakat yap."**
   Çekirdeği kendin doldurma. Kendi yazdığın tanıtım yazısı olur;
   mülakattan çıkan ise işletme talimatı.
3. `zihin/ruh.md` içinde varsayılan modunu seç (iş modu / sohbet modu) ve
   `komuta/bu-hafta.md`'ye ilk maddeni koy.

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

---

## Hook'lar

| Script | Ne zaman | Ne yapar |
|---|---|---|
| `oturum-basla.sh` | oturum açılışında | Son oturum notunu ve aktif iş başlıklarını bağlama enjekte eder; sayacı sıfırlar; ihmal işareti varsa uyarır. |
| `mesaj-say.sh` | her kullanıcı mesajında | Mesaj sayacını bir artırır. |
| `oturum-bitir.sh` | oturum kapanışında | 5'ten fazla mesaj yazıldıysa ve `son-oturum.md` hiç değişmediyse ihmal işaretini bırakır. |

Hook'lar kullanıcı ayarlarına bağlanır, yani **hangi klasörde çalışırsan çalış**
devreye girerler. Oturum sayaçları `.claude/durum/` içinde tutulur ve git'e girmez.

---

## Üç katman

Sistem üç katmanda hatırlar. İkisi zorunlu değil ama neyin nerede durduğunu
bilmek işin yarısı:

| Katman | Ne tutar | Nerede |
|---|---|---|
| **Dosyalar** (zorunlu) | Düşünce, karar, gerekçe, süren iş | bu klasör |
| **Mem0** (isteğe bağlı) | Tek satırlık kalıcı gerçekler | bulutta |
| **Obsidian** (isteğe bağlı) | Aynı dosyaları okuma/gezme arayüzü | yerelde |

> **Dosyalar düşünür, Mem0 hatırlar, Obsidian gösterir.**

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
  Yazdıktan sonra depo okunup kaydın orada olduğu görülmeli. (Madde 6, "yazdıktan
  sonra doğrula" — okuma script'i orada.)
- Mem0 yazdığın cümleyi **İngilizceye çevirip yeniden yazar.** Kaydı ararken
  birebir cümleyi değil kavramı ara.

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

## Kendine göre değiştir

Bu bir çerçeve, kutsal metin değil. Klasör adları Türkçe çünkü Türkçe
düşünen biri için yazıldı — hepsini değiştirebilirsin. Değiştirirsen
`agents.md` madde 1'deki okuma sırasını ve hook'lardaki dosya yollarını da
güncelle.

Değiştirmeden bırakılması önerilen tek şey **makbuz kuralı**: iz bırakmayan
iş, olmamış iştir.

## Lisans

MIT.
