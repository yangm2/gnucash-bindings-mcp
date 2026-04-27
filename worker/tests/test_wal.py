"""Tests for write-ahead log (WAL) — T1.3.x"""

import json
import time


from gnucash_mcp import wal


class TestWALBasics:
    """T1.3.1–T1.3.3: Basic WAL append, commit, and replay."""

    def test_append_writes_entry(self, test_wal_path):
        """T1.3.1: append() writes entry to JSONL file, entry appears in pending()"""
        wal.init(test_wal_path)

        entry = wal.append("fund_project", {"date": "2025-01-01", "amount": "10000.00"})

        assert entry["id"]
        assert entry["logged_at"]
        assert entry["type"] == "fund_project"
        assert entry["committed_at"] is None
        assert entry["transaction_guid"] is None

        # Entry should be in pending
        pending = wal.pending()
        assert len(pending) == 1
        assert pending[0]["id"] == entry["id"]

        # File should exist and be valid JSONL
        assert test_wal_path.exists()
        with open(test_wal_path) as f:
            line = f.read().strip()
            parsed = json.loads(line)
            assert parsed["id"] == entry["id"]

    def test_mark_committed_sets_timestamp(self, test_wal_path):
        """T1.3.2: mark_committed() sets committed_at; entry no longer in pending()"""
        wal.init(test_wal_path)

        entry = wal.append("post_transaction", {"test": "data"})
        assert entry["committed_at"] is None

        wal.mark_committed(entry["id"])

        # Entry should no longer be pending
        pending = wal.pending()
        assert len(pending) == 0

        # Entry should exist in all_entries with committed_at set
        all_entries = wal.all_entries()
        assert len(all_entries) == 1
        assert all_entries[0]["committed_at"] is not None

    def test_replay_returns_entries_in_order(self, test_wal_path):
        """T1.3.3: replay() returns entries in logged_at order"""
        wal.init(test_wal_path)

        # Create three entries with small delays to ensure ordering
        entry1 = wal.append("fund_project", {"num": 1})
        time.sleep(0.01)
        entry2 = wal.append("receive_invoice", {"num": 2})
        time.sleep(0.01)
        entry3 = wal.append("pay_invoice", {"num": 3})

        # Commit entry2 (not entry1 or entry3)
        wal.mark_committed(entry2["id"])

        # replay() should return pending entries in logged_at order
        replayed = wal.replay()
        assert len(replayed) == 2
        assert replayed[0]["id"] == entry1["id"]
        assert replayed[1]["id"] == entry3["id"]
        assert replayed[0]["logged_at"] < replayed[1]["logged_at"]


class TestWALMixedState:
    """T1.3.4–T1.3.6: WAL with mixed committed/pending, crash durability."""

    def test_wal_survives_incomplete_marks(self, test_wal_path):
        """T1.3.4: WAL file survives simulated crash (append without mark_committed)"""
        wal.init(test_wal_path)

        # Append an entry
        entry = wal.append("post_transaction", {"amount": "5000.00"})

        # Simulate crash by not calling mark_committed
        # Next process reads the WAL
        wal._wal_path = None  # reset
        wal.init(test_wal_path)

        pending = wal.pending()
        assert len(pending) == 1
        assert pending[0]["id"] == entry["id"]

    def test_sequential_appends_valid_jsonl(self, test_wal_path):
        """T1.3.5: Two sequential appends produce two valid JSONL lines (no corruption)"""
        wal.init(test_wal_path)

        wal.append("fund_project", {"a": 1})
        wal.append("receive_invoice", {"b": 2})

        # Read file and verify each line is valid JSON
        with open(test_wal_path) as f:
            lines = f.readlines()
            assert len(lines) == 2
            for line in lines:
                obj = json.loads(line.strip())
                assert "id" in obj
                assert "logged_at" in obj

    def test_mixed_committed_and_pending(self, test_wal_path):
        """T1.3.6: WAL with mixed committed and pending entries returns only pending from pending()"""
        wal.init(test_wal_path)

        entry1 = wal.append("fund_project", {"x": 1})
        entry2 = wal.append("receive_invoice", {"y": 2})
        entry3 = wal.append("pay_invoice", {"z": 3})

        # Commit entry1 and entry3
        wal.mark_committed(entry1["id"], transaction_guid="guid-1")
        wal.mark_committed(entry3["id"], transaction_guid="guid-3")

        # pending() should return only entry2
        pending = wal.pending()
        assert len(pending) == 1
        assert pending[0]["id"] == entry2["id"]

        # all_entries() should return all three
        all_entries = wal.all_entries()
        assert len(all_entries) == 3
        assert all_entries[0]["committed_at"] is not None
        assert all_entries[1]["committed_at"] is None
        assert all_entries[2]["committed_at"] is not None


class TestWALTransactionGUID:
    """Tests for transaction GUID storage in WAL entries."""

    def test_mark_committed_with_guid(self, test_wal_path):
        """mark_committed() can store transaction_guid"""
        wal.init(test_wal_path)

        entry = wal.append("post_transaction", {"test": "data"})
        guid_str = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        wal.mark_committed(entry["id"], transaction_guid=guid_str)

        # Retrieve and verify
        all_entries = wal.all_entries()
        assert len(all_entries) == 1
        assert all_entries[0]["transaction_guid"] == guid_str

    def test_entry_schema(self, test_wal_path):
        """WAL entry has correct schema"""
        wal.init(test_wal_path)

        entry = wal.append("post_interest", {"month": "2025-01", "amount": "25.00"})

        required_keys = {"id", "logged_at", "type", "payload", "committed_at", "transaction_guid"}
        assert set(entry.keys()) == required_keys

        # Verify types
        assert isinstance(entry["id"], str)
        assert isinstance(entry["logged_at"], str)
        assert entry["type"] in [
            "fund_project",
            "receive_invoice",
            "pay_invoice",
            "post_transaction",
            "post_interest",
        ]
        assert isinstance(entry["payload"], dict)
        assert entry["committed_at"] is None  # Initially
        assert entry["transaction_guid"] is None  # Initially
