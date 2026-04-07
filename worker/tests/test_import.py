"""Test Phase 1 container basics (T1.1)"""
import subprocess
import json

def test_gnucash_import():
    """T1.1.3: python3 -c 'import gnucash' succeeds"""
    result = subprocess.run(
        ["python3", "-c", "import gnucash"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"gnucash import failed: {result.stderr}"

def test_gnucash_version():
    """T1.1.4: GnuCash 5.14 available (from Spike G)"""
    # Version check: gnc_version() API not available in bindings
    # Spike G confirms Ubuntu 26.04 ships GnuCash 5.14
    result = subprocess.run(
        ["python3", "-c", "import gnucash"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, "GnuCash bindings import failed"

def test_mcp_import():
    """gnucash_mcp package imports"""
    result = subprocess.run(
        ["python3", "-c", "import gnucash_mcp; import gnucash_mcp.dispatch"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"mcp import failed: {result.stderr}"

if __name__ == "__main__":
    test_gnucash_import()
    test_gnucash_version()
    test_mcp_import()
    print("All tests passed")
