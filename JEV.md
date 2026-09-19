# İsteğe bağlı Jev erişim danışmanı

Jev, kaynakları doğrulanmış bilgi kartlarını ve hafıza kataloğu adaylarını soruya göre puanlar. `bilgi_agi`, `konu_sentezi` ve görev paketinin katalog yolu ortak istemciyi kullanır. Kanonik kayıt yazmaz, kullanıcı onayı üretmez. Varsayılan mod `off`.

## Kurulum

Kasada `komuta/jev.json` oluşturun:

```json
{
  "mode": "shadow",
  "model": "jev-1.13.0",
  "provider": "typesafe",
  "base_url": "https://api.typesafe.ai",
  "timeout": 3,
  "max_candidates": 32,
  "max_questions": 96,
  "max_input_chars": 24000,
  "cache_ttl": 300
}
```

`TYPESAFE_API_KEY` ortam değişkenini kullanın; isteğe bağlı `TYPESAFE_BASE_URL` endpoint'i değiştirir. Alternatif `env_file`, bu iki değişkeni içeren dosyanın mutlak yoludur; dosya shell olarak çalıştırılmaz. Anahtarı JSON'a veya Git'e yazmayın. Kişisel yapılandırma ve `.cache/jev/` Git dışında kalır. HTTPS veya yalnız loopback HTTP kabul edilir; yönlendirme takip edilmez.

- `off`: mevcut yerel davranış; ağ çağrısı yok.
- `shadow`: yerel sonuç teslim edilir, Jev adayları ve tanı bilgisi JSON'un `jev` alanına eklenir.
- `on`: doğrudan kaynak kartları ve katalog Jev puanıyla seçilir. Başlangıç eşiği 0–2 ölçeğinde 1.5; kalibre edilmiş güven olasılığı değildir. Kapsama uygun bilgi kartları bulunduğunda alanlar arası uyarlama önerileri eklenmez. Kapsama uygun hiçbir aday yoksa yerel yol korunur.

Modu `off` yapmak anında geri dönüş yoludur. Değişiklik yeni çağrıda okunur, servis yeniden başlatılmaz.

## Kaynak ve kapsam

Yalnız mevcut kodun uygun bulduğu incelemeden geçmiş, güncel kaynaklı, yetkili kapsamdaki adaylar gönderilir. Gönderilen alanlar kimlik, başlık, kısa ifade, kapsam ve alandır; ham sohbetler, tam kaynak dosyaları ve örnek varlıklar gönderilmez. Ağ cevabından sonra kaynak sürümleri yeniden kontrol edilir. Jev kaynak kapısını aşamaz.

Aday havuzu kaynak ve proje kapsamıyla sınırlandırılır; açık alan sözcüğü başka bir örtük kanıt ihtiyacını peşinen dışlamaz. Kaynak/not/ayrı ayrı/geri bildirim isteyen ve `ve`, `ile` veya noktalı virgülle ayrılan en fazla üç kanıt cümleciği ayrı değerlendirilir. Her cümleciğin açık alanı kodla korunur; `site için` gibi öndeki görev alanı diğer nesnelere de taşınır. Diğer çok alanlı sorularda sunum/thumbnail/site alanları ayrı değerlendirilir. Genel doğal dil ayrıştırıcısı değildir. Önce her alanın en yüksek puanlı kartı, sonra kalan kartlar seçilir. `coverage`, puanlanan alanın gerçekten karakter bütçesine sığıp sığmadığını ayırır. Görev paketindeki `knowledge_delivered` ayrıca tüm bölümün teslim edilip edilmediğini belirtir. Bu alanlar bütün olası alt soruların cevaplandığını kanıtlamaz.

## Sınırlar ve hata davranışı

Her erişim yüzeyi tek istek yapar; otomatik tekrar yoktur. Varsayılan üst sınır 32 aday, 96 soru ve 24000 girdi karakteridir. Bunlar token veya günlük harcama sınırı değildir. Görev paketi bilgi ve katalog için en fazla iki istek yapabilir; varsayılan bekleme toplamı yaklaşık 6 saniyeye kadar çıkar, buna yerel işlem süresi eklenir. Timeout olmuş uzak istek sağlayıcıda tamamlanıp ücretlenebilir. Sağlayıcıda ayrıca harcama sınırı belirlenmelidir.

Timeout, 401/403/429/5xx, bozuk yanıt, aday/girdi sınırı ve kaynak değişimi yerel geri dönüşle `degraded` olarak görünür; bunlar “kanıt yok” sayılmaz. Geçersiz kaynak geri dönüşte de teslim edilmez. `confidence` seçim veya izin için kullanılmaz.

Önbellek sorgu, sıralı adaylar, alan soruları, kaynak sürümleri, kapsam, istenen model, sağlayıcı, endpoint ve rubrik sürümüne bağlıdır. Boş seçim de bu anahtara bağlıdır; yeni aday eski boş seçimi geçersiz kılar. Önbellek yalnız puan ve sınırlı model metadata'sı saklar, dosyalar 0600'dür. Sağlayıcının döndürdüğü model adı kaydedilir; bir alias'ın arkasındaki gerçek ağırlık sürümünün sabit olduğu garanti edilmez. Alias kullanırken kısa TTL tercih edin.

Gölge modunu açmak arka plan otomasyonu kurmaz; ölçüm, normal erişim çağrıları sırasında çalışır. Üretimde `on` moduna geçmeden yeni kaynak aileleri, çoklu kanıt, desteksiz sorular, final paket teslimi, gecikme ve maliyet birlikte değerlendirilmelidir. Sentetik güvenlik testleri gerçek kullanıcı faydası değildir.

