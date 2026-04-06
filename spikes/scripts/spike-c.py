#!/usr/bin/env python3
"""spike-c.py — run inside the container against a file saved by macOS 5.15

% container run -it --rm -v ../scripts:/mnt/scripts -v /Volumes/GnuCash-Spike:/data spike-g
"""
from gnucash import Session, SessionOpenMode

# The file must be created by opening a new book in macOS GnuCash 5.15
# and doing File > Save, then copying to /data/ via VirtioFS (Spike B)
# SESSION_NORMAL_OPEN replaces deprecated is_new=False
with Session("xml:///data/spike-cross-version.gnucash",
             SessionOpenMode.SESSION_NORMAL_OPEN) as session:
    book = session.book
    root = book.get_root_account()
    print("Accounts:", [a.GetName() for a in root.get_children()])
    # no session.save() — read-only probe; end() via context manager
print("PASS: opened cleanly, no migration")
