from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uuid
import time
import base64

app = FastAPI()

# -----------------------------
# CORS
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Fixed catalog
# -----------------------------
TOTAL_ORDERS = 60

catalog = [
    {
        "id": i,
        "item": f"Product {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# -----------------------------
# Idempotency storage
# -----------------------------
idempotency_store = {}

# -----------------------------
# Rate limit storage
# -----------------------------
RATE_LIMIT = 19
WINDOW = 10

client_requests = {}


# -----------------------------
# Request model
# -----------------------------
class OrderCreate(BaseModel):
    item: str


# -----------------------------
# Rate limit helper
# -----------------------------
def check_rate_limit(client_id: str):

    now = time.time()

    if client_id not in client_requests:
        client_requests[client_id] = []

    timestamps = client_requests[client_id]

    timestamps = [t for t in timestamps if now - t < WINDOW]

    client_requests[client_id] = timestamps

    if len(timestamps) >= RATE_LIMIT:

        retry_after = WINDOW - (now - timestamps[0])

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(int(retry_after) + 1)
            }
        )

    timestamps.append(now)


# -----------------------------
# POST /orders
# -----------------------------
@app.post("/orders", status_code=201)
def create_order(
    order: OrderCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    client_id: str = Header(..., alias="X-Client-Id"),
):

    check_rate_limit(client_id)

    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    new_order = {
        "id": str(uuid.uuid4()),
        "item": order.item
    }

    idempotency_store[idempotency_key] = new_order

    return new_order


# -----------------------------
# GET /orders
# -----------------------------
@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: str = "",
    x_client_id: str = Header(..., alias="X-Client-Id"),
):

    check_rate_limit(x_client_id)

    start = 0

    if cursor:

        decoded = base64.b64decode(cursor.encode()).decode()

        start = int(decoded)

    end = min(start + limit, TOTAL_ORDERS)

    items = catalog[start:end]

    next_cursor = None

    if end < TOTAL_ORDERS:
        next_cursor = base64.b64encode(
            str(end).encode()
        ).decode()

    return {
        "items": items,
        "next_cursor": next_cursor
    }