from rest_framework.routers import DefaultRouter

from borrowings.views import BorrowingViewSet

router = DefaultRouter()
router.register("borrowings", BorrowingViewSet)

urlpatterns = router.urls
