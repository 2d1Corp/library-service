from django.urls import path

from users.views import UserCreateView

app_name = "users"

urlpatterns = [
    path("", UserCreateView.as_view(), name="create"),
]
