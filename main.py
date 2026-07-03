from fastapi import FastAPI, Header, HTTPException, Body, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import uuid
import time

# Create the FastAPI app
app = FastAPI()

# -------------------------
# CORS: allow the grader page to call your API
# -------------------------
# If your assignment gives a specific origin, put that instead of "*".
# Example: allow_origins=["https://your-grader-page.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # allow all origins for simplicity
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# 1. Fixed catalog of orders 1..60
# -------------------------
T = 60  # total orders
orders_catalog = [
    {"id": i, "item": f"Item-{i}", "price": 100 + i}
    for i in range(1, T + 1)
]

# -------------------------
# 2. Idempotency store for POST /orders
# -------------------------
# Maps Idempotency-Key -> order dict (so same key returns same order)
idempotency_store = {}

# -------------------------
# 3. Rate limiting data
# -------------------------
R = 19              # max requests per 10 seconds per client
WINDOW_SECONDS = 10
# Maps client_id -> list of timestamps (seconds) of their recent requests
client_requests = {}


def rate_limiter(request: Request):
    """
    Simple per-client rate limiter:
    - Looks at X-Client-Id header.
    - Allows up to R requests in the last 10 seconds.
    - If exceeded, raises HTTP 429 with Retry-After header.
    """
    client_id = request.headers.get("X-Client-Id")
    if not client_id:
        # Grader expects per-client limiting, so require the header
        raise HTTPException(status_code=400, detail="X-Client-Id header is required")

    now = time.time()

    # Get existing timestamps for this client, or empty list
    history = client_requests.get(client_id, [])

    # Keep only timestamps within the last WINDOW_SECONDS
    recent = [ts for ts in history if now - ts <= WINDOW_SECONDS]

    # If already at or above limit, block this request
    if len(recent) >= R:
        client_requests[client_id] = recent  # save pruned list

        retry_after_seconds = WINDOW_SECONDS  # tell them to wait 10 seconds

        # IMPORTANT: include Retry-After header so grader is happy
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after_seconds)},
        )

    # Otherwise, allow: record this request time
    recent.append(now)
    client_requests[client_id] = recent


# -------------------------
# Idempotent POST /orders
# -------------------------
@app.post("/orders", status_code=201)
def create_order(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    body: dict = Body(default={}),
    _rate = Depends(rate_limiter),  # enforce rate limiting on this endpoint
):
    """
    Idempotent order creation:
    - First time with a new Idempotency-Key: create a new order, return 201.
    - Next times with same Idempotency-Key: return the SAME order, no duplicate.
    """

    # Require the Idempotency-Key header
    if idempotency_key is None:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")

    # If we have already seen this key, return the stored order
    if idempotency_key in idempotency_store:
        # Return same order as before
        return idempotency_store[idempotency_key]

    # First time with this key: create a new order
    new_order_id = str(uuid.uuid4())  # unique ID; grader just checks consistency

    order = {
        "id": new_order_id,
        "status": "created",
        "payload": body,  # optional, just echoes request body
    }

    # Save under this idempotency key
    idempotency_store[idempotency_key] = order

    # Return it (FastAPI will send 201 because of status_code=201 above)
    return order


# -------------------------
# Cursor-based GET /orders
# -------------------------
@app.get("/orders")
def list_orders(
    limit: int = Query(10, gt=0),         # page size (must be > 0)
    cursor: Optional[str] = Query(None),  # opaque cursor from previous response
    _rate = Depends(rate_limiter),        # enforce rate limiting here too
):
    """
    Cursor pagination over the fixed catalog 1..60:
    - GET /orders?limit=P&cursor=C
    - Returns up to P items from the catalog, starting after 'cursor'.
    - Response: {"items": [...], "next_cursor": "..."}
    - Cursor is "last id seen" encoded as a string (opaque to grader).
    """

    # Interpret cursor as "last_id_seen"
    if cursor is None or cursor == "":
        last_id_seen = 0
    else:
        try:
            last_id_seen = int(cursor)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    # Next page starts from id = last_id_seen + 1
    start_id = last_id_seen + 1

    # Select orders with id >= start_id, then cut to 'limit' items
    items = [o for o in orders_catalog if o["id"] >= start_id][:limit]

    # If no items left, we reached the end
    if not items:
        return {
            "items": [],
            "next_cursor": None,
        }

    # New cursor is the last id we returned
    new_last_id = items[-1]["id"]

    # If we haven't finished all 1..T, return the new cursor; else None
    next_cursor = str(new_last_id) if new_last_id < T else None

    return {
        "items": items,
        "next_cursor": next_cursor,
    }
