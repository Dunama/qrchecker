import base64
import contextvars
import hashlib
import hmac
import io
import json
import logging
import os
import time
import uuid
from datetime import datetime

from dotenv import load_dotenv
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from schemas import Role, Stage

load_dotenv()

# Logging / request correlation
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


# Config (dev-safe defaults) - set via environment variables in production.
SECRET_KEY = os.getenv("SECRET_KEY")
try:
    QR_EXPIRY_HOURS = int(os.getenv("QR_EXPIRY_HOURS"))
except ValueError:
    os.getenv("QR_EXPIRY_HOURS")

# In-memory store (swap for Postgres / Redis in production)
orders_db: dict = {}
events_db: dict = {}

# Role permission matrix
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
        "can_advance": [],
        "see": ["order_id", "item_code", "current_stage"],
    },
}

TRANSITIONS = {
    Stage.CONFIRMED: Stage.ITEM_COLLECTED,
    Stage.ITEM_COLLECTED: Stage.DRY_CLEAN_IN,
    Stage.DRY_CLEAN_IN: Stage.DRY_CLEAN_OUT,
    Stage.DRY_CLEAN_OUT: Stage.DELIVERED,
}

PREVIOUS_STAGE = {v: k for k, v in TRANSITIONS.items()}


# HMAC helpers
def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(order_id: str) -> dict:
    iat = int(time.time())
    exp = iat + (QR_EXPIRY_HOURS * 3600)
    body = json.dumps({"oid": order_id, "iat": iat, "exp": exp}, sort_keys=True)
    return {"oid": order_id, "iat": iat, "exp": exp, "sig": _sign(body)}


def verify_token(token: dict) -> bool:
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
    import qrcode

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
