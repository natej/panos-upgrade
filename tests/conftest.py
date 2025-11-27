"""Pytest configuration and fixtures for PAN-OS Upgrade tests."""

import json
import os
import pytest
from pathlib import Path
from typing import Generator

# Add src and tests to path for imports
import sys
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root / "src"))
sys.path.insert(0, str(_project_root))

from tests.helpers import XMLFixtureLoader, MockPanXapi
from tests.helpers.xml_loader import (
    generate_disk_space_response,
    generate_software_info_response,
    generate_routing_table_response,
    generate_arp_table_response,
    generate_session_info_response,
    generate_download_status_response,
)


# =============================================================================
# XML Fixture Helpers
# =============================================================================

@pytest.fixture
def xml_loader() -> XMLFixtureLoader:
    """
    Provides XML fixture loader with registered generators.
    
    Usage:
        def test_something(xml_loader):
            xml = xml_loader.load("firewall/show_system_info.xml", hostname="fw-01")
    """
    loader = XMLFixtureLoader()
    
    # Register dynamic generators
    loader.register_generator("gen:disk_space", generate_disk_space_response)
    loader.register_generator("gen:software_info", generate_software_info_response)
    loader.register_generator("gen:routing_table", generate_routing_table_response)
    loader.register_generator("gen:arp_table", generate_arp_table_response)
    loader.register_generator("gen:session_info", generate_session_info_response)
    loader.register_generator("gen:download_status", generate_download_status_response)
    
    return loader


# =============================================================================
# Mock API Fixtures
# =============================================================================

@pytest.fixture
def mock_xapi() -> MockPanXapi:
    """
    Provides a fresh MockPanXapi instance.
    
    Usage:
        def test_something(mock_xapi):
            mock_xapi.add_response("show.system.info", "<response>...</response>")
    """
    return MockPanXapi()


@pytest.fixture
def mock_xapi_with_defaults(xml_loader) -> MockPanXapi:
    """
    Provides MockPanXapi with common default responses pre-registered.
    
    Includes responses for:
    - show system info
    - show system disk-space
    - request system software info
    """
    mock = MockPanXapi()
    
    # Register common responses
    mock.add_response(
        "show.system.info",
        xml_loader.load("firewall/show_system_info.xml", 
                       hostname="test-fw", version="10.1.0", serial="001234567890")
    )
    mock.add_response(
        "show.system.disk-space",
        generate_disk_space_response(panrepo_available_gb=15.0)
    )
    mock.add_response(
        "request.system.software.info",
        generate_software_info_response()
    )
    
    return mock


# =============================================================================
# Configuration Fixtures
# =============================================================================

@pytest.fixture
def test_work_dir(tmp_path) -> Path:
    """
    Provides a fresh temporary work directory for each test.
    
    Creates the standard directory structure used by the application.
    """
    work_dir = tmp_path / "panos-upgrade"
    
    # Create directory structure
    dirs = [
        "config",
        "devices",
        "queue/pending",
        "queue/active",
        "queue/completed",
        "queue/cancelled",
        "status/devices",
        "status/ha_pairs",
        "logs/structured",
        "logs/text",
        "validation/pre_flight",
        "validation/post_flight",
        "commands/incoming",
        "commands/processed",
    ]
    
    for d in dirs:
        (work_dir / d).mkdir(parents=True, exist_ok=True)
    
    return work_dir


@pytest.fixture
def test_config(test_work_dir) -> "Config":
    """
    Provides a test configuration pointing to temp directories.
    """
    from panos_upgrade.config import Config
    
    # Create minimal config file
    config_data = {
        "panorama": {
            "host": "test-panorama",
            "api_key": "test-api-key",
            "rate_limit": 100,
            "timeout": 30
        },
        "firewall": {
            "username": "test-user",
            "password": "test-pass"
        },
        "workers": {
            "max": 3,
            "queue_size": 100
        },
        "validation": {
            "tcp_session_margin": 5.0,
            "route_margin": 0.0,
            "arp_margin": 0.0,
            "min_disk_gb": 5.0
        },
        "logging": {
            "level": "DEBUG"
        },
        "paths": {
            "work_dir": str(test_work_dir),
            "upgrade_paths": str(test_work_dir / "config" / "upgrade_paths.json")
        }
    }
    
    config_file = test_work_dir / "config" / "config.json"
    with open(config_file, 'w') as f:
        json.dump(config_data, f, indent=2)
    
    # Create upgrade paths file
    upgrade_paths = {
        "10.0.0": ["10.1.0", "10.2.0", "11.0.0"],
        "10.1.0": ["10.2.0", "11.0.0"],
        "10.2.0": ["11.0.0"],
        "11.0.0": ["11.1.0"]
    }
    
    upgrade_paths_file = test_work_dir / "config" / "upgrade_paths.json"
    with open(upgrade_paths_file, 'w') as f:
        json.dump(upgrade_paths, f, indent=2)
    
    # Pass work_dir to Config to ensure it uses the temp directory
    return Config(config_file=str(config_file), work_dir=str(test_work_dir))


# =============================================================================
# Client Fixtures
# =============================================================================

@pytest.fixture
def mock_panorama_client(mock_xapi, test_config) -> "PanoramaClient":
    """
    Provides a PanoramaClient with mocked API.
    
    Note: Requires PanoramaClient to support xapi injection.
    """
    from panos_upgrade.panorama_client import PanoramaClient
    return PanoramaClient(config=test_config, xapi=mock_xapi)


@pytest.fixture
def mock_firewall_client(mock_xapi) -> "DirectFirewallClient":
    """
    Provides a DirectFirewallClient with mocked API.
    
    Note: Requires DirectFirewallClient to support xapi injection.
    """
    from panos_upgrade.direct_firewall_client import DirectFirewallClient
    return DirectFirewallClient(
        mgmt_ip="10.0.0.1",
        username="test-user",
        password="test-pass",
        xapi=mock_xapi
    )


# =============================================================================
# Utility Fixtures
# =============================================================================

@pytest.fixture
def sample_device_info() -> dict:
    """Provides sample device information for tests."""
    return {
        "serial": "001234567890",
        "hostname": "test-firewall-01",
        "ip-address": "10.0.0.1",
        "model": "PA-VM",
        "sw-version": "10.1.0",
        "connected": "yes",
        "ha": {
            "enabled": "no"
        }
    }


@pytest.fixture
def sample_upgrade_path() -> list:
    """Provides a sample upgrade path for tests."""
    return ["10.1.0", "10.2.0", "11.0.0"]


@pytest.fixture
def sample_job_data() -> dict:
    """Provides sample job data for tests."""
    return {
        "job_id": "test-job-001",
        "type": "standalone",
        "devices": ["001234567890"],
        "dry_run": False,
        "download_only": False,
        "created_at": "2025-01-01T00:00:00Z"
    }


# =============================================================================
# Markers
# =============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )

