# Kaynaklı bilgi ağı

Bu katman tamamlanmış konuşmalardaki anlamlı geri bildirimi, kaynakları ve
kapsamı belirtilmiş bilgi kayıtlarına dönüştürür. Obsidian görünümü bu kayıtlardan
üretilir; not sayısı veya grafiğin yoğunluğu başarı ölçütü değildir.

## İncelemenin soruları

- Kullanıcı gerçekten ne söyledi; alıntı bu dar iddiayı destekliyor mu?
- Bu tercih, karar, ders veya örnek hangi proje ve iş türünde geçerli?
- Geri bildirim hangi dosyanın hangi sürümünü konu alıyor?
- Aynı bilgi zaten var mı; eski kararı değiştiriyor mu, çelişki mi var?
- Sonraki ilgili görevde bulunabiliyor mu; başka alana yanlış taşınıyor mu?

Anlamı inceleyen ajan belirler. Yerel araç kaynak ve kayıt sözleşmesini denetler;
metinden tercih çıkaran ayrı bir model veya yeni ücretli servis çalıştırmaz.
Makbuz üretimi ile bilgi incelemesi iki ayrı iştir. Makbuz checkpoint'i kaynakta
bulunan bütün anlamlı bilginin işlendiğini kanıtlamaz.

## Kapsam ve örnekler

“Sunumun akışı iyi” yalnız sunum akışına ilişkin geri bildirimdir. Bundan renk,
font veya site tasarımı tercihi çıkarılmaz. “Bu kapakta başlık daha okunaklı”
kapaktaki başlığın okunaklılığına ilişkin olabilir; bütün kapak tasarımının
kabulü değildir. Bir dosyanın üretilmiş, açılmış veya test edilmiş olması
kullanıcının onu beğendiği anlamına gelmez.

Her kayıt desteklenen iddiayı, özgün kaynak alıntısını, kaynak sürümünü ve
geçerli iş türünü taşır. İlgili örneklerin dosya sürümleri de korunur. Aynı
konuşmadaki birden çok çıktı varsa hangisinin kastedildiğini incele; belirsiz
örneği kullanıcı tarafından onaylanmış diye kaydetme. Kullanıcı tercihini
genişletmek yerine gerekçeli bekleme bırak.

İlişkileri anlamına göre kur: bir örnek bir tercihi gösterebilir veya yeni bir
karar öncekinin yerini alabilir. Sadece konu benzerliği destek/üstünlük kanıtı
değildir. Kaynağa bağlantı eklemek için eski makbuzları düzenleme; bilgi notundan
kaynağa bağlantı ve dizinden bilgi notuna bağlantı yeterlidir.

## Mevcut incelemeye bağlama

[Hafıza konsolidasyonu](komuta/hafıza-konsolidasyonu.md) bu katmanın işletim
sözleşmesidir. Mevcut inceleme rolü tamamlanmış kaynakları toplam bakım sınırı
içinde işler; eski makbuzu bulunan kaynaklar ilk geçişte ayrıca incelenir.
İlk beş mesaj, kaydetmeme ve özel veri kuralları değişmez. Ana görev ajanı
kanonik kataloğa/Mem0'a doğrudan yazmaz. Belirsizliği kullanıcıya sorabilirsin;
rutin kayıt için onay veya değerlendirme puanı isteme.

Kaynak değişirse kayıt yeni sürüm incelenene kadar güvenilir güncel bilgi
olarak kullanılamaz. Hash'i güncellemek inceleme yerine geçmez. Aynı ilke örnek
dosyası için de geçerlidir. Teknik bütünlük denetimi kullanıcının tercihini veya
çıktının kalitesini ispatlamaz.

## Başarıyı doğrulama

İncelemeden sonra ilgili görev sorusuyla gerçek kaydın geri geldiğini kontrol
et. Aynı kayıt başka iş türüne ait soruda geçerli tercih gibi sunulmamalıdır.
Kaynak veya örnek değiştiğinde eski sürümün dışlanmasını ayrıca sınayabilirsin.
Bu kontroller erişim mekanizmasını gösterir; sonraki gerçek teslimatta doğru
uygulama ve kullanıcı faydası ayrı gözlemdir.

Zamanlanmış rolün bu yönergeyi okuması kurulumun parçasıdır. Elle başarılı bir
çalıştırma zamanlanmış taramanın çalıştığını kanıtlamaz. Boş kuyruk, özellikle
eski makbuzların bilgi incelemesi yapılmadıysa, tam kapsama kanıtı değildir.


## Komutlar ve kayıt sözleşmesi

Komutları kasanın araç dizininin bulunduğu kökten çalıştır; `KASA` hedef kasadır.
Önce kaynakları gerçekten incele, girdiyi hazırladıktan sonra dry-run ve apply:

```bash
python3 araclar/bilgi_agi.py --vault KASA status
python3 araclar/bilgi_agi.py --vault KASA register --input-json bilgi.json
python3 araclar/bilgi_agi.py --vault KASA register --input-json bilgi.json --apply
python3 araclar/bilgi_agi.py --vault KASA context "sunum akış tercihi" --budget 1800
python3 araclar/bilgi_agi.py --vault KASA context "site tasarım tercihi" --budget 1800
```

`bilgi.json` zorunlu alanları:

- `id`: küçük harf/rakam, alt çizgi veya tireyle sabit kimlik.
- `title`, `statement`: başlık ve kaynağın desteklediği dar iddia.
- `kind`: `preference`, `decision`, `lesson` veya `example`.
- `scope`: `user` veya `project:PROJE_KIMLIGI`.
- `domains`: açık iş türü listesi. Mevcut sorgu eşlemesi `site`, `sunum`,
  `thumbnail` alanlarını tanır; `all` yalnız gerçekten alanlar üstü bilgidir.
- `status`: `reviewed`, `proposed`, `rejected` veya `superseded`.
- `sources`: en az bir `{path, sha256, evidence}`. `path` kasa içi göreli
  yoldur; `sha256` dosya baytlarının düz SHA-256 değeridir; `evidence` kaynaktaki
  en az 10 karakterlik birebir alıntıdır.

`reviewed` için gerçek inceleme rolünü belirten `reviewed_by` ve anlam/kapsam
incelemesini anlatan `review_note` gerekir. Bu alanlar kullanıcı kabulü değildir.
İsteğe bağlı `examples` öğeleri `path` (mutlak gerçek dosya), `sha256`, `role`,
`acceptance` (`unknown`, `accepted`, `rejected`) ve `evidence_source` (sources
listesinde sıfır tabanlı indeks) içerir. `accepted` veya `rejected` için ilgili
kaynakta geçen en az 10 karakterlik `acceptance_evidence` gerekir. Alıntının
gerçekten o dosyaya ve özelliğe işaret ettiğini ajan ayrıca incelemelidir.

İsteğe bağlı `relations` öğeleri `{target, reason}` biçimindedir; hedef mevcut
bilgi kimliğidir. İlişkinin anlamını/gerekçesini `reason` içinde açıkla.
Motor ilişki türleri üzerinden mantıksal çıkarım yapmaz. Var olan kaydı
değiştirirken `expected_version` alanına mevcut not dosyasının düz SHA-256
hash'ini ekle; önce kaynakları ve mevcut kaydı yeniden incele.

Notlar `bilgi/KIMLIK.md`, dizin `bilgi/README.md` altında üretilir; önceki
yönetilen sürümler `bilgi/.history/` altında korunur. Yönetilen notun elle
bozulmuş içeriği otomatik ezilmez; bağlamdan çıkar ve açık onarım gerekir.
Kaynak, örnek veya kayıt doğrulaması geçmeyen not geri çağrılmaz.

Proje kapsamlı sorguda `context` komutuna `--project-id PROJE_KIMLIGI` ekle.
Alana özel kayıt, açık alan eşleşmesi olmayan genel soruya taşınmaz. Bu ilk
sürüm bütün doğal dil ifadelerini ve iş türlerini tanımaz; boş sonuç tercih
bulunmadığının kesin kanıtı değildir.

## Kaynak incelemesini ayrıca kapatma

`status` gelen kutusunun doğrudan Markdown dosyalarını ve Codex oturum
makbuzlarını tarar. `unreviewed_sources` güncel inceleme kaydı bulunmayan,
`deferred_sources` gerekçeli bekleyen, `reviewed_sources` incelemesi geçerli
kaynakları verir. İncelenmemiş kaynak mutlaka kaçırılmış karar demek değildir.
Bu liste bütün diskteki konuşmaların keşfi değildir; kaynak tamamlanması ve
kaydetme izni mevcut konsolidasyon akışıyla ayrıca doğrulanır.

Bir kaynak için kayıtlar yazıldıktan veya anlamlı bilgi bulunmadığı gerçekten
incelendikten sonra ayrı değerlendirme girdisi hazırlanır:

```bash
python3 araclar/bilgi_agi.py --vault KASA assess-source --input-json inceleme.json
python3 araclar/bilgi_agi.py --vault KASA assess-source --input-json inceleme.json --apply
```

Girdi tam olarak `path`, `sha256`, `outcome`, `record_ids`, `reason`,
`reviewed_by` alanlarını taşır. `outcome`:

- `linked`: aynı kaynak sürümüne bağlı, erişime uygun `reviewed` kayıt
  kimlikleri `record_ids` içinde verilir. Zaten kapsanmış bilgi de bu yolla
  gösterilir; yalnız aynı konuya benzeyen eski kayıt yeterli değildir.
- `no_relevant_knowledge`: gerçekten incelenmiş kaynakta kalıcı anlamlı bilgi
  yoktur; `record_ids` boş kalır.
- `deferred`: somut engel `reason` içinde yazılır; `record_ids` boş kalır.

İnceleme geçmişi `bilgi/.reviews.jsonl` içinde tutulur. Kaynak değişirse veya
bağlı kayıt geçersizleşirse kaynak tekrar inceleme bekler. Makbuz checkpoint'i
bu değerlendirme yerine geçmez. Yeni kaydı görevde geri çağırma ve kapsam dışı
sorguda dışlama deneyi inceleme raporunda ayrıca belirtilir.


## Alanlar arası uyarlama

Sunum ve site arasında kaynağın açıkça belirttiği anlatı sırası, metin dili,
tipografi, renk, yerleşim veya hareket özelliği için uyarlama önerisi getirilebilir.
Bunlar `transfers` alanında `status=proposed` taşır; hedef alanın onaylı tercihi
olarak `records` listesine girmez. Kaynak kapsamı ve sürümü korunur. Özellik
eşlemesi sınırlı sözcük kurallarıdır; anlamsal uygunluğu ajan görevde inceler.
Bir özelliğin anılması onun beğenildiğini tek başına kanıtlamaz; kaynak cümledeki
olumsuzluk ve koşulları koru. Bahsedilmeyen görsel özellikleri çıkarma.
Doğrudan alan eşleşmeleri önerilerden önce gelir; proje sınırı ve bütçe korunur.
Mevcut köprü sunum ↔ site ile sınırlıdır; bütün alanlar birbirine açılmaz.


## Kaynaklı konu sentezleri

İncelenmiş kartlardan anlatım, görsel tasarım ve çalışma yöntemi için kaynaklı
konu görünümü üretilebilir: [[KONU-SENTEZI]]. Açık konu özeti sorgularında görev
bağlamı sentezi yeniden kurar; eski Markdown dökümü arama kaynağı değildir.
Kullanıcı kapsamlı görünüm: [[bilgi/konu-sentezleri/user]].
