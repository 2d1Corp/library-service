from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

import borrowings
from books.models import Book
from borrowings.models import Borrowing
from django.db import IntegrityError, transaction

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class BorrowingModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="reader@example.com",
            password="testpass123",
        )
        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=3,
            daily_fee="2.50",
        )

    def test_creates_borrowing_without_actual_return_date(self):
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )

        borrowing.refresh_from_db()

        self.assertEqual(borrowing.borrow_date, timezone.localdate())
        self.assertIsNone(borrowing.actual_return_date)

    def test_rejects_expected_return_date_before_borrow_date(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Borrowing.objects.create(
                    user=self.user,
                    book=self.book,
                    expected_return_date=(timezone.localdate() - timedelta(days=1)),
                )

        self.assertEqual(Borrowing.objects.count(), 0)

    def test_rejects_actual_return_date_before_borrow_date(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Borrowing.objects.create(
                    user=self.user,
                    book=self.book,
                    actual_return_date=timezone.localdate() - timedelta(days=1),
                    expected_return_date=(timezone.localdate() + timedelta(days=7)),
                )

        self.assertEqual(Borrowing.objects.count(), 0)

    def test_allows_return_on_borrow_date(self):
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            actual_return_date=timezone.localdate(),
            expected_return_date=timezone.localdate(),
        )

        borrowing.refresh_from_db()
        self.assertEqual(borrowing.actual_return_date, borrowing.borrow_date)
        self.assertEqual(borrowing.expected_return_date, borrowing.borrow_date)

    def test_prevents_deleting_borrowed_book(self):
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )

        with self.assertRaises(ProtectedError):
            self.book.delete()

        self.assertTrue(Book.objects.filter(pk=self.book.pk).exists())
        self.assertTrue(Borrowing.objects.filter(pk=borrowing.pk).exists())

    def test_prevents_deleting_borrower(self):
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )
        with self.assertRaises(ProtectedError):
            self.user.delete()

        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertTrue(Borrowing.objects.filter(pk=borrowing.pk).exists())


class BorrowingApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.client.force_authenticate(user=self.user)

        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=3,
            daily_fee="2.50",
        )

        self.borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
        )

    def test_retrieves_borrowing(self):
        response = self.client.get(
            reverse("borrowing-detail", args=[self.borrowing.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], self.borrowing.id)
        self.assertEqual(response.json()["book"]["id"], self.book.id)

    def test_lists_borrowing(self):
        response = self.client.get(
            reverse("borrowing-list"),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], self.borrowing.id)
        self.assertEqual(response.json()[0]["book"]["id"], self.book.id)
        self.assertEqual(response.json()[0]["book"]["title"], self.book.title)

    def test_returns_404_for_missing_borrowing(self):
        response = self.client.get(
            reverse("borrowing-detail", args=[self.borrowing.id + 1])
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_user_cannot_list_borrowings(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse("borrowing-list"))

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_regular_user_cannot_list_borrowings(self):
        user = get_user_model().objects.create_user(
            email="reader@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse("borrowing-list"))

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_anonymous_user_cannot_retrieve_borrowing(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(
            reverse("borrowing-detail", args=[self.borrowing.id]),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_regular_user_cannot_retrieve_borrowing(self):
        user = get_user_model().objects.create_user(
            email="reader@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=user)

        response = self.client.get(
            reverse("borrowing-detail", args=[self.borrowing.id]),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_write_methods_are_not_allowed(self):
        list_url = reverse("borrowing-list")
        detail_url = reverse(
            "borrowing-detail",
            args=[self.borrowing.id],
        )

        requests = (
            ("post", list_url),
            ("put", detail_url),
            ("patch", detail_url),
            ("delete", detail_url),
        )

        for method, url in requests:
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    url,
                    {},
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_405_METHOD_NOT_ALLOWED,
                )

        self.assertEqual(Borrowing.objects.count(), 1)
        self.assertTrue(Borrowing.objects.filter(pk=self.borrowing.pk).exists())

        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)

    def test_list_uses_one_query_when_borrowings_increase(self):
        url = reverse("borrowing-list")

        with self.assertNumQueries(1):
            response = self.client.get(url)
            data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(data), 1)

        for index in range(3):
            book = Book.objects.create(
                title=f"Book {index}",
                author="Test Author",
                cover=Book.CoverType.SOFT,
                inventory=2,
                daily_fee="1.50",
            )
            Borrowing.objects.create(
                user=self.user,
                book=book,
                expected_return_date=(timezone.localdate() + timedelta(days=7)),
            )

        with self.assertNumQueries(1):
            response = self.client.get(url)
            data = response.json()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(data), 4)
