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