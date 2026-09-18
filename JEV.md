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
- `on`: doğrudan kaynak kartları ve katalog Jev puanıyla seçilir. Başlangıç eşiği 0–2 ölçeğinde 1.5; kalibre edilmiş güven olasılığı değildir. Bilgi kartı adayları bulunduğunda alanlar arası uyarlama önerileri eklenmez. Böyle bir aday yoksa yerel yol ve açıkça `proposed` aktarım davranışı korunur.

Modu `off` yapmak anında geri dönüş yoludur. Değişiklik yeni çağrıda okunur, servis yeniden başlatılmaz.

## Kaynak ve kapsam

Yalnız mevcut kodun uygun bulduğu incelemeden geçmiş, güncel kaynaklı, yetkili kapsamdaki adaylar gönderilir. Gönderilen alanlar kimlik, başlık, kısa ifade, kapsam ve alandır; ham sohbetler, tam kaynak dosyaları ve örnek varlıklar gönderilmez. Ağ cevabından sonra kaynak sürümleri yeniden kontrol edilir. Jev kaynak kapısını aşamaz.

Açık sunum/thumbnail/site birleşik sorularında en fazla üç alan ayrı değerlendirilir; kartın alanı kodla sınırlandırılır. Genel doğal dil ayrıştırıcısı değildir. Önce her alanın en yüksek puanlı kartı, sonra kalan kartlar seçilir. `coverage`, puanlanan alanın gerçekten karakter bütçesine sığıp sığmadığını ayırır. Görev paketindeki `knowledge_delivered` ayrıca tüm bölümün teslim edilip edilmediğini belirtir. Bu alanlar bütün olası alt soruların cevaplandığını kanıtlamaz.

## Sınırlar ve hata davranışı

Her erişim yüzeyi tek istek yapar; otomatik tekrar yoktur. Varsayılan üst sınır 32 aday, 96 soru ve 24000 girdi karakteridir. Bunlar token veya günlük harcama sınırı değildir. Görev paketi bilgi ve katalog için en fazla iki istek yapabilir; varsayılan bekleme toplamı yaklaşık 6 saniyeye kadar çıkar, buna yerel işlem süresi eklenir. Timeout olmuş uzak istek sağlayıcıda tamamlanıp ücretlenebilir. Sağlayıcıda ayrıca harcama sınırı belirlenmelidir.

Timeout, 401/403/429/5xx, bozuk yanıt, aday/girdi sınırı ve kaynak değişimi yerel geri dönüşle `degraded` olarak görünür; bunlar “kanıt yok” sayılmaz. Geçersiz kaynak geri dönüşte de teslim edilmez. `confidence` seçim veya izin için kullanılmaz.

Önbellek sorgu, sıralı adaylar, alan soruları, kaynak sürümleri, kapsam, istenen model, sağlayıcı, endpoint ve rubrik sürümüne bağlıdır. Boş seçim de bu anahtara bağlıdır; yeni aday eski boş seçimi geçersiz kılar. Önbellek yalnız puan ve sınırlı model metadata'sı saklar, dosyalar 0600'dür. Sağlayıcının döndürdüğü model adı kaydedilir; bir alias'ın arkasındaki gerçek ağırlık sürümünün sabit olduğu garanti edilmez. Alias kullanırken kısa TTL tercih edin.

Gölge modunu açmak arka plan otomasyonu kurmaz; ölçüm, normal erişim çağrıları sırasında çalışır. Üretimde `on` moduna geçmeden yeni kaynak aileleri, çoklu kanıt, desteksiz sorular, final paket teslimi, gecikme ve maliyet birlikte değerlendirilmelidir. Sentetik güvenlik testleri gerçek kullanıcı faydası değildir.