## Kaynak desteği ve ilişki incelemesi

İnceleme aracı, hafızayı değiştirmeden doğrulanmış kartları Jev'e değerlendirir:

```sh
python3 araclar/bilgi_agi.py --vault /path/to/vault review --project-id example
python3 araclar/bilgi_agi.py --vault /path/to/vault review --card-id first --card-id second --anchor-id first
```

`--card-id` tekrarlanabilir. Kimlikler mevcut, güncel, `reviewed` ve yetkili kapsamdaki kartlardan gelmelidir. İlişki incelemesi yalnız anchor ile aynı kapsamdaki, alanı örtüşen seçilmiş kartlar arasında yapılır. `--anchor-id` verilmezse yalnız kaynak desteği incelenir. Komut JSON danışman raporu verir; otomatik yazma veya sürekli tarama yapmaz. İstenirse çıktı ayrı bir inceleme dosyasına yönlendirilebilir, kanonik kart yerine kullanılamaz.

Jev'e kısa kart ifadesi ve daha önce karta bağlanmış **birebir kaynak alıntısı** gönderilir. Kaynağın geri kalanı ve örnek dosyalar okunup payload'a eklenmez. Kaynak alıntısının dosyada bulunması mekanik denetimdir; anlamsal destek ayrıca puanlanır. Sonuç `supported`, `contradicted`, `insufficient` veya `uncertain`; bunlar model önerisidir. İlişki sonucu `same_claim`, `incompatible`, `narrows` veya `uncertain` olur. `narrows` yönü kaynak karttan anchor'a doğrudur. Tekrar, supersede, silme veya onay otomatik uygulanmaz.

Kaynak/kart sürümleri iki aşama arasında ve sonda kontrol edilir. İlk aşama başarısızsa ilişki çağrısı atlanır. Yeterli bağlamı olmayan kısa alıntı kesin hükme zorlanmaz. Kaynak değişirse sonuçlar temizlenir; hata “destek yok” sayılmaz. İnceleme en fazla iki istek kullanır; aynı sınırlı istemci ve purpose'a bağlı cache geçerlidir. `off` yapılandırmasında rapor `disabled` döner.

Bu güncelleme daha fazla gerçek bilgi kaydettiği veya çelişkileri otomatik çözdüğü iddiası değildir. İnsan/ajan kaynak incelemesine ek bir kontrol sağlar; model etiketleri hatalı olabilir.

Vercel uyumluluğu: yalnız `provider: vercel` için, toplamı 1 olmayan iki ondalıklı olasılıklar kontrollü olarak ele alınır. Her olasılığın ±0,005 yuvarlama aralığında toplamı 1 olan bir dağılım bulunmalı ve bunun beklenen skoru, bildirilen skorun ±0,005 aralığıyla kesişmelidir. Sağlayıcının skoru değiştirilmez. Bu koşulu karşılayan yanıt `quantized_probability_count` ve tanı koduyla görünür; salt “toplam yakın” olması yeterli değildir. TypeSafe doğrudan sağlayıcı kontrolü katı kalır. Önbellek adaptör sürümünü de içerir.

## Henüz kaydedilmemiş bilgi adayını inceleme

```sh
python3 araclar/bilgi_agi.py --vault /path/to/vault review-candidate --input-json /path/to/proposal.json --project-id example
```

Girdi mevcut bilgi kartı şemasında, `status: proposed` olmalıdır. Kaynağı ve birebir alıntısı önceden mevcut olmalı; aynı kimlikle kart bulunmamalıdır. Araç adayı geçici olarak bile kaydetmez. Kaynak desteği ve en fazla sekiz güncel, aynı kapsam ve örtüşen alandaki mevcut kartla ilişki önerisi üretir; incelenmeyen kart sayısı ayrıca görünür. Bu sınırlı karşılaştırma bütün katalogda anlamsal tekrar kontrolünün yerine geçmez.

Aday JSON'u en fazla24000 karakter, kaynak sayısı en fazla8; istemci sınırları ayrıca geçerlidir. Kaynaklar her aşamadan sonra doğrulanır. Destek ve ilişki çağrıları arasında yapılandırma kapanırsa doğrulanmış destek sonucu korunur, değerlendirilmemiş ilişki üretilmez. Yeni aday retrieval'a dahil olmaz; kayıt ve terfi ayrı kaynak incelemesi gerektirir.

Kaynak öğrenme sırası: tamamlanmış kaynak → önerilen kart → mevcut hafızayla ayrı inceleme → gerekçeli kayıt/tekrar/erteleme → önceden dondurulmuş görev sorularıyla teslim kontrolü. Kaynak sayısını veya kart sayısını artırmak tek başına başarı ölçüsü değildir. API erişimi yoksa kaynak incelemesi yapılabilir; Jev değerlendirmesi yapılmış gibi raporlanmaz.

## Bütünleşik hafıza döngüsü

Bekleyen aday incelemesi, kaynaklı karar koşulları, doğrulanmış sonuçtan ders,
görev bağlamı ve cevap atıf kontrolü için [HAFIZA-DONGUSU.md](HAFIZA-DONGUSU.md).
Tek giriş `araclar/hafiza_dongusu.py`; bakım reviewer'ı ayrıca
`konsolidasyon.py review-pending` kullanabilir. Bunlar semantik kalite kanıtı
veya otomatik kanonik onay değildir; off/shadow/on sınırları korunur.
