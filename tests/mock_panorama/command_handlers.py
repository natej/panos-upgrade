"""Command handlers for PAN-OS API commands."""

import xml.etree.ElementTree as ET
from typing import Optional, Dict
from sqlalchemy.orm import Session

from . import xml_responses
from .device_manager import DeviceManager
from .operation_manager import OperationManager


class CommandHandler:
    """Handles PAN-OS API commands."""
    
    def __init__(
        self,
        device_manager: DeviceManager,
        operation_manager: OperationManager,
        failure_config: Optional[Dict] = None
    ):
        """
        Initialize command handler.
        
        Args:
            device_manager: Device manager instance
            operation_manager: Operation manager instance
            failure_config: Failure injection configuration
        """
        self.device_manager = device_manager
        self.operation_manager = operation_manager
        self.failure_config = failure_config or {}
    
    def handle_command(self, cmd: str, target_serial: Optional[str] = None) -> str:
        """
        Handle API command.
        
        Args:
            cmd: XML command string
            target_serial: Target device serial number
            
        Returns:
            XML response string
        """
        try:
            # Parse command
            root = ET.fromstring(cmd)
            
            # Route to appropriate handler
            if root.tag == "show":
                return self._handle_show_command(root, target_serial)
            elif root.tag == "request":
                return self._handle_request_command(root, target_serial)
            else:
                return xml_responses.create_error_response(f"Unknown command: {root.tag}")
        
        except ET.ParseError as e:
            return xml_responses.create_error_response(f"Invalid XML: {e}")
        except Exception as e:
            return xml_responses.create_error_response(f"Command error: {e}")
    
    def _handle_show_command(self, root: ET.Element, target_serial: Optional[str]) -> str:
        """Handle 'show' commands."""
        # Check for device-independent commands first (no target needed)
        if root.find(".//devices/connected") is not None:
            return self._handle_connected_devices()
        
        # Get device for device-specific commands
        if not target_serial:
            return xml_responses.create_error_response("No target device specified")
        
        device = self.device_manager.get_device(target_serial)
        if not device:
            return xml_responses.create_error_response(f"Device not found: {target_serial}")
        
        # Check if device is online (unless checking system info)
        if device.state == "rebooting" and not self._is_system_info_command(root):
            return xml_responses.create_error_response("Device is rebooting")
        
        # Route based on command structure
        if root.find(".//system/info") is not None:
            return self._handle_system_info(device)
        
        elif root.find(".//high-availability/state") is not None:
            return self._handle_ha_state(device)
        
        elif root.find(".//session/info") is not None:
            return self._handle_session_info(device)
        
        elif root.find(".//routing/route") is not None:
            return self._handle_routing_table(device)
        
        elif root.find(".//arp") is not None:
            return self._handle_arp_table(device)
        
        elif root.find(".//system/disk-space") is not None:
            return self._handle_disk_space(device)
        
        elif root.find(".//system/software/status") is not None:
            return self._handle_software_status(device)
        
        elif root.find(".//system/software/info") is not None:
            return self._handle_software_info(device)
        
        else:
            return xml_responses.create_error_response("Unknown show command")
    
    def _handle_request_command(self, root: ET.Element, target_serial: Optional[str]) -> str:
        """Handle 'request' commands."""
        if not target_serial:
            return xml_responses.create_error_response("No target device specified")
        
        device = self.device_manager.get_device(target_serial)
        if not device:
            return xml_responses.create_error_response(f"Device not found: {target_serial}")
        
        # Check if device is online
        if device.state not in ["online", "downloading", "installing"]:
            return xml_responses.create_error_response(f"Device is {device.state}")
        
        # Route based on command structure
        if root.find(".//system/software/download") is not None:
            version_elem = root.find(".//version")
            version = version_elem.text if version_elem is not None else None
            return self._handle_software_download(device, version)
        
        elif root.find(".//system/software/install") is not None:
            version_elem = root.find(".//version")
            version = version_elem.text if version_elem is not None else None
            return self._handle_software_install(device, version)
        
        elif root.find(".//restart/system") is not None:
            return self._handle_reboot(device)
        
        else:
            return xml_responses.create_error_response("Unknown request command")
    
    def _is_system_info_command(self, root: ET.Element) -> bool:
        """Check if command is system info (allowed during reboot)."""
        return root.find(".//system/info") is not None
    
    def _handle_system_info(self, device) -> str:
        """Handle system info command."""
        device_dict = {
            "hostname": device.hostname,
            "serial": device.serial,
            "current_version": device.current_version,
            "model": device.model,
            "ip_address": device.ip_address
        }
        return xml_responses.create_system_info_response(device_dict)
    
    def _handle_ha_state(self, device) -> str:
        """Handle HA state command."""
        device_dict = {
            "ha_enabled": device.ha_enabled,
            "ha_role": device.ha_role,
            "serial": device.serial
        }
        
        # Get peer if HA enabled
        peer_dict = None
        if device.ha_enabled and device.ha_peer_serial:
            peer = self.device_manager.get_device(device.ha_peer_serial)
            if peer:
                peer_dict = {
                    "ha_role": peer.ha_role,
                    "serial": peer.serial
                }
        
        return xml_responses.create_ha_state_response(device_dict, peer_dict)
    
    def _handle_session_info(self, device) -> str:
        """Handle session info command."""
        return xml_responses.create_session_info_response(device.tcp_sessions)
    
    def _handle_routing_table(self, device) -> str:
        """Handle routing table command."""
        return xml_responses.create_routing_table_response(device.routes)
    
    def _handle_arp_table(self, device) -> str:
        """Handle ARP table command."""
        return xml_responses.create_arp_table_response(device.arp_entries)
    
    def _handle_disk_space(self, device) -> str:
        """Handle disk space command."""
        return xml_responses.create_disk_space_response(device.disk_space_gb)
    
    def _handle_software_status(self, device) -> str:
        """Handle software status command."""
        # Check for active download operation
        operation = self.operation_manager.get_active_operation(device.serial, "download")
        
        if operation and operation.status == "in_progress":
            return xml_responses.create_software_status_response(True, operation.progress)
        else:
            return xml_responses.create_software_status_response(False)
    
    def _handle_software_download(self, device, version: Optional[str]) -> str:
        """Handle software download command."""
        if not version:
            return xml_responses.create_error_response("Version not specified")
        
        # Check if version is available
        if device.available_versions and version not in device.available_versions:
            return xml_responses.create_error_response(f"Version {version} not available")
        
        # Check disk space
        if device.disk_space_gb < 2.0:
            return xml_responses.create_error_response("Insufficient disk space")
        
        # Check for failure injection
        should_fail = self._should_fail(device.serial, "download")
        
        # Start download operation
        self.operation_manager.start_download(device.serial, version, should_fail)
        
        return xml_responses.create_software_download_response(True, f"Downloading {version}")
    
    def _handle_software_install(self, device, version: Optional[str]) -> str:
        """Handle software install command."""
        if not version:
            return xml_responses.create_error_response("Version not specified")
        
        # Check for failure injection
        should_fail = self._should_fail(device.serial, "install")
        
        # Start install operation
        self.operation_manager.start_install(device.serial, version, should_fail)
        
        return xml_responses.create_software_install_response(True, f"Installing {version}")
    
    def _handle_reboot(self, device) -> str:
        """Handle reboot command."""
        # Check for failure injection
        should_fail = self._should_fail(device.serial, "reboot")
        
        # Start reboot operation
        self.operation_manager.start_reboot(device.serial, should_fail)
        
        return xml_responses.create_reboot_response(True, "Rebooting device")
    
    def _should_fail(self, device_serial: str, operation: str) -> bool:
        """Check if operation should fail based on failure config."""
        if not self.failure_config:
            return False
        
        for failure in self.failure_config.get("failures", []):
            if failure.get("device") == device_serial and failure.get("operation") == operation:
                import random
                failure_rate = failure.get("failure_rate", 0.0)
                return random.random() < failure_rate
        
        return False
    
    def _handle_connected_devices(self) -> str:
        """Handle show devices connected command."""
        devices = self.device_manager.list_devices()
        
        device_list = []
        for device in devices:
            device_list.append({
                "serial": device.serial,
                "hostname": device.hostname,
                "ip_address": device.ip_address,
                "current_version": device.current_version,
                "model": device.model
            })
        
        return xml_responses.create_connected_devices_response(device_list)
    
    def _handle_software_info(self, device) -> str:
        """Handle software info command."""
        # Get downloaded versions for this device
        # In mock server, we'll track this in device state
        versions = []
        
        # Current version
        versions.append({
            "version": device.current_version,
            "filename": f"PanOS_{device.model}-{device.current_version}",
            "size": "500MB",
            "downloaded": "yes",
            "current": "yes",
            "sha256": self._get_hash_for_version(device.current_version)
        })
        
        # Available versions (if downloaded)
        for version in device.available_versions:
            if version != device.current_version:
                versions.append({
                    "version": version,
                    "filename": f"PanOS_{device.model}-{version}",
                    "size": "500MB",
                    "downloaded": "no",  # Will be updated after download
                    "current": "no",
                    "sha256": self._get_hash_for_version(version)
                })
        
        return xml_responses.create_software_info_response(versions)
    
    def _get_hash_for_version(self, version: str) -> str:
        """Get hash for version from config or generate fake one."""
        # Check if config has version_hashes
        version_hashes = self.failure_config.get("version_hashes", {})
        
        if version in version_hashes:
            return version_hashes[version]
        
        # Generate deterministic fake hash
        import hashlib
        fake_hash = hashlib.sha256(f"panos-{version}".encode()).hexdigest()
        return fake_hash

