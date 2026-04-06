"""GnuCash session management (M1.4).

Public API:
  open_session(path, is_new=False) -> Session
  close_session(session) -> None
  book_session(path, is_new=False) -> contextmanager[Session]
  get_account(book, full_name) -> Account          raises AccountNotFoundError
  gnc_decimal(amount_str) -> GncNumeric
"""

from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

from gnucash import Session, GnuCashBackendException, SessionOpenMode
from gnucash import ERR_BACKEND_LOCKED, ERR_FILEIO_FILE_NOT_FOUND  # noqa: F401
from gnucash import GncNumeric


class AccountNotFoundError(Exception):
    pass


def open_session(path: Path, is_new: bool = False) -> Session:
    """Open a GnuCash XML session.

    For new books: calls session.save() immediately (required before mutations)
    and calls get_root_account() to fully initialize the XML structure.
    Stale .LCK files from prior crashes are cleared on NORMAL_OPEN.
    """
    path = Path(path)
    lck = Path(str(path) + ".LCK")
    if lck.exists() and not is_new:
        lck.unlink()  # stale lock from prior crash — safe to clear

    mode = (SessionOpenMode.SESSION_NEW_STORE if is_new
            else SessionOpenMode.SESSION_NORMAL_OPEN)
    session = Session(f"xml://{path}", mode)

    if is_new:
        # Early save required before any mutations on new XML books.
        session.save()
        # Trigger root account initialization so XML is fully written.
        session.book.get_root_account()

    return session


def close_session(session: Session) -> None:
    """Save and end session, releasing the .LCK file."""
    session.save()
    session.end()


@contextmanager
def book_session(path: Path, is_new: bool = False):
    """Context manager: open → yield session → save+end even on exception."""
    session = open_session(path, is_new=is_new)
    try:
        yield session
    finally:
        try:
            close_session(session)
        except Exception:
            # end() can fail if session already ended; suppress and try bare end()
            try:
                session.end()
            except Exception:
                pass


def get_account(book, full_name: str):
    """Return Account for colon-separated full_name, e.g. 'Expenses:Construction:Electrical'.

    Raises AccountNotFoundError if any segment is not found.
    """
    parts = full_name.split(":")
    current = book.get_root_account()
    for part in parts:
        children = {acc.name: acc for acc in current.get_children()}
        if part not in children:
            raise AccountNotFoundError(
                f"Account segment '{part}' not found under '{current.name}'. "
                f"Full path: {full_name!r}"
            )
        current = children[part]
    return current


def gnc_decimal(amount_str: str) -> GncNumeric:
    """Convert a decimal string like '15000.00' to GncNumeric without precision loss.

    Uses the string's own decimal places to set the denominator (e.g. '15000.00'
    → GncNumeric(1500000, 100)).
    """
    try:
        d = Decimal(amount_str)
    except InvalidOperation:
        raise ValueError(f"Invalid decimal amount: {amount_str!r}")

    sign, digits, exponent = d.as_tuple()
    # exponent is negative for fractional parts: 15000.00 → exponent=-2
    if exponent >= 0:
        numerator = int(d)
        denominator = 1
    else:
        denominator = 10 ** (-exponent)
        numerator = int(d * denominator)

    if sign:
        numerator = -numerator

    return GncNumeric(numerator, denominator)
