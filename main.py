"""Clothing Rental QR Tracking System — FastAPI Demo.

Privacy-by-design: QR is a pointer (UUID + HMAC), never a document.
"""

import uuid, hmac, hashlib, json, time, io, base64
from datetime import datetime
from enum import Enum
from typing import Optional, List

import contextvars
import logging
from fastapi import Request
from fastapi.responses import JSONResponse

import qrcode
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(
    title="Rental QR Tracker",
    description="Privacy-first QR lifecycle for clothing rentals. "
                "No PII in the code — UUID + HMAC only.",
    version="0.1.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Logging / request correlation ───────────────────────────────────────────
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

logger = logging.getLogger("rental_qr_tracker")
if not logger.handlers:
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _get_request_id() -> str:
    rid = _request_id_ctx.get()
    return rid or ""


def _log(event: str, **fields):
    payload = {
        "ts": _now_iso(),
        "event": event,
        "request_id": _get_request_id(),
        **fields,
    }
    logger.info(json.dumps(payload, default=str, separators=(",", ":")))


def _with_request_id(payload: dict, status_code: int = 200) -> dict:
    return {**payload, "request_id": _get_request_id(), "status_code": status_code}


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = _request_id_ctx.set(request_id)

    start = time.perf_counter()
    _log(
        "http_request_start",
        method=request.method,
        path=request.url.path,
        client=str(request.client.host) if request.client else None,
    )
    try:
        response = await call_next(request)
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        _log(
            "http_request_end",
            method=request.method,
            path=request.url.path,
            status_code=getattr(locals().get("response"), "status_code", None),
            duration_ms=duration_ms,
        )
        _request_id_ctx.reset(token)

    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    _log(
        "http_exception",
        method=request.method,
        path=request.url.path,
        status_code=exc.status_code,
        detail=str(exc.detail),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": str(exc.detail),
            "request_id": _get_request_id(),
            "status_code": exc.status_code,
        },
        headers={"X-Request-ID": _get_request_id()} if _get_request_id() else None,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _log(
        "unhandled_exception",
        method=request.method,
        path=request.url.path,
        error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error.",
            "request_id": _get_request_id(),
            "status_code": 500,
        },
        headers={"X-Request-ID": _get_request_id()} if _get_request_id() else None,
    )

# ── Config (dev-safe defaults) ───────────────────────────────────────────────
# In production, set these via environment variables.
SECRET_KEY = os.getenv("SECRET_KEY") 
try:
    QR_EXPIRY_HOURS = int(os.getenv("QR_EXPIRY_HOURS"))
except ValueError:
    os.getenv("QR_EXPIRY_HOURS")      

# ── In-memory store (swap for Postgres / Redis in production) ────────────────
orders_db: dict = {}   # order_id → order record
events_db: dict = {}   # order_id → list of audit events

# ── Enums ────────────────────────────────────────────────────────────────────
class Stage(str, Enum):
    CONFIRMED        = "CONFIRMED"
    ITEM_COLLECTED   = "ITEM_COLLECTED"    # 1.1  seller pickup
    DRY_CLEAN_IN     = "DRY_CLEAN_IN"     # 1.2a hotel intake
    DRY_CLEAN_OUT    = "DRY_CLEAN_OUT"    # 1.2b hotel release
    DELIVERED        = "DELIVERED"         # 1.3  logistics drop-off

class Role(str, Enum):
    SELLER    = "seller"
    HOTEL     = "hotel"
    LOGISTICS = "logistics"
    RENTER    = "renter"

# ── Role permission matrix ───────────────────────────────────────────────────
ROLE_PERMS = {
    Role.SELLER: {
        "can_advance": [Stage.ITEM_COLLECTED],
        "see": ["order_id", "item_code", "current_stage"],
    },
    Role.HOTEL: {
        "can_advance": [Stage.DRY_CLEAN_IN, Stage.DRY_CLEAN_OUT],
        "see": ["order_id", "item_code", "current_stage", "dry_clean_notes"],
    },
    Role.LOGISTICS: {
        "can_advance": [Stage.DELIVERED],
        "see": ["order_id", "item_code", "current_stage", "delivery_window"],
    },
    Role.RENTER: {
        "can_advance": [],    # read-only
        "see": ["order_id", "item_code", "current_stage"],
    },
}

