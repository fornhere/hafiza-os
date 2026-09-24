"""Dizin özeti sidecar aracının testleri."""

import json
import tempfile
import unittest
from pathlib import Path

import ozet


def l0_satiri(metin):
    """Özet dosyasından L0 satırını alır."""
    return ozet.l0_ayikla(metin)


def govde(metin):
    """Frontmatter sonrası gövde."""
    return metin.split("---\n", 2)[2]


class Ozet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name).resolve()
        (self.v / "projeler/ornek-proje").mkdir(parents=True)
        (self.v / "projeler/ornek-proje/dersler").mkdir()
        (self.v / "zihin").mkdir()
        (self.v / "günlük").mkdir()
        (self.v / ".obsidian").mkdir()
        (self.v / "projeler/OKU.md").write_text(
            "# Projeler\n\nHer projenin bir klasörü var.\n\n## Liste\n\n- ornek-proje\n", encoding="utf-8"
        )
        (self.v / "projeler/ornek-proje/DURUM.md").write_text(
            "# Örnek proje\n\nİlk proje, aktif.\n\n## Kimlik\n\nmetin\n\n## Sayılar\n\nmetin\n",
            encoding="utf-8",
        )
        (self.v / "projeler/ornek-proje/kapak-yenileme.md").write_text(
            "# Kapak\n\nKapak akışı yenileniyor.\n", encoding="utf-8"
        )
        (self.v / "projeler/ornek-proje/dersler/ders.md").write_text(
            "# Ders\n\nPencere sonucu doğrulanır.\n", encoding="utf-8"
        )
        (self.v / "zihin/ruh.md").write_text("# Ruh\n\nKısa ilke metni.\n", encoding="utf-8")
        (self.v / "günlük/gun.md").write_text("# Gün\n\nGünlük not.\n", encoding="utf-8")
        (self.v / ".obsidian/not.md").write_text("# Gizli\n\nAyar.\n", encoding="utf-8")

    def oku(self, goreli):
        return (self.v / goreli / ozet.OZET_ADI).read_text(encoding="utf-8")

    def test_l0_256_karakter_sinirini_asmaz(self):
        (self.v / "projeler/ornek-proje/DURUM.md").write_text(
            "# Örnek proje\n\n" + ("çok uzun bir durum cümlesi " * 60) + "\n", encoding="utf-8"
        )
        ozet.build(self.v)
        satir = l0_satiri(self.oku("projeler/ornek-proje"))
        self.assertLessEqual(len(satir), ozet.L0_SINIR)
        self.assertTrue(satir.endswith("…"))

    def test_l1_govdesi_4000_karakteri_asmaz_ve_dosya_listesi_kisalir(self):
        for sira in range(60):
            (self.v / f"projeler/ornek-proje/not-{sira:02d}.md").write_text(
                f"# Not {sira}\n\n" + ("uzun içerik cümlesi " * 30) + "\n", encoding="utf-8"
            )
        ozet.build(self.v)
        metin = self.oku("projeler/ornek-proje")
        self.assertLessEqual(len(govde(metin)), ozet.GOVDE_SINIR)
        self.assertIn("dosya daha", metin)

    def test_hash_degismezse_dosya_hic_degismez(self):
        ozet.build(self.v, tarih="2026-01-01")
        yol = self.v / "projeler/ornek-proje" / ozet.OZET_ADI
        onceki, mtime = yol.read_text(encoding="utf-8"), yol.stat().st_mtime_ns
        sonuc = ozet.build(self.v, tarih="2026-02-02")
        self.assertEqual(sonuc["yenilendi"], 0)
        self.assertEqual(yol.read_text(encoding="utf-8"), onceki)
        self.assertIn("2026-01-01", onceki)
        self.assertEqual(yol.stat().st_mtime_ns, mtime)

    def test_kaynak_degisince_yenilenir_ve_ust_dizine_yayilir(self):
        ozet.build(self.v, tarih="2026-01-01")
        (self.v / "projeler/ornek-proje/dersler/ders.md").write_text(
            "# Ders\n\nYeni ders metni.\n", encoding="utf-8"
        )
        durum = ozet.status(self.v)
        self.assertIn("projeler/ornek-proje/dersler", durum["eski"])
        sonuc = ozet.build(self.v, tarih="2026-02-02")
        self.assertIn("projeler/ornek-proje/dersler", sonuc["dizinler"])
        self.assertIn("projeler/ornek-proje", sonuc["dizinler"])
        self.assertIn("projeler", sonuc["dizinler"])
        self.assertNotIn("zihin", sonuc["dizinler"])
        self.assertIn("Yeni ders metni.", self.oku("projeler/ornek-proje/dersler"))

    def test_haric_dizinlere_ozet_yazilmaz(self):
        ozet.build(self.v)
        for goreli in ("günlük", ".obsidian"):
            self.assertFalse((self.v / goreli / ozet.OZET_ADI).exists())
        self.assertFalse((self.v / ozet.OZET_ADI).exists())
        self.assertTrue((self.v / "zihin" / ozet.OZET_ADI).exists())

    def test_sir_satiri_ozete_girmez(self):
        (self.v / "zihin/anahtar.md").write_text(
            "# Anahtar\n\napi_key: sk-" + "abcdefghijklmnopqrstuvwxyz0123\n\nGörünür açıklama satırı.\n",
            encoding="utf-8",
        )
        ozet.build(self.v)
        metin = self.oku("zihin")
        self.assertNotIn("sk-" + "abcdefghijklmnopqrstuvwxyz0123", metin)
        self.assertNotIn("api_key", metin)
        self.assertIn("Görünür açıklama satırı.", metin)

    def test_alt_dizin_l0_ust_ozete_girer_ve_frontmatter_sozlesmesi_korunur(self):
        ozet.build(self.v, tarih="2026-03-03")
        metin = self.oku("projeler/ornek-proje")
        self.assertIn("- `dersler/` — Pencere sonucu doğrulanır.", metin)
        self.assertIn("## Alt klasörler", metin)
        self.assertIn("- `DURUM.md` — İlk proje, aktif. [başlıklar: Kimlik; Sayılar]", metin)
        satirlar = metin.splitlines()
        self.assertEqual(satirlar[0], "---")
        self.assertEqual(satirlar[1], "kind: ozet")
        self.assertEqual(satirlar[2], "dir: projeler/ornek-proje")
        self.assertEqual(satirlar[3], "generated_at: 2026-03-03")
        kaynaklar = json.loads(satirlar[4].split(": ", 1)[1])
        altlar = json.loads(satirlar[5].split(": ", 1)[1])
        self.assertEqual(set(kaynaklar), {"DURUM.md", "kapak-yenileme.md"})
        self.assertTrue(kaynaklar["DURUM.md"].startswith("sha256:"))
        alt_metin = self.oku("projeler/ornek-proje/dersler")
        self.assertEqual(altlar["dersler"], ozet.hash_metin(alt_metin))

    def test_map_ciktisi_butce_altinda_ve_derinlik_sinirli(self):
        ozet.build(self.v)
        harita = ozet.harita(self.v, depth=2)
        self.assertLess(len(harita), ozet.HARITA_HEDEFI)
        self.assertIn("- `projeler/` —", harita)
        self.assertIn("- `projeler/ornek-proje/` —", harita)
        self.assertNotIn("projeler/ornek-proje/dersler/", harita)
        self.assertIn("toplam:", harita)
        self.assertIn("- `projeler/ornek-proje/dersler/` —", ozet.harita(self.v, depth=3))

    def test_dry_run_yazmaz_ve_show_ozeti_dondurur(self):
        sonuc = ozet.build(self.v, dry_run=True)
        self.assertTrue(sonuc["yenilendi"])
        self.assertFalse((self.v / "projeler" / ozet.OZET_ADI).exists())
        with self.assertRaises(ValueError):
            ozet.show(self.v, "projeler")
        ozet.build(self.v)
        self.assertIn("# ornek-proje", ozet.show(self.v, "projeler/ornek-proje"))
        self.assertEqual(ozet.status(self.v)["eksik"], [])

    def test_kapak_yoksa_l0_dosya_cumlelerinden_turetilir(self):
        (self.v / "zihin/ikinci.md").write_text("# İkinci\n\nİkinci not gövdesi.\n", encoding="utf-8")
        ozet.build(self.v)
        satir = l0_satiri(self.oku("zihin"))
        self.assertIn("Kısa ilke metni.", satir)
        self.assertIn("İkinci not gövdesi.", satir)

    def test_kod_blogu_ve_frontmatter_ozete_girmez(self):
        (self.v / "zihin/ruh.md").write_text(
            "---\ntitle: Ruh\n---\n\n# Ruh\n\n```bash\nornek-sayi --canli\n```\n\nGövde cümlesi.\n",
            encoding="utf-8",
        )
        ozet.build(self.v)
        metin = self.oku("zihin")
        self.assertNotIn("ornek-sayi", metin)
        self.assertNotIn("title: Ruh", metin)
        self.assertIn("Gövde cümlesi.", metin)


if __name__ == "__main__":
    unittest.main()
