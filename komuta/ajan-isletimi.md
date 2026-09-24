# Ajan işletim ayrıntıları

Bu belge yalnız görev gerektirdiğinde okunur. Açılış sözleşmesi [[agents]],
akış ve komut haritası [[SISTEM]] içindedir. Düzenleme: 2026-09-24.

## Kayıt ve bakım girişleri

- Kayıt uygunluğu, kaynak incelemesi ve güncel bakım adımları: [[komuta/hafıza-konsolidasyonu]].
- Veri sahipliği, tek yazıcı ve Mem0 politikası: [[zihin/hafıza-sistemi]].
- İstemci hook olayları, kurulum ve eski shell hook geçişi: [[ENTEGRASYONLAR]].
- Görünür kullanım ve doğrulanmış kayıt bildirimi: [[HAFIZA-GORUNURLUGU]].
- Kaynaklı cevap kontrolü ve koşullu dersler: [[HAFIZA-DONGUSU]].

## İş durumu

İş defteri ve türetilmiş görünüm [[SISTEM]] sahiplik tablosunda tanımlıdır.
Güncellik eşiği ve kayıt işlemleri [[komuta/hafıza-konsolidasyonu]] içindedir.
[[komuta/bu-hafta]] ikinci bir iş listesi değildir. Yeni konu türünde
[[komuta/ajan-briefingi]] yönlendirmesi güncellenebilir; otomatik commit zorunluluğu yoktur.

## Bağlantılar

Kalıcı notu ilgili merkezden erişilebilir tut; hedefi var olan bir wikilink
veya Markdown bağlantısı kullan. Modern hook'un kapanışta bağlantı denetimi
çalıştırdığı varsayılmaz; belge değişikliğinde hedefler ayrıca doğrulanır.

## Yürütme kuralları

**Kendi başına ilerle** — iş güvenliyse ve geri alınabilirse.
Dosya yazmak, düzenlemek, commit atmak, araştırmak, taslak hazırlamak,
denemek ve düzeltmek: sorma, yap. Sonucu raporla.

**Açık onay al** — iş şu dört kutudan birine giriyorsa:

- **Para hareketi** — ödeme, transfer, swap, abonelik, satın alma.
- **Dışarıya çıkan mesaj** — mail, mesaj, yayın, paylaşım, PR, yorum.
  Dışarı çıkan geri alınamaz.
- **Silme** — dosya, klasör, geçmiş, branch, hesap. Üzerine yazmak da silmektir.
- **Gizli bilgi** — parola, anahtar, token, kimlik, özel yazışma.
  Okumak da, taşımak da, göstermek de onaya tabidir.

Onay şu oturuma ve şu işe aittir. Bir kere "evet" dendi diye ikincisi serbest değil.
Emin değilsen: sor. Şüphe onay değildir.

---

## İşin kanıtı

**Her iş bir makbuz bırakır.**

Makbuz sayılan: bir commit, güncellenmiş bir not, diske yazılmış bir dosya,
gösterilmiş bir çıktı.

Makbuz sayılmayan: "yaptım", "hallettim", "tamamdır".
Beyan makbuz değildir. İz yoksa iş olmamıştır.

Bir işi bitiremediysen, bunu da yaz. Yarım iş bir makbuzdur; sessizlik değildir.

---

## Klasörler

| Klasör | Ne için |
|---|---|
| `gelen-kutusu/` | Ham giriş. Ayıklanmamış her şey önce buraya düşer. |
| `komuta/` | Yön. Bu hafta ne önemli, ajandan ne bekleniyor. |
| `projeler/` | Süren işler. Her projenin kendi dosyası. |
| `zihin/` | Kalıcı bellek. Ruh, çekirdek, açık işler, son oturum. |
| `günlük/` | Tarihli kayıtlar. Geriye dönük okunur, üzerine yazılmaz. |
| `arşiv/` | Bitmiş ve soğumuş olan. Silmek yerine buraya taşınır. |

Şüphedeysen `gelen-kutusu/`'na koy. Yanlış yere koymak, kaybetmekten iyidir.
