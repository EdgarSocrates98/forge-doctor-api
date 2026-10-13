"""Dynamic route construction — paths are not literal strings."""

from fastapi import FastAPI

app = FastAPI()

BASE = "/api"

# f-string path — not statically literal
@app.get(f"{BASE}/users/{'{'}uid{'}'}")
def dyn_users(uid: str) -> dict:
    return {}

ROUTE = "/computed"
