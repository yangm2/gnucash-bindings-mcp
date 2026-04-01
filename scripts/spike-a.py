#!/usr/bin/env python3
"""
spike-a.py — run inside container to validate python3-gnucash and Session API
"""
from gnucash import Session, GnuCashBackendException, SessionOpenMode, ERR_BACKEND_LOCKED
import tempfile, os

# Test 1: module imports
import gnucash
print(f"GnuCash version: {gnucash.gnucash_core_c.gnc_version()}")

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
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s1:
        s1.book  # create it
    # SESSION_NORMAL_OPEN replaces deprecated is_new=False
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN) as s2:
        book2 = s2.book
        print(f"Reopened root: {book2.get_root_account()}")
    print("PASS: reopen")

# Test 5: lock detection
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "test_lock.gnucash")
    with Session(f"xml://{path}", SessionOpenMode.SESSION_NEW_STORE) as s1:
        try:
            s2 = Session(f"xml://{path}", SessionOpenMode.SESSION_NORMAL_OPEN)
            print("FAIL: expected ERR_BACKEND_LOCKED")
        except GnuCashBackendException as e:
            assert ERR_BACKEND_LOCKED in e.errors
            print("PASS: lock detection via GnuCashBackendException")
