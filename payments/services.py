from django.conf import settings
from stripe import StripeClient, StripeError

from payments.models import Payment


class PaymentCreationError(Exception):
    pass


def calculate_borrowing_amount(borrowing):
    duration = borrowing.expected_return_date - borrowing.borrow_date
    days = max(1, duration.days)

    return days * borrowing.book.daily_fee


def create_payment_for_borrowing(borrowing):
    secret_key = settings.STRIPE_SECRET_KEY

    if not secret_key.startswith("sk_test_"):
        raise PaymentCreationError("Stripe test key is not configured.")

    amount = calculate_borrowing_amount(borrowing)
    amount_in_cents = int(amount * 100)

    client = StripeClient(secret_key)

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
                "success_url": "https://example.com/success",
                "cancel_url": "https://example.com/cancel",
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
