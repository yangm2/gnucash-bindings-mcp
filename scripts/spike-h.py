#!/usr/bin/env python3
"""spike-h.py — PDF extraction from directory mount (run inside container)

Tests H1–H4:
  H1  Text layer detection (text-layer vs scanned)
  H2  Invoice field extraction (vendor, ref, date, total)
  H3  Bank statement row extraction
  H4  Read-only mount enforcement (write attempt fails)

Usage (from macOS host):
  container run --rm \\
    --volume /Volumes/GnuCash-Spike/invoices:/invoices:ro \\
    gnucash-mcp:latest \\
    python3 /scripts/spike-h.py [--invoices /invoices] [--statements /statements]

Install dependencies in container (if not already present):
  pip3 install --break-system-packages pdfplumber
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed. Run: pip3 install --break-system-packages pdfplumber")
    sys.exit(1)


# ── H1: Text layer detection ──────────────────────────────────────────────────

def has_text_layer(pdf_path: Path) -> bool:
    """Return True if any page of the PDF contains extractable text."""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            if page.extract_text():
                return True
    return False


def test_h1(invoices_dir: Path) -> None:
    print("\n=== H1: Text layer detection ===")
    pdfs = sorted(invoices_dir.glob("*.pdf"))
    if not pdfs:
        print(f"  No PDFs found in {invoices_dir} — skipping H1")
        return
    for p in pdfs:
        t0 = time.perf_counter()
        result = has_text_layer(p)
        elapsed = time.perf_counter() - t0
        tag = "text-layer" if result else "scanned (no text layer)"
        print(f"  {p.name}: {tag}  ({elapsed:.2f}s)")


# ── H2: Invoice field extraction ──────────────────────────────────────────────

# Patterns tuned for typical software-generated PDF invoices.
# Adjust regexes to match your actual vendor invoice formats.
_AMOUNT_RE = re.compile(r"\$?\s*([\d,]+\.\d{2})")
_DATE_RE   = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
_REF_RE    = re.compile(r"(?:invoice\s*#?|inv\.?\s*#?|reference\s*#?)\s*([A-Z0-9\-]+)", re.I)


def extract_invoice_fields(pdf_path: Path) -> dict:
    """Extract best-effort invoice fields from a text-layer PDF."""
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Vendor: first non-empty line is usually the company name
    vendor = lines[0] if lines else None

    # Invoice reference
    ref_match = _REF_RE.search(text)
    ref = ref_match.group(1) if ref_match else None

    # Date: first date pattern found
    date_match = _DATE_RE.search(text)
    date = date_match.group(1) if date_match else None

    # Total: last dollar amount on a line containing "total" (case-insensitive)
    total = None
    for line in reversed(lines):
        if re.search(r"\btotal\b", line, re.I):
            m = _AMOUNT_RE.search(line)
            if m:
                total = m.group(1).replace(",", "")
                break
    # Fallback: last dollar amount in document
    if total is None:
        amounts = _AMOUNT_RE.findall(text)
        total = amounts[-1].replace(",", "") if amounts else None

    return {
        "file": pdf_path.name,
        "vendor": vendor,
        "invoice_ref": ref,
        "date": date,
        "total": total,
        "extraction_complete": all([vendor, ref, date, total]),
    }


def test_h2(invoices_dir: Path) -> None:
    print("\n=== H2: Invoice field extraction ===")
    pdfs = [p for p in sorted(invoices_dir.glob("*.pdf")) if has_text_layer(p)]
    if not pdfs:
        print(f"  No text-layer PDFs found in {invoices_dir} — skipping H2")
        return
    complete = 0
    for p in pdfs:
        t0 = time.perf_counter()
        fields = extract_invoice_fields(p)
        elapsed = time.perf_counter() - t0
        status = "COMPLETE" if fields["extraction_complete"] else "PARTIAL"
        print(f"  {p.name} [{status}] ({elapsed:.2f}s)")
        print(f"    vendor={fields['vendor']!r}  ref={fields['invoice_ref']!r}"
              f"  date={fields['date']!r}  total={fields['total']!r}")
        if fields["extraction_complete"]:
            complete += 1
    pct = 100 * complete // len(pdfs) if pdfs else 0
    result = "PASS" if pct >= 90 else "FAIL"
    print(f"  {result}: {complete}/{len(pdfs)} fully extracted ({pct}%) — target ≥90%")


# ── H3: Bank statement extraction ────────────────────────────────────────────

def extract_statement_transactions(pdf_path: Path) -> list[dict]:
    """Extract transaction rows from a text-layer bank statement PDF."""
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # Try table extraction first (best for grid-layout statements)
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row and any(cell for cell in row):
                        rows.append({
                            "date":        (row[0] or "").strip(),
                            "description": (row[1] or "").strip(),
                            "debit":       (row[2] or "").strip() if len(row) > 2 else "",
                            "credit":      (row[3] or "").strip() if len(row) > 3 else "",
                            "balance":     (row[4] or "").strip() if len(row) > 4 else "",
                        })
            # If no tables, fall back to line-by-line with date detection
            if not tables:
                text = page.extract_text() or ""
                for line in text.splitlines():
                    line = line.strip()
                    if _DATE_RE.match(line):
                        amounts = _AMOUNT_RE.findall(line)
                        rows.append({
                            "raw": line,
                            "amounts": amounts,
                        })
    return rows


def test_h3(statements_dir: Path) -> None:
    print("\n=== H3: Bank statement extraction ===")
    pdfs = sorted(statements_dir.glob("*.pdf"))
    if not pdfs:
        print(f"  No PDFs found in {statements_dir} — skipping H3")
        return
    for p in pdfs:
        if not has_text_layer(p):
            print(f"  {p.name}: scanned — cannot extract without OCR")
            continue
        t0 = time.perf_counter()
        rows = extract_statement_transactions(p)
        elapsed = time.perf_counter() - t0
        print(f"  {p.name}: {len(rows)} rows ({elapsed:.2f}s)")
        for row in rows[:5]:
            print(f"    {json.dumps(row)}")
        if len(rows) > 5:
            print(f"    ... ({len(rows) - 5} more)")


# ── H4: Read-only mount enforcement ──────────────────────────────────────────

def test_h4(mount_path: Path) -> None:
    print("\n=== H4: Read-only mount enforcement ===")
    probe = mount_path / ".write-probe"
    try:
        probe.write_text("probe")
        probe.unlink()
        print(f"  FAIL: write to {mount_path} succeeded — mount is NOT read-only")
    except OSError as e:
        print(f"  PASS: write attempt raised {type(e).__name__}: {e.strerror}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Spike H — PDF extraction spike")
    parser.add_argument("--invoices",   default="/invoices",   help="Directory of invoice PDFs (default: /invoices)")
    parser.add_argument("--statements", default="/statements", help="Directory of bank statement PDFs (default: /statements)")
    parser.add_argument("--ro-check",   default="/invoices",   help="Path to check for read-only enforcement (default: /invoices)")
    args = parser.parse_args()

    invoices_dir   = Path(args.invoices)
    statements_dir = Path(args.statements)
    ro_path        = Path(args.ro_check)

    print(f"spike-h: invoices={invoices_dir}  statements={statements_dir}")

    test_h1(invoices_dir)
    test_h2(invoices_dir)
    test_h3(statements_dir)
    test_h4(ro_path)

    print("\nDone.")


if __name__ == "__main__":
    main()
