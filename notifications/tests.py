import json
from io import BytesIO
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from notifications.telegram import send_telegram_message


class TelegramMessageTests(SimpleTestCase):
    @override_settings(TELEGRAM_BOT_TOKEN="test-token", TELEGRAM_CHAT_ID="12345")
    @patch("notifications.telegram.urlopen")
    def test_sends_message_to_configured_chat(self, urlopen):
        urlopen.return_value.__enter__.return_value = BytesIO(b'{"ok": true}')

        result = send_telegram_message("Книга: Дюна")

        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://api.telegram.org/bottest-token/sendMessage",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data),
            {"chat_id": "12345", "text": "Книга: Дюна"},
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)
        self.assertEqual(result, {"ok": True})
