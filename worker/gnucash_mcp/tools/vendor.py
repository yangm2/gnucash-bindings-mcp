"""Vendor management tools — M2.2 (not yet implemented)."""


class RequiresConfirmationError(Exception):
    pass


class VendorHasHistoryError(Exception):
    pass


def vendor_add(name, trade=None, expense_category=None):
    raise NotImplementedError


def vendor_list():
    raise NotImplementedError


def vendor_get_details(name):
    raise NotImplementedError


def vendor_rename(old_name, new_name):
    raise NotImplementedError


def vendor_update(name, trade=None, expense_category=None):
    raise NotImplementedError


def vendor_delete(name, confirm=False):
    raise NotImplementedError


def vendor_guide_resource():
    raise NotImplementedError
