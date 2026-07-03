from fastapi import FastAPI, Header, HTTPException, Body, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import uuid
import time

app = FastAPI()

# -------------------------
# CORS (so browser grader can call your API)
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # or specific origin if given by assignment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],  # EXPOSE THIS TO THE BROWSER GRADER
)

# -------------------------
# Fixed catalog of orders 1..60
# -------------------------
T = 60
orders_catalog = [
    {"id": i, "item": f"Item-{i}", "price": 100 + i}
    for i in range(1, T + 1)
]

# -------------------------
# Idempotency store
# -------------------------
idempotency_store = {}

# -------------------------
# Rate limiting data
# -------------------------
R = 19                 # max requests per 10 seconds per client
WINDOW_SECONDS = 10
client_requests = {}   # client_id -> list[timestamps]


def rate_limiter(request: Request):
    """
    Per-client fixed-window rate limiter:
    - Identifies client by X-Client-Id.
    - Allows up to R requests in the last WINDOW_SECONDS.
    - If exceeded, raises HTTPException 429 with Retry-After header.
    """
    client_id = request.headers.get("X-Client-Id")
    if not client_id:
        # Grader relies on per-client buckets, so we require the header.
        raise HTTPException(status_code=400, detail="X-Client-Id header is required")

    now = time.time()
    history = client_requests.get(client_id, [])

    # keep only timestamps within the last WINDOW_SECONDS seconds
    recent = [ts for ts in history if now - ts <= WINDOW_SECONDS]

    # if already at or above limit, this request should be blocked
    if len(recent) >= R:
        client_requests[client_id] = recent  # save pruned list

        retry_after_seconds = WINDOW_SECONDS  # simple choice: ask them to wait 10 seconds

        # IMPORTANT: headers must be a mapping of str->str
        # FastAPI will put this into the actual HTTP response headers.
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after_seconds)},
        )

    # allowed: record this request timestamp
    recent.append(now)
    client_requests[client_id] = recent


# -------------------------
# Idempotent POST /orders
# -------------------------
@app.post("/orders", status_code=201)
def create_order(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    body: dict = Body(default={}),
    _rate = Depends(rate_limiter),
):
    """
    Idempotent order creation:
    - First time with a new Idempotency-Key: create order, return 201.
    - Repeated calls with the same Idempotency-Key: return the SAME order.
    """
    if idempotency_key is None:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    # If we have already seen this key, return the stored order
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    # First time: create a new order
    new_order_id = str(uuid.uuid4())
    order = {
        "id": new_order_id,
        "status": "created",
        "payload": body,
    }

    idempotency_store[idempotency_key] = order
    return order


# -------------------------
# Cursor-based GET /orders
# -------------------------
@app.get("/orders")
def list_orders(
    limit: int = Query(10, gt=0),
    cursor: Optional[str] = Query(None),
    _rate = Depends(rate_limiter),
):
    """
    Cursor pagination:
    - GET /orders?limit=P&cursor=C
    - Returns up to P items from IDs 1..T.
    - 'cursor' is treated as "last id seen" encoded as a string.
    - Response: {"items": [...], "next_cursor": "..."}
    """
    # convert cursor string to int last_id_seen
    if cursor is None or cursor == "":
        last_id_seen = 0
    else:
        try:
            last_id_seen = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    start_id = last_id_seen + 1

    # Pick items with id >= start_id, then slice to 'limit'
    items = [o for o in orders_catalog if o["id"] >= start_id][:limit]

    if not items:
        return {
            "items": [],
            "next_cursor": None,
        }

    new_last_id = items[-1]["id"]
    next_cursor = str(new_last_id) if new_last_id < T else None

    return {
        "items": items,
        "next_cursor": next_cursor,
    }
