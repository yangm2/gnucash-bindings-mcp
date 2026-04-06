#!/usr/bin/env python3
"""
spike-a.py — run inside container to validate python3-gnucash and Session API
"""
from gnucash import Session, GnuCashBackendException, SessionOpenMode, ERR_BACKEND_LOCKED
import tempfile, os
from pathlib import Path

# Test 1: module imports
import gnucash
print(f"GnuCash version: {gnucash.gnucash_core_c.GNC_TT_NAME}")

# Test 2: create a new book using modern SessionOpenMode API
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test.gnucash")
    # SESSION_NEW_STORE replaces deprecated is_new=True
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as session:
        book = session.book
        root = book.get_root_account()
        print(f"Root account: {root}")
        # context manager calls session.save() then session.end() on exit
    print("PASS: session create/save/end via context manager")

# Test 3: early-save pattern for new books
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_early_save.gnucash")
    session = Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE)
    session.save()   # early save — must happen before any mutations
    book = session.book
    # ... mutations would go here ...
    session.save()
    session.end()
    print("PASS: early-save pattern")

# Test 4: reopen existing book
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_reopen.gnucash")
    print(f"Creating new book at {path}...")
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s1:
        # s1.save()
        book = s1.book  # create it
        root = book.get_root_account() # access it to ensure it's fully initialized

    # dpath = Path(d)
    # print(f"Directory ({dpath}) contents: {[p.name for p in dpath.iterdir()]}")

    # SESSION_NORMAL_OPEN replaces deprecated is_new=False
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN) as s2:
        book2 = s2.book
        print(f"Reopened root: {book2.get_root_account()}")
    print("PASS: reopen")

# Test 5: lock detection
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_lock.gnucash")
    # Phase 1: create the book and close it cleanly so the file exists on disk
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s:
        root = s.book.get_root_account()
    # Phase 2: reopen and hold it open — this is the locked session
    s1 = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)
    try:
        s2 = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)
        s2.end()
        print("FAIL: expected ERR_BACKEND_LOCKED")
    except GnuCashBackendException as e:
        assert ERR_BACKEND_LOCKED in e.errors
        print("PASS: lock detection via GnuCashBackendException")
    finally:
        s1.end()
