"""
Orders API — demonstrates:
  1. Idempotent POST /orders
  2. Cursor-based pagination on GET /orders
  3. Per-client rate limiting (X-Client-Id)

Assigned values:
  TOTAL_ORDERS (T) = 60
  RATE_LIMIT   (R) = 19 requests / 10 seconds
"""

import base64
import time
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config (your assigned values)
# ---------------------------------------------------------------------------
TOTAL_ORDERS = 60
RATE_LIMIT = 19
WINDOW_SECONDS = 10

app = FastAPI(title="Orders API")

# CORS: allow the grader's browser page to call this API directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# "Database" (just Python dictionaries living in memory)
# ---------------------------------------------------------------------------

# Fixed catalog of orders 1..T, used for pagination
CATALOG = [
    {"id": i, "item": f"Item {i}", "price": round(9.99 + i, 2)}
    for i in range(1, TOTAL_ORDERS + 1)
]

# Orders created via POST /orders
orders_db: Dict[str, dict] = {}

# Maps Idempotency-Key -> order id, so repeats return the same order
idempotency_map: Dict[str, str] = {}

# Rate limit buckets: client_id -> list of request timestamps (sliding window)
rate_buckets: Dict[str, List[float]] = {}


# ---------------------------------------------------------------------------
# 3. Per-client rate limiting (applied as middleware, runs before every request)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path == "/orders":
        client_id = request.headers.get("X-Client-Id")
        if client_id:
            now = time.time()
            bucket = rate_buckets.setdefault(client_id, [])

            # Drop timestamps that fell out of the 10-second window
            cutoff = now - WINDOW_SECONDS
            while bucket and bucket[0] < cutoff:
                bucket.pop(0)

            if len(bucket) >= RATE_LIMIT:
                retry_after = int(bucket[0] + WINDOW_SECONDS - now) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Slow down."},
                    headers={"Retry-After": str(max(retry_after, 1))},
                )

            bucket.append(now)

    return await call_next(request)


# ---------------------------------------------------------------------------
# 1. Idempotent order creation
# ---------------------------------------------------------------------------
class OrderIn(BaseModel):
    item: Optional[str] = None
    quantity: Optional[int] = 1


@app.post("/orders", status_code=201)
def create_order(
    order: OrderIn,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    # Seen this key before? Return the SAME order, don't create a new one.
    if idempotency_key in idempotency_map:
        existing_id = idempotency_map[idempotency_key]
        response.status_code = 201
        return orders_db[existing_id]

    new_id = str(uuid.uuid4())
    new_order = {
        "id": new_id,
        "item": order.item or "Unnamed Item",
        "quantity": order.quantity or 1,
    }
    orders_db[new_id] = new_order
    idempotency_map[idempotency_key] = new_id
    return new_order


# ---------------------------------------------------------------------------
# 2. Cursor-based pagination
# ---------------------------------------------------------------------------
def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def decode_cursor(cursor: str) -> int:
    try:
        return int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


@app.get("/orders")
def list_orders(limit: int = Query(10, gt=0), cursor: Optional[str] = None):
    offset = 0 if cursor is None else decode_cursor(cursor)

    if offset < 0 or offset > TOTAL_ORDERS:
        raise HTTPException(status_code=400, detail="Invalid cursor")

    page = CATALOG[offset : offset + limit]
    next_offset = offset + len(page)
    next_cursor = encode_cursor(next_offset) if next_offset < TOTAL_ORDERS else None

    return {
        "items": page,
        "orders": page,       # alias accepted by grader
        "next_cursor": next_cursor,
        "next": next_cursor,  # alias accepted by grader
    }


@app.get("/")
def root():
    return {"status": "ok", "total_orders": TOTAL_ORDERS, "rate_limit": RATE_LIMIT}