"""§99 golden repo: fastapi-service — small but complete FastAPI surface."""

from fastapi import FastAPI

app = FastAPI(title="Users API")


@app.get("/users/{user_id}", operation_id="getUser")
def get_user(user_id: str) -> dict:
    return {"id": user_id, "email": "a@b.c"}


@app.post("/users", operation_id="createUser")
def create_user() -> dict:
    return {"id": "new"}
