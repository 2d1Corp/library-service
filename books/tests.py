from decimal import Decimal

from django.test import TestCase

from books.models import Book

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


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


class BookApiTests(APITestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.staff)

    def test_creates_book(self):
        payload = {
            "title": "The Hobbit",
            "author": "J. R. R. Tolkien",
            "cover": "HARD",
            "inventory": 3,
            "daily_fee": "2.50",
        }

        response = self.client.post(
            reverse("book-list"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Book.objects.count(), 1)

    def create_book(self):
        return Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=3,
            daily_fee=Decimal("2.50"),
        )

    def test_retrieves_book(self):
        book = self.create_book()

        response = self.client.get(
            reverse("book-detail", args=[book.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], book.id)
        self.assertEqual(response.json()["title"], book.title)

    def test_updates_book_inventory(self):
        book = self.create_book()

        response = self.client.patch(
            reverse("book-detail", args=[book.id]),
            {"inventory": 0},
            format="json",
        )

        book.refresh_from_db()

        self.assertEqual(book.inventory, 0)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["inventory"], 0)

    def test_deletes_book(self):
        book = self.create_book()

        response = self.client.delete(
            reverse("book-detail", args=[book.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Book.objects.filter(id=book.id).exists())

    def test_rejects_negative_inventory(self):
        book = self.create_book()

        response = self.client.patch(
            reverse("book-detail", args=[book.id]),
            {"inventory": -1},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        book.refresh_from_db()

        self.assertEqual(book.inventory, 3)
        self.assertEqual(Book.objects.count(), 1)

    def test_lists_books(self):
        book = self.create_book()

        response = self.client.get(reverse("book-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], book.id)

    def test_replaces_book(self):
        book = self.create_book()
        payload = {
            "title": "Dune",
            "author": "Frank Herbert",
            "cover": "SOFT",
            "inventory": 5,
            "daily_fee": "4.00",
        }

        response = self.client.put(
            reverse("book-detail", args=[book.id]),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        book.refresh_from_db()
        self.assertEqual(book.title, payload["title"])
        self.assertEqual(book.author, payload["author"])
        self.assertEqual(book.cover, payload["cover"])
        self.assertEqual(book.inventory, payload["inventory"])
        self.assertEqual(book.daily_fee, Decimal(payload["daily_fee"]))
        self.assertEqual(Book.objects.count(), 1)

    def test_returns_404_for_missing_book(self):
        response = self.client.get(
            reverse("book-detail", args=[999]),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_reject_creation_with_negative_inventory(self):
        payload = {
            "title": "The Hobbit",
            "author": "J. R. R. Tolkien",
            "cover": "HARD",
            "inventory": -1,
            "daily_fee": "2.50",
        }

        response = self.client.post(
            reverse("book-list"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Book.objects.count(), 0)
