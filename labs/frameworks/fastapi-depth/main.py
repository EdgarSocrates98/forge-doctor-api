"""FastAPI depth fixture: auth dep + DI + error contract.

No Query/Path/Body/Field param defaults — the validation surface is
deliberately absent so the lab asserts the explicit unknown.
"""
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import OAuth2PasswordBearer

app = FastAPI()
oauth = OAuth2PasswordBearer(tokenUrl="token")


def get_db():
    ...


@app.exception_handler(ValueError)
async def on_value(request, exc):
    ...


@app.get("/pets/{pet_id}")
def pet(
    pet_id: int,
    tok: str = Security(oauth),
    db=Depends(get_db),
):
    raise HTTPException(status_code=404, detail="not found")
