import requests


def get_charge(charge_id: str):
    return requests.get(f"https://api.example.com/v1/charges/{charge_id}")
