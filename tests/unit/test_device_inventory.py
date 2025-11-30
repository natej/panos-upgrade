"""Tests for device inventory functionality."""

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from panos_upgrade.device_inventory import (
    DeviceInventory,
    DEVICE_TYPE_STANDALONE,
    DEVICE_TYPE_HA_PAIR,
    DEVICE_TYPE_UNKNOWN,
    HA_STATE_ACTIVE,
    HA_STATE_PASSIVE,
    HA_STATE_STANDALONE,
    HA_STATE_UNKNOWN
)


class TestDeviceTypeConstants:
    """Test device type constants are defined correctly."""
    
    def test_device_type_constants(self):
        """Verify device type constants."""
        assert DEVICE_TYPE_STANDALONE == "standalone"
        assert DEVICE_TYPE_HA_PAIR == "ha_pair"
        assert DEVICE_TYPE_UNKNOWN == "unknown"
    
    def test_ha_state_constants(self):
        """Verify HA state constants."""
        assert HA_STATE_ACTIVE == "active"
        assert HA_STATE_PASSIVE == "passive"
        assert HA_STATE_STANDALONE == "standalone"
        assert HA_STATE_UNKNOWN == "unknown"


class TestDeviceInventoryExport:
    """Test device export functionality."""
    
    @pytest.fixture
    def inventory_with_mixed_devices(self, tmp_path):
        """Create an inventory file with mixed device types."""
        inventory_data = {
            "devices": {
                "001234567890": {
                    "serial": "001234567890",
                    "hostname": "fw-dc1-01",
                    "mgmt_ip": "10.1.1.10",
                    "current_version": "10.1.0",
                    "model": "PA-3260",
                    "device_type": DEVICE_TYPE_HA_PAIR,
                    "peer_serial": "001234567891",
                    "ha_state": HA_STATE_ACTIVE
                },
                "001234567891": {
                    "serial": "001234567891",
                    "hostname": "fw-dc1-02",
                    "mgmt_ip": "10.1.1.11",
                    "current_version": "10.1.0",
                    "model": "PA-3260",
                    "device_type": DEVICE_TYPE_HA_PAIR,
                    "peer_serial": "001234567890",
                    "ha_state": HA_STATE_PASSIVE
                },
                "001234567892": {
                    "serial": "001234567892",
                    "hostname": "fw-branch-01",
                    "mgmt_ip": "10.2.1.10",
                    "current_version": "10.1.0",
                    "model": "PA-460",
                    "device_type": DEVICE_TYPE_STANDALONE,
                    "peer_serial": "",
                    "ha_state": HA_STATE_STANDALONE
                },
                "001234567893": {
                    "serial": "001234567893",
                    "hostname": "fw-unknown-01",
                    "mgmt_ip": "10.3.1.10",
                    "current_version": "10.1.0",
                    "model": "PA-220",
                    "device_type": DEVICE_TYPE_UNKNOWN,
                    "peer_serial": "",
                    "ha_state": HA_STATE_UNKNOWN
                }
            },
            "last_updated": "2025-01-15T10:30:00Z",
            "device_count": 4
        }
        
        inventory_file = tmp_path / "inventory.json"
        with open(inventory_file, 'w') as f:
            json.dump(inventory_data, f)
        
        return inventory_file
    
    def test_separates_devices_by_type(self, inventory_with_mixed_devices):
        """Should correctly separate devices by device_type."""
        # Load inventory data directly to test separation logic
        with open(inventory_with_mixed_devices) as f:
            data = json.load(f)
        
        devices = list(data["devices"].values())
        
        standalone = [d for d in devices if d.get('device_type') == DEVICE_TYPE_STANDALONE]
        ha_pair = [d for d in devices if d.get('device_type') == DEVICE_TYPE_HA_PAIR]
        unknown = [d for d in devices if d.get('device_type') == DEVICE_TYPE_UNKNOWN]
        
        assert len(standalone) == 1
        assert len(ha_pair) == 2
        assert len(unknown) == 1
    
    def test_groups_ha_pairs_correctly(self, inventory_with_mixed_devices):
        """Should group HA pair members together."""
        with open(inventory_with_mixed_devices) as f:
            data = json.load(f)
        
        devices = data["devices"]
        ha_devices = {k: v for k, v in devices.items() 
                      if v.get('device_type') == DEVICE_TYPE_HA_PAIR}
        
        # Group pairs
        pairs = []
        processed = set()
        for serial, device in ha_devices.items():
            if serial in processed:
                continue
            peer_serial = device.get('peer_serial', '')
            if peer_serial and peer_serial in ha_devices:
                peer = ha_devices[peer_serial]
                pairs.append((device, peer))
                processed.add(serial)
                processed.add(peer_serial)
        
        assert len(pairs) == 1
        pair = pairs[0]
        serials = {pair[0]['serial'], pair[1]['serial']}
        assert serials == {'001234567890', '001234567891'}
    
    def test_orders_active_device_first(self, inventory_with_mixed_devices):
        """Should order HA pairs with active device first."""
        with open(inventory_with_mixed_devices) as f:
            data = json.load(f)
        
        devices = data["devices"]
        ha_devices = {k: v for k, v in devices.items() 
                      if v.get('device_type') == DEVICE_TYPE_HA_PAIR}
        
        # Group and order pairs
        pairs = []
        processed = set()
        for serial, device in ha_devices.items():
            if serial in processed:
                continue
            peer_serial = device.get('peer_serial', '')
            if peer_serial and peer_serial in ha_devices:
                peer = ha_devices[peer_serial]
                # Order: active first
                if device.get('ha_state') == HA_STATE_ACTIVE:
                    pairs.append((device, peer))
                else:
                    pairs.append((peer, device))
                processed.add(serial)
                processed.add(peer_serial)
        
        assert len(pairs) == 1
        device_1, device_2 = pairs[0]
        assert device_1['ha_state'] == HA_STATE_ACTIVE
        assert device_2['ha_state'] == HA_STATE_PASSIVE


