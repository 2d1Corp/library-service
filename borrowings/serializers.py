import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

from books.models import Book
from books.serializers import BookSerializer
from borrowings.models import Borrowing
from payments.serializers import PaymentSerializer
from payments.services import (
    PaymentCreationError,
    create_payment_for_borrowing,
)

logger = logging.getLogger(__name__)


class PaymentServiceUnavailable(APIException):
    status_code = 503
    default_detail = "Could not prepare payment. Please try again later."
    default_code = "payment_service_unavailable"


class BorrowingReadSerializer(serializers.ModelSerializer):
    book = BookSerializer(read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Borrowing
        fields = (
            "id",
            "book",
            "user",
            "borrow_date",
            "expected_return_date",
            "actual_return_date",
            "payments",
        )


class BorrowingCreateSerializer(serializers.ModelSerializer):
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Borrowing
        fields = (
            "id",
            "book",
            "expected_return_date",
            "payments",
        )
        read_only_fields = ("id",)

    def validate_expected_return_date(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError(
                "Expected return date cannot be in the past."
            )
        return value

    def create(self, validated_data):
        book = validated_data["book"]

        try:
            with transaction.atomic():
                updated = Book.objects.filter(
                    pk=book.pk,
                    inventory__gt=0,
                ).update(
                    inventory=F("inventory") - 1,
                )

                if updated == 0:
                    raise serializers.ValidationError(
                        {"book": "No copies of this book are available."}
                    )

                borrowing = Borrowing.objects.create(**validated_data)
                create_payment_for_borrowing(
                    borrowing,
                    self.context["request"],
                )

        except PaymentCreationError as error:
            logger.exception("Payment preparation failed.")
            raise PaymentServiceUnavailable() from error

        return borrowing
