# Library Service API

REST API for managing a library. Currently implements user accounts, book catalog CRUD, and borrowing creation, reading, filtering, and returns.

## Implemented features

- User registration with email and password
- JWT authentication with access and refresh tokens
- Viewing and updating your own profile
- Public book list and detail; staff-only creation, updates, and deletion
- Authenticated borrowing creation with atomic inventory updates
- Borrowing list and detail with nested book data: users see their own records, staff see all
- Borrowing filters by active status; staff can also filter by user ID
- Borrowing returns with atomic inventory restoration and duplicate-return protection
- Borrowing date constraints and protection against deleting related books or users
- OpenAPI schema and Swagger UI
- Telegram notifications to the library chat after a borrowing is created
- Automatic Stripe sandbox Checkout sessions and server-verified payment confirmation

## Local setup (PowerShell)

Tested with Python 3.12. Run the following commands in PowerShell:

```powershell
git clone https://github.com/2d1Corp/library-service.git
cd library-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Generate a local secret key and save it to `.env`:

```powershell
python -c "from pathlib import Path; from django.core.management.utils import get_random_secret_key; Path('.env').write_text('SECRET_KEY=' + get_random_secret_key() + '\n', encoding='utf-8')"
```

Run this once during initial setup: it replaces the contents of `.env`. The file is ignored by Git; `.env.example` documents the required variable without a real secret.

Apply migrations and create a superuser to create, update, and delete books:

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

These instructions start the local development server. To send notifications,
also configure Telegram and run Redis and a Celery worker as described below.

## Borrowing notifications (Telegram)

Creating a borrowing saves the record and decrements book inventory first.
After the database transaction commits, Django queues a task in Redis.
A separate Celery worker loads the borrowing and sends its ID, book title,
and expected return date to the library's Telegram chat.

At **09:00 UTC each day**, Celery beat queues a second task. It notifies the
chat separately about every unreturned borrowing with an expected return
date of **today or earlier**, including its book, reader email, and dates.
If there are none, it sends `No borrowings overdue today!` once.
Payment notifications are not implemented yet.

Create a Telegram bot and add it to a chat where it can post messages. In
`.env`, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (see `.env.example`).
Never commit real credentials. The setup command above overwrites `.env`,
so add these values **after** running it.

Start Redis locally with Docker:

```powershell
docker run -d --name library-redis -p 127.0.0.1:6379:6379 redis:7-alpine
docker exec library-redis redis-cli ping
```

The ping should return `PONG`. On later runs, use
`docker start library-redis` instead of `docker run`. The default broker
address is `redis://127.0.0.1:6379/0`; set `CELERY_BROKER_URL` in `.env`
if your Redis server has a different address.

In another PowerShell terminal with the virtual environment activated, run:

```powershell
python -m celery -A drf_library_practice worker -P solo -l info
```

Restart the worker after changing `notifications/tasks.py` so it discovers
new tasks.

Start the daily scheduler in a third PowerShell terminal:

```powershell
python -m celery -A drf_library_practice beat -l info
```

Run only one beat instance for this schedule, or duplicate daily
notifications may be sent. The default scheduler writes a local
`celerybeat-schedule` file (ignored by Git).

Keep Redis and the worker running to send notifications. The Django
development server is also needed for API requests, but not for the daily
schedule. `runserver` alone sends no notifications. `-P solo` is used for
local Windows worker development.

To check delivery without waiting until 09:00 UTC, enqueue the overdue
task manually while Redis and the worker are running:

```powershell
python manage.py shell -c "from notifications.tasks import notify_overdue_borrowings; notify_overdue_borrowings.delay()"
```

This sends real messages to the configured Telegram chat. Running it
manually in addition to the daily schedule can send duplicates.

## API documentation and authentication

