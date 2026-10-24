from borrowings.models import Borrowing
from django.db import models


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"

    class PaymentType(models.TextChoices):
        PAYMENT = "PAYMENT", "Payment"
        FINE = "FINE", "Fine"

    borrowing = models.ForeignKey(
        Borrowing, on_delete=models.PROTECT, related_name="payments"
    )
    status = models.CharField(
        max_length=7,
        choices=Status,
        default=Status.PENDING,
    )
    payment_type = models.CharField(
        max_length=7,
        choices=PaymentType,
        default=PaymentType.PAYMENT,
    )
    money_to_pay = models.DecimalField(max_digits=10, decimal_places=2)
    session_id = models.CharField(max_length=255)
    session_url = models.URLField(max_length=2048)
