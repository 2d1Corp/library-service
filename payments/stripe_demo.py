from decimal import Decimal

from django.conf import settings
from stripe import StripeClient

from borrowings.models import Borrowing
from payments.models import Payment


def create_test_payment(borrowing_id):
    secret_key = settings.STRIPE_SECRET_KEY

    if not secret_key.startswith("sk_test_"):
        raise ValueError("Configure a Stripe test secret key first.")

    borrowing = Borrowing.objects.select_related("book").get(
        pk=borrowing_id,
    )

    amount = Decimal("6.00")
    amount_in_cents = int(amount * 100)

    client = StripeClient(secret_key)

    session = client.v1.checkout.sessions.create(
        {
            "mode": "payment",
            "line_items": [
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": amount_in_cents,
                        "product_data": {
                            "name": f"Library borrowing: {borrowing.book.title}",
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

    payment = Payment.objects.create(
        borrowing=borrowing,
        money_to_pay=amount,
        session_id=session.id,
        session_url=session.url,
    )

    print(f"Payment ID: {payment.pk}")
    print(f"Borrowing ID: {borrowing.pk}")
    print(f"Checkout URL: {payment.session_url}")

    return payment
