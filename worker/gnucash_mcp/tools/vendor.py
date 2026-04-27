"""Vendor management tools — M2.2 (not yet implemented)."""


class RequiresConfirmationError(Exception):
    pass


class VendorHasHistoryError(Exception):
    pass


def vendor_add(name, trade=None, expense_category=None) -> dict:
    raise NotImplementedError


def vendor_list() -> list[dict]:
    raise NotImplementedError


def vendor_get_details(name) -> dict:
    raise NotImplementedError


def vendor_rename(old_name, new_name) -> dict:
    raise NotImplementedError


def vendor_update(name, trade=None, expense_category=None) -> dict:
    raise NotImplementedError


def vendor_delete(name, confirm=False) -> dict:
    raise NotImplementedError


def vendor_guide_resource() -> str:
    raise NotImplementedError
