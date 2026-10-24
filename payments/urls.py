from django.urls import path
from rest_framework.routers import DefaultRouter

from payments.views import PaymentCancelView, PaymentSuccessView, PaymentViewSet

router = DefaultRouter()
router.register("payments", PaymentViewSet, basename="payment")

urlpatterns = [
    path("payments/success/", PaymentSuccessView.as_view(), name="payment-success"),
    path("payments/cancel/", PaymentCancelView.as_view(), name="payment-cancel"),
] + router.urls
