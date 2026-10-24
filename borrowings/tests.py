from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone
from kombu.exceptions import OperationalError

import borrowings
from books.models import Book
from borrowings.models import Borrowing
from notifications.tasks import notify_borrowing_created
from django.db import IntegrityError, transaction

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.test import override_settings
from stripe import StripeError

from payments.models import Payment


class BorrowingModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="reader@example.com",
            password="testpass123",
        )
        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=3,
            daily_fee="2.50",
        )

    def test_creates_borrowing_without_actual_return_date(self):
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )

        borrowing.refresh_from_db()

        self.assertEqual(borrowing.borrow_date, timezone.localdate())
        self.assertIsNone(borrowing.actual_return_date)

    def test_rejects_expected_return_date_before_borrow_date(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Borrowing.objects.create(
                    user=self.user,
                    book=self.book,
                    expected_return_date=(timezone.localdate() - timedelta(days=1)),
                )

        self.assertEqual(Borrowing.objects.count(), 0)

    def test_rejects_actual_return_date_before_borrow_date(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Borrowing.objects.create(
                    user=self.user,
                    book=self.book,
                    actual_return_date=timezone.localdate() - timedelta(days=1),
                    expected_return_date=(timezone.localdate() + timedelta(days=7)),
                )

        self.assertEqual(Borrowing.objects.count(), 0)

    def test_allows_return_on_borrow_date(self):
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            actual_return_date=timezone.localdate(),
            expected_return_date=timezone.localdate(),
        )

        borrowing.refresh_from_db()
        self.assertEqual(borrowing.actual_return_date, borrowing.borrow_date)
        self.assertEqual(borrowing.expected_return_date, borrowing.borrow_date)

    def test_prevents_deleting_borrowed_book(self):
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )

        with self.assertRaises(ProtectedError):
            self.book.delete()

        self.assertTrue(Book.objects.filter(pk=self.book.pk).exists())
        self.assertTrue(Borrowing.objects.filter(pk=borrowing.pk).exists())

    def test_prevents_deleting_borrower(self):
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )
        with self.assertRaises(ProtectedError):
            self.user.delete()

        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertTrue(Borrowing.objects.filter(pk=borrowing.pk).exists())


