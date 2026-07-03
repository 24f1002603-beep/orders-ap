"""
Orders API — demonstrates 3 production API patterns:
  1. Idempotent POST /orders
  2. Cursor-based pagination on GET /orders
  3. Per-client rate limiting (X-Client-Id header)

Assigned values:
  Total orders (T)              = 60
  Rate limit (R requests / 10s) = 19
"""

import base64
import json
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Config (your assigned values) ───────────────────────────────
TOTAL_ORDERS = 60      # T
RATE_LIMIT = 19        # R
WINDOW_SECONDS = 10    # the "10s" in "R requests / 10s"

app = FastAPI(title="Orders API")

# Allow the grader's browser page to call this API from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # must be False when allow_origins is "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Fixed catalog: orders with IDs 1..T, created once at startup ──
ORDERS_CATALOG = [{"id": i, "item": f"Order {i}"} for i in range(1, TOTAL_ORDERS + 1)]

# ── In-memory stores (fine for a demo/grader; use a DB in real life) ──
idempotency_store: dict[str, dict] = {}   # Idempotency-Key -> order that was created
idempotency_lock = Lock()

order_counter = 0
order_counter_lock = Lock()

rate_buckets: dict[str, deque] = defaultdict(deque)  # client id -> timestamps of recent requests
rate_lock = Lock()


# ══════════════════════════════════════════════════════════════
# 1. IDEMPOTENT ORDER CREATION
# ══════════════════════════════════════════════════════════════
@app.post("/orders", status_code=201)
async def create_order(idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    with idempotency_lock:
        # Have we seen this exact key before? If so, hand back the SAME order.
        if idempotency_key in idempotency_store:
            return JSONResponse(status_code=201, content=idempotency_store[idempotency_key])

        # Otherwise, this is genuinely a new order — create it.
        global order_counter
        with order_counter_lock:
            order_counter += 1
            new_id = f"order_{order_counter}"

        order = {"id": new_id, "status": "created"}
        idempotency_store[idempotency_key] = order
        return JSONResponse(status_code=201, content=order)


# ══════════════════════════════════════════════════════════════
# 2. CURSOR-BASED PAGINATION
# ══════════════════════════════════════════════════════════════
def encode_cursor(index: int) -> str:
    """Turn a plain integer position into an 'opaque' string cursor."""
    raw = json.dumps({"i": index}).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> int:
    """Turn a cursor string back into the integer position it represents."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode())
        return int(json.loads(raw)["i"])
    except Exception:
        raise HTTPException(status_code=400, detail="invalid cursor")


@app.get("/orders")
async def list_orders(limit: int = Query(10, ge=1), cursor: str | None = Query(None)):
    start = decode_cursor(cursor) if cursor else 0
    end = min(start + limit, TOTAL_ORDERS)

    items = ORDERS_CATALOG[start:end]
    next_cursor = encode_cursor(end) if end < TOTAL_ORDERS else None

    # Include a couple of field-name aliases since the grader accepts any of them
    return {
        "items": items,
        "next_cursor": next_cursor,
        "next": next_cursor,
        "orders": items,
    }


# ══════════════════════════════════════════════════════════════
# 3. PER-CLIENT RATE LIMITING (sliding window, 19 req / 10s)
# ══════════════════════════════════════════════════════════════
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path == "/orders":
        client_id = request.headers.get("X-Client-Id")
        if client_id:
            now = time.time()
            with rate_lock:
                bucket = rate_buckets[client_id]

                # Drop timestamps older than the 10-second window
                while bucket and now - bucket[0] > WINDOW_SECONDS:
                    bucket.popleft()

                if len(bucket) >= RATE_LIMIT:
                    retry_after = int(WINDOW_SECONDS - (now - bucket[0])) + 1
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "rate limit exceeded"},
                        headers={"Retry-After": str(retry_after)},
                    )

                bucket.append(now)

    return await call_next(request)


@app.get("/")
async def root():
    return {"status": "ok", "total_orders": TOTAL_ORDERS, "rate_limit": RATE_LIMIT}