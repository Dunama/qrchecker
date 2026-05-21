# Clothing Rental QR Tracker — FastAPI Demo

This project is a privacy-first QR tracking system for clothing rentals. It models a real-world operational flow (seller pickup, hotel dry cleaning, logistics delivery) while keeping the QR payload free of PII. The QR code is only a signed pointer to a server-side record, and every scan is validated and logged.


## What this service does

This is a single-QR, multi-role workflow:

- One QR code is generated at order creation and shared with every party.
- The QR contains only `{oid, iat, exp, sig}` — no names, addresses, or room numbers.
- Every scan is verified server-side using HMAC, and can only advance to the next legal stage.
- Responses are scoped by role so each party sees only the fields they need.

Roles and behavior:

- `seller`: confirms pickup (`CONFIRMED → ITEM_COLLECTED`).
- `hotel`: dry-cleaning intake/release with optional notes.
- `logistics`: delivery confirmation (`DRY_CLEAN_OUT → DELIVERED`).
- `renter`: read-only tracking view.
                                        

## Minimal demo flow

1. Open the frontend.
2. **Create Order** → you’ll get an `order_id`, a QR image, and a `qr_token` JSON blob.
3. **Scan / Advance Stage** → paste the `qr_token` JSON and pick a role:
    - `seller` advances `CONFIRMED → ITEM_COLLECTED`
    - `hotel` advances `ITEM_COLLECTED → DRY_CLEAN_IN → DRY_CLEAN_OUT`
    - `logistics` advances `DRY_CLEAN_OUT → DELIVERED`
    - `renter` is read-only and returns a timeline view
4. **Timeline** → paste the `order_id` to view the full audit events.

## Three core principles

| Principle | Implementation |
|---|---|
| **Privacy by design** | QR payload = `{oid, iat, exp, sig}` — no names, no room numbers, no PII |
| **Signed & tamper-proof** | HMAC-SHA256 over the payload; server checks expiry; revocable server-side |
| **Role-scoped responses** | Same QR, four different views. Seller sees item code. Hotel adds dry-clean notes. Logistics sees delivery window. Renter sees timeline only. |

## Lifecycle

```
Payment confirmed
    ↓
POST /orders              → QR generated, broadcast to all parties
    ↓
POST /scan  (role=seller)    → ITEM_COLLECTED  (stage 1.1)
    ↓
POST /scan  (role=hotel)     → DRY_CLEAN_IN    (stage 1.2a)
POST /scan  (role=hotel)     → DRY_CLEAN_OUT   (stage 1.2b)
    ↓
POST /scan  (role=logistics) → DELIVERED       (stage 1.3)
    ↓
GET  /orders/{id}/timeline   → full audit trail
```

## Key design decisions

### QR is a pointer, not a document
The printed code contains only `{oid, iat, exp, sig}`.  
No name. No room number. No item description.  
PII never leaves the server.

### Stage cannot be forged
Even if someone copies the raw QR bytes, they cannot advance a stage out of sequence.  
The server holds the transition table (`CONFIRMED → ITEM_COLLECTED → …`).  
A role mismatch returns a friendly "no action required" — not an error.

### Opt-out / revoke
`POST /orders/{id}/revoke` immediately invalidates the code server-side.  
No new code needs to be printed.

### Extending to production
- Replace `orders_db` / `events_db` with Postgres + Redis
- Issue role tokens via OAuth2 (FastAPI `Depends` on a `get_current_role`)
- Store `SECRET_KEY` in a secrets manager (Vault, AWS Secrets Manager)
- Add WebSocket push so all parties see stage updates in real time
- Print QR on a thermal receipt — embed as PNG from `qr_image_b64`

## Response shape (high level)

Most responses include:

- `request_id` for correlation across logs and clients.
- `status_code` for quick client-side checks.

Errors follow a consistent shape:

- `detail` with the error reason.
- `request_id` and `status_code`.

## Deployment notes (Render)

Backend (FastAPI Web Service):

- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Env: `SECRET_KEY`, `QR_EXPIRY_HOURS`

Frontend (Static Site):

- Root directory: `frontend`
- Build: `npm install && npm run build`
- Publish: `frontend/dist`
- Env: `VITE_API_BASE_URL=https://YOUR-API.onrender.com`