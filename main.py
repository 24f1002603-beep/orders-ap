from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
# Fixed catalog
# -----------------------------
catalog = [
    {"id": i, "item": f"Product {i}"}
    for i in range(1, TOTAL_ORDERS + 1)
]

# -----------------------------
# Stores
# -----------------------------
idempotency_store = {}
client_requests = {}

# -----------------------------
# Root
# -----------------------------
@app.get("/")
def root():
    return {"status": "running"}

# -----------------------------
# Rate Limit Middleware
# -----------------------------
@app.middleware("http")
async def rate_limit(request: Request, call_next):

    # Skip OPTIONS (CORS preflight)
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id", "default")

    now = time.time()

    if client_id not in client_requests:
        client_requests[client_id] = []

    # Keep only timestamps within WINDOW seconds
    client_requests[client_id] = [
        t for t in client_requests[client_id]
        if now - t < WINDOW
    ]

    if len(client_requests[client_id]) >= RATE_LIMIT:

        retry_after = max(
            1,
            int(WINDOW - (now - client_requests[client_id][0])) + 1,
        )

        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={
                "Retry-After": str(retry_after)
            },
        )

    client_requests[client_id].append(now)

    return await call_next(request)

# -----------------------------
# POST /orders
# -----------------------------
@app.post("/orders", status_code=201)
def create_order(
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):

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
def get_orders(
    limit: int = 10,
    cursor: str | None = None,
):

    start = 0

    if cursor:
        try:
            start = int(base64.b64decode(cursor.encode()).decode())
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    end = min(start + limit, TOTAL_ORDERS)

    items = catalog[start:end]

    next_cursor = None

    if end < TOTAL_ORDERS:
        next_cursor = base64.b64encode(str(end).encode()).decode()

    return {
        "items": items,
        "next_cursor": next_cursor,
    }
