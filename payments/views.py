import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from payments.models import Payment
from payments.serializers import (
    PaymentCallbackResponseSerializer,
    PaymentSerializer,
    PaymentSuccessQuerySerializer,
)
from payments.services import (
    PaymentSessionMismatch,
    PaymentVerificationError,
    confirm_payment,
)

logger = logging.getLogger(__name__)


class PaymentViewSet(ReadOnlyModelViewSet):
    queryset = Payment.objects.select_related("borrowing")
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if user.is_staff:
            return queryset

        return queryset.filter(borrowing__user=user)


class PaymentSuccessView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="session_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
            ),
        ],
        responses={
            200: PaymentCallbackResponseSerializer,
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
            409: PaymentCallbackResponseSerializer,
            503: PaymentCallbackResponseSerializer,
        },
    )
    def get(self, request):
        query = PaymentSuccessQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        payment = get_object_or_404(
            Payment,
            session_id=query.validated_data["session_id"],
        )

        try:
            paid = confirm_payment(payment)
        except PaymentSessionMismatch:
            return Response(
                {"detail": "Stripe session does not match this payment."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except PaymentVerificationError:
            logger.exception("Payment verification failed.")
            return Response(
                {"detail": "Payment service is unavailable. Try again later."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not paid:
            return Response(
                {"detail": "Payment has not been confirmed by Stripe."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response({"detail": "Payment confirmed."})


class PaymentCancelView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Static checkout cancel return page",
        description=(
            "Static informational return page. It does not read or validate "
            "session_id, look up a Payment, or contact Stripe. It returns the "
            "same message for every request and never changes payment status."
        ),
        responses={200: PaymentCallbackResponseSerializer},
    )
    def get(self, request):
        return Response(
            {
                "detail": (
                    "You can complete payment later using the checkout link "
                    "while the session remains active (normally 24 hours)."
                ),
            },
        )
