"""Device state management."""

import random
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from sqlalchemy.orm import Session

from .models import Device, Operation


class DeviceManager:
    """Manages device state and operations."""
    
    def __init__(self, db_session: Session):
        """
        Initialize device manager.
        
        Args:
            db_session: SQLAlchemy session
        """
        self.db = db_session
    
    def add_device(
        self,
        serial: str,
        hostname: str,
        model: str,
        current_version: str,
        ip_address: str = "192.168.1.1",
        ha_enabled: bool = False,
        ha_role: str = "standalone",
        ha_peer_serial: Optional[str] = None,
        tcp_sessions: int = 45000,
        route_count: int = 1200,
        arp_count: int = 500,
        disk_space_gb: float = 15.0,
        available_versions: Optional[List[str]] = None
    ) -> Device:
        """
        Add a device to the mock Panorama.
        
        Args:
            serial: Device serial number
            hostname: Device hostname
            model: Device model
            current_version: Current software version
            ip_address: Device IP address
            ha_enabled: Whether HA is enabled
            ha_role: HA role (active, passive, standalone)
            ha_peer_serial: HA peer serial number
            tcp_sessions: Number of TCP sessions
            route_count: Number of routes
            arp_count: Number of ARP entries
            disk_space_gb: Available disk space in GB
            available_versions: List of available software versions
            
        Returns:
            Device object
        """
        # Generate sample routes
        routes = self._generate_routes(route_count)
        
        # Generate sample ARP entries
        arp_entries = self._generate_arp_entries(arp_count)
        
        device = Device(
            serial=serial,
            hostname=hostname,
            model=model,
            current_version=current_version,
            ip_address=ip_address,
            ha_enabled=ha_enabled,
            ha_role=ha_role,
            ha_peer_serial=ha_peer_serial,
            state="online",
            tcp_sessions=tcp_sessions,
            route_count=route_count,
            routes=routes,
            arp_count=arp_count,
            arp_entries=arp_entries,
            disk_space_gb=disk_space_gb,
            available_versions=available_versions or []
        )
        
        self.db.add(device)
        self.db.commit()
        
        return device
    
    def get_device(self, serial: str) -> Optional[Device]:
        """Get device by serial number."""
        return self.db.query(Device).filter(Device.serial == serial).first()
    
    def update_device_version(self, serial: str, new_version: str):
        """Update device software version."""
        device = self.get_device(serial)
        if device:
            device.current_version = new_version
            device.updated_at = datetime.utcnow()
            self.db.commit()
    
    def set_device_state(self, serial: str, state: str):
        """Set device state."""
        device = self.get_device(serial)
        if device:
            device.state = state
            device.updated_at = datetime.utcnow()
            self.db.commit()
    
    def reboot_device(self, serial: str):
        """Mark device as rebooting."""
        device = self.get_device(serial)
        if device:
            device.state = "rebooting"
            device.last_reboot = datetime.utcnow()
            device.updated_at = datetime.utcnow()
            self.db.commit()
    
    def bring_device_online(self, serial: str):
        """Bring device back online after reboot."""
        device = self.get_device(serial)
        if device:
            device.state = "online"
            device.updated_at = datetime.utcnow()
            
            # Slightly vary metrics after reboot (realistic behavior)
            device.tcp_sessions = max(0, device.tcp_sessions + random.randint(-100, 100))
            
            # Occasionally add/remove a route
            if random.random() < 0.2:
                if random.random() < 0.5 and device.routes:
                    # Remove a route
                    device.routes = device.routes[:-1]
                    device.route_count = len(device.routes)
                else:
                    # Add a route
                    new_route = {
                        "destination": f"172.{random.randint(16, 31)}.0.0/12",
                        "gateway": f"10.1.1.{random.randint(2, 254)}",
                        "interface": f"ethernet1/{random.randint(1, 4)}"
                    }
                    device.routes.append(new_route)
                    device.route_count = len(device.routes)
            
            # Occasionally add/remove ARP entry
            if random.random() < 0.3:
                if random.random() < 0.5 and device.arp_entries:
                    device.arp_entries = device.arp_entries[:-1]
                    device.arp_count = len(device.arp_entries)
                else:
                    new_arp = {
                        "ip": f"10.1.1.{random.randint(2, 254)}",
                        "mac": self._generate_mac(),
                        "interface": f"ethernet1/{random.randint(1, 4)}"
                    }
                    device.arp_entries.append(new_arp)
                    device.arp_count = len(device.arp_entries)
            
            self.db.commit()
    
    def is_device_online(self, serial: str) -> bool:
        """Check if device is online."""
        device = self.get_device(serial)
        return device and device.state == "online"
    
    def consume_disk_space(self, serial: str, amount_gb: float):
        """Consume disk space (for downloads)."""
        device = self.get_device(serial)
        if device:
            device.disk_space_gb = max(0, device.disk_space_gb - amount_gb)
            self.db.commit()
    
    def free_disk_space(self, serial: str, amount_gb: float):
        """Free disk space."""
        device = self.get_device(serial)
        if device:
            device.disk_space_gb += amount_gb
            self.db.commit()
    
    def list_devices(self) -> List[Device]:
        """List all devices."""
        return self.db.query(Device).all()
    
    def _generate_routes(self, count: int) -> List[Dict]:
        """Generate sample routing table."""
        routes = []
        for i in range(count):
            routes.append({
                "destination": f"10.{i // 256}.{i % 256}.0/24",
                "gateway": f"192.168.{(i % 4) + 1}.1",
                "interface": f"ethernet1/{(i % 4) + 1}"
            })
        return routes
    
    def _generate_arp_entries(self, count: int) -> List[Dict]:
        """Generate sample ARP table."""
        arp_entries = []
        for i in range(count):
            arp_entries.append({
                "ip": f"10.1.{i // 256}.{i % 256}",
                "mac": self._generate_mac(),
                "interface": f"ethernet1/{(i % 4) + 1}"
            })
        return arp_entries
    
    def _generate_mac(self) -> str:
        """Generate random MAC address."""
        return ":".join([f"{random.randint(0, 255):02x}" for _ in range(6)])

