from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class UserRegistrationTests(APITestCase):
    def test_rejects_short_password(self):
        payload = {
            "email": "test@example.com",
            "password": "123",
        }

        response = self.client.post(
            reverse("users:create"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_creates_user(self):
        payload = {
            "email": "test@example.com",
            "password": "secret123",
        }

        response = self.client.post(
            reverse("users:create"),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertNotIn("password", response.json())

        user = get_user_model().objects.get(email=payload["email"])

        self.assertTrue(user.check_password(payload["password"]))

    def test_rejects_duplicate_email(self):
        get_user_model().objects.create_user(
            email="test@example.com",
            password="secret123",
        )

        response = self.client.post(
            reverse("users:create"),
            {
                "email": "test@example.com",
                "password": "another123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(get_user_model().objects.count(), 1)


class UserProfileTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="profile@example.com",
            password="secret123",
            first_name="Alex",
        )

    def test_retrieves_own_profile(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.get(reverse("users:me"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], self.user.id)
        self.assertNotIn("password", response.json())

    def test_updates_own_name(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            reverse("users:me"),
            {"first_name": "Oleksandr"},
            format="json",
        )

        self.user.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.user.first_name, "Oleksandr")
        self.assertTrue(self.user.check_password("secret123"))

    def test_updates_own_password(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            reverse("users:me"),
            {"password": "newsecret456"},
            format="json",
        )

        self.user.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(self.user.check_password("newsecret456"))
        self.assertFalse(self.user.check_password("secret123"))
        self.assertNotIn("password", response.json())

    def test_requires_authentication(self):
        response = self.client.get(reverse("users:me"))

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_cannot_promote_self(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.patch(
            reverse("users:me"),
            {
                "first_name": "Oleksandr",
                "is_staff": True,
                "is_superuser": True,
            },
            format="json",
        )

        self.user.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self.user.first_name, "Oleksandr")
        self.assertFalse(self.user.is_staff)
        self.assertFalse(self.user.is_superuser)
