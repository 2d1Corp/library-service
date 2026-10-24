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


class PaymentSuccessQuerySerializer(serializers.Serializer):
    session_id = serializers.CharField(max_length=255)


class PaymentCallbackResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
