from django.urls import path

from users.views import UserCreateView, UserProfileView

app_name = "users"

urlpatterns = [
    path("", UserCreateView.as_view(), name="create"),
    path("me/", UserProfileView.as_view(), name="me"),
]
