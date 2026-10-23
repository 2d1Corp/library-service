from celery import shared_task
from django.utils import timezone

from borrowings.models import Borrowing
from notifications.telegram import send_telegram_message


@shared_task
def notify_borrowing_created(borrowing_id):
    borrowing = Borrowing.objects.select_related("book").get(pk=borrowing_id)
    message = f"Borrowing {borrowing.id} has been created.\nBook title: {borrowing.book.title}\nExpected return date: {borrowing.expected_return_date}"
    send_telegram_message(message)


@shared_task
def notify_overdue_borrowings():
    overdue = (
        Borrowing.objects.filter(
            expected_return_date__lte=timezone.localdate(),
            actual_return_date__isnull=True,
        )
        .select_related("book", "user")
        .order_by("pk")
    )

    found = False
    for borrowing in overdue:
        found = True
        message = (
            f"Borrowing {borrowing.pk} is overdue.\n"
            f"Book title: {borrowing.book.title}\n"
            f"Borrowed by: {borrowing.user.email}\n"
            f"Borrow date: {borrowing.borrow_date}\n"
            f"Expected return date: {borrowing.expected_return_date}"
        )
        send_telegram_message(message)

    if not found:
        send_telegram_message("No borrowings overdue today!")
