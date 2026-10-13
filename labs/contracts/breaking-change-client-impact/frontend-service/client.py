"""frontend-service client consuming GET /users/{id}."""

import requests


def fetch_user_email() -> str:
    resp = requests.get("https://api.example.com/users/42")
    data = resp.json()
    return data["email"]
