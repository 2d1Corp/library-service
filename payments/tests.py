from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from books.models import Book
from borrowings.models import Borrowing
from payments.models import Payment
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings

from payments.stripe_demo import create_test_payment


class PaymentApiTests(APITestCase):
    def setUp(self):
        self.reader = get_user_model().objects.create_user(
            email="reader@example.com",
            password="testpass123",
        )
        self.other = get_user_model().objects.create_user(
            email="other@example.com",
            password="testpass123",
        )
        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=3,
            daily_fee="2.00",
        )

        self.payment = self.create_payment(self.reader, "cs_test_reader")
        self.other_payment = self.create_payment(self.other, "cs_test_other")

    def create_payment(self, user, session_id):
        borrowing = Borrowing.objects.create(
            user=user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=3),
        )
        return Payment.objects.create(
            borrowing=borrowing,
            money_to_pay="6.00",
            session_id=session_id,
            session_url=f"https://example.com/checkout/{session_id}",
        )

    def test_reader_lists_only_own_payments(self):
        self.client.force_authenticate(user=self.reader)

        response = self.client.get(reverse("payment-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [payment["id"] for payment in response.json()],
            [self.payment.id],
        )

    def test_reader_cannot_retrieve_another_users_payment(self):
        self.client.force_authenticate(user=self.reader)

        response = self.client.get(
            reverse("payment-detail", args=[self.other_payment.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_lists_all_payments(self):
        staff = get_user_model().objects.create_user(
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=staff)

        response = self.client.get(reverse("payment-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            [payment["id"] for payment in response.json()],
            [self.payment.id, self.other_payment.id],
        )

    def test_anonymous_user_cannot_list_payments(self):
        response = self.client.get(reverse("payment-list"))

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reader_retrieves_own_payment(self):
        self.client.force_authenticate(user=self.reader)

        response = self.client.get(
            reverse("payment-detail", args=[self.payment.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "id": self.payment.id,
                "borrowing": self.payment.borrowing_id,
                "status": "PENDING",
                "payment_type": "PAYMENT",
                "money_to_pay": "6.00",
                "session_id": "cs_test_reader",
                "session_url": self.payment.session_url,
            },
        )

    def test_payment_writes_are_not_allowed(self):
        self.client.force_authenticate(user=self.reader)
        detail_url = reverse("payment-detail", args=[self.payment.id])

        requests = (
            ("post", reverse("payment-list")),
            ("put", detail_url),
            ("patch", detail_url),
            ("delete", detail_url),
        )

        for method, url in requests:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    url,
                    {"status": "PAID"},
                    format="json",
                )
                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                )

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertEqual(Payment.objects.count(), 2)

    @override_settings(STRIPE_SECRET_KEY="sk_test_example")
    def test_creates_payment_from_stripe_session(self):
        with patch("payments.stripe_demo.StripeClient") as client_class:
            create_session = client_class.return_value.v1.checkout.sessions.create
            create_session.return_value.id = "cs_test_demo"
            create_session.return_value.url = (
                "https://checkout.stripe.com/c/pay/cs_test_demo"
            )

            payment = create_test_payment(self.payment.borrowing_id)

        client_class.assert_called_once_with("sk_test_example")
        create_session.assert_called_once()

        parameters = create_session.call_args.args[0]
        item = parameters["line_items"][0]

        self.assertEqual(parameters["mode"], "payment")
        self.assertEqual(item["price_data"]["currency"], "usd")
        self.assertEqual(item["price_data"]["unit_amount"], 600)
        self.assertEqual(item["quantity"], 1)

        payment.refresh_from_db()
        self.assertEqual(payment.borrowing_id, self.payment.borrowing_id)
        self.assertEqual(payment.money_to_pay, Decimal("6.00"))
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.session_id, "cs_test_demo")
        self.assertEqual(
            payment.session_url,
            "https://checkout.stripe.com/c/pay/cs_test_demo",
        )
        self.assertEqual(Payment.objects.count(), 3)

    @override_settings(STRIPE_SECRET_KEY="")
    def test_missing_key_does_not_create_payment(self):
        with patch("payments.stripe_demo.StripeClient") as client_class:
            with self.assertRaisesMessage(
                ValueError,
                "Configure a Stripe test secret key first.",
            ):
                create_test_payment(self.payment.borrowing_id)

        client_class.assert_not_called()
        self.assertEqual(Payment.objects.count(), 2)
