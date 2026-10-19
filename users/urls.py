from django.urls import path

from users.views import UserCreateView, UserProfileView
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

app_name = "users"

urlpatterns = [
    path("", UserCreateView.as_view(), name="create"),
    path("me/", UserProfileView.as_view(), name="me"),
    path("token/", TokenObtainPairView.as_view(), name="token"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
]
