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
  "timeout": 2.5,
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

## 1. aşama: rerank ve hook gölgesi

Varsayılan `rerank_facets: true` ile birden çok ihtiyaç içeren sorgular, aynı aday havuzu üzerinde en fazla üç facet için `retrieval_rerank_facets` amacıyla ayrı ayrı sorulur; tek ihtiyaçta veya `rerank_facets: false` ayarında mevcut `retrieval_rerank` sorusu ve önbellek anahtarı korunur. Önce her facet için `rerank_p2` eşiğini karşılayan en iyi aday, sonra facet'ler üzerinden en yüksek seviye 2 olasılığına göre kalan adaylar seçilir; paketlerde aday sayısı × facet sayısı `max_questions` sınırını aşmaz. Sonuçtaki `facet_count` ve `rerank_purpose` kullanılan yolu, çok ihtiyaçlı yoldaki `coverage` ise rerank çıktısında teslim edilen katalog kayıtları ve bütçeye sığan notlar üzerinden her facet için `covered` veya `unresolved` durumunu bildirir.

Aday havuzunun boyutu `rerank_candidates` ile belirlenir (varsayılan 24); aday, soru veya girdi karakteri bütçesi aşılırsa havuz sırası korunarak paketlere bölünür ve en fazla üç paket paralel değerlendirilir. Paket hatasında veya tek başına bütçeye sığmayan adaylarda yerel sıralama kullanılır; başarılı paketlerin kabul ettiği adaylar önce gelir, hiçbir paket değerlendirilemezse tam yerel yola dönülür.

`QUERY_EXPANDERS` / `expand_query` varsayılan olarak yerel Türkçe ek zincirleri ve mevcut eşanlamlı gruplarından en fazla 24 terim üretir; havuz önce özgün sorgu örtüşmesi, eşitlikte genişletilmiş terim örtüşmesiyle sıralanır ve `arama_anahtarlari` da yerel aramaya katılır.
Genişletme yalnız aday üretir, teslim kararı rerank'te kalır; gelecekte eklenebilecek `fn(query) -> Iterable[str]` genişleticilere sır/özel istem gönderilmemeli, mevcut sürüm LLM genişleticisi içermez.

`retrieval_mode: rerank` önce üç seçenekli bir kapı kullanır: `search_memory`, `no_memory`, `insufficient_context`. Varsayılan `rerank_gate_scope: memory` ayarında son iki karar yalnız katalog kaydı ve bilgi notu seçimini susturur; proje kartı, prosedür ve dersler kendi kurallarıyla devam eder. `rerank_gate_scope: all` tüm paketi susturur ve yalnız kontrollü karşılaştırma içindir. Kapı eşiği `rerank_gate_threshold` (varsayılan 0,70), aday seçimi `rerank_p2` (varsayılan 0,75) ile ayarlanır. Sıralama seviye 2 olasılığını kullanır, en fazla üç kayıt seçer. Eski `rerank_threshold` yalnız uyumluluk kaydıdır. Kapı en fazla 1 saniye, tüm Jev istekleri ortak 2,5 saniyelik son tarihle sınırlanır. Tüm paketler başarısız olduğunda yerel sonuca dönülür ve `degraded` olarak raporlanır.

`komuta/gorev-baglam.json` içindeki isteğe bağlı `erisim` nesnesi iki güvenlik ağını ayarlar:

