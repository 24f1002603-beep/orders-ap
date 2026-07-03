from fastapi import FastAPI, Header, HTTPException, Body, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import uuid
import time

app = FastAPI()

# CORS for browser-based grader
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or specific origin URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Fixed catalog 1..60
T = 60
orders_catalog = [
    {"id": i, "item": f"Item-{i}", "price": 100 + i}
    for i in range(1, T + 1)
]

# 2. Idempotency store
idempotency_store = {}

# 3. Rate limiting
R = 19
WINDOW_SECONDS = 10
client_requests = {}  # client_id -> list[timestamps]

def rate_limiter(request: Request):
    client_id = request.headers.get("X-Client-Id")
    if not client_id:
        raise HTTPException(status_code=400, detail="X-Client-Id header is required")

    now = time.time()
    history = client_requests.get(client_id, [])
    recent = [ts for ts in history if now - ts <= WINDOW_SECONDS]

    if len(recent) >= R:
        retry_after = WINDOW_SECONDS
        client_requests[client_id] = recent
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )

    recent.append(now)
    client_requests[client_id] = recent

# ---- Idempotent POST /orders ----

@app.post("/orders", status_code=201)
def create_order(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    body: dict = Body(default={}),
    _rate = Depends(rate_limiter),
):
    if idempotency_key is None:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    if idempotency_key in idempotency_store:
        # Return same order as before
        return idempotency_store[idempotency_key]

    new_order_id = str(uuid.uuid4())
    order = {
        "id": new_order_id,
        "status": "created",
        "payload": body,
    }
    idempotency_store[idempotency_key] = order
    return order

# ---- Cursor GET /orders ----

@app.get("/orders")
def list_orders(
    limit: int = Query(10, gt=0),
    cursor: Optional[str] = Query(None),
    _rate = Depends(rate_limiter),
):
    if cursor is None or cursor == "":
        last_id_seen = 0
    else:
        try:
            last_id_seen = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    start_id = last_id_seen + 1

    items = [o for o in orders_catalog if o["id"] >= start_id][:limit]

    if not items:
        return {
            "items": [],
            "next_cursor": None
        }

    new_last_id = items[-1]["id"]
    next_cursor = str(new_last_id) if new_last_id < T else None

    return {
        "items": items,
        "next_cursor": next_cursor
    }
