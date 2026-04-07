"""GnuCash session management (M1.4).

Public API:
  open_session(path, is_new=False) -> Session
  close_session(session) -> None
  book_session(path, is_new=False) -> contextmanager[Session]
  clear_stale_lock(path) -> None
  get_account(book, full_name) -> Account          raises AccountNotFoundError
  gnc_decimal(amount_str) -> GncNumeric
  set_txn_isodate(txn, date_str) -> None
  get_txn_isodate(txn) -> str
  account_balance_float(acc, negate=False) -> float
"""

from contextlib import contextmanager
from datetime import date as Date, datetime
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


def clear_stale_lock(path: Path) -> None:
    """Remove a .LCK file left by a prior crash.

    flock() locks are process-scoped — released when the process dies.  Any .LCK
    present at process startup belongs to a dead process and is safe to remove.
    Call once at startup, before the first open_session(), to preserve live-lock
    detection within the current process.
    """
    lck = Path(str(path) + ".LCK")
    try:
        lck.unlink()
    except FileNotFoundError:
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


def set_txn_isodate(txn, date_str: str) -> None:
    """Set a transaction's date from an ISO-8601 string (YYYY-MM-DD).

    GnuCash's xaccTransSetDate signature is (day, month, year) — the opposite
    of the conventional (year, month, day) order.  This wrapper encodes that
    knowledge so callers never touch the raw argument order.
    """
    d = Date.fromisoformat(date_str)
    txn.SetDate(d.day, d.month, d.year)


def get_txn_isodate(txn) -> str:
    """Return a transaction's date as an ISO-8601 string (YYYY-MM-DD).

    Pairs with set_txn_isodate; avoids scattering strftime("%Y-%m-%d") calls
    across the codebase.
    """
    return txn.GetDate().strftime("%Y-%m-%d")


def account_balance_float(acc, negate: bool = False) -> float:
    """Return an account's balance as a float.

    Pass negate=True for liability/AP accounts: GnuCash stores credit-normal
    balances as negative values; negating gives the conventional positive amount
    owed.
    """
    raw = acc.GetBalance().to_double()
    return -raw if negate else raw


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
