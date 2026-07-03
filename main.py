from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import uuid
import time

app = FastAPI()

# -------------------------------
# CORS
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Accept requests from anywhere
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Assignment Values
# -------------------------------
TOTAL_ORDERS = 60
RATE_LIMIT = 19          # requests
WINDOW = 10              # seconds

# -------------------------------
# Fixed catalog (IDs 1 to 60)
# -------------------------------
catalog = [
    {
        "id": i,
        "item": f"Product {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# -------------------------------
# In-memory storage
# -------------------------------
idempotency_store = {}   # key -> order
client_requests = {}     # client_id -> timestamps


# =========================================================
# 1. Idempotent Order Creation
# =========================================================
@app.post("/orders", status_code=201)
def create_order(
    idempotency_key: str = Header(..., alias="Idempotency-Key")
):

    # Already created?
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    # Create new order
    order = {
        "id": str(uuid.uuid4()),
        "status": "created"
    }

    idempotency_store[idempotency_key] = order

    return JSONResponse(
        status_code=201,
        content=order
    )


# =========================================================
# 2. Cursor Pagination
# =========================================================
@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: Optional[str] = None
):

    start = int(cursor) if cursor else 0

    items = catalog[start:start + limit]

    if start + limit >= TOTAL_ORDERS:
        next_cursor = None
    else:
        next_cursor = str(start + limit)

    return {
        "items": items,
        "next_cursor": next_cursor
    }


# =========================================================
# 3. Rate Limiting
# =========================================================
@app.get("/limited")
def limited_endpoint(
    response: Response,
    x_client_id: str = Header(..., alias="X-Client-Id")
):

    now = time.time()

    timestamps = client_requests.get(x_client_id, [])

    # Keep only timestamps within last 10 seconds
    timestamps = [
        t for t in timestamps
        if now - t < WINDOW
    ]

    if len(timestamps) >= RATE_LIMIT:

        retry_after = WINDOW - (now - timestamps[0])

        response.headers["Retry-After"] = str(int(retry_after) + 1)

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(int(retry_after) + 1)
            }
        )

    timestamps.append(now)

    client_requests[x_client_id] = timestamps

    return {
        "message": "Request accepted",
        "remaining": RATE_LIMIT - len(timestamps)
    }


# =========================================================
# Health Check
# =========================================================
@app.get("/")
def home():
    return {
        "message": "Orders API is running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }