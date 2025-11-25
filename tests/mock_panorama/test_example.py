"""Example test using mock Panorama server."""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from panos_upgrade.config import Config
from panos_upgrade.panorama_client import PanoramaClient
from panos_upgrade.validation import ValidationSystem
from panos_upgrade.upgrade_manager import UpgradeManager


def test_single_device_upgrade():
    """Test upgrading a single device."""
    print("=" * 60)
    print("Test: Single Device Upgrade")
    print("=" * 60)
    
    # Configure to use mock server
    config = Config()
    config.set("panorama.host", "localhost:8443")
    config.set("panorama.api_key", "test-api-key")
    config.set("panorama.timeout", 30)
    config.set("validation.min_disk_gb", 2.0)
    
    # Set upgrade paths
    config._config["paths"]["upgrade_paths"] = str(
        Path(__file__).parent / "test_upgrade_paths.json"
    )
    
    # Create clients
    panorama = PanoramaClient(config)
    validation = ValidationSystem(config, panorama)
    upgrade_manager = UpgradeManager(config, panorama, validation)
    
    # Test device serial
    serial = "001234567890"
    
    try:
        # Get device info
        print(f"\n1. Getting device info for {serial}...")
        device_info = panorama.get_device_info(serial)
        print(f"   Device: {device_info.get('hostname')}")
        print(f"   Model: {device_info.get('model')}")
        print(f"   Current Version: {device_info.get('sw_version')}")
        
        # Get system metrics
        print(f"\n2. Collecting system metrics...")
        metrics = panorama.get_system_metrics(serial)
        print(f"   TCP Sessions: {metrics.get('tcp_sessions')}")
        print(f"   Routes: {metrics.get('route_count')}")
        print(f"   ARP Entries: {metrics.get('arp_count')}")
        print(f"   Disk Space: {metrics.get('disk_available_gb')} GB")
        
        # Start upgrade (dry run)
        print(f"\n3. Starting upgrade (dry run)...")
        success, message = upgrade_manager.upgrade_device(
            serial=serial,
            job_id="test-job-001",
            dry_run=True
        )
        
        if success:
            print(f"   ✓ Upgrade completed successfully")
        else:
            print(f"   ✗ Upgrade failed: {message}")
        
        return success
        
    except Exception as e:
        print(f"\n   ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ha_pair_upgrade():
    """Test upgrading an HA pair."""
    print("\n" + "=" * 60)
    print("Test: HA Pair Upgrade")
    print("=" * 60)
    
    # Configure to use mock server
    config = Config()
    config.set("panorama.host", "localhost:8443")
    config.set("panorama.api_key", "test-api-key")
    
    # Create client
    panorama = PanoramaClient(config)
    
    # Test HA pair serials
    primary_serial = "001234567890"
    secondary_serial = "001234567891"
    
    try:
        # Get HA state for both devices
        print(f"\n1. Checking HA state...")
        
        ha_state_primary = panorama.get_ha_state(primary_serial)
        print(f"   Primary ({primary_serial}): {ha_state_primary.get('local_state')}")
        
        ha_state_secondary = panorama.get_ha_state(secondary_serial)
        print(f"   Secondary ({secondary_serial}): {ha_state_secondary.get('local_state')}")
        
        # Determine passive member
        if 'passive' in ha_state_primary.get('local_state', '').lower():
            passive_serial = primary_serial
            active_serial = secondary_serial
        else:
            passive_serial = secondary_serial
            active_serial = primary_serial
        
        print(f"\n2. Upgrade order:")
        print(f"   First: {passive_serial} (passive)")
        print(f"   Second: {active_serial} (active)")
        
        return True
        
    except Exception as e:
        print(f"\n   ✗ Error: {e}")
        return False


def test_validation():
    """Test pre/post-flight validation."""
    print("\n" + "=" * 60)
    print("Test: Validation System")
    print("=" * 60)
    
    # Configure to use mock server
    config = Config()
    config.set("panorama.host", "localhost:8443")
    config.set("panorama.api_key", "test-api-key")
    config.set("validation.min_disk_gb", 2.0)
    
    # Create clients
    panorama = PanoramaClient(config)
    validation = ValidationSystem(config, panorama)
    
    serial = "001234567890"
    
    try:
        # Run pre-flight validation
        print(f"\n1. Running pre-flight validation...")
        passed, metrics, error = validation.run_pre_flight_validation(serial)
        
        if passed:
            print(f"   ✓ Pre-flight validation passed")
            print(f"   TCP Sessions: {metrics.tcp_sessions}")
            print(f"   Routes: {metrics.route_count}")
            print(f"   ARP Entries: {metrics.arp_count}")
            print(f"   Disk Space: {metrics.disk_available_gb} GB")
        else:
            print(f"   ✗ Pre-flight validation failed: {error}")
        
        return passed
        
    except Exception as e:
        print(f"\n   ✗ Error: {e}")
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Mock Panorama Server - Test Suite")
    print("=" * 60)
    print("\nMake sure the mock server is running:")
    print("  python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml")
    print("\nWaiting 3 seconds for you to start the server...")
    time.sleep(3)
    
    results = []
    
    # Run tests
    results.append(("Single Device Upgrade", test_single_device_upgrade()))
    results.append(("HA Pair Upgrade", test_ha_pair_upgrade()))
    results.append(("Validation System", test_validation()))
    
    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:8} {test_name}")
    
    total = len(results)
    passed_count = sum(1 for _, passed in results if passed)
    print(f"\nTotal: {passed_count}/{total} passed")
    
    return passed_count == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

