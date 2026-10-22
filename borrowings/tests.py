from datetime import timedelta
from unittest.mock import patch

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

    def test_anonymous_user_cannot_retrieve_borrowing(self):
        self.client.force_authenticate(user=None)

        response = self.client.get(
            reverse("borrowing-detail", args=[self.borrowing.id]),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_write_methods_are_not_allowed(self):
        detail_url = reverse(
            "borrowing-detail",
            args=[self.borrowing.id],
        )

        requests = (
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

    def test_regular_user_can_create_borrowing(self):
        reader = get_user_model().objects.create_user(
            email="reader@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=reader)

        expected_date = timezone.localdate() + timedelta(days=7)
        payload = {
            "book": self.book.id,
            "expected_return_date": expected_date.isoformat(),
            "user": self.user.id,
        }

        response = self.client.post(
            reverse("borrowing-list"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        borrowing = Borrowing.objects.get(pk=response.json()["id"])
        self.assertEqual(borrowing.user_id, reader.id)
        self.assertEqual(borrowing.book_id, self.book.id)
        self.assertEqual(borrowing.expected_return_date, expected_date)
        self.assertEqual(borrowing.borrow_date, timezone.localdate())
        self.assertIsNone(borrowing.actual_return_date)

        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 2)
        self.assertEqual(Borrowing.objects.count(), 2)

    def test_rejects_borrowing_when_no_copies_available(self):
        self.book.inventory = 0
        self.book.save(update_fields=["inventory"])

        response = self.client.post(
            reverse("borrowing-list"),
            {
                "book": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("book", response.json())
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 0)
        self.assertEqual(Borrowing.objects.count(), 1)

    def test_rejects_creation_with_past_expected_return_date(self):
        response = self.client.post(
            reverse("borrowing-list"),
            {
                "book": self.book.id,
                "expected_return_date": (
                    timezone.localdate() - timedelta(days=1)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("expected_return_date", response.json())
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)
        self.assertEqual(Borrowing.objects.count(), 1)

    def test_anonymous_user_cannot_create_borrowing(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            reverse("borrowing-list"),
            {
                "book": self.book.id,
                "expected_return_date": (
                    timezone.localdate() + timedelta(days=7)
                ).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)
        self.assertEqual(Borrowing.objects.count(), 1)

    def test_rolls_back_inventory_when_borrowing_creation_fails(self):
        with patch(
            "borrowings.serializers.Borrowing.objects.create",
            side_effect=RuntimeError("Simulated creation failure"),
        ) as create_mock:
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("borrowing-list"),
                    {
                        "book": self.book.id,
                        "expected_return_date": (
                            timezone.localdate() + timedelta(days=7)
                        ).isoformat(),
                    },
                    format="json",
                )

        create_mock.assert_called_once()
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, 3)
        self.assertEqual(Borrowing.objects.count(), 1)


class BorrowingAccessTests(APITestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            email="admin@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.reader = get_user_model().objects.create_user(
            email="first@example.com",
            password="testpass123",
        )
        self.other_reader = get_user_model().objects.create_user(
            email="second@example.com",
            password="testpass123",
        )

        self.book = Book.objects.create(
            title="The Hobbit",
            author="J. R. R. Tolkien",
            cover=Book.CoverType.HARD,
            inventory=3,
            daily_fee="2.50",
        )

        self.own_active = self.create_borrowing(self.reader)
        self.own_returned = self.create_borrowing(
            self.reader,
            returned=True,
        )
        self.other_active = self.create_borrowing(self.other_reader)

        self.client.force_authenticate(user=self.reader)
        self.list_url = reverse("borrowing-list")

    def create_borrowing(self, user, returned=False):
        return Borrowing.objects.create(
            user=user,
            book=self.book,
            expected_return_date=timezone.localdate() + timedelta(days=7),
            actual_return_date=timezone.localdate() if returned else None,
        )

    def response_ids(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {item["id"] for item in response.json()}

    def test_regular_user_lists_only_own_borrowings(self):
        response = self.client.get(self.list_url)

        self.assertEqual(
            self.response_ids(response),
            {self.own_active.id, self.own_returned.id},
        )

    def test_regular_user_retrieves_own_borrowing(self):
        response = self.client.get(
            reverse("borrowing-detail", args=[self.own_active.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], self.own_active.id)

    def test_regular_user_cannot_retrieve_another_users_borrowing(self):
        response = self.client.get(
            reverse("borrowing-detail", args=[self.other_active.id]),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_regular_user_cannot_select_another_user(self):
        response = self.client.get(
            self.list_url,
            {"user_id": self.other_reader.id},
        )

        self.assertEqual(
            self.response_ids(response),
            {self.own_active.id, self.own_returned.id},
        )

    def test_regular_user_filters_active_borrowings(self):
        response = self.client.get(
            self.list_url,
            {"is_active": "true"},
        )

        self.assertEqual(
            self.response_ids(response),
            {self.own_active.id},
        )

    def test_regular_user_filters_returned_borrowings(self):
        response = self.client.get(
            self.list_url,
            {"is_active": "false"},
        )

        self.assertEqual(
            self.response_ids(response),
            {self.own_returned.id},
        )

    def test_staff_lists_all_borrowings(self):
        self.client.force_authenticate(user=self.staff)

        response = self.client.get(self.list_url)

        self.assertEqual(
            self.response_ids(response),
            {
                self.own_active.id,
                self.own_returned.id,
                self.other_active.id,
            },
        )

    def test_staff_filters_by_user_and_active_status(self):
        self.client.force_authenticate(user=self.staff)

        response = self.client.get(
            self.list_url,
            {
                "user_id": self.reader.id,
                "is_active": "true",
            },
        )

        self.assertEqual(
            self.response_ids(response),
            {self.own_active.id},
        )

    def test_rejects_invalid_active_filter(self):
        response = self.client.get(
            self.list_url,
            {"is_active": "wrong"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("is_active", response.json())

    def test_staff_rejects_invalid_user_filter(self):
        self.client.force_authenticate(user=self.staff)

        for value in ("wrong", "0", "-1"):
            with self.subTest(user_id=value):
                response = self.client.get(
                    self.list_url,
                    {"user_id": value},
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )
                self.assertIn("user_id", response.json())

    def test_staff_filter_for_missing_user_returns_empty_list(self):
        self.client.force_authenticate(user=self.staff)
        missing_id = (
            max(
                self.staff.id,
                self.reader.id,
                self.other_reader.id,
            )
            + 1
        )

        response = self.client.get(
            self.list_url,
            {"user_id": missing_id},
        )

        self.assertEqual(self.response_ids(response), set())
