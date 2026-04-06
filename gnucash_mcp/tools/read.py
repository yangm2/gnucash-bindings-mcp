"""Placeholder read tools extracted from DEVELOPMENT.md — implement as needed"""
def get_account_balance(account_path: str) -> dict:
    return {"account": account_path, "balance": 0}

def list_accounts(parent_path: str = None) -> list:
    return []

def list_transactions(account_path: str, limit: int = 20) -> list:
    return []

def get_transaction(tx_id: str) -> dict:
    return {}

def get_project_summary() -> dict:
    return {"construction": {}, "professional_fees": {}}

def get_audit_log() -> list:
    return []

def unlock_ledger() -> dict:
    return {"book": None, "tool_groups": {}, "resource_index": {}}

def vendors_resource() -> list:
    return []
