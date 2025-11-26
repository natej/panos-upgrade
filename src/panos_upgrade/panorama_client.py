"""Panorama API client for device management and upgrades."""

import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any
from pan.xapi import PanXapi, PanXapiError

from panos_upgrade.logging_config import get_logger
from panos_upgrade.config import Config


class PanoramaClient:
    """Client for interacting with Panorama API."""
    
    def __init__(self, config: Config, rate_limiter=None):
        """
        Initialize Panorama client.
        
        Args:
            config: Configuration instance
            rate_limiter: Rate limiter instance
        """
        self.config = config
        self.rate_limiter = rate_limiter
        self.logger = get_logger("panos_upgrade.panorama")
        self._xapi: Optional[PanXapi] = None
    
    def _get_xapi(self) -> PanXapi:
        """Get or create PanXapi instance."""
        if self._xapi is None:
            try:
                # Check if we're connecting to localhost (mock server)
                # Mock server uses HTTP, production uses HTTPS
                hostname = self.config.panorama_host
                use_http = 'localhost' in hostname or '127.0.0.1' in hostname
                
                # pan-python uses 'use_http' parameter for HTTP connections
                # Don't prepend http:// - let pan-python handle it
                self._xapi = PanXapi(
                    api_key=self.config.panorama_api_key,
                    hostname=hostname,
                    timeout=self.config.get("panorama.timeout", 300),
                    use_http=use_http  # Tell pan-python to use HTTP instead of HTTPS
                )
                self.logger.info(f"Connected to Panorama: {self.config.panorama_host} (HTTP: {use_http})")
            except PanXapiError as e:
                self.logger.error(f"Failed to connect to Panorama: {e}")
                raise
        return self._xapi
    
    def _rate_limited_call(self, func, *args, **kwargs):
        """Execute API call with rate limiting."""
        if self.rate_limiter:
            self.rate_limiter.acquire(blocking=True)
        return func(*args, **kwargs)
    
    def _op_command(self, cmd: str, serial: Optional[str] = None) -> ET.Element:
        """
        Execute operational command.
        
        Args:
            cmd: XML command string
            serial: Device serial number (for targeting specific device)
            
        Returns:
            XML response element
        """
        xapi = self._get_xapi()
        
        # Add target parameter for specific device
        extra_qs = {}
        if serial:
            extra_qs['target'] = serial
        
        try:
            self._rate_limited_call(xapi.op, cmd=cmd, extra_qs=extra_qs)
            return xapi.element_result
        except PanXapiError as e:
            self.logger.error(f"API command failed: {e}")
            raise
    
    def get_device_info(self, serial: str) -> Dict[str, Any]:
        """
        Get device information.
        
        Args:
            serial: Device serial number
            
        Returns:
            Dictionary with device information
        """
        self.logger.debug(f"Getting device info for {serial}")
        
        try:
            cmd = "<show><system><info></info></system></show>"
            result = self._op_command(cmd, serial=serial)
            
            # Parse XML response
            info = {}
            if result is not None:
                info['hostname'] = result.findtext('.//hostname', '')
                info['serial'] = result.findtext('.//serial', '')
                info['sw_version'] = result.findtext('.//sw-version', '')
                info['model'] = result.findtext('.//model', '')
                info['ip_address'] = result.findtext('.//ip-address', '')
            
            return info
        except Exception as e:
            self.logger.error(f"Failed to get device info for {serial}: {e}")
            raise
    
    def get_ha_state(self, serial: str) -> Dict[str, Any]:
        """
        Get HA state for a device.
        
        Args:
            serial: Device serial number
            
        Returns:
            Dictionary with HA state information
        """
        self.logger.debug(f"Getting HA state for {serial}")
        
        try:
            cmd = "<show><high-availability><state></state></high-availability></show>"
            result = self._op_command(cmd, serial=serial)
            
            ha_info = {}
            if result is not None:
                ha_info['enabled'] = result.findtext('.//enabled', 'no')
                ha_info['local_state'] = result.findtext('.//local-info/state', 'standalone')
                ha_info['peer_state'] = result.findtext('.//peer-info/state', '')
                ha_info['local_serial'] = result.findtext('.//local-info/serial-num', '')
                ha_info['peer_serial'] = result.findtext('.//peer-info/serial-num', '')
            
            return ha_info
        except Exception as e:
            self.logger.error(f"Failed to get HA state for {serial}: {e}")
            raise
    
    def get_system_metrics(self, serial: str) -> Dict[str, Any]:
        """
        Get system metrics for validation.
        
        Args:
            serial: Device serial number
            
        Returns:
            Dictionary with system metrics
        """
        self.logger.debug(f"Getting system metrics for {serial}")
        
        metrics = {}
        
        try:
            # Get TCP session count
            cmd = "<show><session><info></info></session></show>"
            result = self._op_command(cmd, serial=serial)
            if result is not None:
                metrics['tcp_sessions'] = int(result.findtext('.//num-active', '0'))
            
            # Get routing table
            cmd = "<show><routing><route></route></routing></show>"
            result = self._op_command(cmd, serial=serial)
            routes = []
            if result is not None:
                for entry in result.findall('.//entry'):
                    route = {
                        'destination': entry.findtext('destination', ''),
                        'gateway': entry.findtext('nexthop', ''),
                        'interface': entry.findtext('interface', '')
                    }
                    routes.append(route)
            metrics['routes'] = routes
            metrics['route_count'] = len(routes)
            
            # Get ARP table
            cmd = "<show><arp><entry name='all'/></arp></show>"
            result = self._op_command(cmd, serial=serial)
            arp_entries = []
            if result is not None:
                for entry in result.findall('.//entry'):
                    arp = {
                        'ip': entry.findtext('ip', ''),
                        'mac': entry.findtext('mac', ''),
                        'interface': entry.findtext('interface', '')
                    }
                    arp_entries.append(arp)
            metrics['arp_entries'] = arp_entries
            metrics['arp_count'] = len(arp_entries)
            
            # Get disk space
            cmd = "<show><system><disk-space></disk-space></system></show>"
            result = self._op_command(cmd, serial=serial)
            if result is not None:
                # PAN-OS returns df-like output as text content
                text_output = result.text or ""
                if not text_output:
                    # Try to get text from child elements
                    text_output = "".join(result.itertext())
                
                metrics['disk_available_gb'] = self._parse_disk_space_output(text_output)
            
            return metrics
        except Exception as e:
            self.logger.error(f"Failed to get system metrics for {serial}: {e}")
            raise
    
    def _parse_disk_space_output(self, text_output: str) -> float:
        """
        Parse df-like disk space output from PAN-OS.
        
        Looks for /opt/panrepo partition first (where software downloads),
        then falls back to root partition.
        
        Example output line:
        /dev/sda8     7.6G  4.0G  3.3G   55% /opt/panrepo
        
        Args:
            text_output: Raw text from disk-space command
            
        Returns:
            Available disk space in GB
        """
        import re
        
        lines = text_output.strip().split('\n')
        
        # Priority order: /opt/panrepo (software downloads), then root /
        target_mounts = ['/opt/panrepo', '/']
        
        for target_mount in target_mounts:
            for line in lines:
                # Skip header line
                if line.startswith('Filesystem') or not line.strip():
                    continue
                
                # Check if this line is for our target mount
                if target_mount == '/' and not line.rstrip().endswith(' /'):
                    continue
                elif target_mount != '/' and target_mount not in line:
                    continue
                
                # Parse the line: Filesystem Size Used Avail Use% Mounted
                # Example: /dev/sda5     7.6G  4.0G  3.3G   55% /opt/pancfg
                parts = line.split()
                if len(parts) >= 4:
                    avail_str = parts[3]  # Available column
                    
                    # Parse size with unit suffix
                    match = re.match(r'([\d.]+)([GMKT]?)', avail_str)
                    if match:
                        value = float(match.group(1))
                        unit = match.group(2).upper() if match.group(2) else ''
                        
                        if unit == 'G':
                            return value
                        elif unit == 'M':
                            return value / 1024
                        elif unit == 'T':
                            return value * 1024
                        elif unit == 'K':
                            return value / (1024 * 1024)
                        else:
                            # Assume bytes
                            return value / (1024 * 1024 * 1024)
        
        self.logger.warning(f"Could not parse disk space from output: {text_output[:200]}")
        return 0.0
    
    def download_software(self, serial: str, version: str) -> bool:
        """
        Download software version to device.
        
        Args:
            serial: Device serial number
            version: Software version to download
            
        Returns:
            True if download initiated successfully
        """
        self.logger.info(f"Downloading version {version} to device {serial}")
        
        try:
            cmd = f"<request><system><software><download><version>{version}</version></download></software></system></request>"
            result = self._op_command(cmd, serial=serial)
            
            # Check for success
            if result is not None:
                status = result.findtext('.//status', '')
                if 'success' in status.lower():
                    self.logger.info(f"Download initiated for {serial}")
                    return True
            
            return False
        except Exception as e:
            self.logger.error(f"Failed to download software for {serial}: {e}")
            raise
    
    def check_download_status(self, serial: str) -> Dict[str, Any]:
        """
        Check software download status.
        
        Args:
            serial: Device serial number
            
        Returns:
            Dictionary with download status
        """
        try:
            cmd = "<show><system><software><status></status></software></system></show>"
            result = self._op_command(cmd, serial=serial)
            
            status = {}
            if result is not None:
                status['downloading'] = result.findtext('.//downloading', 'no')
                status['progress'] = result.findtext('.//progress', '0')
            
            return status
        except Exception as e:
            self.logger.error(f"Failed to check download status for {serial}: {e}")
            raise
    
    def install_software(self, serial: str, version: str) -> bool:
        """
        Install software version on device.
        
        Args:
            serial: Device serial number
            version: Software version to install
            
        Returns:
            True if installation initiated successfully
        """
        self.logger.info(f"Installing version {version} on device {serial}")
        
        try:
            cmd = f"<request><system><software><install><version>{version}</version></install></software></system></request>"
            result = self._op_command(cmd, serial=serial)
            
            if result is not None:
                status = result.findtext('.//status', '')
                if 'success' in status.lower():
                    self.logger.info(f"Installation initiated for {serial}")
                    return True
            
            return False
        except Exception as e:
            self.logger.error(f"Failed to install software for {serial}: {e}")
            raise
    
    def reboot_device(self, serial: str) -> bool:
        """
        Reboot device.
        
        Args:
            serial: Device serial number
            
        Returns:
            True if reboot initiated successfully
        """
        self.logger.info(f"Rebooting device {serial}")
        
        try:
            cmd = "<request><restart><system></system></restart></request>"
            result = self._op_command(cmd, serial=serial)
            
            if result is not None:
                self.logger.info(f"Reboot initiated for {serial}")
                return True
            
            return False
        except Exception as e:
            self.logger.error(f"Failed to reboot device {serial}: {e}")
            raise
    
    def get_connected_devices(self) -> List[Dict[str, Any]]:
        """
        Get list of connected devices from Panorama.
        
        Returns:
            List of device dictionaries with serial, hostname, ip, version, model
        """
        self.logger.info("Querying Panorama for connected devices")
        
        try:
            cmd = "<show><devices><connected></connected></devices></show>"
            result = self._op_command(cmd, serial=None)
            
            devices = []
            if result is not None:
                for entry in result.findall('.//entry'):
                    device = {
                        "serial": entry.findtext('serial', ''),
                        "hostname": entry.findtext('hostname', ''),
                        "ip_address": entry.findtext('ip-address', ''),
                        "sw_version": entry.findtext('sw-version', ''),
                        "model": entry.findtext('model', '')
                    }
                    devices.append(device)
            
            self.logger.info(f"Found {len(devices)} connected devices")
            return devices
            
        except Exception as e:
            self.logger.error(f"Failed to get connected devices: {e}")
            raise
    
    def get_software_info(self, serial: str) -> Dict[str, Any]:
        """
        Get software information including downloaded versions and hashes.
        
        Args:
            serial: Device serial number
            
        Returns:
            Dictionary with software information
        """
        self.logger.debug(f"Getting software info for {serial}")
        
        try:
            # Use 'request system software info' to get available/downloaded versions
            cmd = "<request><system><software><info></info></software></system></request>"
            result = self._op_command(cmd, serial=serial)
            
            versions = []
            if result is not None:
                for entry in result.findall('.//sw-version'):
                    version_info = {
                        "version": entry.findtext('version', ''),
                        "filename": entry.findtext('filename', ''),
                        "size": entry.findtext('size', ''),
                        "downloaded": entry.findtext('downloaded', 'no'),
                        "current": entry.findtext('current', 'no'),
                        "sha256": entry.findtext('sha256', '')
                    }
                    versions.append(version_info)
            
            return {"versions": versions}
            
        except Exception as e:
            self.logger.error(f"Failed to get software info for {serial}: {e}")
            raise
    
    def check_device_ready(self, serial: str, timeout: int = 600) -> bool:
        """
        Check if device is ready after reboot.
        
        Args:
            serial: Device serial number
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if device is ready
        """
        self.logger.info(f"Waiting for device {serial} to be ready")
        
        start_time = time.time()
        poll_interval = 5  # Poll every 5 seconds
        
        while time.time() - start_time < timeout:
            try:
                # Try to get system metrics - this will fail if device is rebooting
                # but succeed once device is fully online
                metrics = self.get_system_metrics(serial)
                
                if metrics and metrics.get('tcp_sessions') is not None:
                    self.logger.info(f"Device {serial} is ready and responding to queries")
                    return True
            except Exception as e:
                # Device not ready yet - this is expected during reboot
                error_msg = str(e)
                if "rebooting" in error_msg.lower():
                    self.logger.debug(f"Device {serial} still rebooting...")
                else:
                    self.logger.debug(f"Device {serial} not ready yet: {e}")
            
            time.sleep(poll_interval)
        
        self.logger.error(f"Device {serial} did not become ready within {timeout} seconds")
        return False

