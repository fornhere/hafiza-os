# Hafıza sistemi güncellemesi yayımlama

Kamu deposuna yalnız paylaşılabilir kod ve şablon gelir. Kişisel kasadaki
oturum, tercih, görev ve görsel kaynakları bu depoya taşınmaz.

1. Değişiklik ve güncelleme notlarını incele; yerel/kamu ortak kodunu uzlaştır.
2. `publication-manifest.json` ortak dosyaları listeler. `shared` dosyaları
   birebir eşleşir. `reviewed-variant` yalnız gerekçesi yazılmış iki SHA256
   eşleştiğinde geçer; kişiselleştirilmiş dosya değişince fark yeniden incelenir.
   Manifest hash'lerini kontrolü susturmak için körlemesine güncelleme.
3. İncelenen değişiklikleri commit et. Betik commit üretmez, kirli ağacı reddeder.
4. Kamu repo kökünde `python3 araclar/yayinla.py --vault "$MEMORY_VAULT"`
   çalıştır. Ortak dosyalar, tam commit arşivindeki testler ve yayın taraması
   kontrol edilir. `MEMORY_VAULT` kişisel kasa yoludur.
5. `python3 araclar/yayinla.py --vault "$MEMORY_VAULT" --apply` testleri
   yeniden doğrular, mevcut gh kimlik yardımcısıyla force kullanmadan main'e
   gönderir ve uzak SHA'yı geri okur. Başarısız komut yayınlandı sayılmaz.

CI aynı commit testlerini ve kamu içerik taramasını çalıştırır; kişisel kasaya
erişemediğinden yerel/kamu eşliği yalnız yerel yayın kapısında doğrulanır.
GitHub branch protection bu dosyanın eklenmesiyle kendiliğinden açılmaz.
Tarama bilinen sır kalıplarına karşı ek kontroldür; içerik incelemesinin yerini
almaz. Betik uzak silme, force push veya kişisel kasa push yapmaz.
