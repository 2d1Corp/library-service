from rest_framework import serializers

from payments.models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = (
            "id",
            "borrowing",
            "status",
            "payment_type",
            "money_to_pay",
            "session_id",
            "session_url",
        )
        read_only_fields = fields
