# Hafızadan beklenti ve verimlilik kararı

Bu belge Hafıza OS'nin neyi başarmaya çalıştığını ve hangi durumda daha
karmaşık bir erişim katmanına geçilmesi gerektiğini sınırlar. Araştırma
bulgusu, bu depoya ilişkin çıkarım ve bağlayıcı ürün kararı birbirine
karıştırılmaz.

## Gerçekçi beklenti

Bir ajan hafızası izin verilmiş kaynaklardan güncel tercihleri ve kararları
bulmalı; kararın gerekçesini ve geçerlilik koşulunu iddiayla birlikte taşımalı;
eski ve yeni bilgiyi ayırmalı; kaynaklar çeliştiğinde belirsizliği göstermelidir.
Devam edilecek işi ve doğrulanmış çıktıyı geri çağırması beklenebilir.

"Her şeyi hatırlama", her deneyimden doğru genelleme çıkarma veya hafıza
eklendiği için kendiliğinden daha iyi karar verme beklenmez. Uzun dönem hafıza
değerlendirmeleri bilgi çıkarma, çok oturumlu birleştirme, zamansal akıl yürütme
ve bilgi yokluğunu ayrı yetenekler olarak ölçer; birindeki başarı diğerlerini
garanti etmez.

## Bağlayıcı ürün kararları

- Yerel Markdown kasa kanoniktir; Mem0 yalnız yeniden üretilebilir indekstir.
- İlk beş gerçek kullanıcı mesajı kaydedilmez ve kayıt bildirimi yapılmaz.
  Altıncıdan itibaren yalnız anlamlı, sırsız özetler aday olabilir; basit sorular
  ve kaydetmeme talepleri kayıt dışındadır.
- Sırlar ve kişisel içerik kamu deposuna çıkmaz. Uzak servis paylaşımı ayrıca
  gizlilik ve izin sınırlarına tabidir.
- Makbuz kanonik gerçek değildir. Görev ajanı kataloğa veya Mem0'a doğrudan
  terfi yapmaz; kaynaklı aday ayrı incelemeden geçer.
- Jev danışmandır; deterministik doğrulama, insan onayı veya kanıt yerine geçmez.
- İddia, gerekçe, koşul, kaynak, tarih, kapsam ve güven mümkün olduğunca birlikte
  taşınır. Koşul bütçeye sığmıyorsa koşulu düşürmek yerine kayıt atlanır.

## Kapsam ve bağlam sözleşmesi

Tekrar/çelişki denetimi önce kapsamı ayırır; konu kimliği
`(scope, subject_key)` olur. Aynı kapsamda normalize edilmiş aynı ifadenin
tekrar, aynı anahtardaki farklı ifadenin çelişki sayılması korunur.
Kapsamı eksik eski değerlendirme girdileri `user` kabul edilir.

Kullanıcı-geneli tercih ile proje istisnası ayrı incelenen kayıtlardır.
Birbirini otomatik duplicate/conflict saymaz, silmez veya `supersedes` yapmaz.
İlgili proje sorgusu her ikisini getirebilir; başka projeye istisna taşınmaz.
Yeni bir otomatik "proje kazanır" önceliği eklenmez: uygulanabilirlik mevcut
kaynak, kapsam ve koşullarla değerlendirilir.

Yerel ve Mem0 destekli CLI yolları aynı `context_from_results` formatter'ını
kullanır. Uzak CLI araması kimlikleri sıralar; metin ve ek alanlar güncel,
kaynak denetiminden geçen yerel kayıttan alınır. `build_context_package`
çağıranları, eksik Mem0 metadata alanlarını tamamlamak için `records` ile
kanonik kayıtları verebilir. Bu lookup tek başına kaynak sürümü doğrulamaz;
CLI dışı çağıran, kayıtların güncelliğini ayrıca doğrulamalıdır.
İfade, gerekçe, koşul ve atıf tek bütçe birimidir; sığmayan kayıt atlanır,
koşulu kırpılarak koşulsuz iddia üretilmez.

