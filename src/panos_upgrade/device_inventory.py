"""Device inventory management."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

from panos_upgrade.logging_config import get_logger
from panos_upgrade.utils.file_ops import atomic_write_json, safe_read_json
from panos_upgrade.panorama_client import PanoramaClient
from panos_upgrade.exceptions import DeviceNotFoundError


# Device type constants
DEVICE_TYPE_STANDALONE = "standalone"
DEVICE_TYPE_HA_PAIR = "ha_pair"
DEVICE_TYPE_UNKNOWN = "unknown"

# HA state constants
HA_STATE_ACTIVE = "active"
HA_STATE_PASSIVE = "passive"
HA_STATE_STANDALONE = "standalone"
HA_STATE_UNKNOWN = "unknown"


class DeviceInventory:
    """Manages device inventory from Panorama."""
    
    def __init__(
        self, 
        inventory_file: Path, 
        panorama_client: PanoramaClient,
        firewall_username: str = "",
        firewall_password: str = ""
    ):
        """
        Initialize device inventory.
        
        Args:
            inventory_file: Path to inventory.json
            panorama_client: Panorama client instance
            firewall_username: Username for direct firewall connections
            firewall_password: Password for direct firewall connections
        """
        self.inventory_file = Path(inventory_file)
        self.panorama = panorama_client
        self.firewall_username = firewall_username
        self.firewall_password = firewall_password
        self.logger = get_logger("panos_upgrade.inventory")
        self._inventory: Dict[str, Dict[str, Any]] = {}
        self._load_inventory()
    
    def _load_inventory(self):
        """Load inventory from file."""
        try:
            data = safe_read_json(self.inventory_file, default={})
            self._inventory = data.get("devices", {})
            last_updated = data.get("last_updated", "never")
            self.logger.debug(
                f"Loaded inventory: {len(self._inventory)} devices "
                f"(last updated: {last_updated})"
            )
        except Exception as e:
            self.logger.error(f"Failed to load inventory: {e}")
            self._inventory = {}
    
    def reload(self):
        """Reload inventory from disk."""
        self._load_inventory()
    
    def discover_devices(
        self, 
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, int]:
        """
        Discover devices from Panorama and query HA state for each.
        
        Args:
            progress_callback: Optional callback for progress updates.
                              Called with (current, total, message)
        
        Returns:
            Dictionary with discovery statistics
        """
        from panos_upgrade.direct_firewall_client import DirectFirewallClient
        
        self.logger.info("Discovering devices from Panorama...")
        
        try:
            # Query Panorama for connected devices
            devices = self.panorama.get_connected_devices()
            total_devices = len(devices)
            
            stats = {
                "total": total_devices,
                "new": 0,
                "updated": 0,
                "standalone": 0,
                "ha_pair": 0,
                "unknown": 0,
                "ha_query_failures": 0
            }
            
            for idx, device in enumerate(devices, 1):
                serial = device.get("serial", "")
                if not serial:
                    continue
                
                hostname = device.get("hostname", "")
                mgmt_ip = device.get("ip_address", "")
                
                # Report progress
                if progress_callback:
                    progress_callback(idx, total_devices, f"Querying {hostname or serial}...")
                
                if serial in self._inventory:
                    stats["updated"] += 1
                else:
                    stats["new"] += 1
                
                # Query HA state directly from firewall
                device_type = DEVICE_TYPE_UNKNOWN
                peer_serial = ""
                ha_state = HA_STATE_UNKNOWN
                
                if mgmt_ip and self.firewall_username and self.firewall_password:
                    try:
                        firewall_client = DirectFirewallClient(
                            mgmt_ip=mgmt_ip,
                            username=self.firewall_username,
                            password=self.firewall_password
                        )
                        ha_info = firewall_client.get_ha_state()
                        
                        # Determine device type and HA state
                        ha_enabled = ha_info.get('enabled', 'no')
                        local_state = ha_info.get('local_state', 'standalone').lower()
                        peer = ha_info.get('peer_serial', '')
                        
                        if ha_enabled == 'yes' and peer:
                            device_type = DEVICE_TYPE_HA_PAIR
                            peer_serial = peer
                            # Normalize HA state
                            if 'active' in local_state:
                                ha_state = HA_STATE_ACTIVE
                            elif 'passive' in local_state:
                                ha_state = HA_STATE_PASSIVE
                            else:
                                ha_state = local_state
                            stats["ha_pair"] += 1
                        else:
                            device_type = DEVICE_TYPE_STANDALONE
                            ha_state = HA_STATE_STANDALONE
                            stats["standalone"] += 1
                            
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to query HA state for {serial} ({mgmt_ip}): {e}"
                        )
                        stats["ha_query_failures"] += 1
                        stats["unknown"] += 1
                else:
                    # No credentials or mgmt_ip - can't query HA state
                    stats["unknown"] += 1
                
                # Store device info
                self._inventory[serial] = {
                    "serial": serial,
                    "hostname": hostname,
                    "mgmt_ip": mgmt_ip,
                    "current_version": device.get("sw_version", ""),
                    "model": device.get("model", ""),
                    "device_type": device_type,
                    "peer_serial": peer_serial,
                    "ha_state": ha_state,
                    "discovered_at": datetime.now(timezone.utc).isoformat() + "Z"
                }
            
            # Save inventory
            self._save_inventory()
            
            self.logger.info(
                f"Discovery complete: {stats['total']} devices "
                f"({stats['new']} new, {stats['updated']} updated, "
                f"{stats['standalone']} standalone, {stats['ha_pair']} HA pair members, "
                f"{stats['unknown']} unknown)"
            )
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Device discovery failed: {e}", exc_info=True)
            raise
    
    def _save_inventory(self):
        """Save inventory to file."""
        data = {
            "devices": self._inventory,
            "last_updated": datetime.now(timezone.utc).isoformat() + "Z",
            "device_count": len(self._inventory)
        }
        
        atomic_write_json(self.inventory_file, data)
        self.logger.debug(f"Saved inventory: {len(self._inventory)} devices")
    
    def get_device(self, serial: str) -> Optional[Dict[str, Any]]:
        """
        Get device information.
        
        Args:
            serial: Device serial number
            
        Returns:
            Device info dictionary or None
        """
        return self._inventory.get(serial)
    
    def get_device_mgmt_ip(self, serial: str) -> str:
        """
        Get device management IP address.
        
        Args:
            serial: Device serial number
            
        Returns:
            Management IP address
            
        Raises:
            DeviceNotFoundError: If device not in inventory
        """
        device = self.get_device(serial)
        if not device:
            raise DeviceNotFoundError(serial)
        
        mgmt_ip = device.get("mgmt_ip", "")
        if not mgmt_ip:
            raise ValueError(f"No management IP for device {serial}")
        
        return mgmt_ip
    
    def list_devices(self) -> List[Dict[str, Any]]:
        """Get list of all devices."""
        return list(self._inventory.values())
    
    def get_devices_by_version(self, version: str) -> List[Dict[str, Any]]:
        """
        Get devices with specific current version.
        
        Args:
            version: Software version
            
        Returns:
            List of devices with that version
        """
        return [
            device for device in self._inventory.values()
            if device.get("current_version") == version
        ]
    
    def count(self) -> int:
        """Get total device count."""
        return len(self._inventory)

