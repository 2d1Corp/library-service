from celery import shared_task

from borrowings.models import Borrowing
from notifications.telegram import send_telegram_message


@shared_task
def notify_borrowing_created(borrowing_id):
    borrowing = Borrowing.objects.select_related("book").get(pk=borrowing_id)
    message = f"Borrowing {borrowing.id} has been created.\nBook title: {borrowing.book.title}\nExpected return date: {borrowing.expected_return_date}"
    send_telegram_message(message)