Open [Swagger UI](http://127.0.0.1:8000/api/docs/) after starting the server. The OpenAPI schema is available at `/api/schema/`.

To authenticate:

1. Send your email and password to `POST /api/users/token/` to obtain access and refresh tokens. Use the superuser account created above to create, update, and delete books.
2. Send the access token in the following header for protected requests:

   ```text
   Authorize: Bearer <access_token>
   ```

   The configured header name is `Authorize`. In Swagger UI, click **Authorize** and enter `Bearer <access_token>` (including the prefix and space). Swagger UI does not add the prefix automatically for this custom header.
3. Send the refresh token to `POST /api/users/token/refresh/` to obtain a new access token.

Regular accounts can register at `POST /api/users/` and access their own profile at `/api/users/me/`.

Anyone can list and retrieve books without authentication. Creating, updating, and deleting books requires an authenticated staff user.

## Book fields

| Field | Description |
|---|---|
| `id` | Generated by the database; read-only |
| `title` | Book title, up to 255 characters |
| `author` | Author name, up to 255 characters |
| `cover` | `HARD` or `SOFT` |
| `inventory` | Available copies; zero is allowed |
| `daily_fee` | Daily rental fee, from `0.01` to `9999.99` |

## Borrowings

| Method | Endpoint | Access |
|---|---|---|
| POST | `/api/borrowings/` | Any authenticated user |
| GET | `/api/borrowings/` | Own records for regular users; all records for staff |
| GET | `/api/borrowings/<id>/` | Owner or staff |
| POST | `/api/borrowings/<id>/return/` | Owner or staff |

GET responses include the borrowing ID, nested book data, user ID, borrow date,
expected return date, and nullable actual return date. The list response is an
unpaginated JSON array.

Anonymous requests receive `401`. Regular users can list and retrieve only
their own borrowings. Staff can access all borrowings. Requests for nonexistent
borrowings, or borrowings outside the user's permitted records, return `404`.

The list endpoint supports these optional filters:

- `is_active=true`: borrowings not returned yet.
- `is_active=false`: returned borrowings.
- `user_id=12`: borrowings of user 12; staff only. This parameter is ignored
  for regular users, who always see only their own records.

Staff can combine both filters:
`/api/borrowings/?user_id=12&is_active=true`.

Invalid `is_active` values or invalid staff `user_id` values return `400`.
The `user_id` value must be a positive integer; a valid ID with no matching
borrowings returns an empty list. Filters apply only to the list endpoint.
PUT, PATCH, and DELETE are not supported (`405` for authenticated users).

### Create a borrowing

Send an authenticated `POST /api/borrowings/` with a book ID and expected return
date. For example (replace the ID and date with current valid values):

```json
{
  "book": 7,
  "expected_return_date": "2026-10-29"
}
```

The expected return date must be today or later, and the book must have at least
one available copy. A successful request returns `201` with `id`, `book` (the
book ID), `expected_return_date`, and a read-only `payments` array.

The owner is always the authenticated user; a `user` value in the request body
cannot assign the borrowing to another account. The borrow date is set
automatically, and the actual return date starts as null.

Creating the borrowing and decrementing book inventory by one happen in a single
transaction. Inventory is decremented only if its current database value is
positive. If borrowing creation fails, the inventory change is rolled back.

An unavailable book, a nonexistent book ID, or a past expected return date
returns `400` without creating a borrowing or changing inventory. An anonymous
POST returns `401` without changes.

### Return a borrowing

Send an authenticated `POST /api/borrowings/<id>/return/` with no request body.
The owner or a staff user can return the borrowing. A successful request returns
`200` with the full borrowing representation, including nested book data.

The server sets the actual return date to today and increases available book
inventory by one in a single transaction. If the inventory update fails, the
return date is rolled back. The borrowing remains in the database as history.
A second return attempt receives `400` without changing the date or inventory.

Anonymous requests receive `401`. A nonexistent borrowing or one belonging to
another regular user receives `404`. GET on the return endpoint receives `405`.
After return, the borrowing appears under `is_active=false` rather than
`is_active=true`.

Expected and actual return dates cannot precede the borrow date. Returning on
the borrow date is allowed; the actual return date can be null until return.
Related books and users cannot be deleted while borrowing records reference them.
Reading borrowings does not change book inventory.

## Payments

- GET `/api/payments/` — own payments for regular users; all payments for staff.
- GET `/api/payments/<id>/` — payment details for the owner or staff.
- Authentication is required (`401` for anonymous requests).
- Missing payments and other users' payments return `404`.
- POST, PUT, PATCH and DELETE are not supported (`405` for authenticated users).

Responses include the borrowing ID, status, payment type, amount in USD,
and Stripe session ID and URL.

### Manual Stripe sandbox demo

Add `STRIPE_SECRET_KEY` to your local `.env` using a sandbox secret key
starting with `sk_test_`. Never commit the key.

Choose an existing borrowing ID and run the following command,
replacing `1` with that ID:

```powershell
python manage.py shell -c "from payments.stripe_demo import create_test_payment; create_test_payment(1)"
```

This command contacts Stripe, creates a sandbox Checkout Session for a
fixed USD 6.00, and saves a related Payment with the returned session ID
and URL. Each run creates a new Session and Payment.

Open the printed Checkout URL. Use Stripe's test card
`4242 4242 4242 4242`, a future expiry date, and any three-digit CVC.

The success and cancel URLs are placeholders at example.com.
This historical demo keeps placeholder return URLs, so paying its Session
does not update the local status automatically. To confirm an existing demo
payment, call the success endpoint below with its session ID.

### Automatic borrowing payments

Set `STRIPE_SECRET_KEY` in `.env` to a sandbox key starting with `sk_test_`.
The key is required to create borrowings.

POST `/api/borrowings/` automatically creates a Stripe Checkout Session
and a related PENDING Payment.

The amount in USD is:
`max(1, (expected_return_date - borrow_date).days) * book.daily_fee`.
Same-day borrowing costs one daily fee. The expected return day is not
added separately. The amount is converted to cents for Stripe.

Borrowing create, list and detail responses include a read-only
`payments` array containing payment records and checkout URLs.

If payment preparation raises a handled Stripe error, the API returns
503 and [rolls](https://www.youtube.com/shorts/_6HzLIJPH2A) back the local borrowing and inventory changes.
Database rollback does not undo a Session already created in Stripe.

New automatic Sessions use success and cancel URLs built from the current
request host. Existing Sessions retain the URLs used when they were created.

### Payment confirmation

- GET `/api/payments/success/?session_id=cs_test_...` checks the Session on
  Stripe's server. It verifies the Session ID, borrowing metadata, USD amount,
  sandbox mode and payment mode before accepting `payment_status=paid`.
  A confirmed Payment becomes PAID and the endpoint returns `200`.
- Repeating success for an already confirmed Payment returns `200` without
  creating records or repeating the status transition.
- A missing, empty or oversized session ID returns `400`; an unknown local
  session returns `404`; mismatched Session data returns `400`; an unpaid
  Session returns `409`. These responses leave the Payment status unchanged.
- Missing sandbox credentials or a Stripe request failure returns `503` and
  leaves the Payment status unchanged.
- GET `/api/payments/cancel/` returns a payment-can-be-completed-later message.
  It does not cancel the Stripe Session or change any Payment. Checkout links
  normally remain valid for 24 hours after Session creation.

These two return endpoints are public because Stripe redirects a browser
without a JWT header. They return only a short message, not customer or
borrowing details. Payment list/detail endpoints still require authentication
and retain their ownership restrictions.

This assignment implementation verifies payments when the browser visits
success. If a customer closes the browser before returning, or a payment
settles later, the local record may remain PENDING until success is revisited.
Webhook-driven confirmation is not implemented. Do not treat redirect-based
confirmation as guaranteed background payment reconciliation.

## Development

Run all tests with coverage:

```powershell
python -m coverage run manage.py test
python -m coverage report -m
```

Check Python code formatting:

```powershell
python -m black --check books users borrowings notifications payments drf_library_practice manage.py
```