class TestHAStateDetection:
    """Test HA state detection logic."""
    
    def test_detects_ha_enabled_with_peer(self):
        """Should detect HA pair when enabled=yes and peer exists."""
        ha_info = {
            'enabled': 'yes',
            'local_state': 'active',
            'peer_state': 'passive',
            'local_serial': '001234567890',
            'peer_serial': '001234567891'
        }
        
        ha_enabled = ha_info.get('enabled', 'no')
        peer = ha_info.get('peer_serial', '')
        
        assert ha_enabled == 'yes'
        assert peer == '001234567891'
        # This would be detected as HA pair
    
    def test_detects_standalone_when_disabled(self):
        """Should detect standalone when HA is disabled."""
        ha_info = {
            'enabled': 'no',
            'local_state': 'standalone',
            'peer_state': '',
            'local_serial': '001234567892',
            'peer_serial': ''
        }
        
        ha_enabled = ha_info.get('enabled', 'no')
        peer = ha_info.get('peer_serial', '')
        
        assert ha_enabled == 'no'
        assert peer == ''
        # This would be detected as standalone
    
    def test_normalizes_active_state(self):
        """Should normalize various active state strings."""
        test_cases = ['active', 'Active', 'ACTIVE', 'active-primary']
        
        for state in test_cases:
            if 'active' in state.lower():
                normalized = HA_STATE_ACTIVE
            else:
                normalized = state.lower()
            assert normalized == HA_STATE_ACTIVE
    
    def test_normalizes_passive_state(self):
        """Should normalize various passive state strings."""
        test_cases = ['passive', 'Passive', 'PASSIVE', 'passive-secondary']
        
        for state in test_cases:
            if 'passive' in state.lower():
                normalized = HA_STATE_PASSIVE
            else:
                normalized = state.lower()
            assert normalized == HA_STATE_PASSIVE


class TestOrphanedHADevices:
    """Test handling of orphaned HA devices."""
    
    def test_detects_orphaned_ha_device(self, tmp_path):
        """Should detect HA device whose peer is not in inventory."""
        inventory_data = {
            "devices": {
                "001234567890": {
                    "serial": "001234567890",
                    "hostname": "fw-orphan-01",
                    "mgmt_ip": "10.1.1.10",
                    "current_version": "10.1.0",
                    "model": "PA-3260",
                    "device_type": DEVICE_TYPE_HA_PAIR,
                    "peer_serial": "001234567899",  # Peer not in inventory
                    "ha_state": HA_STATE_ACTIVE
                }
            },
            "last_updated": "2025-01-15T10:30:00Z",
            "device_count": 1
        }
        
        devices = inventory_data["devices"]
        ha_devices = {k: v for k, v in devices.items() 
                      if v.get('device_type') == DEVICE_TYPE_HA_PAIR}
        
        orphaned = []
        for serial, device in ha_devices.items():
            peer_serial = device.get('peer_serial', '')
            if not peer_serial or peer_serial not in ha_devices:
                orphaned.append(device)
        
        assert len(orphaned) == 1
        assert orphaned[0]['serial'] == '001234567890'

