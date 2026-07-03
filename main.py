from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import uuid
import time

app = FastAPI()

# =====================================================
# CORS
# =====================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================================================
# Assignment Values
# =====================================================

TOTAL_ORDERS = 60
RATE_LIMIT = 19
WINDOW = 10

# =====================================================
# Fixed Catalog
# =====================================================

catalog = [
    {
        "id": i,
        "item": f"Product {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# =====================================================
# In-memory Stores
# =====================================================

idempotency_store = {}
client_requests = {}

# =====================================================
# Rate Limiter
# =====================================================

def check_rate_limit(client_id: Optional[str]):
    if client_id is None:
        return None

    now = time.time()

    timestamps = client_requests.get(client_id, [])

    # Keep only requests in the last 10 seconds
    timestamps = [t for t in timestamps if now - t < WINDOW]

    if len(timestamps) >= RATE_LIMIT:

        retry_after = max(
            1,
            int(WINDOW - (now - timestamps[0])) + 1
        )

        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded"
            },
            headers={
                "Retry-After": str(retry_after)
            }
        )

    timestamps.append(now)
    client_requests[client_id] = timestamps

    return None


# =====================================================
# Home
# =====================================================

@app.get("/")
def home():
    return {
        "message": "Orders API running"
    }


# =====================================================
# Health
# =====================================================

@app.get("/health")
def health():
    return {
        "status": "healthy"
    }


# =====================================================
# POST /orders
# =====================================================

@app.post("/orders")
def create_order(
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_client_id: Optional[str] = Header(None, alias="X-Client-Id")
):

    response = check_rate_limit(x_client_id)
    if response:
        return response

    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    order = {
        "id": str(uuid.uuid4()),
        "status": "created"
    }

    idempotency_store[idempotency_key] = order

    return JSONResponse(
        status_code=201,
        content=order
    )


# =====================================================
# GET /orders
# =====================================================

@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: Optional[str] = None,
    x_client_id: Optional[str] = Header(None, alias="X-Client-Id")
):

    response = check_rate_limit(x_client_id)
    if response:
        return response

    if limit < 1:
        limit = 1

    try:
        start = int(cursor) if cursor else 0
    except ValueError:
        start = 0

    start = max(0, start)

    items = catalog[start:start + limit]

    next_cursor = None

    if start + limit < TOTAL_ORDERS:
        next_cursor = str(start + limit)

    return {
        "items": items,
        "next_cursor": next_cursor
    }