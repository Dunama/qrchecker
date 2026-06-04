import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException

from modules import (
    PREVIOUS_STAGE,
    ROLE_PERMS,
    TRANSITIONS,
    _log,
    _now_iso,
    _with_request_id,
    events_db,
    make_token,
    orders_db,
    qr_to_base64,
    verify_token,
)
from schemas import CreateOrderReq, RevokeReq, Role, ScanReq, Stage

router = APIRouter()


@router.post("/orders", summary="Create order - generate QR")
def create_order(req: CreateOrderReq):
    order_id = str(uuid.uuid4())
    token = make_token(order_id)

    orders_db[order_id] = {
        "order_id": order_id,
        "item_code": req.item_code,
        "current_stage": Stage.CONFIRMED,
        "delivery_window": req.delivery_window,
        "dry_clean_notes": None,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "revoked": False,
        "qr_token": token,
    }
    events_db[order_id] = [
        {"stage": Stage.CONFIRMED, "by": "system", "ts": datetime.utcnow().isoformat() + "Z"}
    ]

    qr_image = qr_to_base64(token)

    _log("order_created", order_id=order_id, item_code=req.item_code)

    return _with_request_id(
        {
            "order_id": order_id,
            "message": "QR generated and broadcast to all parties.",
            "qr_token": token,
            "qr_image_b64": qr_image,
        }
    )


@router.post("/scan", summary="Scan QR - role-scoped response")
def scan_qr(req: ScanReq):
    token = {k: v for k, v in req.qr_token.items()}
    role = req.role

    _log(
        "scan_received",
        role=str(role),
        oid=token.get("oid"),
        has_sig=bool(token.get("sig")),
    )

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

    if role == Role.RENTER:
        _log("scan_read_only", role=str(role), order_id=order_id, current_stage=str(curr))
        return _with_request_id(
            {
                "role": role,
                "order_id": order_id,
                "item_code": order["item_code"],
                "current_stage": curr,
                "timeline": [e["stage"] for e in events_db.get(order_id, [])],
                "message": "Tracking view - no action required.",
            }
        )

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

        return _with_request_id(
            {
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
            }
        )

    prev = curr
    order["current_stage"] = next_
    if req.notes and role == Role.HOTEL:
        order["dry_clean_notes"] = req.notes

    events_db[order_id].append(
        {
            "stage": next_,
            "by": role,
            "ts": _now_iso(),
            "notes": req.notes,
        }
    )

    _log(
        "scan_advanced",
        role=str(role),
        order_id=order_id,
        from_stage=str(prev),
        to_stage=str(next_),
        has_notes=bool(req.notes),
    )

    resp = {"role": role, "event": next_, "order_id": order_id}
    for field in perms["see"]:
        if field in order:
            resp[field] = order[field]

    resp["message"] = f"Advanced stage: {prev} -> {next_}."
    return _with_request_id(resp)


@router.get("/orders/{order_id}/timeline", summary="Full audit trail (internal)")
def get_timeline(order_id: str):
    if order_id not in orders_db:
        raise HTTPException(404, "Order not found.")
    _log("timeline_fetched", order_id=order_id)
    return _with_request_id(
        {
            "order_id": order_id,
            "item_code": orders_db[order_id]["item_code"],
            "events": events_db.get(order_id, []),
        }
    )


@router.post("/orders/{order_id}/revoke", summary="Server-side QR invalidation")
def revoke_order(order_id: str, req: RevokeReq = RevokeReq()):
    if order_id not in orders_db:
        raise HTTPException(404, "Order not found.")
    orders_db[order_id]["revoked"] = True
    events_db[order_id].append(
        {
            "stage": "REVOKED",
            "by": "system",
            "ts": _now_iso(),
            "notes": req.reason,
        }
    )
    _log("order_revoked", order_id=order_id, reason=req.reason)
    return _with_request_id(
        {"message": f"QR for order {order_id} revoked.", "reason": req.reason}
    )


@router.get("/health")
def health():
    return _with_request_id({"status": "ok", "orders": len(orders_db)})
