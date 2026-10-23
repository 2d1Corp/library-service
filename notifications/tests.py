import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from books.models import Book
from borrowings.models import Borrowing
from notifications.tasks import notify_overdue_borrowings
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


class OverdueNotificationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="reader@example.com", password="testpass123"
        )
        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=4,
            daily_fee="2.50",
        )

    def test_notifies_each_unreturned_borrowing_due_today_or_earlier(self):
        today = timezone.localdate()
        past = Borrowing.objects.create(
            user=self.user, book=self.book, expected_return_date=today
        )
        Borrowing.objects.filter(pk=past.pk).update(
            borrow_date=today - timedelta(days=2),
            expected_return_date=today - timedelta(days=1),
        )
        past.refresh_from_db()
        due_today = Borrowing.objects.create(
            user=self.user, book=self.book, expected_return_date=today
        )
        future = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=today + timedelta(days=1),
        )
        returned = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=today,
            actual_return_date=today,
        )

        with patch("notifications.tasks.send_telegram_message") as send_mock:
            notify_overdue_borrowings.run()

        messages = [call.args[0] for call in send_mock.call_args_list]
        self.assertEqual(len(messages), 2)
        for borrowing in (past, due_today):
            message = next(
                message
                for message in messages
                if message.startswith(f"Borrowing {borrowing.pk} is overdue.")
            )
            self.assertIn(self.book.title, message)
            self.assertIn(self.user.email, message)
            self.assertIn(str(borrowing.borrow_date), message)
            self.assertIn(str(borrowing.expected_return_date), message)
        self.assertNotIn(f"Borrowing {future.pk} is overdue.", "\n".join(messages))
        self.assertNotIn(f"Borrowing {returned.pk} is overdue.", "\n".join(messages))

    def test_reports_no_overdue_borrowings_once(self):
        today = timezone.localdate()
        Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=today + timedelta(days=1),
        )
        Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=today,
            actual_return_date=today,
        )

        with patch("notifications.tasks.send_telegram_message") as send_mock:
            notify_overdue_borrowings.run()

        send_mock.assert_called_once_with("No borrowings overdue today!")
