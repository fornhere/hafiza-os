# Kavram ağı

Kavram ağı, incelenmiş kayıtları konulara bağlayan bir yönlendirme katmanıdır.
Kanonik katalog JSONL'de kaldığı için Obsidian grafiği beynin kendisini
göstermez; bu katman onu `beyin/` altında görünür kılar ve kısa sorularda
kullanıcının farklı kelimelerini doğru kayda bağlar. Yeni tercih, kanıt veya
onay üretmez.

## Tanım dosyası

Kavramlar kasadaki `komuta/kavramlar.json` dosyasındadır. Örnek:
[examples/kavramlar.örnek.json](examples/kavramlar.örnek.json). Dosya yoksa
katman hiçbir şeyi değiştirmez.

- `selectors`: kaydın kendi ifadesinde geçerse kayıt kavrama üye olur.
- `aliases`: üye kayda ek arama anahtarı olur. Kullanıcı "gain" der, kayıtta
  "kazanç" yazar; eş sözcük bu boşluğu kapatır.
- `related`: kavramlar arası elle tanımlanan bağ. Ortak üyesi olan kavramlar
  ayrıca otomatik bağlanır.
- `ozne` (isteğe bağlı): not adlarından atılacak baştaki özne kelimeleri.

## Arama kuralları

Kavram katmanı yalnız ekleme yapar. Önce olağan sıralama hiç değiştirilmeden
çalışır ve sonucu olduğu gibi, başta kalır. Ardından sorgudaki bir kelime bir
kaydın eş sözcüğüyle gerçekten eşleşiyorsa, olağan sıralamanın seçmediği en
fazla üç kayıt sona eklenir. Sonuç her zaman olağan sonucun üst kümesidir;
sorguda hiçbir eş sözcük geçmiyorsa birebir aynıdır. Eklenen kayıt da kendi
metninde sorguyla eşleşmelidir; eş sözcük tek başına kayıt seçemez. Altıdan
fazla içerik kelimesi olan uzun istemlerde ekleme yapılmaz. Anahtarlar bağlam
metnine girmez.

Tanım dosyasını değiştirdikten sonra aynı soru kümesiyle önce/sonra ölç
(`araclar/erisim_olc.py evaluate`); tek bir soruya göre kelime eklemek
başka istemlerde gürültü üretebilir.

## Obsidian görünümü

```sh
python3 araclar/kavram_agi.py --vault . status
python3 araclar/kavram_agi.py --vault . export --apply
```

`beyin/Beyin.md` kavramları listeler; `beyin/kavramlar/` her kavram için
üye kayıtları, bilgi kartlarını, ilgili kavramları ve projeleri bağlar;
`beyin/hafıza/` her etkin, normal hassasiyetli ve kaynağı geçerli katalog
kaydı için bir not taşır. Kavram notları ayrıca başlığı (Codex makbuzunda ilk
özet paragrafı) kavram sözcükleriyle eşleşen oturumları listeler; bir oturum en
fazla üç kavrama bağlanır, eski kayıtlar düzenlenmez. Bu konu ilişkisidir, kanıt
veya karar değildir. Karantinadaki, silinmiş veya kaynağı değişmiş kayıt
dökülmez. Dosyalar yönetilen anlık görüntüdür: sonlarındaki işaret içerik
hash'ini taşır, elle değişen dosyanın üzerine yazılmaz, artık karşılığı
olmayan dosya silinir. Aramanın doğruluk kaynağı katalogdur, bu sayfalar değil.

## Proje kavramları ve öneriler

`komuta/gorev-baglam.json` içindeki her proje kendiliğinden bir grafik
kavramı olur (`Proje <id>`). Üyelik kelimeyle değil kapsamla kurulur:
kapsamı `project:<id>` olan kayıtlar ve kartlar, ön bilgisinde
`projeler: [...]` listesinde o proje geçen oturum kayıtları. Proje
kavramlarının eş sözcüğü yoktur, aramayı değiştirmez. Aynı kimlikte veya
dosya adında elle yazılmış bir kavram varsa proje kavramı oluşturulmaz.

`Beyin.md` sonunda "Kavram adayları" listesi bulunur: hiçbir konu
kavramına bağlanmayan oturum başlıklarında en az üç kez geçen kelimeler.
Oturum kalıp kelimeleri ve bütün başlıkların %8'inden fazlasında geçen
kelimeler elenir. Liste karar değildir; sözlüğe eklemeden önce erişimi ölç.

## Zamanlayıcıyla bakım

`bakim` komutu modelsiz ve ağsızdır: kavram dökümünü ve zaten var olan konu
sentezi dökümlerini yeniler, kanonik kayıt yazmaz. Her adımı dener; biri
hata verirse sonuç `ok: false` ve çıkış kodu 1 olur.

```sh
python3 araclar/kavram_agi.py --vault . bakim --apply
```

Model gerektiren aday incelemesi ayrı inceleme rolünde kalır. Kişisel bir
systemd kullanıcı zamanlayıcısı örneği (`<KASA>` yerine kasa yolunu yaz):

```ini
# ~/.config/systemd/user/hafiza-bakim.service
[Service]
Type=oneshot
WorkingDirectory=<KASA>
ExecStart=/usr/bin/python3 -X utf8 araclar/kavram_agi.py --vault . bakim --apply
Nice=15

# ~/.config/systemd/user/hafiza-bakim.timer
[Timer]
OnCalendar=hourly
Persistent=true
[Install]
WantedBy=timers.target
```

`systemctl --user enable --now hafiza-bakim.timer` ile etkinleştirilir;
son sonuç `journalctl --user -u hafiza-bakim.service` ile okunur.
