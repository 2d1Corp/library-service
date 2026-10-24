from django.conf import settings
from django.urls import reverse
from stripe import StripeClient, StripeError

from payments.models import Payment


class PaymentCreationError(Exception):
    pass


class PaymentVerificationError(Exception):
    pass


class PaymentSessionMismatch(Exception):
    pass


def calculate_borrowing_amount(borrowing):
    duration = borrowing.expected_return_date - borrowing.borrow_date
    days = max(1, duration.days)

    return days * borrowing.book.daily_fee


def create_payment_for_borrowing(borrowing, request):
    secret_key = settings.STRIPE_SECRET_KEY

    if not secret_key.startswith("sk_test_"):
        raise PaymentCreationError("Stripe test key is not configured.")

    amount = calculate_borrowing_amount(borrowing)
    amount_in_cents = int(amount * 100)

    client = StripeClient(secret_key)
    success_url = (
        request.build_absolute_uri(reverse("payment-success"))
        + "?session_id={CHECKOUT_SESSION_ID}"
    )
    cancel_url = request.build_absolute_uri(reverse("payment-cancel"))

    try:
        session = client.v1.checkout.sessions.create(
            {
                "mode": "payment",
                "line_items": [
                    {
                        "price_data": {
                            "currency": "usd",
                            "unit_amount": amount_in_cents,
                            "product_data": {
                                "name": (f"Library borrowing: {borrowing.book.title}"),
                            },
                        },
                        "quantity": 1,
                    },
                ],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": {
                    "borrowing_id": str(borrowing.pk),
                },
            },
        )
    except StripeError as error:
        raise PaymentCreationError(
            "Could not create a Stripe checkout session."
        ) from error

    return Payment.objects.create(
        borrowing=borrowing,
        money_to_pay=amount,
        session_id=session.id,
        session_url=session.url,
    )


def confirm_payment(payment):
    if payment.status == Payment.Status.PAID:
        return True

    secret_key = settings.STRIPE_SECRET_KEY
    if not secret_key.startswith("sk_test_"):
        raise PaymentVerificationError("Stripe test key is not configured.")

    client = StripeClient(secret_key)
    try:
        session = client.v1.checkout.sessions.retrieve(payment.session_id).to_dict()
    except StripeError as error:
        raise PaymentVerificationError(
            "Could not verify the Stripe session."
        ) from error

    matches = (
        session.get("id") == payment.session_id
        and session.get("mode") == "payment"
        and session.get("livemode") is False
        and session.get("currency") == "usd"
        and session.get("amount_total") == int(payment.money_to_pay * 100)
        and (session.get("metadata") or {}).get("borrowing_id")
        == str(payment.borrowing_id)
    )
    if not matches:
        raise PaymentSessionMismatch("Stripe session does not match this payment.")

    if session.get("payment_status") != "paid":
        return False

    updated = Payment.objects.filter(
        pk=payment.pk,
        status=Payment.Status.PENDING,
    ).update(status=Payment.Status.PAID)
    if updated == 1:
        return True

    # Another request may have confirmed it after our initial read.
    return Payment.objects.filter(pk=payment.pk, status=Payment.Status.PAID).exists()
