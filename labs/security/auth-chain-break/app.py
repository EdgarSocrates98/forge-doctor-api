"""Contract declares apiKey but the implementation carries none."""

from fastapi import FastAPI

app = FastAPI(title="Orders API")


@app.get("/orders/{order_id}", operation_id="getOrder")
def get_order(order_id: str) -> dict:
    return {"id": order_id}
