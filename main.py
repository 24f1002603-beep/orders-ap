from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Assignment values
# -----------------------------
TOTAL_ORDERS = 60
RATE_LIMIT = 19
WINDOW = 10

# -----------------------------
# Fixed catalog (IDs 1..60)
# -----------------------------
catalog = [
    {
        "id": i,
        "item": f"Product {i}"
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# -----------------------------
# Memory stores
# -----------------------------
idempotency_store = {}
client_requests = {}

# -----------------------------
# Root endpoint (optional)
# -----------------------------
@app.get("/")
def root():
    return {"status": "running"}

# -----------------------------
# Rate limiting helper
# -----------------------------
def check_rate_limit(client_id: str):
    now = time.time()

    if client_id not in client_requests:
        client_requests[client_id] = []

    # Keep only requests within last 10 seconds
    client_requests[client_id] = [
        t for t in client_requests[client_id]
        if now - t < WINDOW
    ]

    if len(client_requests[client_id]) >= RATE_LIMIT:
        retry_after = int(WINDOW - (now - client_requests[client_id][0])) + 1

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)}
        )

    client_requests[client_id].append(now)

# -----------------------------
# POST /orders
# -----------------------------
@app.post("/orders", status_code=201)
def create_order(
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    x_client_id: str = Header(default="default", alias="X-Client-Id"),
):
    check_rate_limit(x_client_id)

    # Same key -> same order
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    order = {
        "id": str(uuid.uuid4())
    }

    idempotency_store[idempotency_key] = order

    return order

# -----------------------------
# GET /orders
# -----------------------------
@app.get("/orders")
def list_orders(
    limit: int = 10,
    cursor: str | None = None,
    x_client_id: str = Header(default="default", alias="X-Client-Id"),
):
    check_rate_limit(x_client_id)

    start = 0

    if cursor:
        try:
            start = int(base64.b64decode(cursor).decode())
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    end = min(start + limit, TOTAL_ORDERS)

    items = catalog[start:end]

    next_cursor = None

    if end < TOTAL_ORDERS:
        next_cursor = base64.b64encode(str(end).encode()).decode()

    return {
        "items": items,
        "next_cursor": next_cursor
    }
