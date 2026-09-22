import unittest
import capture_source as c


class CompoundPrivacyTests(unittest.TestCase):
    """Whole-session scope inside a mixed request must reach review."""

    COMPOUND = (
        "Bu konuşmayı kaydetme ve şimdi devam edelim.",
        "Bu oturumu kaydetme, sadece sorumu yanıtla.",
        "Bu sohbeti saklama ve işleme devam et.",
        "Şu dosyayı düzelt, bu oturumu kaydetme.",
        "Testi çalıştır ama bu konuşmayı hafızaya alma",
        "Kanka bu sohbeti hafızaya alma, kodu düzelt yeter",
    )

    def test_compound_requests_are_ambiguous_not_commands(self):
        for text in self.COMPOUND:
            with self.subTest(text=text):
                self.assertTrue(c.privacy_ambiguous(text))
                self.assertFalse(c.privacy_command(text))

    def test_whole_message_command_still_persistent(self):
        for text in ("Bu oturumu kaydetme.", "Kanka bu konuşmayı hafızaya alma lütfen"):
            with self.subTest(text=text):
                self.assertTrue(c.privacy_command(text))
                self.assertTrue(c.privacy_ambiguous(text))

    def test_discussion_and_quotes_stay_clear(self):
        for text in (
            "kaydetme komutu hata veriyor, bu oturumu incele",
            "\"bu oturumu kaydetme\" örneğini test et",
            "Bu oturumu özetle ve bunu benim kabul ettiğim karar olarak kaydetme",
            "Bu konuşmayı kaydet, sonra devam edelim.",
        ):
            with self.subTest(text=text):
                self.assertFalse(c.privacy_ambiguous(text))
                self.assertFalse(c.privacy_command(text))


if __name__ == "__main__":
    unittest.main()
