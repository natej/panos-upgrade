# Testing Guide

This document explains how to run tests for the PAN-OS Upgrade application.

## Quick Start

Run all tests with a single command:

```bash
./env/bin/pytest
```

## Prerequisites

Install test dependencies:

```bash
./env/bin/pip install pytest pytest-cov
```

## Running Tests

### All Tests

```bash
# Run all tests
./env/bin/pytest

# Run with verbose output
./env/bin/pytest -v

# Run with very verbose output (shows individual assertions)
./env/bin/pytest -vv
```

### Specific Test Files

```bash
# Run disk space parsing tests
./env/bin/pytest tests/unit/test_disk_space_parsing.py

# Run validation tests
./env/bin/pytest tests/unit/test_validation.py

# Run download progress tests
./env/bin/pytest tests/unit/test_download_progress.py
```

### Specific Test Classes or Functions

```bash
# Run a specific test class
./env/bin/pytest tests/unit/test_disk_space_parsing.py::TestDirectFirewallDiskSpaceParsing

# Run a specific test function
./env/bin/pytest tests/unit/test_disk_space_parsing.py::TestDirectFirewallDiskSpaceParsing::test_parses_panrepo_partition
```

### By Test Name Pattern

```bash
# Run tests matching a pattern
./env/bin/pytest -k "disk_space"

# Run tests NOT matching a pattern
./env/bin/pytest -k "not slow"
```

## Test Coverage

Generate coverage reports:

```bash
# Run with coverage
./env/bin/pytest --cov=src/panos_upgrade

# Generate HTML coverage report
./env/bin/pytest --cov=src/panos_upgrade --cov-report=html

# View HTML report (opens in browser)
open htmlcov/index.html
```

## Test Categories

### Unit Tests (`tests/unit/`)

Fast tests that don't require external services:

| File | Description |
|------|-------------|
| `test_command_matcher.py` | XML command pattern matching |
| `test_disk_space_parsing.py` | Disk space output parsing |
| `test_software_info_parsing.py` | Software version info parsing |
| `test_download_progress.py` | Download status and progress |
| `test_validation.py` | Pre-flight and post-flight validation |

### Integration Tests (`tests/integration/`)

Tests that require the mock Panorama server (coming soon).

## Test Markers

Skip slow tests:

```bash
./env/bin/pytest -m "not slow"
```

Skip integration tests:

```bash
./env/bin/pytest -m "not integration"
```

## Test Output Options

```bash
# Show print statements
./env/bin/pytest -s

# Show local variables on failure
./env/bin/pytest -l

# Stop on first failure
./env/bin/pytest -x

# Stop after N failures
./env/bin/pytest --maxfail=3

# Show slowest N tests
./env/bin/pytest --durations=10
```

## Writing Tests

### Using Mock API

Tests use `MockPanXapi` to simulate Panorama/firewall responses:

```python
def test_example(mock_xapi):
    # Register a response for a command pattern
    mock_xapi.add_response(
        "show.system.disk-space",
        '<response status="success"><result>...</result></response>'
    )
    
    # Create client with mock
    client = DirectFirewallClient(
        mgmt_ip="10.0.0.1",
        username="test",
        password="test",
        xapi=mock_xapi
    )
    
    # Call method - will use mock response
    result = client.check_disk_space()
    
    # Verify
    assert result == 15.0
    mock_xapi.assert_called_with("show.system.disk-space")
```

### Using XML Fixtures

Load XML fixtures with placeholder substitution:

```python
def test_with_fixture(xml_loader, mock_xapi):
    # Load fixture with custom values
    response = xml_loader.load(
        "firewall/show_system_disk_space.xml",
        available_gb="15.5",
        total_gb="20.0",
        used_gb="4.5",
        use_percent="23"
    )
    
    mock_xapi.add_response("show.system.disk-space", response)
```

### Using Response Generators

For complex dynamic responses:

```python
from tests.helpers.xml_loader import generate_disk_space_response

def test_with_generator(mock_xapi):
    mock_xapi.add_response(
        "show.system.disk-space",
        generate_disk_space_response(panrepo_available_gb=15.0)
    )
```

## Troubleshooting

### Import Errors

If you see `ModuleNotFoundError`, ensure the project is installed:

```bash
./env/bin/pip install -e .
```

### Test Discovery Issues

Pytest should automatically find tests. If not, check:

1. Test files are named `test_*.py`
2. Test classes are named `Test*`
3. Test functions are named `test_*`

### Mock Not Working

Ensure you're passing the mock to the client:

```python
# Wrong - creates real connection
client = DirectFirewallClient(mgmt_ip="10.0.0.1", ...)

# Correct - uses mock
client = DirectFirewallClient(mgmt_ip="10.0.0.1", ..., xapi=mock_xapi)
```

