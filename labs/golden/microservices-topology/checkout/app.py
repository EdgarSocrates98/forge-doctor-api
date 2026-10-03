from payments_sdk import get_charge


def checkout(charge_id: str):
    return get_charge(charge_id)
