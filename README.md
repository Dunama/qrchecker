# Rental QR Tracker

A QR-based tracking service for multi-party clothing workflows. A single QR code is shared across pickup, cleaning, and delivery steps, while the server enforces legal stage transitions and logs a full audit trail.

## Why this exists

Hand-offs across sellers, hotels, and logistics providers often rely on fragmented checklists and ad-hoc updates. This service centralizes tracking so every scan is validated, sequenced, and recorded in one consistent timeline.

## Problems solved

- Prevents out-of-order updates by enforcing a server-side transition table.
- Avoids leaking sensitive details by keeping the QR payload minimal and signed.
- Reduces hand-off confusion with role-scoped responses and a clear audit trail.

## Tech stack

- Backend: FastAPI, Uvicorn, Pydantic
- QR: qrcode (Pillow)
- Frontend: React, Vite

## What is implemented

- Order creation with QR generation and a signed token payload
- Role-based scans that advance stages only when allowed
- Full timeline endpoint for audit events
- QR revocation to immediately invalidate a code
- Frontend workflow to create, scan, and view timelines

## How to run locally

### Backend

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Set environment variables (PowerShell):

```powershell
$env:SECRET_KEY="change-me"
$env:QR_EXPIRY_HOURS="72"
```

3. Start the API:

```bash
uvicorn main:app --reload
```

The API runs at `http://127.0.0.1:8000`.

### Frontend

1. Install dependencies:

```bash
cd frontend
npm install
```

2. Set the API base URL:

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
```

3. Start the dev server:

```bash
npm run dev
```

## API overview

- `POST /orders` creates an order and returns a QR token plus an image payload
- `POST /scan` validates the token, enforces the next stage, and returns role-scoped data
- `GET /orders/{id}/timeline` returns the full audit trail
- `POST /orders/{id}/revoke` invalidates the QR token server-side

## Example flow

1. Create an order to receive `order_id` and `qr_token`.
2. Scan with a role to advance the stage in order: seller -> hotel -> logistics.
3. Fetch the timeline to see all audit events.

## Configuration

- `SECRET_KEY`: HMAC signing key for QR tokens (required).
- `QR_EXPIRY_HOURS`: QR token expiry in hours.
- `VITE_API_BASE_URL`: frontend base URL for the API.

## Notes for production

- Replace in-memory stores with a persistent database and cache.
- Add role authentication to limit who can advance stages.
- Store secrets in a managed secrets service.