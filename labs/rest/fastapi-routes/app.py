"""§98 rest domain: FastAPI implementation evidence only."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/items/{item_id}")
def get_item(item_id: str) -> dict:
    return {"id": item_id}


@app.post("/items")
def create_item() -> dict:
    return {"id": "new"}
