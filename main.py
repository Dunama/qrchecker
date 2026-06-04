"""Clothing Rental QR Tracking System - FastAPI Demo.

Privacy-by-design: QR is a pointer (UUID + HMAC), never a document.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from modules import (
    http_exception_handler,
    request_context_middleware,
    unhandled_exception_handler,
)
from routes import router

app = FastAPI(
    title="Rental QR Tracker",
    description="Privacy-first QR lifecycle for clothing rentals. "
                "No PII in the code — UUID + HMAC only.",
    version="0.1.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(request_context_middleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.include_router(router)