"""FastAPI implementation of the Users API (golden §226 demo)."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/users/{user_id}")
def get_user(user_id: str) -> dict:
    return {"id": user_id}
