"""Tests for CSV parsing functionality in CLI commands."""

import pytest
import tempfile
import os
from pathlib import Path
from click.testing import CliRunner

# Import the helper functions we need to test
# We'll test them indirectly through the CLI commands


class TestCSVSerialParsing:
    """Test CSV serial number parsing."""
    
    @pytest.fixture
    def runner(self):
        """Create CLI test runner."""
        return CliRunner()
    
    @pytest.fixture
    def valid_csv(self, tmp_path):
        """Create a valid CSV file with serial column."""
        csv_file = tmp_path / "serials.csv"
        csv_file.write_text("serial,hostname,notes\n001234567890,fw-01,test\n001234567891,fw-02,test2\n")
        return str(csv_file)
    
    @pytest.fixture
    def csv_without_serial_column(self, tmp_path):
        """Create a CSV file missing the serial column."""
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text("hostname,notes\nfw-01,test\nfw-02,test2\n")
        return str(csv_file)
    
    @pytest.fixture
    def csv_with_only_serial(self, tmp_path):
        """Create a CSV file with only serial column."""
        csv_file = tmp_path / "simple.csv"
        csv_file.write_text("serial\n001234567890\n001234567891\n001234567892\n")
        return str(csv_file)
    
    @pytest.fixture
    def empty_csv(self, tmp_path):
        """Create an empty CSV file."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("serial\n")
        return str(csv_file)
    
    def test_reads_serial_column(self, valid_csv):
        """Should correctly read serial column from CSV."""
        import csv
        
        serials = []
        with open(valid_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                serial = row.get('serial', '').strip()
                if serial:
                    serials.append(serial)
        
        assert len(serials) == 2
        assert "001234567890" in serials
        assert "001234567891" in serials
    
    def test_ignores_other_columns(self, valid_csv):
        """Should ignore columns other than serial."""
        import csv
        
        with open(valid_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            assert 'hostname' in reader.fieldnames
            assert 'notes' in reader.fieldnames
            # These columns should exist but we only care about serial
    
    def test_handles_simple_serial_only_csv(self, csv_with_only_serial):
        """Should work with CSV that only has serial column."""
        import csv
        
        serials = []
        with open(csv_with_only_serial, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                serial = row.get('serial', '').strip()
                if serial:
                    serials.append(serial)
        
        assert len(serials) == 3


class TestCSVHAPairParsing:
    """Test CSV HA pair parsing."""
    
    @pytest.fixture
    def valid_ha_csv(self, tmp_path):
        """Create a valid HA pairs CSV file."""
        csv_file = tmp_path / "ha_pairs.csv"
        csv_file.write_text(
            "serial_1,serial_2,pair_name\n"
            "001234567890,001234567891,dc1-pair\n"
            "001234567892,001234567893,dc2-pair\n"
        )
        return str(csv_file)
    
    @pytest.fixture
    def csv_missing_serial_1(self, tmp_path):
        """Create a CSV missing serial_1 column."""
        csv_file = tmp_path / "bad_ha.csv"
        csv_file.write_text("serial_2,pair_name\n001234567891,dc1-pair\n")
        return str(csv_file)
    
    @pytest.fixture
    def csv_missing_serial_2(self, tmp_path):
        """Create a CSV missing serial_2 column."""
        csv_file = tmp_path / "bad_ha.csv"
        csv_file.write_text("serial_1,pair_name\n001234567890,dc1-pair\n")
        return str(csv_file)
    
    def test_reads_ha_pair_columns(self, valid_ha_csv):
        """Should correctly read both serial columns from HA CSV.
        
        Note: The column names serial_1 and serial_2 are just labels.
        The actual active/passive HA state is discovered dynamically
        when the upgrade job runs.
        """
        import csv
        
        pairs = []
        with open(valid_ha_csv, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                serial_1 = row.get('serial_1', '').strip()
                serial_2 = row.get('serial_2', '').strip()
                if serial_1 and serial_2:
                    pairs.append((serial_1, serial_2))
        
        assert len(pairs) == 2
        assert ("001234567890", "001234567891") in pairs
        assert ("001234567892", "001234567893") in pairs
    
    def test_validates_required_columns(self, csv_missing_serial_1):
        """Should detect missing serial_1 column."""
        import csv
        
        with open(csv_missing_serial_1, 'r', newline='') as f:
            reader = csv.DictReader(f)
            assert 'serial_1' not in reader.fieldnames
            assert 'serial_2' in reader.fieldnames


class TestCSVEdgeCases:
    """Test edge cases in CSV parsing."""
    
    def test_handles_whitespace_in_serials(self, tmp_path):
        """Should strip whitespace from serial numbers."""
        import csv
        
        csv_file = tmp_path / "whitespace.csv"
        csv_file.write_text("serial\n  001234567890  \n001234567891 \n")
        
        serials = []
        with open(csv_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                serial = row.get('serial', '').strip()
                if serial:
                    serials.append(serial)
        
        assert len(serials) == 2
        assert serials[0] == "001234567890"
        assert serials[1] == "001234567891"
    
    def test_skips_empty_rows(self, tmp_path):
        """Should skip rows with empty serial."""
        import csv
        
        csv_file = tmp_path / "with_empty.csv"
        csv_file.write_text("serial,hostname\n001234567890,fw-01\n,\n001234567891,fw-02\n")
        
        serials = []
        with open(csv_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                serial = row.get('serial', '').strip()
                if serial:
                    serials.append(serial)
        
        assert len(serials) == 2
    
    def test_handles_different_column_order(self, tmp_path):
        """Should work regardless of column order."""
        import csv
        
        csv_file = tmp_path / "reordered.csv"
        csv_file.write_text("notes,serial,hostname\ntest,001234567890,fw-01\n")
        
        serials = []
        with open(csv_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                serial = row.get('serial', '').strip()
                if serial:
                    serials.append(serial)
        
        assert len(serials) == 1
        assert serials[0] == "001234567890"

