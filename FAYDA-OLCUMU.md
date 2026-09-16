# Gerçek görevlerde fayda ölçümü

İki haftalık pilotta benzer zorluktaki kapak, oyun ve video görevlerini izle.
A: hafızasız; B: küçük sabit profil/proje paketi; C: dinamik görev bağlamı.
Aynı model ve yöntem sürümünü kullan; koşulları sırayla dengele. Aynı görevi
tekrar yapmak öğrenme etkisi yaratabilir, sonucu nedensel kanıt diye sunma.

JSONL gözleminde task_id, condition (A/B/C), workflow, model,
protocol_version, outcome (accepted/rejected/abandoned/unknown) ve
kanıtın yolunu gösteren evidence_source zorunludur. İsteğe bağlı ölçümler:
repeat_explanations, correction_rounds, elapsed_seconds, maintenance_seconds.
Eksik ölçümü null bırak; tahminle sıfır yazma. Kullanıcı kabulünü kendin üretme.
Gözlem kaydı kişisel veridir; kamu deposuna yükleme. İlk beş mesaj ve
kaydetmeme politikası kalıcı gözlemler için de geçerlidir.

`python3 araclar/fayda_olc.py --observations gozlemler.jsonl`

Araç iş türü, model, yöntem ve koşula göre sayım/medyan verir. Kanıt alanının
anlamsal doğruluğu inceleyen sorumluluğundadır; araç dosya varlığını veya kabul
beyanını bağımsız doğrulamaz. Reddedilen ve vazgeçilen işler sonuçtan çıkarılmaz.
Dinamik paketi yalnız açıklama tekrarını/düzeltmeyi azaltıyor ve bakım yükü
kazanımı tüketmiyorsa genişlet. Veri yoksa sonuç: henüz fayda ölçülmedi.

## İlk karşılaştırmadan sonra

Önce çıktı gereksinimlerini önceden yazılmış ölçütlerle sınayın. B koşulu
güncel proje ve yöntem bilgisini içermelidir; hafızanın kazanması için B'yi
bilerek zayıflatmayın. C aynı pakete gerçek erişim sonucunu ekler. Aynı model
ve düşünme ayarını çalışma kaydından doğrulayın. Koşullar birbirinin çıktısını
görmesin; değerlendiriciye koşul eşlemesini vermeyin. Protokol sapmasını saklamayın.

Küçük örneklemde beraberlik veya C'nin geride kalması, dinamik katmanı
büyütmek için gerekçe değildir. Kaynak arşivi korunur, kısa güncel paket
temel kalır; ayrıntılı geçmiş ihtiyaç halinde çağrılır. Görsel üretimindeki
rastlantısallık nedeniyle tek çift kalıcı kalite farkını ispatlamaz.

Modelin rubrik puanını kullanıcı kabulü veya azalan düzeltme turuna
çevirmeyin. Üretim süresi ile kabul edilen sonuca kadar süreyi ayırın.
Çalışma kaydındaki toplam tokenlar sistem yönergelerini, araç çıktılarını
ve tekrar gönderilen bağlamı kapsayabilir; hepsi hafızanın ek maliyeti değildir.
Önbellek miktarını ayrıca gösterin. Fatura bilinmiyorsa ücret uydurmayın.

Normal işlerde olağan geri bildirimden kaynaklı gözlem çıkarın; rutin puan
istemi, aynı işi kullanıcıya iki kez yaptırma veya sentetik sonuçtan insan
faydası üretme yoktur. Bakım yükünü kazançtan düşmeden net fayda iddia etmeyin.

## Kaynaklı doğal gözlem kaydı

Olağan kabul/ret/vazgeçme geri bildirimini `fayda_olc.py record` kapısından
geçirin. Bu komut tamamlanmış kaynak, özgün kullanıcı alıntısı, ilk beş
mesaj ve kaydetmeme kurallarını denetler. `observational` koşulu A/B/C’den
ayrıdır; kabul nedeni veya zaman kazancı otomatik çıkarılmaz. Bu ilk yazıcı
yalnız sonucu kaydeder; dört nicel insan ölçümü null kalmalıdır. Tekrar
güvenliği ve eklemeli sürümler desteklenir. Ayrıntılı alanlar ve inceleme
sırası [konsolidasyon yönergesinde](komuta/hafıza-konsolidasyonu.md).