# Legal stage transitions (enforced server-side — QR cannot forge this)
TRANSITIONS = {
    Stage.CONFIRMED:      Stage.ITEM_COLLECTED,
    Stage.ITEM_COLLECTED: Stage.DRY_CLEAN_IN,
    Stage.DRY_CLEAN_IN:   Stage.DRY_CLEAN_OUT,
    Stage.DRY_CLEAN_OUT:  Stage.DELIVERED,
}

PREVIOUS_STAGE = {v: k for k, v in TRANSITIONS.items()}

# ── HMAC helpers ─────────────────────────────────────────────────────────────
def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()

def make_token(order_id: str) -> dict:
    """
    QR payload — pointer only, zero PII.
    oid  : order UUID
    iat  : issued-at  (unix seconds)
    exp  : expiry     (unix seconds)
    sig  : HMAC-SHA256 over {oid, iat, exp}
    """
    iat = int(time.time())
    exp = iat + (QR_EXPIRY_HOURS * 3600)
    body = json.dumps({"oid": order_id, "iat": iat, "exp": exp}, sort_keys=True)
    return {"oid": order_id, "iat": iat, "exp": exp, "sig": _sign(body)}

def verify_token(token: dict) -> bool:
    """Returns False on bad signature or expired token."""
    try:
        sig = token.get("sig", "")
        body = json.dumps(
            {"oid": token["oid"], "iat": token["iat"], "exp": token["exp"]},
            sort_keys=True,
        )
        if not hmac.compare_digest(sig, _sign(body)):
            return False
        return token["exp"] >= int(time.time())
    except Exception:
        return False

