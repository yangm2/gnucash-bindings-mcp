"""GnuCash session management (M1.4).

Public API:
  open_session(path, is_new=False) -> Session
  close_session(session) -> None
  book_session(path, is_new=False) -> contextmanager[Session]
  get_account(book, full_name) -> Account          raises AccountNotFoundError
  gnc_decimal(amount_str) -> GncNumeric
"""

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
import glob
from pathlib import Path

from gnucash import Session, SessionOpenMode
from gnucash import ERR_BACKEND_LOCKED, ERR_FILEIO_FILE_NOT_FOUND  # noqa: F401
from gnucash import GncNumeric


class AccountNotFoundError(Exception):
    pass


def _purge_same_second_backup(path: Path) -> None:
    """Remove the GnuCash backup that would collide with the current-second save.

    GnuCash XML backend creates ``{path}.YYYYMMDDHHMMSS.gnucash`` before each
    save.  When two saves occur within the same second the backup already exists
    and the save silently writes nothing.  Deleting it lets the save proceed.
    """
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    for f in glob.glob(f"{path}.{ts}.gnucash"):
        try:
            Path(f).unlink()
        except OSError:
            pass


def open_session(path: Path, is_new: bool = False) -> Session:
    """Open a GnuCash XML session.

    For new books: initializes the root account then saves so the file exists
    on disk before any mutations.  GnuCash uses OS-level flock() on .LCK files
    to distinguish stale from live locks, so we leave .LCK management to it.
    """
    path = Path(path)
    mode = (SessionOpenMode.SESSION_NEW_STORE if is_new
            else SessionOpenMode.SESSION_NORMAL_OPEN)
    session = Session(f"xml://{path}", mode)

    if is_new:
        # Initialize root account first so the XML has content to write.
        session.book.get_root_account()
        # Save to disk — now the file is created.
        _purge_same_second_backup(path)
        session.save()

    return session


def close_session(session: Session, path: Path = None) -> None:
    """Save and end session, releasing the .LCK file."""
    if path is not None:
        _purge_same_second_backup(path)
    session.save()
    session.end()


@contextmanager
def book_session(path: Path, is_new: bool = False):
    """Context manager: open → yield session → save+end even on exception."""
    path = Path(path)
    session = open_session(path, is_new=is_new)
    try:
        yield session
    finally:
        try:
            close_session(session, path=path)
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
    # int() and int(d * N) both preserve sign, so no manual sign flip needed.
    if exponent >= 0:
        numerator = int(d)
        denominator = 1
    else:
        denominator = 10 ** (-exponent)
        numerator = int(d * denominator)

    return GncNumeric(numerator, denominator)
