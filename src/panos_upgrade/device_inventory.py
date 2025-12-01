"""Device inventory management."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple

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
    
    def _query_ha_state_with_retry(
        self,
        device: Dict[str, Any],
        retry_attempts: int = 3
    ) -> Tuple[Dict[str, Any], str, str, str]:
        """
        Query HA state for a single device with retry logic.
        
        Args:
            device: Device info from Panorama
            retry_attempts: Number of retry attempts
            
        Returns:
            Tuple of (device_info, device_type, peer_serial, ha_state)
        """
        from panos_upgrade.direct_firewall_client import DirectFirewallClient
        
        serial = device.get("serial", "")
        hostname = device.get("hostname", "")
        mgmt_ip = device.get("ip_address", "")
        
        device_type = DEVICE_TYPE_UNKNOWN
        peer_serial = ""
        ha_state = HA_STATE_UNKNOWN
        
        if mgmt_ip and self.firewall_username and self.firewall_password:
            last_error = None
            for attempt in range(1, retry_attempts + 1):
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
                    else:
                        device_type = DEVICE_TYPE_STANDALONE
                        ha_state = HA_STATE_STANDALONE
                    
                    # Success - break out of retry loop
                    break
                    
                except Exception as e:
                    last_error = e
                    if attempt < retry_attempts:
                        # Wait before retry with exponential backoff
                        wait_time = 2 ** (attempt - 1)  # 1s, 2s, 4s...
                        self.logger.debug(
                            f"Retry {attempt}/{retry_attempts} for {serial} ({mgmt_ip}) "
                            f"after {wait_time}s: {e}"
                        )
                        time.sleep(wait_time)
                    else:
                        self.logger.warning(
                            f"Failed to query HA state for {serial} ({mgmt_ip}) "
                            f"after {retry_attempts} attempts: {last_error}"
                        )
        
        return (device, device_type, peer_serial, ha_state)
    
    def discover_devices(
        self, 
        max_workers: int = 5,
        retry_attempts: int = 3,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, int]:
        """
        Discover devices from Panorama and query HA state for each in parallel.
        
        Args:
            max_workers: Number of parallel workers for HA state queries
            retry_attempts: Number of retry attempts per device
            progress_callback: Optional callback for progress updates.
                              Called with (current, total, message)
        
        Returns:
            Dictionary with discovery statistics
        """
        self.logger.info(f"Discovering devices from Panorama (workers: {max_workers})...")
        
        try:
            # Query Panorama for connected devices (single call)
            all_devices = self.panorama.get_connected_devices()
            
            # Filter to only devices with valid serial numbers
            devices = [d for d in all_devices if d.get("serial")]
            total_devices = len(devices)
            
            if len(all_devices) != total_devices:
                self.logger.debug(
                    f"Filtered {len(all_devices) - total_devices} devices without serial numbers"
                )
            
            stats = {
                "total": total_devices,
                "new": 0,
                "updated": 0,
                "standalone": 0,
                "ha_pair": 0,
                "unknown": 0,
                "ha_query_failures": 0
            }
            
            if total_devices == 0:
                self.logger.info("No devices found from Panorama")
                return stats
            
            # Track progress with thread-safe counter
            completed_count = 0
            progress_lock = threading.Lock()
            
            def update_progress():
                nonlocal completed_count
                with progress_lock:
                    completed_count += 1
                    if progress_callback:
                        progress_callback(
                            completed_count, 
                            total_devices, 
                            f"Discovered {completed_count}/{total_devices} devices..."
                        )
            
            # Track which devices are new vs updated
            for device in devices:
                serial = device.get("serial", "")
                if serial in self._inventory:
                    stats["updated"] += 1
                else:
                    stats["new"] += 1
            
            # Query HA state in parallel
            results = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_device = {
                    executor.submit(
                        self._query_ha_state_with_retry, 
                        device,
                        retry_attempts
                    ): device
                    for device in devices
                }
                
                # Process results as they complete
                for future in as_completed(future_to_device):
                    try:
                        result = future.result()
                        results.append(result)
                        update_progress()
                    except Exception as e:
                        device = future_to_device[future]
                        self.logger.error(
                            f"Unexpected error querying {device.get('serial')}: {e}"
                        )
                        # Still count as processed
                        update_progress()
            
            # Process results and update inventory
            for device, device_type, peer_serial, ha_state in results:
                serial = device.get("serial", "")
                if not serial:
                    continue
                
                # Update stats based on device type
                if device_type == DEVICE_TYPE_STANDALONE:
                    stats["standalone"] += 1
                elif device_type == DEVICE_TYPE_HA_PAIR:
                    stats["ha_pair"] += 1
                else:
                    stats["unknown"] += 1
                    if self.firewall_username and self.firewall_password:
                        stats["ha_query_failures"] += 1
                
                # Store device info
                self._inventory[serial] = {
                    "serial": serial,
                    "hostname": device.get("hostname", ""),
                    "mgmt_ip": device.get("ip_address", ""),
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

