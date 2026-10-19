# Library Service API

REST API for managing a library.

## Implemented features

- User registration with email and password
- JWT authentication
- Viewing and updating your own profile
- OpenAPI schema and Swagger documentation

## Local setup (PowerShell)

Requires Python 3.12.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Generate a new local secret key:

```powershell
python -c "from pathlib import Path; from django.core.management.utils import get_random_secret_key; Path('.env').write_text('SECRET_KEY=' + get_random_secret_key() + '\n', encoding='utf-8')"
```

Apply migrations and start the development server:

```powershell
python manage.py migrate
python manage.py runserver
```

## API documentation

After starting the development server, open:
http://127.0.0.1:8000/api/docs/

## Running tests

python manage.py test users