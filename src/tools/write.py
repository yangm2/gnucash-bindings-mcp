"""Placeholder write tools (stubs) extracted from DEVELOPMENT.md"""
def post_transaction(date, description, splits: list) -> dict:
    return {"status": "ok", "id": "stub"}

def fund_project(date, amount, memo) -> dict:
    return {"status": "ok"}

def receive_invoice(date, vendor, invoice_ref, amount, expense_account) -> dict:
    return {"status": "ok"}

def pay_invoice(date, vendor, invoice_ref, amount) -> dict:
    return {"status": "ok"}

def post_interest(month, amount) -> dict:
    return {"status": "ok"}