Biçimleyiciye verilen kanonik kaydın gerekçe ve koşulları, alanların yokluğu
dahil, uzak metadata'dan önce gelir. Biçimsiz veya sır içeren ek alan varsa
koşulsuz iddia üretmek yerine kaydın tamamı dışlanır. `null` veya boş metin
olan isteğe bağlı alanlar eski, ayrıntısız çıktı biçimini korur.

## Önerilen minimum mimari — çıkarım

Okuma yolu kademelidir:

1. Güncel hedef, kısıtlar, kararlar, sonraki adım ve kaynak sürümlerinden oluşan
   küçük bir proje paketiyle başla.
2. Paket yetmiyorsa kapsam ve zaman filtreli erişim yap.
3. İndeks sonucunu güncel kanonik kaynaktan doğrula.
4. Çok oturumlu "neden?" ve karşılaştırma sorularında gerektiğinde sentez yap;
   basit sorularda pahalı sentez çağırma.

Yazma yolu: kayıt politikası kontrolü → kaynaklı episodik aday → ayrı inceleme →
kanonik gerçek/karar veya koşullu yöntem → yeniden üretilebilir indeks. Güncelleme
eski bilgiyi görünmezce ezmez; geçerlilik ve yerine-geçme ilişkisini korur.

Bu tasarım araştırmadan yapılan bir çıkarımdır; Hafıza OS için ölçülmüş üstünlük
iddiası değildir. Özellikle Mem0 araştırmasındaki çıkarma ve konsolidasyon
sonuçları, bu deponun `infer: False` indeks kullanımına doğrudan taşınamaz.

## Faydayı kanıtlama

[FAYDA-OLCUMU.md](FAYDA-OLCUMU.md) protokolüyle aynı görev ailesini karşılaştır:

- **A:** hafızasız,
- **B:** güçlü ve güncel sabit proje paketi,
- **C:** aynı paket + dinamik erişim.

Aynı model ve yöntemle tekrarlanan açıklama, düzeltme turu, kabul edilen sonuca
kadar süre, kaçırılan hata ve bakım yükünü ölç. C, B'ye göre güvenilir ve bakım
maliyetini aşan bir kazanç göstermiyorsa dinamik katmanı büyütme.

İki haftalık karşılaştırmada model, düşünme ayarı ve yöntem sürümünü sabit tut;
benzer zorluktaki işleri ve koşul sırasını dengele. B'yi bilerek zayıflatma.
Koşullar birbirinin çıktısını görmesin; değerlendirici koşulu bilmesin.
Eksik ölçümleri `null` bırak; model puanını kullanıcı kabulü sayma. Ret ve
vazgeçme sonuçlarını koru. Gözlemler özeldir; aynı kayıt politikası uygulanır.
Küçük örneklem veya tek başarılı çift kesin nedensel kanıt değildir. Veri yoksa
sonuç: **henüz fayda ölçülmedi**.

## Birincil kaynaklar ve sınırlar

- [LongMemEval](https://arxiv.org/abs/2410.10813): uzun dönem hafızayı ayrı
  yetenekler üzerinden değerlendirir.
- [Mem0](https://arxiv.org/abs/2504.19413): seçici çıkarma ve konsolidasyon
  yaklaşımını kendi deney ortamında inceler.
- [LongMemEval-V2](https://arxiv.org/abs/2605.12493): dosyalardan ajanla kanıt
  toplama lehine sonuç bildiren 2026 ön baskısıdır; gecikme maliyeti vardır ve
  bu deponun Türkçe kullanımında doğrudan fayda kanıtı değildir.
- [LangChain memory concepts](https://docs.langchain.com/oss/python/concepts/memory):
  episodik, semantik ve prosedürel hafıza ayrımını açıklar.
- [Microsoft event sourcing pattern](https://learn.microsoft.com/azure/architecture/patterns/event-sourcing):
  olay günlüğünün denetim ve karmaşıklık bedellerini açıklar.
- [Anthropic context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents):
  küçük çalışma bağlamı, gerektiğinde kaynak açma ve sıkıştırma ödünleşimlerini
  tartışır.
