"""Direct firewall client for download-only operations."""

import time
import xml.etree.ElementTree as ET
from typing import Dict, Optional, Any
from pan.xapi import PanXapi, PanXapiError

from panos_upgrade.logging_config import get_logger
from panos_upgrade.config import Config


class DirectFirewallClient:
    """Client for direct firewall connections (not through Panorama)."""
    
    def __init__(self, mgmt_ip: str, username: str, password: str, rate_limiter=None, xapi=None):
        """
        Initialize direct firewall client.
        
        Args:
            mgmt_ip: Firewall management IP address
            username: Username for authentication
            password: Password for authentication
            rate_limiter: Rate limiter instance (optional)
            xapi: Optional PanXapi instance for dependency injection (testing)
        """
        self.mgmt_ip = mgmt_ip
        self.username = username
        self.password = password
        self.rate_limiter = rate_limiter
        self.logger = get_logger("panos_upgrade.direct_firewall")
        self._xapi: Optional[PanXapi] = xapi  # Allow injection for testing
    
    def _get_xapi(self) -> PanXapi:
        """Get or create PanXapi instance."""
        if self._xapi is None:
            try:
                # Check if connecting to localhost (mock server)
                use_http = 'localhost' in self.mgmt_ip or '127.0.0.1' in self.mgmt_ip
                
                # Direct firewall connections use username/password
                self._xapi = PanXapi(
                    api_username=self.username,
                    api_password=self.password,
                    hostname=self.mgmt_ip,
                    timeout=300,
                    use_http=use_http  # Mock uses HTTP, real firewalls use HTTPS
                )
                self.logger.info(f"Connected to firewall: {self.mgmt_ip} (user: {self.username})")
            except PanXapiError as e:
                self.logger.error(f"Failed to connect to firewall {self.mgmt_ip}: {e}")
                raise
        return self._xapi
    
    def _rate_limited_call(self, func, *args, **kwargs):
        """Execute API call with rate limiting."""
        if self.rate_limiter:
            self.rate_limiter.acquire(blocking=True)
        return func(*args, **kwargs)
    
    def _op_command(self, cmd: str) -> ET.Element:
        """
        Execute operational command.
        
        Args:
            cmd: XML command string
            
        Returns:
            XML response element
        """
        xapi = self._get_xapi()
        
        try:
            self._rate_limited_call(xapi.op, cmd=cmd)
            return xapi.element_result
        except PanXapiError as e:
            self.logger.error(f"API command failed on {self.mgmt_ip}: {e}")
            raise
    
    def check_disk_space(self) -> float:
        """
        Check available disk space on /opt/pancfg (where software downloads go).
        
        Returns:
            Available disk space in GB
        """
        self.logger.debug(f"Checking disk space on {self.mgmt_ip}")
        
        try:
            cmd = "<show><system><disk-space></disk-space></system></show>"
            result = self._op_command(cmd)
            
            if result is not None:
                # PAN-OS returns df-like output as text content
                # Example: "/dev/sda5   7.6G  4.0G  3.3G   55% /opt/pancfg"
                text_output = result.text or ""
                if not text_output:
                    # Try to get text from child elements
                    text_output = "".join(result.itertext())
                
                self.logger.debug(f"Disk space output: {text_output[:500]}")
                
                # Parse the df-like output - look for /opt/pancfg partition
                # where software images are downloaded
                available_gb = self._parse_disk_space_output(text_output)
                self.logger.debug(f"Parsed available disk space: {available_gb} GB")
                return available_gb
            
            return 0.0
            
        except Exception as e:
            self.logger.error(f"Failed to check disk space on {self.mgmt_ip}: {e}")
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
                # Must match exactly at end of line to avoid matching /opt/panrepo_backup for /opt/panrepo
                if not line.rstrip().endswith(' ' + target_mount):
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
    
    def download_software(self, version: str) -> bool:
        """
        Download software version to firewall.
        
        Args:
            version: Software version to download
            
        Returns:
            True if download initiated successfully
        """
        self.logger.info(f"Downloading version {version} to {self.mgmt_ip}")
        
        try:
            cmd = f"<request><system><software><download><version>{version}</version></download></software></system></request>"
            result = self._op_command(cmd)
            
            if result is not None:
                status = result.findtext('.//status', '')
                if 'success' in status.lower():
                    self.logger.info(f"Download initiated for {version} on {self.mgmt_ip}")
                    return True
            
            return False
        except Exception as e:
            self.logger.error(f"Failed to download software on {self.mgmt_ip}: {e}")
            raise
    
    def check_download_status(self) -> Dict[str, Any]:
        """
        Check software download status.
        
        Returns:
            Dictionary with download status
        """
        try:
            cmd = "<show><system><software><status></status></software></system></show>"
            result = self._op_command(cmd)
            
            status = {}
            if result is not None:
                status['downloading'] = result.findtext('.//downloading', 'no')
                status['progress'] = result.findtext('.//progress', '0')
            
            return status
        except Exception as e:
            self.logger.error(f"Failed to check download status on {self.mgmt_ip}: {e}")
            raise
    
    def get_software_info(self) -> Dict[str, Any]:
        """
        Get software information including downloaded versions.
        
        Returns:
            Dictionary with software information
        """
        self.logger.debug(f"Getting software info from {self.mgmt_ip}")
        
        try:
            # Use 'request system software info' to get available/downloaded versions
            cmd = "<request><system><software><info></info></software></system></request>"
            result = self._op_command(cmd)
            
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
            self.logger.error(f"Failed to get software info from {self.mgmt_ip}: {e}")
            raise
    
    def wait_for_download(self, version: str, timeout: int = 1800) -> bool:
        """
        Wait for download to complete.
        
        Args:
            version: Software version being downloaded
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if download completed successfully
        """
        self.logger.info(f"Waiting for download of {version} on {self.mgmt_ip}")
        
        start_time = time.time()
        poll_interval = 30
        
        while time.time() - start_time < timeout:
            try:
                status = self.check_download_status()
                downloading = status.get('downloading', 'no')
                
                if downloading.lower() == 'no':
                    self.logger.info(f"Download completed for {version} on {self.mgmt_ip}")
                    return True
                
                # Log progress
                progress = status.get('progress', '0')
                self.logger.debug(f"Download progress: {progress}")
                
                time.sleep(poll_interval)
                
            except Exception as e:
                self.logger.warning(f"Error checking download status: {e}")
                time.sleep(poll_interval)
        
        self.logger.error(
            f"Download did not complete within {timeout} seconds on {self.mgmt_ip}"
        )
        return False
    
    def get_downloaded_versions(self) -> Dict[str, Dict[str, Any]]:
        """
        Get list of already-downloaded software versions.
        
        Returns:
            Dictionary mapping version to info dict with keys:
            - downloaded: bool
            - current: bool (installed/running)
            - sha256: str (hash if available)
        """
        self.logger.debug(f"Checking downloaded versions on {self.mgmt_ip}")
        
        try:
            software_info = self.get_software_info()
            
            result = {}
            for sw in software_info.get("versions", []):
                version = sw.get("version", "")
                if version:
                    result[version] = {
                        "downloaded": sw.get("downloaded", "no").lower() == "yes",
                        "current": sw.get("current", "no").lower() == "yes",
                        "sha256": sw.get("sha256", "")
                    }
            
            downloaded_count = sum(1 for v in result.values() if v["downloaded"])
            self.logger.info(
                f"Found {downloaded_count} downloaded versions on {self.mgmt_ip}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to get downloaded versions from {self.mgmt_ip}: {e}")
            raise