- `static_preferences: "off" | "rerank" | "always"` (varsayılan `"rerank"`) ve `static_preferences_chars: 0..2000` (varsayılan `600`): kaynak ve kapsam denetiminden geçen, henüz seçilmemiş `category: preference/profile` katalog kayıtlarından yalnız istemle sözcük eşleşmesi olan tercihler eklenir. Eşleşme, `arama_anahtarlari` dahil `search_text` üzerinden mevcut `rank_records` sözcük ve ayırt edici terim kurallarını kullanır. Önce ilgililik skoru, eşitlikte kullanıcı/proje kapsamı ve kimlik sırası kullanılır; ifadelerin toplam karakter sınırına sığmayan kayıt atlanır, sonraki denenir. Mevcut kaynak sürümü, kart ve paket bütçesi denetimleri sürer. Varsayılan yalnız rerank'te açıktır; ilgili tercihler kapı veya üç kayıt sınırıyla elense de bu bloktan eklenebilir, local/assist/on varsayılan teslim davranışı değişmez. Kapalı kapıya rağmen çalışır; `rerank_gate_scope: all` erken boş dönüşü bu bloğu da susturur.
- `gate_override_min_terms: 0..5` (varsayılan `2`, `0` kapalı): yalnız rerank'te, kaynak ve kapsam denetiminden geçen bir kayıt sorgunun en az bu kadar ayırt edici terimini eşlerse kapı yeniden açılır. Terimler `rank_records` ile aynı sıklık ve sözcük eşleşmesi kurallarını kullanır. İki terim varsayılanı güçlü yerel eşleşmeyi korur; yalnız Jev rerank değerlendirmesini açar, bu yoldaki teslimi yine rerank skoru belirler. `lexical_override` ve `override_ids` nedenini gösterir; `needed` ilk Jev kararını, `effective_needed` geçersiz kılma sonrası kararı tutar. Override, `all` erken dönüşünden önce değerlendirilir.

Eksik nesne/anahtar varsayılanı kullanır; geçersiz değer veya tip yalnız ilgili anahtarı kapatır (`"off"` veya `0`, karakter sınırı da `0`). Nesnenin kendisi geçersizse üç ayar da kapanır.

Claude hook için `claude_hook_mode: off|shadow|on` varsayılanı `shadow`dur. Gölge modunda kullanıcının gördüğü metin yerel kalır; Jev kapı/sıralama tanısı `.cache/jev-golge/*.jsonl` altında tutulur. Günlükte istem metni bulunmaz; yalnız SHA-256 hash, seçilen kimlikler, skorlar, tanılar ve gecikme bulunur. Gizli veya özel istemler Jev'e gönderilmez. `on` modu yapılandırılmış Jev yolunu kullanır. Codex hook'ta `HAFIZA_HOOK_JEV=0` kapatma bayrağı geçerlidir.

`erisim_olc.py` seed 7 ile iki yarı ölçer; kanal başına teslim edilen karakter, p50/p95 gecikme, `degraded`, `abstain`, istenen ve etkili mod raporlanır. 2026-09-24 v2 seti eşik geliştirmesinde kullanıldığı için bağımsız başarı testi sayılmaz.

`pool_coverage`, yalnız `jev.catalog.pool_ids` listesi bulunan ve gold etiketi boş olmayan istemlerde havuza giren gold oranını (`recall`), aynı istemlerde teslim edilen gold oranını (`delivered_recall`) ve havuzdayken teslim edilmeyen gold sayısını (`lost_after_pool`) ölçer; mevcut teslim precision/recall hesabını değiştirmez.
Sonuç satırlarındaki `pool_ids`, `pool_hits` ve `pool_misses` sıralı kimlik listeleridir; havuz ölçülmemişse `null`, kurulmuş ama boşsa `pool_ids: []` olur ve degraded rerank çıktısındaki havuz da ölçüme katılır.
Etikette isteğe bağlı `needs_memory` yalnız boolean kabul eder ve açık `false` gold bulunsa da önceliklidir; alan yoksa `relevant_memory_ids` veya `relevant_notes` doluluğundan türetilir.
`gate_false_negative`, hafıza gerektiren istemlerde ham `needed` ve override sonrası `effective_needed` için ayrı yanlış negatif oranları verir (ikinci alan yoksa birincisine düşer); lexical override, bypass ve degraded sayıları aynı etiketli alt kümeye aittir, bypass/degraded oran paydasına girmez, `abstain` ise değerlendirilmiş karar olarak kalır ve `jev_yes_on_not_needed` yalnız değerlendirilmiş, hafıza gerektirmeyen istemlerdeki ham olumlu kararları sayar.
İki ölçü `certain_only` içinde de hesaplanır; oran paydası sıfırsa oran `null` kalır, etiket ve tanı sayıları korunur, havuz/kapı verisi bulunmayan rerank dışı çalıştırmalarda Markdown ölçülmedi der.

