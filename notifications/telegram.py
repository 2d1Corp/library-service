import json
from urllib.request import Request, urlopen

from django.conf import settings


def send_telegram_message(text):
    url = f"https://api.telegram.org/" f"bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
    }
    body = json.dumps(payload).encode("utf-8")

    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(request, timeout=10) as response:
        result = json.load(response)

    return result
