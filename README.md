# Rental QR Tracker

A privacy-first QR lifecycle system for clothing rentals.

The QR code is a **pointer, not a document**. It carries only an order UUID and an
HMAC signature — never personal data, never the item history. Every scan is
resolved server-side and answered according to *who is asking*, so a courier, a
dry cleaner, and the renter each see a different, minimal view of the same order.

> **Status:** early demo (`v0.1.0`). The backend uses an in-memory store and is
> meant as a reference implementation, not a production deployment.

---

## Why this exists

Hand-offs across sellers, hotels, and logistics providers often rely on fragmented
checklists and ad-hoc updates. Many "smart" QR workflows also encode data directly
into the code — names, addresses, order contents — so anyone with a camera can read
it. This project takes the opposite approach:

- **The code is opaque.** It contains `{ order_id, issued_at, expires_at, signature }`
  and nothing else.
- **The server is the source of truth.** Scans are validated (signature + expiry +
  revocation) before anything is returned.
- **Responses are role-scoped.** The same QR returns different fields and different
  allowed actions depending on the scanning party's role.
- **QRs are revocable.** A code can be invalidated server-side at any time, even
  though it is already printed or shared.

## How it works

An order moves through a fixed lifecycle. Each party can only advance the stage
they are responsible for:

```
CONFIRMED  ──seller──▶  ITEM_COLLECTED  ──hotel──▶  DRY_CLEAN_IN
                                                        │
                                                      hotel
                                                        ▼
DELIVERED  ◀──logistics──  DRY_CLEAN_OUT
```

| Role        | Can advance to                  | Sees                                          |
|-------------|---------------------------------|-----------------------------------------------|
| `seller`    | `ITEM_COLLECTED`                | order id, item code, current stage            |
| `hotel`     | `DRY_CLEAN_IN`, `DRY_CLEAN_OUT` | the above + dry-clean notes                   |
| `logistics` | `DELIVERED`                     | the above + delivery window                   |
| `renter`    | — (read-only)                   | order id, item code, current stage, timeline  |

If a role scans at the wrong moment, the API doesn't error — it returns a helpful
`ROLE_NO_ACTION` response explaining which stage is expected next and who handles it.

## Architecture

```
qrcode/
├── main.py          # FastAPI app: middleware, exception handlers, router wiring
├── routes.py        # Endpoints: /orders, /scan, /timeline, /revoke, /health
├── modules.py       # Config, HMAC token signing, logging, QR image generation
├── schemas.py       # Pydantic models + Stage/Role enums
├── requirements.txt
├── tests/           # pytest suite
└── frontend/        # React + Vite demo UI
```

- **Token security:** HMAC-SHA256 over a canonical JSON body. Verification uses
  `hmac.compare_digest` (constant-time) plus an expiry check.
- **Observability:** every request gets an `X-Request-ID` (honored from the header
  or generated), structured JSON logs, and request-scoped correlation via
  `contextvars`.
- **Storage:** in-memory dicts for the demo. Swap `orders_db` / `events_db` in
  `modules.py` for Postgres/Redis in production.

## Tech stack

- Backend: FastAPI, Uvicorn, Pydantic
- QR generation: `qrcode` (Pillow)
- Frontend: React 19, Vite

## Getting started

### Backend

Requires Python 3.10+.

```bash
# from the repo root
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env               # then edit SECRET_KEY
uvicorn main:app --reload
```

The API is now at `http://localhost:8000`. Interactive docs (Swagger UI) are at
`http://localhost:8000/docs`.

> If you skip the `.env`, the app still runs with an **insecure development key**
> and logs a warning. Always set a real `SECRET_KEY` before deploying.

### Frontend

Requires Node 18+.

```bash
cd frontend
npm install
cp .env.example .env               # optional; defaults to http://localhost:8000
npm run dev
```

Open the printed URL (typically `http://localhost:5173`). The demo UI lets you
create an order, scan/advance stages as any role, and inspect the timeline.

## API reference

| Method | Path                          | Description                              |
|--------|-------------------------------|------------------------------------------|
| POST   | `/orders`                     | Create an order and generate its QR      |
| POST   | `/scan`                       | Scan a QR; role-scoped read or advance   |
| GET    | `/orders/{order_id}/timeline` | Full audit trail (internal)              |
| POST   | `/orders/{order_id}/revoke`   | Invalidate a QR server-side              |
| GET    | `/health`                     | Liveness + order count                   |

### Example: create an order

```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"item_code": "DRESS-001", "delivery_window": "2-4 hours"}'
```

Returns the `order_id`, the `qr_token`, and a base64 PNG (`qr_image_b64`).

### Example: scan as the seller

```bash
curl -X POST http://localhost:8000/scan \
  -H "Content-Type: application/json" \
  -d '{"qr_token": { ...token from /orders... }, "role": "seller"}'
```

A typical flow: create an order, then scan in sequence
`seller → hotel → hotel → logistics`, then fetch the timeline.

## Configuration

Backend (root `.env`, see `.env.example`):

| Variable          | Default | Description                                   |
|-------------------|---------|-----------------------------------------------|
| `SECRET_KEY`      | *(dev)* | HMAC signing key. **Required in production.**  |
| `QR_EXPIRY_HOURS` | `72`    | How long a QR token stays valid.              |
| `LOG_LEVEL`       | `INFO`  | `DEBUG` / `INFO` / `WARNING` / `ERROR`.        |

Frontend (`frontend/.env`, see `frontend/.env.example`):

| Variable            | Default                 | Description       |
|---------------------|-------------------------|-------------------|
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend base URL. |

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers token signing/verification (including tampering and expiry), the
full order lifecycle, role permissions, read-only access, revocation, and error
handling.

## Roadmap

Natural next steps for taking this beyond a demo:

- Persistent storage (Postgres) and an event store for the audit trail.
- Authentication for roles (right now the role is self-declared in the request).
- Rate limiting and per-role API keys.
- Key rotation for the HMAC secret.
- Container / deployment manifests.

## Contributing

Contributions are welcome. Please open an issue to discuss substantial changes
first. For code changes: fork, create a branch, keep the tests green (`pytest`),
and open a pull request.

## License

Released under the [MIT License](LICENSE).

## Security note

This is a reference implementation. Roles are currently trusted (declared by the
caller), storage is in-memory, and CORS is open (`*`) for local development. Do
not deploy as-is without adding authentication, persistence, and a locked-down
CORS policy.
