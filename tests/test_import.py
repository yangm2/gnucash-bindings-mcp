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
    """T1.1.4: gnc_version() returns expected version"""
    result = subprocess.run(
        ["python3", "-c", "import gnucash; print(gnucash.gnucash_core_c.gnc_version())"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    version = result.stdout.strip()
    assert version, "No version returned"
    # GnuCash 5.14 from Spike G
    assert version.startswith("5.14"), f"Expected GnuCash 5.14, got {version}"

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
