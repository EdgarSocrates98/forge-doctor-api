"""§99 golden repo: fastapi-service — small but complete FastAPI surface."""

from fastapi import FastAPI, Security
from fastapi.security import APIKeyHeader

app = FastAPI(title="Users API")
api_key_header = APIKeyHeader(name="X-Key")


@app.get("/users/{user_id}", operation_id="getUser")
def get_user(
    user_id: str, _key: str = Security(api_key_header)
) -> dict:
    return {"id": user_id, "email": "a@b.c"}


@app.post("/users", operation_id="createUser")
def create_user(_key: str = Security(api_key_header)) -> dict:
    return {"id": "new"}
