from decimal import Decimal

from django.test import TestCase

from books.models import Book

from django.core.exceptions import ValidationError


class BookModelTests(TestCase):
    def test_allows_zero_inventory(self):
        book = Book(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=0,
            daily_fee=Decimal("2.50"),
        )

        book.full_clean()
        book.save()
        book.refresh_from_db()

        self.assertEqual(book.inventory, 0)

    def test_rejects_negative_inventory(self):
        book = Book(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=-1,
            daily_fee=Decimal("2.50"),
        )

        with self.assertRaises(ValidationError):
            book.full_clean()

    def test_rejects_invalid_cover(self):
        book = Book(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover="NONE",
            inventory=1,
            daily_fee=Decimal("2.50"),
        )

        with self.assertRaises(ValidationError):
            book.full_clean()

    def test_rejects_zero_daily_fee(self):
        book = Book(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=1,
            daily_fee=Decimal("0.00"),
        )

        with self.assertRaises(ValidationError):
            book.full_clean()
