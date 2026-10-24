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
from stripe import StripeError
from stripe.checkout import Session

from payments.stripe_demo import create_test_payment


@override_settings(STRIPE_SECRET_KEY="sk_test_example")
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

    def mock_stripe_session(self, **changes):
        stripe_patch = patch("payments.services.StripeClient")
        self.addCleanup(stripe_patch.stop)
        client_class = stripe_patch.start()
        retrieve = client_class.return_value.v1.checkout.sessions.retrieve
        data = {
            "id": self.payment.session_id,
            "object": "checkout.session",
            "mode": "payment",
            "livemode": False,
            "currency": "usd",
            "amount_total": 600,
            "metadata": {"borrowing_id": str(self.payment.borrowing_id)},
            "payment_status": "paid",
        }
        data.update(changes)
        retrieve.return_value = Session.construct_from(data, "sk_test_example")
        return retrieve

    def test_success_confirms_payment_only_once(self):
        retrieve = self.mock_stripe_session()
        url = reverse("payment-success")
        query = {"session_id": self.payment.session_id}

        first = self.client.get(url, query)
        second = self.client.get(url, query)

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.json(), {"detail": "Payment confirmed."})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.other_payment.refresh_from_db()
        self.assertEqual(self.other_payment.status, Payment.Status.PENDING)
        self.assertEqual(Payment.objects.count(), 2)
        retrieve.assert_called_once_with(self.payment.session_id)

    def test_unpaid_session_does_not_confirm_payment(self):
        self.mock_stripe_session(payment_status="unpaid")
        response = self.client.get(
            reverse("payment-success"),
            {"session_id": self.payment.session_id},
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_mismatched_session_does_not_confirm_payment(self):
        retrieve = self.mock_stripe_session()
        invalid_values = {
            "id": "cs_test_unrelated",
            "mode": "setup",
            "livemode": True,
            "currency": "eur",
            "amount_total": 1,
            "metadata": {"borrowing_id": "unrelated"},
        }
        for field, invalid_value in invalid_values.items():
            with self.subTest(field=field):
                original = retrieve.return_value[field]
                retrieve.return_value[field] = invalid_value
                response = self.client.get(
                    reverse("payment-success"),
                    {"session_id": self.payment.session_id},
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.payment.refresh_from_db()
                self.assertEqual(self.payment.status, Payment.Status.PENDING)
                retrieve.return_value[field] = original

    def test_success_requires_session_id(self):
        retrieve = self.mock_stripe_session()
        for query in ({}, {"session_id": ""}, {"session_id": "x" * 256}):
            with self.subTest(query=query):
                response = self.client.get(reverse("payment-success"), query)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        retrieve.assert_not_called()

    def test_unknown_session_returns_404(self):
        retrieve = self.mock_stripe_session()
        response = self.client.get(
            reverse("payment-success"),
            {"session_id": "cs_test_missing"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        retrieve.assert_not_called()

    def test_stripe_failure_keeps_payment_pending(self):
        retrieve = self.mock_stripe_session()
        retrieve.side_effect = StripeError("Test Stripe failure")
        with self.assertLogs("payments.views", level="ERROR"):
            response = self.client.get(
                reverse("payment-success"),
                {"session_id": self.payment.session_id},
            )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    @override_settings(STRIPE_SECRET_KEY="")
    def test_confirmation_without_key_keeps_payment_pending(self):
        retrieve = self.mock_stripe_session()
        with self.assertLogs("payments.views", level="ERROR"):
            response = self.client.get(
                reverse("payment-success"),
                {"session_id": self.payment.session_id},
            )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        retrieve.assert_not_called()

    def test_cancel_does_not_change_payment(self):
        retrieve = self.mock_stripe_session()
        for payment_status in (Payment.Status.PENDING, Payment.Status.PAID):
            with self.subTest(payment_status=payment_status):
                Payment.objects.filter(pk=self.payment.pk).update(status=payment_status)
                response = self.client.get(reverse("payment-cancel"))
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.payment.refresh_from_db()
                self.assertEqual(self.payment.status, payment_status)
                self.assertEqual(Payment.objects.count(), 2)
        retrieve.assert_not_called()
