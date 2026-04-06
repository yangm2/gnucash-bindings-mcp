from gnucash import Session, GnuCashBackendException, SessionOpenMode
from gnucash import ERR_BACKEND_LOCKED, ERR_FILEIO_FILE_NOT_FOUND
from contextlib import contextmanager
from pathlib import Path

def open_session(path: Path, is_new: bool = False) -> Session:
    """Open a GnuCash XML session. Clears stale .LCK if present."""
    lck = Path(str(path) + ".LCK")
    if lck.exists() and not is_new:
        lck.unlink()   # stale lock from prior crash — safe to clear
    mode = (SessionOpenMode.SESSION_NEW_STORE if is_new
            else SessionOpenMode.SESSION_NORMAL_OPEN)
    session = Session(f"xml://{path}", mode)
    if is_new:
        # Early save required before any mutations on new XML books.
        # Skipping this causes subtle corruption (per GnuCash example scripts).
        session.save()
    return session

def close_session(session: Session) -> None:
    """Save and end a session, releasing the .LCK file."""
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
            # end() can fail if session already ended; suppress
            try:
                session.end()
            except Exception:
                pass
