from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from borrowings.models import Borrowing
from borrowings.serializers import (
    BorrowingCreateSerializer,
    BorrowingReadSerializer,
)


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="is_active",
                type=OpenApiTypes.BOOL,
                description="Filter by return status: true or false.",
            ),
            OpenApiParameter(
                name="user_id",
                type=OpenApiTypes.INT,
                description="Filter by user ID. Staff only.",
            ),
        ],
    ),
)
class BorrowingViewSet(
    mixins.CreateModelMixin,
    viewsets.ReadOnlyModelViewSet,
):
    queryset = Borrowing.objects.select_related("book", "user")
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return BorrowingCreateSerializer
        return BorrowingReadSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user

        if not user.is_authenticated:
            return queryset.none()

        if not user.is_staff:
            queryset = queryset.filter(user=user)

        if self.action != "list":
            return queryset

        filters = serializers.Serializer(
            data=self.request.query_params,
        )
        filters.fields["is_active"] = serializers.ChoiceField(
            choices=("true", "false"),
            required=False,
        )
        filters.fields["user_id"] = serializers.IntegerField(
            min_value=1,
            required=False,
        )

        if not user.is_staff:
            del filters.fields["user_id"]

        filters.is_valid(raise_exception=True)

        is_active = filters.validated_data.get("is_active")
        user_id = filters.validated_data.get("user_id")

        if is_active is not None:
            queryset = queryset.filter(
                actual_return_date__isnull=(is_active == "true"),
            )

        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)

        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
