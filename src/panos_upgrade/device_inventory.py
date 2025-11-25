"""Device inventory management."""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from panos_upgrade.logging_config import get_logger
from panos_upgrade.utils.file_ops import atomic_write_json, safe_read_json
from panos_upgrade.panorama_client import PanoramaClient
from panos_upgrade.exceptions import DeviceNotFoundError


class DeviceInventory:
    """Manages device inventory from Panorama."""
    
    def __init__(self, inventory_file: Path, panorama_client: PanoramaClient):
        """
        Initialize device inventory.
        
        Args:
            inventory_file: Path to inventory.json
            panorama_client: Panorama client instance
        """
        self.inventory_file = Path(inventory_file)
        self.panorama = panorama_client
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
    
    def discover_devices(self) -> Dict[str, int]:
        """
        Discover devices from Panorama.
        
        Returns:
            Dictionary with discovery statistics
        """
        self.logger.info("Discovering devices from Panorama...")
        
        try:
            # Query Panorama for connected devices
            devices = self.panorama.get_connected_devices()
            
            stats = {
                "total": len(devices),
                "new": 0,
                "updated": 0
            }
            
            for device in devices:
                serial = device.get("serial", "")
                if not serial:
                    continue
                
                if serial in self._inventory:
                    stats["updated"] += 1
                else:
                    stats["new"] += 1
                
                # Store device info
                self._inventory[serial] = {
                    "serial": serial,
                    "hostname": device.get("hostname", ""),
                    "mgmt_ip": device.get("ip_address", ""),
                    "current_version": device.get("sw_version", ""),
                    "model": device.get("model", ""),
                    "discovered_at": datetime.utcnow().isoformat() + "Z"
                }
            
            # Save inventory
            self._save_inventory()
            
            self.logger.info(
                f"Discovery complete: {stats['total']} devices "
                f"({stats['new']} new, {stats['updated']} updated)"
            )
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Device discovery failed: {e}", exc_info=True)
            raise
    
    def _save_inventory(self):
        """Save inventory to file."""
        data = {
            "devices": self._inventory,
            "last_updated": datetime.utcnow().isoformat() + "Z",
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