def qr_to_base64(data: dict) -> str:
    """Render QR as a base64 PNG string."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=6,
        border=2,
    )
    qr.add_data(json.dumps(data, separators=(",", ":")))
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

# ── Pydantic models ───────────────────────────────────────────────────────────
class CreateOrderReq(BaseModel):
    item_code:       str
    delivery_window: str = "2–4 hours"

class ScanReq(BaseModel):
    qr_token: dict
    role:     Role
    notes:    Optional[str] = None

class RevokeReq(BaseModel):
    reason: Optional[str] = "manual revocation"

# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/orders", summary="Create order → generate QR")
def create_order(req: CreateOrderReq):
    """
    Called after payment confirmation.
    Returns one QR token that is broadcast to seller, hotel, logistics, and renter.
    The token carries no names, addresses, or room numbers.
    """
    order_id = str(uuid.uuid4())
    token    = make_token(order_id)

    orders_db[order_id] = {
        "order_id":       order_id,
        "item_code":      req.item_code,
        "current_stage":  Stage.CONFIRMED,
        "delivery_window": req.delivery_window,
        "dry_clean_notes": None,
        "created_at":     datetime.utcnow().isoformat() + "Z",
        "revoked":        False,
        "qr_token":       token,
    }
    events_db[order_id] = [
        {"stage": Stage.CONFIRMED, "by": "system", "ts": datetime.utcnow().isoformat() + "Z"}
    ]

    qr_image = qr_to_base64(token)

    _log("order_created", order_id=order_id, item_code=req.item_code)

    return _with_request_id({
        "order_id":     order_id,
        "message":      "QR generated and broadcast to all parties.",
        "qr_token":     token,
        "qr_image_b64": qr_image,   # embed as <img src="data:image/png;base64,...">
    })


@app.post("/scan", summary="Scan QR — role-scoped response")
def scan_qr(req: ScanReq):
    """
    All four parties call this endpoint when they scan the QR.
    The server verifies the HMAC, checks stage legality, and returns
    only the fields that the caller's role is permitted to see.

    Stage advancement is atomic and server-enforced the QR itself
    cannot be replayed to skip stages.
    """
    token = {k: v for k, v in req.qr_token.items()}   # shallow copy
    role = req.role

    _log(
        "scan_received",
        role=str(role),
        oid=token.get("oid"),
        has_sig=bool(token.get("sig")),
    )

    # 1. Cryptographic verification
    if not verify_token(token):
        _log("scan_rejected", reason="invalid_or_expired_token", role=str(role))
        raise HTTPException(403, "QR invalid or expired.")

    order_id = token["oid"]
    order = orders_db.get(order_id)
    if not order:
        _log("scan_rejected", reason="order_not_found", role=str(role), order_id=order_id)
        raise HTTPException(404, "Order not found.")
    if order["revoked"]:
        _log("scan_rejected", reason="order_revoked", role=str(role), order_id=order_id)
        raise HTTPException(403, "QR has been revoked by the issuer.")

    perms = ROLE_PERMS[role]
    curr = order["current_stage"]
    next_ = TRANSITIONS.get(curr)

    # 2. Renter — always read-only
    if role == Role.RENTER:
        _log("scan_read_only", role=str(role), order_id=order_id, current_stage=str(curr))
        return _with_request_id({
            "role":          role,
            "order_id":      order_id,
            "item_code":     order["item_code"],
            "current_stage": curr,
            "timeline":      [e["stage"] for e in events_db.get(order_id, [])],
            "message":       "Tracking view — no action required.",
        })

    # 3. Does this role have anything to do at this stage?
    if next_ not in perms["can_advance"]:
        roles_expected = [
            str(r) for r, p in ROLE_PERMS.items() if next_ in p.get("can_advance", [])
        ]
        actionable_when = [
            str(PREVIOUS_STAGE.get(target))
            for target in perms.get("can_advance", [])
            if PREVIOUS_STAGE.get(target)
        ]

        _log(
            "scan_no_action",
            role=str(role),
            order_id=order_id,
            current_stage=str(curr),
            next_expected_stage=str(next_),
            next_expected_by_roles=roles_expected,
        )

        return _with_request_id({
            "role": role,
            "order_id": order_id,
            "current_stage": curr,
            "blocked": True,
            "reason_code": "ROLE_NO_ACTION",
            "next_expected_stage": next_,
            "next_expected_by_roles": roles_expected,
            "role_can_advance_to": perms.get("can_advance", []),
            "role_actionable_when_current_stage_in": actionable_when,
            "message": (
                f"No action for {role} at stage {curr}. "
                f"Next expected: {next_} (handled by: {', '.join(roles_expected) or 'unknown'})."
            ),
        })

    # 4. Advance stage (server-side, not derivable from QR alone)
    prev = curr
    order["current_stage"] = next_
    if req.notes and role == Role.HOTEL:
        order["dry_clean_notes"] = req.notes

    events_db[order_id].append({
        "stage": next_,
        "by":    role,
        "ts":    _now_iso(),
        "notes": req.notes,
    })

    _log(
        "scan_advanced",
        role=str(role),
        order_id=order_id,
        from_stage=str(prev),
        to_stage=str(next_),
        has_notes=bool(req.notes),
    )

    # 5. Build role-scoped response (principle of least privilege)
    resp = {"role": role, "event": next_, "order_id": order_id}
    for field in perms["see"]:
        if field in order:
            resp[field] = order[field]

    resp["message"] = f"Advanced stage: {prev} → {next_}."
    return _with_request_id(resp)


@app.get("/orders/{order_id}/timeline", summary="Full audit trail (internal)")
def get_timeline(order_id: str):
    """
    In production, restrict this to authenticated back-office staff.
    Exposed here for demo inspection only.
    """
    if order_id not in orders_db:
        raise HTTPException(404, "Order not found.")
    _log("timeline_fetched", order_id=order_id)
    return _with_request_id({
        "order_id": order_id,
        "item_code": orders_db[order_id]["item_code"],
        "events":   events_db.get(order_id, []),
    })


@app.post("/orders/{order_id}/revoke", summary="Server-side QR invalidation")
def revoke_order(order_id: str, req: RevokeReq = RevokeReq()):
    """
    Instantly invalidates the QR without touching the physical code.
    Subsequent scans receive 403 regardless of HMAC validity.
    """
    if order_id not in orders_db:
        raise HTTPException(404, "Order not found.")
    orders_db[order_id]["revoked"] = True
    events_db[order_id].append({
        "stage": "REVOKED",
        "by":    "system",
        "ts":    _now_iso(),
        "notes": req.reason,
    })
    _log("order_revoked", order_id=order_id, reason=req.reason)
    return _with_request_id({"message": f"QR for order {order_id} revoked.", "reason": req.reason})


@app.get("/health")
def health():
    return _with_request_id({"status": "ok", "orders": len(orders_db)})