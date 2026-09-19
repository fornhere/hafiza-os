# Araç geliştirme kapsamı

Önce depo kökündeki [CONTRIBUTING.md](../CONTRIBUTING.md) rehberini oku.
Bu dizin kişisel hafıza verisi değil, kamuya açık Python motoru ve testlerdir.

- Kök dizinden test çalıştır; geçici kasalar kullan, gerçek kullanıcı ayarlarını değiştirme.
- UTF-8, Windows/POSIX yolları ve süreç kilitleri için mevcut yardımcıları koru.
- Yakalanan aday, incelenmiş makbuz ve kanonik terfiyi birbirine karıştırma.
- Kaynak hash'i, ilk beş mesaj, kaydetmeme, sır taraması ve ayrı inceleme
  korumalarını atlatma. Değişen davranışı ilgili regresyon testiyle doğrula.
- Runtime dosyası eklerken/değiştirirken `publication-manifest.json` ve yayın
  eşliği gereksinimini incele; kişisel kasa dosyalarını buraya kopyalama.
- Yerel test sonucu yalnız çalıştırılan ortamın kanıtıdır. Yayın ve canlı
  istemci doğrulamasını ayrıca raporla.
