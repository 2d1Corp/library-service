from django.conf import settings
from django.db import models


class Borrowing(models.Model):
    book = models.ForeignKey(
        "books.Book",
        on_delete=models.PROTECT,
        related_name="borrowings",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="borrowings"
    )
    borrow_date = models.DateField(auto_now_add=True)
    expected_return_date = models.DateField()
    actual_return_date = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    expected_return_date__gte=models.F("borrow_date"),
                ),
                name="borrowing_expected_not_before_borrow",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(actual_return_date__isnull=True)
                    | models.Q(
                        actual_return_date__gte=models.F("borrow_date"),
                    )
                ),
                name="borrowing_actual_not_before_borrow",
            ),
        ]
