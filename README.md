# Piecehunt API

Piecehunt API is the backend service for the Piecehunt application. It powers authentication, user sets, LEGO inventory tracking, email workflows, and reporting features for missing parts and app feedback.

Built with FastAPI, SQLAlchemy, Supabase, and PostgreSQL.

## Table of Contents

- [Overview](#overview)
- [Production API](#production-api)
- [Technologies](#technologies)
- [Project Structure](#project-structure)
- [Internal Development Notes](#internal-development-notes)
- [Environment Variables](#environment-variables)
- [Authentication](#authentication)
- [Main Endpoints](#main-endpoints)
- [Rate Limiting](#rate-limiting)
- [Logging and Error Handling](#logging-and-error-handling)
- [Contributing](#contributing)

## Overview

This API provides the following core functionalities:

- User registration and login via Supabase
- Email verification and password reset
- Management of a user's LEGO collection
- Saving and updating part status per set
- Tracking missing parts and generating reports
- Sending feedback from the app
- Handling email delivery through Resend

## Production API

This project is already deployed and running online. In normal use, clients should target the live API URL rather than running a local instance.

Base URL example:

```text
https://your-production-api-url
```

Use the interactive API docs at:

- Swagger UI: `https://your-production-api-url/docs`
- ReDoc: `https://your-production-api-url/redoc`

## Technologies

- Python 3.14+
- FastAPI
- SQLAlchemy
- PostgreSQL
- Supabase Auth
- Pydantic
- Uvicorn
- SlowAPI (rate limiting)
- Resend for email delivery

## Projectstructuur

```text
.
├── main.py                 # FastAPI app bootstrap
├── config.py               # Environment config
├── database.py             # Database session setup
├── dependencies.py         # Auth dependencies
├── rate_limit.py           # Rate limiting config
├── models/
│   └── models.py           # SQLAlchemy models
├── routers/
│   ├── accounts.py
│   ├── auth.py
│   ├── auth_supabase.py
│   ├── feedback.py
│   ├── parts.py
│   ├── reports.py
│   └── sets.py
├── services/
│   ├── email/
│   └── supabase_client.py
├── logs/
├── scripts/
├── pyproject.toml
└── .env
```

## Internal Development Notes

This project is intended as a private backend service for the Piecehunt platform and is not designed to be cloned and run by external users.

The repository is mainly used by the project team for:

- backend maintenance
- feature development
- deployment updates
- debugging auth and data workflows

If local execution is ever needed internally, the required environment is still the same as the production setup, including the configured secrets and database access.

Typical local requirements:

- Python 3.14 or higher
- PostgreSQL database access
- Supabase project access
- Resend email configuration
- project environment variables loaded from `.env`

Example local start command for internal use only:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

## Environment Variables

Create a `.env` file in the project root with the following values:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-supabase-jwt-secret
DATABASE_URL=postgresql://user:password@host:5432/database
REBRICKABLE_KEY=your-rebrickable-api-key
DEVELOPER_EMAIL=dev@example.com
NO_REPLY_EMAIL=noreply@example.com
FEEDBACK_EMAIL=feedback@example.com
ALLOWED_ORIGINS=http://localhost:3000
API_BASE_URL=http://localhost:8000
RESEND_API_KEY=your-resend-api-key
```

Important notes:

- `ALLOWED_ORIGINS` is a comma-separated list.
- `SUPABASE_JWT_SECRET` is used for local verification of access tokens.
- `DATABASE_URL` must point to the PostgreSQL database for the project.

## Authentication

The API uses Bearer tokens from Supabase.

Example header:

```http
Authorization: Bearer <access_token>
```

Some routes require a verified user with an authenticated email. These are protected through dependencies in `dependencies.py`.

## Main Endpoints

### Auth

- `POST /auth/login`
  - Log in with email and password
- `POST /auth/register`
  - Register a new user
- `POST /auth/refresh`
  - Refresh an access token
- `POST /auth/email-verification/request`
  - Send a verification email
- `GET /auth/email-verification/status`
  - Check verification status
- `GET /auth/email-verification/confirm`
  - Process email verification via token in the browser
- `POST /auth/password-reset/request`
  - Request a password reset
- `GET /auth/password-reset/confirm`
  - Open the reset link
- `POST /auth/password-reset/confirm`
  - Set a new password

### Sets

- `GET /sets/{set_num}/status`
  - Check whether a set is already owned
- `POST /sets/{set_num}`
  - Add a set for the user
- `GET /sets/mine`
  - Get all sets for the logged-in user
- `GET /sets/{user_set_id}`
  - Get details for one user set
- `DELETE /sets/{user_set_id}`
  - Delete a user set

### Parts

- `GET /sets/{user_set_id}/parts`
  - Get all parts for a set
- `GET /sets/{user_set_id}/minifigs`
  - Get minifigures for a set
- `GET /sets/{user_set_id}/colors`
  - Get colors used in a set
- `PATCH /sets/{user_set_id}/parts/{userpart_id}`
  - Update the found quantity
- `POST /sets/{user_set_id}/parts/actions`
  - Bulk actions such as reset or complete set

### Accounts

- `DELETE /accounts/me`
  - Delete the current account

### Reports and Feedback

- `POST /reports/missing-parts/email`
  - Send a missing-parts report via email
- `POST /feedback/report`
  - Send app feedback with optional logs or an image

### General

- `GET /health`
  - Check whether the API is working

## Rate Limiting

The API uses SlowAPI for rate limiting. This is configured in `rate_limit.py` and attached to the app in `main.py`.

Typical use cases:

- limit requests per IP or user
- prevent brute-force attacks on login and auth endpoints

## Logging and Error Handling

- Logging is configured in `logs/logging_config.py`
- The app records errors, email sending, and feedback processing
- HTTP error codes are returned through FastAPI by default
- Authentication failures typically return `401` or `403`

## Contributing

This repository is intended for internal project development.

1. Create a feature branch from the active development branch
2. Implement your changes in the relevant router or service
3. Validate the API through the live environment or local debug setup
4. Test the affected endpoints and auth flows
5. Open a pull request with a clear summary of the change

The project is not intended to be treated as a public open-source backend for general community use.

## Note

This README reflects the current codebase and the actual routes included in the app. If additional modules or custom auth flows are added later, this documentation can be extended accordingly.
