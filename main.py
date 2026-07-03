from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import uuid
import time

app = FastAPI()

# ==========================================
# CORS
# ==========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Assignment Values
# ==========================================

TOTAL_ORDERS = 60
RATE_LIMIT = 19
WINDOW = 10

# ==========================================
# Fixed Catalog
# ==========================================

catalog = [
    {
        "id": i,
        "item": f"Product {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# ==========================================
# In-memory Stores
# ==========================================

idempotency_store = {}
client_requests = {}

# ==========================================
# Rate Limiter
# ==========================================

def rate_limit(
    x_client_id: Optional[str] = Header(None, alias="X-Client-Id")
):
    if x_client_id is None:
        return

    now = time.time()

    timestamps = client_requests.get(x_client_id, [])

    timestamps = [
        t
        for t in timestamps
        if now - t < WINDOW
    ]

    if len(timestamps) >= RATE_LIMIT:

        retry_after = max(
            1,
            int(WINDOW - (now - timestamps[0])) + 1
        )

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after)
            }
        )

    timestamps.append(now)
    client_requests[x_client_id] = timestamps

# ==========================================
# Home
# ==========================================

@app.get("/")
def home():
    return {
        "message": "Orders API is running"
    }

# ==========================================
# Health
# ==========================================

@app.get("/health")
def health():
    return {
        "status": "healthy"
    }

# ==========================================
# Idempotent POST
# ==========================================

@app.post("/orders")
def create_order(
    idempotency_key: str = Header(..., alias="Idempotency-Key")
):

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

# ==========================================
# Pagination
# ==========================================

@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: Optional[str] = None
):

    if limit < 1:
        limit = 1

    start = 0

    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0

    items = catalog[start:start + limit]

    next_cursor = None

    if start + limit < TOTAL_ORDERS:
        next_cursor = str(start + limit)

    return {
        "items": items,
        "next_cursor": next_cursor
    }

# ==========================================
# Rate Limited Endpoint
# ==========================================

@app.get("/limited")
def limited_endpoint(
    _: None = Depends(rate_limit)
):
    return {
        "message": "Request accepted"
    }