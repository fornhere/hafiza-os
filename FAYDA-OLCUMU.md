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
