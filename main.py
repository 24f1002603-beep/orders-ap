from fastapi import FastAPI, Header, HTTPException
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
    allow_origins=["*"],      # Allow all origins for grader
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Assignment Values
# ==========================================

TOTAL_ORDERS = 60
RATE_LIMIT = 19
WINDOW = 10  # seconds

# ==========================================
# Fixed Catalog (IDs 1 to 60)
# ==========================================

catalog = [
    {
        "id": i,
        "item": f"Product {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# ==========================================
# In-memory Storage
# ==========================================

# Stores created orders
idempotency_store = {}

# Stores request timestamps for each client
client_requests = {}

# ==========================================
# Home
# ==========================================

@app.get("/")
def home():
    return {
        "message": "Orders API is running"
    }

# ==========================================
# Health Check
# ==========================================

@app.get("/health")
def health():
    return {
        "status": "healthy"
    }

# ==========================================
# 1. Idempotent Order Creation
# ==========================================

@app.post("/orders")
def create_order(
    idempotency_key: str = Header(..., alias="Idempotency-Key")
):

    # If this key already created an order,
    # return the exact same order.
    if idempotency_key in idempotency_store:
        return JSONResponse(
            status_code=201,
            content=idempotency_store[idempotency_key]
        )

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
# 2. Cursor Pagination
# ==========================================

@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: Optional[str] = None
):

    start = int(cursor) if cursor else 0

    items = catalog[start:start + limit]

    next_cursor = None

    if start + limit < TOTAL_ORDERS:
        next_cursor = str(start + limit)

    return {
        "items": items,
        "next_cursor": next_cursor
    }

# ==========================================
# 3. Per-Client Rate Limiting
# ==========================================

@app.get("/limited")
def limited_endpoint(
    x_client_id: str = Header(..., alias="X-Client-Id")
):

    now = time.time()

    # Get timestamps for this client
    timestamps = client_requests.get(x_client_id, [])

    # Remove requests older than 10 seconds
    timestamps = [
        t
        for t in timestamps
        if now - t < WINDOW
    ]

    # Save cleaned timestamps
    client_requests[x_client_id] = timestamps

    # Rate limit exceeded?
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

    # Record current request
    timestamps.append(now)
    client_requests[x_client_id] = timestamps

    return {
        "message": "Request accepted",
        "remaining": RATE_LIMIT - len(timestamps)
    }