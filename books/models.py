from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class Book(models.Model):
    class CoverType(models.TextChoices):
        HARD = "HARD", "Hard cover"
        SOFT = "SOFT", "Soft cover"

    cover = models.CharField(
        max_length=4,
        choices=CoverType.choices,
    )
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    inventory = models.PositiveIntegerField()
    daily_fee = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