@override_settings(STRIPE_SECRET_KEY="sk_test_example")
class BorrowingApiTests(APITestCase):
    def setUp(self):
        stripe_patch = patch("payments.services.StripeClient")
        self.addCleanup(stripe_patch.stop)
        client_class = stripe_patch.start()

        self.stripe_create = client_class.return_value.v1.checkout.sessions.create
        self.stripe_create.return_value.id = "cs_test_borrowing"
        self.stripe_create.return_value.url = (
            "https://checkout.stripe.com/c/pay/cs_test_borrowing"
        )
        self.user = get_user_model().objects.create_user(
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.user)

        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=3,
            daily_fee="2.50",
        )

        self.borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )

    def test_retrieves_borrowing(self):
        response = self.client.get(
            reverse("borrowing-detail", args=[self.borrowing.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], self.borrowing.id)
        self.assertEqual(response.json()["book"]["id"], self.book.id)

    def test_lists_borrowing(self):
        response = self.client.get(
            reverse("borrowing-list"),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], self.borrowing.id)
        self.assertEqual(response.json()[0]["book"]["id"], self.book.id)
        self.assertEqual(response.json()[0]["book"]["title"], self.book.title)

    def test_returns_404_for_missing_borrowing(self):
        response = self.client.get(
            reverse("borrowing-detail", args=[self.borrowing.id + 1])
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_user_cannot_list_borrowings(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse("borrowing-list"))

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_anonymous_user_cannot_retrieve_borrowing(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(
            reverse("borrowing-detail", args=[self.borrowing.id]),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_write_methods_are_not_allowed(self):
        detail_url = reverse(
            "borrowing-detail",
            args=[self.borrowing.id],
        )

        requests = (
            ("put", detail_url),
            ("patch", detail_url),
            ("delete", detail_url),
        )

        for method, url in requests:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    url,
                    {},
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                )

        self.assertEqual(Borrowing.objects.count(), 1)
        self.assertTrue(Borrowing.objects.filter(pk=self.borrowing.pk).exists())

        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)

    def test_list_uses_two_queries_when_borrowings_increase(self):
        url = reverse("borrowing-list")

        with self.assertNumQueries(2):
            response = self.client.get(url)
            data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(data), 1)

        for index in range(3):
            book = Book.objects.create(
                title=f"Book {index}",
                author="Test Author",
                cover=Book.CoverType.SOFT,
                inventory=2,
                daily_fee="1.50",
            )
            Borrowing.objects.create(
                user=self.user,
                book=book,
                expected_return_date=(timezone.localdate() + timedelta(days=7)),
            )

        with self.assertNumQueries(2):
            response = self.client.get(url)
            data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(data), 4)

    def test_regular_user_can_create_borrowing(self):
        reader = get_user_model().objects.create_user(
            email="reader@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=reader)

        expected_date = timezone.localdate() + timedelta(days=7)
        payload = {
            "book": self.book.id,
            "expected_return_date": expected_date.isoformat(),
            "user": self.user.id,
        }

        with (
            patch("notifications.tasks.send_telegram_message") as telegram_mock,
            patch(
                "borrowings.views.notify_borrowing_created.delay",
                side_effect=notify_borrowing_created.run,
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(
                reverse("borrowing-list"),
                payload,
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        borrowing = Borrowing.objects.get(pk=response.json()["id"])
        self.assertEqual(borrowing.user_id, reader.id)
        self.assertEqual(borrowing.book_id, self.book.id)
        self.assertEqual(borrowing.expected_return_date, expected_date)
        self.assertEqual(borrowing.borrow_date, timezone.localdate())
        self.assertIsNone(borrowing.actual_return_date)

        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)
        self.assertEqual(Borrowing.objects.count(), 2)

        telegram_mock.assert_called_once()
        message = telegram_mock.call_args.args[0]
        self.assertIn(f"Borrowing {borrowing.id}", message)
        self.assertIn(self.book.title, message)
        self.assertIn(expected_date.isoformat(), message)

    def test_creates_borrowing_when_notification_queue_is_unavailable(self):
        with (
            patch(
                "borrowings.views.notify_borrowing_created.delay",
                side_effect=OperationalError("Broker unavailable"),
            ),
            self.assertLogs("borrowings.views", level="ERROR"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(
                reverse("borrowing-list"),
                {
                    "book": self.book.id,
                    "expected_return_date": (
                        timezone.localdate() + timedelta(days=7)
                    ).isoformat(),
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        borrowing = Borrowing.objects.get(pk=response.json()["id"])
        self.assertEqual(borrowing.book_id, self.book.id)
        self.assertEqual(borrowing.user_id, self.user.id)
        self.assertEqual(Borrowing.objects.count(), 2)

        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)

    def test_rejects_borrowing_when_no_copies_available(self):
        self.book.inventory = 0
        self.book.save(update_fields=["inventory"])

        response = self.client.post(
            reverse("borrowing-list"),
            {
                "book": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("book", response.json())
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 0)
        self.assertEqual(Borrowing.objects.count(), 1)

    def test_rejects_creation_with_past_expected_return_date(self):
        response = self.client.post(
            reverse("borrowing-list"),
            {
                "book": self.book.id,
                "expected_return_date": (
                    timezone.localdate() - timedelta(days=1)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expected_return_date", response.json())
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)
        self.assertEqual(Borrowing.objects.count(), 1)

    def test_anonymous_user_cannot_create_borrowing(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            reverse("borrowing-list"),
            {
                "book": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)
        self.assertEqual(Borrowing.objects.count(), 1)

    def test_rolls_back_inventory_when_borrowing_creation_fails(self):
        with patch(
            "borrowings.serializers.Borrowing.objects.create",
            side_effect=RuntimeError("Simulated creation failure"),
        ) as create_mock:
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("borrowing-list"),
                    {
                        "book": self.book.id,
                        "expected_return_date": (
                            timezone.localdate() + timedelta(days=7)
                        ).isoformat(),
                    },
                    format="json",
                )

        create_mock.assert_called_once()
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)
        self.assertEqual(Borrowing.objects.count(), 1)

    def test_creates_borrowing_with_payment(self):
        response = self.client.post(
            reverse("borrowing-list"),
            {
                "book": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=3)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        payment = Payment.objects.get(
            borrowing_id=response.json()["id"],
        )
        self.assertEqual(str(payment.money_to_pay), "7.50")
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.session_id, "cs_test_borrowing")

        self.assertEqual(len(response.json()["payments"]), 1)
        self.assertEqual(
            response.json()["payments"][0]["id"],
            payment.id,
        )
        self.assertEqual(
            response.json()["payments"][0]["session_url"],
            payment.session_url,
        )

        self.stripe_create.assert_called_once()
        parameters = self.stripe_create.call_args.args[0]
        self.assertEqual(
            parameters["success_url"],
            "http://testserver/api/payments/success/?session_id={CHECKOUT_SESSION_ID}",
        )
        self.assertEqual(
            parameters["cancel_url"],
            "http://testserver/api/payments/cancel/",
        )
        self.assertEqual(
            parameters["line_items"][0]["price_data"]["unit_amount"],
            750,
        )

        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)
        self.assertEqual(Borrowing.objects.count(), 2)
        self.assertEqual(Payment.objects.count(), 1)

    def test_stripe_failure_rolls_back_borrowing_and_inventory(self):
        self.stripe_create.side_effect = StripeError("Test Stripe failure")

        with self.assertLogs("borrowings.serializers", level="ERROR"):
            response = self.client.post(
                reverse("borrowing-list"),
                {
                    "book": self.book.id,
                    "expected_return_date": (
                        timezone.localdate() + timedelta(days=3)
                    ).isoformat(),
                },
                format="json",
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)
        self.assertEqual(Borrowing.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 0)

    def test_same_day_borrowing_costs_one_day(self):
        response = self.client.post(
            reverse("borrowing-list"),
            {
                "book": self.book.id,
                "expected_return_date": timezone.localdate().isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        payment = Payment.objects.get(
            borrowing_id=response.json()["id"],
        )
        self.assertEqual(str(payment.money_to_pay), "2.50")

        parameters = self.stripe_create.call_args.args[0]
        self.assertEqual(
            parameters["line_items"][0]["price_data"]["unit_amount"],
            250,
        )


class BorrowingAccessTests(APITestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            email="admin@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.reader = get_user_model().objects.create_user(
            email="first@example.com",
            password="testpass123",
        )
        self.other_reader = get_user_model().objects.create_user(
            email="second@example.com",
            password="testpass123",
        )

        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=3,
            daily_fee="2.50",
        )

        self.own_active = self.create_borrowing(self.reader)
        self.own_returned = self.create_borrowing(
            self.reader,
            returned=True,
        )
        self.other_active = self.create_borrowing(self.other_reader)

        self.client.force_authenticate(user=self.reader)
        self.list_url = reverse("borrowing-list")

    def create_borrowing(self, user, returned=False):
        return Borrowing.objects.create(
            user=user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
            actual_return_date=timezone.localdate() if returned else None,
        )

    def response_ids(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {item["id"] for item in response.json()}

    def test_regular_user_lists_only_own_borrowings(self):
        response = self.client.get(self.list_url)

        self.assertEqual(
            self.response_ids(response),
            {self.own_active.id, self.own_returned.id},
        )

    def test_regular_user_retrieves_own_borrowing(self):
        response = self.client.get(
            reverse("borrowing-detail", args=[self.own_active.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], self.own_active.id)

    def test_regular_user_cannot_retrieve_another_users_borrowing(self):
        response = self.client.get(
            reverse("borrowing-detail", args=[self.other_active.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_regular_user_cannot_select_another_user(self):
        response = self.client.get(
            self.list_url,
            {"user_id": self.other_reader.id},
        )

        self.assertEqual(
            self.response_ids(response),
            {self.own_active.id, self.own_returned.id},
        )

    def test_regular_user_filters_active_borrowings(self):
        response = self.client.get(
            self.list_url,
            {"is_active": "true"},
        )

        self.assertEqual(
            self.response_ids(response),
            {self.own_active.id},
        )

    def test_regular_user_filters_returned_borrowings(self):
        response = self.client.get(
            self.list_url,
            {"is_active": "false"},
        )

        self.assertEqual(
            self.response_ids(response),
            {self.own_returned.id},
        )

    def test_staff_lists_all_borrowings(self):
        self.client.force_authenticate(user=self.staff)

        response = self.client.get(self.list_url)

        self.assertEqual(
            self.response_ids(response),
            {
                self.own_active.id,
                self.own_returned.id,
                self.other_active.id,
            },
        )

    def test_staff_filters_by_user_and_active_status(self):
        self.client.force_authenticate(user=self.staff)

        response = self.client.get(
            self.list_url,
            {
                "user_id": self.reader.id,
                "is_active": "true",
            },
        )

        self.assertEqual(
            self.response_ids(response),
            {self.own_active.id},
        )

    def test_rejects_invalid_active_filter(self):
        response = self.client.get(
            self.list_url,
            {"is_active": "wrong"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("is_active", response.json())

    def test_staff_rejects_invalid_user_filter(self):
        self.client.force_authenticate(user=self.staff)

        for value in ("wrong", "0", "-1"):
            with self.subTest(user_id=value):
                response = self.client.get(
                    self.list_url,
                    {"user_id": value},
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )
                self.assertIn("user_id", response.json())

    def test_staff_filter_for_missing_user_returns_empty_list(self):
        self.client.force_authenticate(user=self.staff)
        missing_id = (
            max(
                self.staff.id,
                self.reader.id,
                self.other_reader.id,
            )
            + 1
        )

        response = self.client.get(
            self.list_url,
            {"user_id": missing_id},
        )

        self.assertEqual(self.response_ids(response), set())


class BorrowingReturnTests(APITestCase):
    def setUp(self):
        self.reader = get_user_model().objects.create_user(
            email="reader@example.com",
            password="testpass123",
        )
        self.other_reader = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )
        self.staff = get_user_model().objects.create_user(
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )

        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=2,
            daily_fee="2.50",
        )
        self.borrowing = Borrowing.objects.create(
            user=self.reader,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )

        self.url = reverse(
            "borrowing-return",
            args=[self.borrowing.id],
        )
        self.client.force_authenticate(user=self.reader)

    def assert_not_returned(self):
        self.borrowing.refresh_from_db()
        self.book.refresh_from_db()

        self.assertIsNone(self.borrowing.actual_return_date)
        self.assertEqual(self.book.inventory, 2)

    def test_owner_can_return_borrowing(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.borrowing.refresh_from_db()
        self.book.refresh_from_db()

        self.assertEqual(
            self.borrowing.actual_return_date,
            timezone.localdate(),
        )
        self.assertEqual(self.book.inventory, 3)
        self.assertEqual(response.json()["id"], self.borrowing.id)
        self.assertEqual(
            response.json()["actual_return_date"],
            timezone.localdate().isoformat(),
        )
        self.assertEqual(response.json()["book"]["inventory"], 3)
        self.assertEqual(Borrowing.objects.count(), 1)

    def test_cannot_return_borrowing_twice(self):
        first_response = self.client.post(self.url)
        self.assertEqual(first_response.status_code, status.HTTP_200_OK)

        self.borrowing.refresh_from_db()
        first_return_date = self.borrowing.actual_return_date

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.borrowing.refresh_from_db()
        self.book.refresh_from_db()

        self.assertEqual(
            self.borrowing.actual_return_date,
            first_return_date,
        )
        self.assertEqual(self.book.inventory, 3)

    def test_staff_can_return_another_users_borrowing(self):
        self.client.force_authenticate(user=self.staff)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.borrowing.refresh_from_db()
        self.book.refresh_from_db()

        self.assertEqual(
            self.borrowing.actual_return_date,
            timezone.localdate(),
        )
        self.assertEqual(self.book.inventory, 3)

    def test_regular_user_cannot_return_another_users_borrowing(self):
        self.client.force_authenticate(user=self.other_reader)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assert_not_returned()

    def test_anonymous_user_cannot_return_borrowing(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assert_not_returned()

    def test_returns_404_for_missing_borrowing(self):
        response = self.client.post(
            reverse(
                "borrowing-return",
                args=[self.borrowing.id + 1],
            ),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assert_not_returned()

    def test_get_cannot_return_borrowing(self):
        response = self.client.get(self.url)

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assert_not_returned()

    def test_rolls_back_return_date_when_inventory_update_fails(self):
        with patch(
            "borrowings.views.Book.objects.filter",
        ) as filter_mock:
            filter_mock.return_value.update.side_effect = RuntimeError(
                "Simulated inventory update failure"
            )

            with self.assertRaises(RuntimeError):
                self.client.post(self.url)

        filter_mock.return_value.update.assert_called_once()
        self.assert_not_returned()