## Kaynak ve kapsam

Yalnız mevcut kodun uygun bulduğu incelemeden geçmiş, güncel kaynaklı, yetkili kapsamdaki adaylar gönderilir. Gönderilen alanlar kimlik, başlık, kısa ifade, kapsam ve alandır; ham sohbetler, tam kaynak dosyaları ve örnek varlıklar gönderilmez. Ağ cevabından sonra kaynak sürümleri yeniden kontrol edilir. Jev kaynak kapısını aşamaz.

Aday havuzu kaynak ve proje kapsamıyla sınırlandırılır; açık alan sözcüğü başka bir örtük kanıt ihtiyacını peşinen dışlamaz. Kaynak/not/ayrı ayrı/geri bildirim isteyen ve `ve`, `ile` veya noktalı virgülle ayrılan en fazla üç kanıt cümleciği ayrı değerlendirilir. Her cümleciğin açık alanı kodla korunur; `site için` gibi öndeki görev alanı diğer nesnelere de taşınır. Diğer çok alanlı sorularda sunum/thumbnail/site alanları ayrı değerlendirilir. Genel doğal dil ayrıştırıcısı değildir. Önce her alanın en yüksek puanlı kartı, sonra kalan kartlar seçilir. `coverage`, puanlanan alanın gerçekten karakter bütçesine sığıp sığmadığını ayırır. Görev paketindeki `knowledge_delivered` ayrıca tüm bölümün teslim edilip edilmediğini belirtir. Bu alanlar bütün olası alt soruların cevaplandığını kanıtlamaz.

## Sınırlar ve hata davranışı

Rerank paketlemesi dışında her erişim yüzeyi tek istek yapar; otomatik tekrar yoktur. İstek başına varsayılan üst sınır 32 aday, 96 soru ve 24000 girdi karakteridir. Bunlar token veya günlük harcama sınırı değildir. Rerank dışındaki görev paketi bilgi, katalog ve isteğe bağlı prosedür seçimi için en fazla üç istek yapabilir; üç bağımsız okuyucu paralel çalışır ve ortak varsayılan inference süresi yaklaşık 2,5 saniyeyle sınırlıdır; buna yerel işlem süresi eklenir. Timeout olmuş uzak istek sağlayıcıda tamamlanıp ücretlenebilir. Sağlayıcıda ayrıca harcama sınırı belirlenmelidir.

Timeout, 401/403/429/5xx, bozuk yanıt, aday/girdi sınırı ve kaynak değişimi yerel geri dönüşle `degraded` olarak görünür; bunlar “kanıt yok” sayılmaz. Geçersiz kaynak geri dönüşte de teslim edilmez. `confidence` seçim veya izin için kullanılmaz.

Önbellek sorgu, sıralı adaylar, alan soruları, kaynak sürümleri, kapsam, istenen model, sağlayıcı, endpoint ve rubrik sürümüne bağlıdır. Boş seçim de bu anahtara bağlıdır; yeni aday eski boş seçimi geçersiz kılar. Önbellek doğrulanmış puan, olasılık dağılımı, seçim ve sınırlı model metadata'sı saklar, dosyalar 0600'dür. Sağlayıcının döndürdüğü model adı kaydedilir; bir alias'ın arkasındaki gerçek ağırlık sürümünün sabit olduğu garanti edilmez. Alias kullanırken kısa TTL tercih edin.

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

## Kurulum sihirbazı

