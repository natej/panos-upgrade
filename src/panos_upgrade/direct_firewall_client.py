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
        
        Looks for /opt/pancfg partition first (where software downloads),
        then falls back to root partition.
        
        Example output line:
        /dev/sda8     7.6G  4.0G  3.3G   55% /opt/pancfg
        
        Args:
            text_output: Raw text from disk-space command
            
        Returns:
            Available disk space in GB
        """
        import re
        
        lines = text_output.strip().split('\n')
        
        # Priority order: /opt/pancfg (software downloads), then root /
        target_mounts = ['/opt/pancfg', '/']
        
        for target_mount in target_mounts:
            for line in lines:
                # Skip header line
                if line.startswith('Filesystem') or not line.strip():
                    continue
                
                # Check if this line is for our target mount
                # Must match exactly at end of line to avoid matching /opt/pancfg_backup for /opt/pancfg
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
    
    def download_software(self, version: str) -> Optional[str]:
        """
        Download software version to firewall.
        
        Args:
            version: Software version to download
            
        Returns:
            Job ID if download initiated successfully, None on failure
        """
        self.logger.info(f"Downloading version {version} to {self.mgmt_ip}")
        
        try:
            cmd = f"<request><system><software><download><version>{version}</version></download></software></system></request>"
            result = self._op_command(cmd)
            
            if result is not None:
                # Response contains a job ID for the async download
                # Example: <result><job>2</job><msg>...</msg></result>
                job_id = result.findtext('.//job', '')
                if job_id:
                    self.logger.info(f"Download initiated for {version} on {self.mgmt_ip} (job: {job_id})")
                    return job_id
                
                # Check for error message
                msg = result.findtext('.//msg', '') or result.findtext('.//line', '')
                if msg:
                    self.logger.error(f"Download failed for {version}: {msg}")
            
            return None
        except Exception as e:
            self.logger.error(f"Failed to download software on {self.mgmt_ip}: {e}")
            raise
    
    def check_job_status(self, job_id: str) -> Dict[str, Any]:
        """
        Check status of a job by ID.
        
        Args:
            job_id: Job ID to check
            
        Returns:
            Dictionary with job status including:
            - status: Job status (ACT, FIN, etc.)
            - result: Job result (OK, FAIL, etc.)
            - progress: Progress percentage
            - details: Job description/details
        """
        try:
            cmd = f"<show><jobs><id>{job_id}</id></jobs></show>"
            result = self._op_command(cmd)
            
            status = {
                'status': 'UNKNOWN',
                'result': '',
                'progress': '0',
                'details': ''
            }
            
            if result is not None:
                job = result.find('.//job')
                if job is not None:
                    status['status'] = job.findtext('status', 'UNKNOWN')
                    status['result'] = job.findtext('result', '')
                    status['progress'] = job.findtext('progress', '0')
                    status['details'] = job.findtext('details', '') or job.findtext('description', '')
            
            return status
        except Exception as e:
            self.logger.error(f"Failed to check job status on {self.mgmt_ip}: {e}")
            raise
    
    def check_download_status(self) -> Dict[str, Any]:
        """
        Check software download status (legacy method).
        
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
    
    def get_software_info(self, timeout: int = 120) -> Dict[str, Any]:
        """
        Get software information including downloaded versions.
        
        This runs 'request system software info' which can take time on devices
        with many software versions.
        
        Args:
            timeout: Command timeout in seconds (default 90)
        
        Returns:
            Dictionary with software information
        """
        self.logger.debug(f"Getting software info from {self.mgmt_ip}")
        
        try:
            # Store original timeout and set new one for this operation
            xapi = self._get_xapi()
            original_timeout = xapi.timeout
            xapi.timeout = timeout
            
            try:
                # Use 'request system software info' to get available/downloaded versions
                cmd = "<request><system><software><info></info></software></system></request>"
                result = self._op_command(cmd)
                
                versions = []
                if result is not None:
                    # Try multiple element names - PAN-OS versions may vary
                    # Common patterns: <entry>, <sw-version>, or direct children of <versions>
                    entries = result.findall('.//entry')
                    if not entries:
                        entries = result.findall('.//sw-version')
                    if not entries:
                        # Try looking for versions container
                        versions_elem = result.find('.//versions')
                        if versions_elem is not None:
                            entries = list(versions_elem)
                    
                    self.logger.debug(f"Found {len(entries)} software entries in response")
                    
                    for entry in entries:
                        version_info = {
                            "version": entry.findtext('version', ''),
                            "filename": entry.findtext('filename', ''),
                            "size": entry.findtext('size', ''),
                            "downloaded": entry.findtext('downloaded', 'no'),
                            "current": entry.findtext('current', 'no'),
                            "sha256": entry.findtext('sha256', '')
                        }
                        # Only add if we got a version
                        if version_info["version"]:
                            versions.append(version_info)
                            self.logger.debug(
                                f"Version {version_info['version']}: downloaded={version_info['downloaded']}"
                            )
                
                self.logger.debug(f"Parsed {len(versions)} versions from software info")
                return {"versions": versions}
            
            finally:
                # Restore original timeout
                xapi.timeout = original_timeout
            
        except Exception as e:
            self.logger.error(f"Failed to get software info from {self.mgmt_ip}: {e}")
            raise
    
    def wait_for_download(
        self,
        job_id: str,
        version: str,
        timeout: int = 1800,
        progress_callback: Optional[callable] = None
    ) -> bool:
        """
        Wait for download job to complete.
        
        Args:
            job_id: Job ID returned from download_software()
            version: Software version being downloaded (for logging)
            timeout: Maximum time to wait in seconds
            progress_callback: Optional callback function(progress_percent: int) called on progress updates
            
        Returns:
            True if download completed successfully
        """
        self.logger.info(f"Waiting for download job {job_id} ({version}) on {self.mgmt_ip}")
        
        start_time = time.time()
        poll_interval = 10  # Poll every 10 seconds
        last_progress = -1
        
        while time.time() - start_time < timeout:
            try:
                status = self.check_job_status(job_id)
                job_status = status.get('status', 'UNKNOWN')
                job_result = status.get('result', '')
                progress_str = status.get('progress', '0')
                
                # Parse progress as int
                try:
                    progress = int(progress_str)
                except (ValueError, TypeError):
                    progress = 0
                
                self.logger.debug(
                    f"Job {job_id} status: {job_status}, result: {job_result}, progress: {progress}%"
                )
                
                # Call progress callback if progress changed
                if progress_callback and progress != last_progress:
                    try:
                        progress_callback(progress)
                    except Exception as e:
                        self.logger.warning(f"Progress callback error: {e}")
                    last_progress = progress
                
                # Job finished
                if job_status == 'FIN':
                    if job_result == 'OK':
                        self.logger.info(f"Download completed for {version} on {self.mgmt_ip}")
                        return True
                    else:
                        details = status.get('details', 'Unknown error')
                        self.logger.error(
                            f"Download failed for {version} on {self.mgmt_ip}: {details}"
                        )
                        return False
                
                # Job still running (ACT = active)
                if job_status in ('ACT', 'PEND'):
                    time.sleep(poll_interval)
                    continue
                
                # Unknown status - keep polling
                self.logger.warning(f"Unknown job status: {job_status}")
                time.sleep(poll_interval)
                
            except Exception as e:
                self.logger.warning(f"Error checking job status: {e}")
                time.sleep(poll_interval)
        
        self.logger.error(
            f"Download job {job_id} did not complete within {timeout} seconds on {self.mgmt_ip}"
        )
        return False
    
    def get_downloaded_versions(self, timeout: int = 120) -> Dict[str, Dict[str, Any]]:
        """
        Get list of already-downloaded software versions.
        
        Args:
            timeout: Command timeout in seconds (default 90)
        
        Returns:
            Dictionary mapping version to info dict with keys:
            - downloaded: bool
            - current: bool (installed/running)
            - sha256: str (hash if available)
        """
        self.logger.debug(f"Checking downloaded versions on {self.mgmt_ip}")
        
        try:
            software_info = self.get_software_info(timeout=timeout)
            
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
    
    def check_software_updates(self, timeout: int = 60) -> bool:
        """
        Check for available software updates from Palo Alto servers.
        
        This command contacts Palo Alto's update servers to refresh the list
        of available software versions. Must be run before downloading new
        versions to ensure they appear in the software info list.
        
        Args:
            timeout: Maximum time to wait for command completion in seconds
            
        Returns:
            True if check completed successfully, False on failure/timeout
        """
        self.logger.info(f"Checking for software updates on {self.mgmt_ip}")
        
        try:
            # Store original timeout and set new one for this operation
            xapi = self._get_xapi()
            original_timeout = xapi.timeout
            xapi.timeout = timeout
            
            try:
                cmd = "<request><system><software><check></check></software></system></request>"
                result = self._op_command(cmd)
                
                if result is not None:
                    # Command completed - check for success indicators
                    status_text = "".join(result.itertext()).lower()
                    if 'error' in status_text:
                        self.logger.warning(
                            f"Software check returned error on {self.mgmt_ip}: {status_text[:200]}"
                        )
                        return False
                    
                    self.logger.info(f"Software check completed successfully on {self.mgmt_ip}")
                    return True
                
                self.logger.warning(f"Software check returned no result on {self.mgmt_ip}")
                return False
                
            finally:
                # Restore original timeout
                xapi.timeout = original_timeout
                
        except Exception as e:
            self.logger.warning(
                f"Software check failed or timed out on {self.mgmt_ip}, continuing anyway: {e}"
            )
            return False
    
    def get_system_info(self) -> Dict[str, Any]:
        """
        Get system information from the firewall.
        
        Returns:
            Dictionary with system information including:
            - hostname: Device hostname
            - serial: Serial number
            - sw_version: Software version
            - model: Device model
            - ip_address: Management IP
        """
        self.logger.debug(f"Getting system info from {self.mgmt_ip}")
        
        try:
            cmd = "<show><system><info></info></system></show>"
            result = self._op_command(cmd)
            
            info = {}
            if result is not None:
                info['hostname'] = result.findtext('.//hostname', '')
                info['serial'] = result.findtext('.//serial', '')
                info['sw_version'] = result.findtext('.//sw-version', '')
                info['model'] = result.findtext('.//model', '')
                info['ip_address'] = result.findtext('.//ip-address', '')
            
            return info
        except Exception as e:
            self.logger.error(f"Failed to get system info from {self.mgmt_ip}: {e}")
            raise
    
    def get_ha_state(self) -> Dict[str, Any]:
        """
        Get HA state for the firewall.
        
        Returns:
            Dictionary with HA state information including:
            - enabled: Whether HA is enabled
            - local_state: Local HA state (active/passive/standalone)
            - peer_state: Peer HA state
            - local_serial: Local serial number
            - peer_serial: Peer serial number
        """
        self.logger.debug(f"Getting HA state from {self.mgmt_ip}")
        
        try:
            cmd = "<show><high-availability><state></state></high-availability></show>"
            result = self._op_command(cmd)
            
            ha_info = {}
            if result is not None:
                ha_info['enabled'] = result.findtext('.//enabled', 'no')
                ha_info['local_state'] = result.findtext('.//local-info/state', 'standalone')
                ha_info['peer_state'] = result.findtext('.//peer-info/state', '')
                ha_info['local_serial'] = result.findtext('.//local-info/serial-num', '')
                ha_info['peer_serial'] = result.findtext('.//peer-info/serial-num', '')
            
            return ha_info
        except Exception as e:
            self.logger.error(f"Failed to get HA state from {self.mgmt_ip}: {e}")
            raise
    
    def install_software(self, version: str) -> Optional[str]:
        """
        Install software version on the firewall.
        
        Args:
            version: Software version to install
            
        Returns:
            Job ID if installation initiated successfully, None on failure
        """
        self.logger.info(f"Installing version {version} on {self.mgmt_ip}")
        
        try:
            cmd = f"<request><system><software><install><version>{version}</version></install></software></system></request>"
            result = self._op_command(cmd)
            
            if result is not None:
                # Response contains a job ID for the async install
                job_id = result.findtext('.//job', '')
                if job_id:
                    self.logger.info(f"Installation initiated for {version} on {self.mgmt_ip} (job: {job_id})")
                    return job_id
                
                # Check for error message
                msg = result.findtext('.//msg', '') or result.findtext('.//line', '')
                if msg:
                    self.logger.error(f"Installation failed for {version}: {msg}")
            
            return None
        except Exception as e:
            self.logger.error(f"Failed to install software on {self.mgmt_ip}: {e}")
            raise
    
    def wait_for_install(
        self,
        job_id: str,
        version: str,
        timeout: int = 1800,
        progress_callback: Optional[callable] = None
    ) -> bool:
        """
        Wait for installation job to complete.
        
        Args:
            job_id: Job ID returned from install_software()
            version: Software version being installed (for logging)
            timeout: Maximum time to wait in seconds
            progress_callback: Optional callback function(progress_percent: int)
            
        Returns:
            True if installation completed successfully
        """
        self.logger.info(f"Waiting for install job {job_id} ({version}) on {self.mgmt_ip}")
        
        start_time = time.time()
        poll_interval = 10
        last_progress = -1
        
        while time.time() - start_time < timeout:
            try:
                status = self.check_job_status(job_id)
                job_status = status.get('status', 'UNKNOWN')
                job_result = status.get('result', '')
                progress_str = status.get('progress', '0')
                
                try:
                    progress = int(progress_str)
                except (ValueError, TypeError):
                    progress = 0
                
                self.logger.debug(
                    f"Install job {job_id} status: {job_status}, result: {job_result}, progress: {progress}%"
                )
                
                if progress_callback and progress != last_progress:
                    try:
                        progress_callback(progress)
                    except Exception as e:
                        self.logger.warning(f"Progress callback error: {e}")
                    last_progress = progress
                
                if job_status == 'FIN':
                    if job_result == 'OK':
                        self.logger.info(f"Installation completed for {version} on {self.mgmt_ip}")
                        return True
                    else:
                        details = status.get('details', 'Unknown error')
                        self.logger.error(
                            f"Installation failed for {version} on {self.mgmt_ip}: {details}"
                        )
                        return False
                
                if job_status in ('ACT', 'PEND'):
                    time.sleep(poll_interval)
                    continue
                
                self.logger.warning(f"Unknown job status: {job_status}")
                time.sleep(poll_interval)
                
            except Exception as e:
                self.logger.warning(f"Error checking install job status: {e}")
                time.sleep(poll_interval)
        
        self.logger.error(
            f"Install job {job_id} did not complete within {timeout} seconds on {self.mgmt_ip}"
        )
        return False
    
    def reboot_device(self) -> bool:
        """
        Reboot the firewall.
        
        Returns:
            True if reboot initiated successfully
        """
        self.logger.info(f"Rebooting device {self.mgmt_ip}")
        
        try:
            cmd = "<request><restart><system></system></restart></request>"
            result = self._op_command(cmd)
            
            if result is not None:
                self.logger.info(f"Reboot initiated for {self.mgmt_ip}")
                return True
            
            return False
        except Exception as e:
            self.logger.error(f"Failed to reboot device {self.mgmt_ip}: {e}")
            raise
    
    def check_device_ready(
        self,
        timeout: int = 600,
        max_poll_interval: int = 300
    ) -> bool:
        """
        Check if device is ready after reboot.
        
        Uses exponential backoff with a maximum poll interval to handle
        the 5-10 minute reboot time.
        
        Args:
            timeout: Maximum time to wait in seconds (default 10 minutes)
            max_poll_interval: Maximum interval between polls in seconds (default 5 minutes)
            
        Returns:
            True if device is ready
        """
        self.logger.info(f"Waiting for device {self.mgmt_ip} to be ready")
        
        start_time = time.time()
        poll_interval = 10  # Start with 10 seconds
        backoff_factor = 1.5
        
        while time.time() - start_time < timeout:
            try:
                # Clear any cached xapi connection since device is rebooting
                self._xapi = None
                
                # Try to get system info - this will fail if device is rebooting
                info = self.get_system_info()
                
                if info and info.get('hostname'):
                    self.logger.info(
                        f"Device {self.mgmt_ip} is ready and responding "
                        f"(hostname: {info.get('hostname')}, version: {info.get('sw_version')})"
                    )
                    return True
                    
            except Exception as e:
                error_msg = str(e).lower()
                if "rebooting" in error_msg:
                    self.logger.debug(f"Device {self.mgmt_ip} still rebooting...")
                else:
                    self.logger.debug(f"Device {self.mgmt_ip} not ready yet: {e}")
            
            # Wait before next poll
            time.sleep(poll_interval)
            
            # Increase poll interval with backoff, but cap at max_poll_interval
            poll_interval = min(poll_interval * backoff_factor, max_poll_interval)
        
        self.logger.error(f"Device {self.mgmt_ip} did not become ready within {timeout} seconds")
        return False
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """
        Get system metrics for validation (pre-flight and post-flight checks).
        
        Returns:
            Dictionary with system metrics including:
            - tcp_sessions: Active TCP session count
            - routes: List of routing table entries
            - route_count: Number of routes
            - arp_entries: List of ARP entries
            - arp_count: Number of ARP entries
            - disk_available_gb: Available disk space in GB
        """
        self.logger.debug(f"Getting system metrics from {self.mgmt_ip}")
        
        metrics = {}
        
        try:
            # Get TCP session count
            cmd = "<show><session><info></info></session></show>"
            result = self._op_command(cmd)
            if result is not None:
                metrics['tcp_sessions'] = int(result.findtext('.//num-active', '0'))
            
            # Get routing table
            cmd = "<show><routing><route></route></routing></show>"
            result = self._op_command(cmd)
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
            result = self._op_command(cmd)
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
            metrics['disk_available_gb'] = self.check_disk_space()
            
            return metrics
        except Exception as e:
            self.logger.error(f"Failed to get system metrics from {self.mgmt_ip}: {e}")
            raise