README'deki tek komut “anahtarın var mı?” sorusuyla mevcut anahtar, yeni
Vercel anahtarı veya atlama seçeneklerini sunar. Yeni anahtar yolunda resmi
Vercel model ve API Keys sayfaları açılır; kullanıcı adım adım yönlendirilir.
Enter ile geçilirse Jev kapalı kalır. Anahtar gizli girişle alınır ve kasa
dışındaki `credentials_file` dosyasına kaydedilir; loga yazılmaz.

| Sağlayıcı | Model | Base URL | Anahtar alanı |
| --- | --- | --- | --- |
| Vercel | typesafe-ai/jev | https://ai-gateway.vercel.sh/typesafe | AI_GATEWAY_API_KEY |
| TypeSafe | jev-latest | https://api.typesafe.ai | TYPESAFE_API_KEY |

Vercel bağlantısı [resmi TypeSafe uyumlu API](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe)
kullanır. Her iki sağlayıcıda da `/v1/systemone` çağrısı yapılır.
Sağlayıcıya ait ortam değişkeni özel dosyadan önceliklidir; TypeSafe ortam
anahtarı Vercel kurulumunu değiştirmez. Eski `env_file` desteği sürer.
Anahtarın geçerliliği kurulumda canlı istekle sınanmaz.

## Bağımsız görevler ve yardımcı erişim

Mevcut kurulumda görevleri ayrı etkinleştirmek için `komuta/jev.json` içine:

```json
{
  "mode": "shadow",
  "retrieval_mode": "assist",
  "procedure_mode": "on"
}
```

Diğer bağlantı alanlarını koruyun. `retrieval_mode` varsayılanı `inherit`;
`off`, `shadow`, `assist`, `on` seçenekleri yalnız erişimi değiştirir.
`procedure_mode` varsayılanı `off`; `shadow` ve `on` desteklenir.
Ana `mode: off` bütün görevleri kapatır. Yukarıdaki ayarda mevcut kaynak ve
ilişki incelemeleri gölge modunda kalır.

`assist`, yerel bilgi/katalog seçimini korur; her yüzeyde en fazla iki eksik
Jev kaynak adayını kalan karakter bütçesinde gösterir. Aday yolu bir tercih,
kabul veya doğrulanmış cevap değildir; ajan ilgili kaynağı okumalıdır.
Video kapsamı anlatı ve kapak kanıtlarını, proje bağlamı kendi yetkili
adaylarının alanlarını dışlamaz. Kaynak güncelliği ve proje yetkisi önce
kodla kontrol edilir; model bunları genişletemez.

Prosedür yönlendirmesi yalnız yedi incelenmiş yerel dosya için kısa sabit
açıklamaları puanlar. Model dosya yolu üretemez. Mevcut dosyalardan en fazla
üçü, toplam 1000 karakter içinde okuma önerisi olur. Dosya içerikleri API'ye
gönderilmez. Eksik/değişen kaynak, bozuk ayar ve ağ hatasında öneri verilmez;
temel kurallar aynen geçerlidir. Yeni zorunlu açılış okuması oluşturmaz.

Bu seçenekler iş başına API gecikmesi ekler; basit sorularda da yapılandırılmış
yüzeyler çağrılabilir. Her yüzey en fazla bir çağrı yapar, otomatik tekrar yoktur.
Puanlar ve token kullanımı tanı verisidir; fatura tutarı değildir.
`on` ile tek seçiciye geçiş ayrıca yeni sorularla geri çağırma, yanlış aday,
karakter bütçesi, son paket teslimi ve gecikme ölçümü gerektirir.

Paralellik, tekil çağrı paylaşımı, kapasite, kaynak snapshot ve görevler arası
ayrım için [mimari sözleşmesi](MIMARI.md).

Görevlerin bilinen kaynaklarla eşleştirilmesi için ayrı, varsayılan kapalı
`task_mapping_mode: shadow` danışmanı eklendi. Okuma/yazma kümeleri veya
çalışma izinleri modelden türetilmez. Kullanım ve sınırlar: [GOREV-PLANI.md](GOREV-PLANI.md).
