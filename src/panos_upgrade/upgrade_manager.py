"""Upgrade orchestration and management."""

import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum

from panos_upgrade.config import Config
from panos_upgrade.logging_config import get_logger, log_with_context
from panos_upgrade.models import (
    DeviceStatus, UpgradeStatus, HARole, DiskSpaceInfo, ValidationMetrics
)
from panos_upgrade.panorama_client import PanoramaClient
from panos_upgrade.validation import ValidationSystem
from panos_upgrade.utils.file_ops import atomic_write_json, read_json, safe_read_json
from panos_upgrade.device_inventory import DeviceInventory
from panos_upgrade.direct_firewall_client import DirectFirewallClient
from panos_upgrade import constants


class UpgradePhase(Enum):
    """Upgrade phase enumeration."""
    INIT = "init"
    PRE_FLIGHT = "pre_flight_validation"
    DOWNLOAD = "download"
    INSTALL = "install"
    REBOOT = "reboot"
    POST_FLIGHT = "post_flight_validation"
    COMPLETE = "complete"


class UpgradeManager:
    """Manages device upgrade orchestration."""
    
    def __init__(
        self,
        config: Config,
        panorama_client: PanoramaClient,
        validation_system: ValidationSystem,
        device_inventory: DeviceInventory
    ):
        """
        Initialize upgrade manager.
        
        Args:
            config: Configuration instance
            panorama_client: Panorama client instance
            validation_system: Validation system instance
            device_inventory: Device inventory instance
        """
        self.config = config
        self.panorama = panorama_client
        self.validation = validation_system
        self.inventory = device_inventory
        self.logger = get_logger("panos_upgrade.manager")
        
        # Load upgrade paths
        self.upgrade_paths = self._load_upgrade_paths()
        
        # Cancellation tracking
        self._cancel_lock = threading.Lock()
        self._cancelled_jobs: set = set()
        self._cancelled_devices: set = set()
        
        # Track devices that have had software check run (to avoid duplicate checks)
        self._software_check_done: set = set()
    
    def _load_upgrade_paths(self) -> Dict[str, List[str]]:
        """Load upgrade paths from configuration file."""
        paths_file = self.config.upgrade_paths_file
        
        try:
            paths = safe_read_json(paths_file, default={})
            self.logger.info(f"Loaded upgrade paths for {len(paths)} versions")
            return paths
        except Exception as e:
            self.logger.error(f"Failed to load upgrade paths from {paths_file}: {e}")
            return {}
    
    def get_upgrade_path(self, current_version: str) -> Optional[List[str]]:
        """
        Get upgrade path for a version.
        
        Args:
            current_version: Current device version
            
        Returns:
            List of versions to upgrade through, or None if not found
        """
        return self.upgrade_paths.get(current_version)
    
    def upgrade_device(
        self,
        serial: str,
        job_id: str,
        dry_run: bool = False
    ) -> Tuple[bool, str]:
        """
        Upgrade a standalone device.
        
        Args:
            serial: Device serial number
            job_id: Job identifier
            dry_run: Whether this is a dry run
            
        Returns:
            Tuple of (success, message)
        """
        self.logger.info(f"Starting upgrade for device {serial} (job: {job_id}, dry_run: {dry_run})")
        
        # Initialize device status
        device_status = self._init_device_status(serial, job_id)
        
        try:
            # Get device info
            device_info = self.panorama.get_device_info(serial)
            device_status.hostname = device_info.get('hostname', serial)
            device_status.current_version = device_info.get('sw_version', '')
            device_status.ha_role = HARole.STANDALONE.value
            
            # Check for upgrade path
            upgrade_path = self.get_upgrade_path(device_status.current_version)
            
            if upgrade_path is None:
                msg = f"No upgrade path found for version {device_status.current_version}"
                self.logger.warning(msg, extra={'serial': serial})
                device_status.upgrade_status = UpgradeStatus.SKIPPED.value
                device_status.skip_reason = msg
                device_status.upgrade_message = f"Skipped: No upgrade path for version {device_status.current_version}"
                self._save_device_status(device_status)
                return False, msg
            
            device_status.upgrade_path = upgrade_path
            device_status.target_version = upgrade_path[-1] if upgrade_path else ""
            self._save_device_status(device_status)
            
            # Execute upgrade through path
            success = self._execute_upgrade_path(device_status, job_id, dry_run)
            
            if success:
                device_status.upgrade_status = UpgradeStatus.COMPLETE.value
                device_status.upgrade_message = f"Upgrade completed successfully to version {device_status.target_version}"
                msg = f"Upgrade completed successfully for {serial}"
                self.logger.info(msg, extra={'serial': serial})
            else:
                device_status.upgrade_status = UpgradeStatus.FAILED.value
                device_status.upgrade_message = f"Upgrade failed - see error log for details"
                msg = f"Upgrade failed for {serial}"
                self.logger.error(msg, extra={'serial': serial})
            
            self._save_device_status(device_status)
            return success, msg
            
        except Exception as e:
            msg = f"Upgrade error for {serial}: {str(e)}"
            self.logger.error(msg, exc_info=True, extra={'serial': serial})
            device_status.upgrade_status = UpgradeStatus.FAILED.value
            device_status.add_error("upgrade", msg, str(e))
            self._save_device_status(device_status)
            return False, msg
    
    def upgrade_ha_pair(
        self,
        primary_serial: str,
        secondary_serial: str,
        job_id: str,
        dry_run: bool = False
    ) -> Tuple[bool, str]:
        """
        Upgrade an HA pair (passive first, then active).
        
        Args:
            primary_serial: Primary device serial
            secondary_serial: Secondary device serial
            job_id: Job identifier
            dry_run: Whether this is a dry run
            
        Returns:
            Tuple of (success, message)
        """
        self.logger.info(
            f"Starting HA pair upgrade (job: {job_id}, dry_run: {dry_run}): "
            f"{primary_serial}, {secondary_serial}"
        )
        
        try:
            # Determine which is passive
            ha_state_primary = self.panorama.get_ha_state(primary_serial)
            ha_state_secondary = self.panorama.get_ha_state(secondary_serial)
            
            primary_state = ha_state_primary.get('local_state', 'unknown')
            secondary_state = ha_state_secondary.get('local_state', 'unknown')
            
            # Determine upgrade order (passive first)
            if 'passive' in primary_state.lower():
                first_serial, second_serial = primary_serial, secondary_serial
            elif 'passive' in secondary_state.lower():
                first_serial, second_serial = secondary_serial, primary_serial
            else:
                msg = f"Could not determine passive member for HA pair"
                self.logger.error(msg)
                return False, msg
            
            self.logger.info(f"Upgrading passive member first: {first_serial}")
            
            # Upgrade passive member
            success, msg = self.upgrade_device(first_serial, job_id, dry_run)
            if not success:
                return False, f"Failed to upgrade passive member: {msg}"
            
            # Check for cancellation
            if self._is_cancelled(job_id, first_serial):
                return False, "Upgrade cancelled"
            
            self.logger.info(f"Upgrading active member: {second_serial}")
            
            # Upgrade active member
            success, msg = self.upgrade_device(second_serial, job_id, dry_run)
            if not success:
                return False, f"Failed to upgrade active member: {msg}"
            
            return True, "HA pair upgrade completed successfully"
            
        except Exception as e:
            msg = f"HA pair upgrade error: {str(e)}"
            self.logger.error(msg, exc_info=True)
            return False, msg
    
    def _execute_upgrade_path(
        self,
        device_status: DeviceStatus,
        job_id: str,
        dry_run: bool
    ) -> bool:
        """
        Execute upgrade through version path.
        
        Args:
            device_status: Device status object
            job_id: Job identifier
            dry_run: Whether this is a dry run
            
        Returns:
            True if successful
        """
        serial = device_status.serial
        
        for idx, target_version in enumerate(device_status.upgrade_path):
            # Check for cancellation
            if self._is_cancelled(job_id, serial):
                self.logger.info(f"Upgrade cancelled for {serial}")
                device_status.upgrade_status = UpgradeStatus.CANCELLED.value
                self._save_device_status(device_status)
                return False
            
            device_status.current_path_index = idx
            device_status.upgrade_message = f"Upgrading to version {target_version} (step {idx + 1} of {len(device_status.upgrade_path)})"
            self._save_device_status(device_status)
            
            self.logger.info(
                f"Upgrading {serial} to version {target_version} "
                f"({idx + 1}/{len(device_status.upgrade_path)})"
            )
            
            # Execute single version upgrade
            success = self._upgrade_to_version(device_status, target_version, job_id, dry_run)
            
            if not success:
                return False
        
        return True
    
    def _upgrade_to_version(
        self,
        device_status: DeviceStatus,
        target_version: str,
        job_id: str,
        dry_run: bool
    ) -> bool:
        """
        Upgrade device to a specific version.
        
        Args:
            device_status: Device status object
            target_version: Target version
            job_id: Job identifier
            dry_run: Whether this is a dry run
            
        Returns:
            True if successful
        """
        serial = device_status.serial
        
        try:
            # Phase 1: Pre-flight validation
            device_status.current_phase = UpgradePhase.PRE_FLIGHT.value
            device_status.upgrade_status = UpgradeStatus.VALIDATING.value
            device_status.progress = 10
            device_status.upgrade_message = f"Running pre-flight validation for version {target_version}"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would validate {serial}")
                device_status.upgrade_message = f"[DRY RUN] Would validate {serial} before upgrading to {target_version}"
                self._save_device_status(device_status)
            else:
                passed, metrics, error = self.validation.run_pre_flight_validation(serial)
                
                if not passed:
                    device_status.add_error(UpgradePhase.PRE_FLIGHT.value, error)
                    self._save_device_status(device_status)
                    return False
                
                # Store disk space info
                device_status.disk_space = DiskSpaceInfo(
                    available_gb=metrics.disk_available_gb,
                    required_gb=self.config.min_disk_gb,
                    check_passed=True
                )
            
            # Phase 2: Refresh software list (only once per device)
            if serial not in self._software_check_done:
                device_status.current_phase = UpgradePhase.DOWNLOAD.value
                device_status.upgrade_status = UpgradeStatus.DOWNLOADING.value
                device_status.progress = 25
                device_status.upgrade_message = "Refreshing available software versions..."
                self._save_device_status(device_status)
                
                if dry_run:
                    self.logger.info(f"[DRY RUN] Would refresh software version list on {serial}")
                else:
                    software_check_timeout = self.config.software_check_timeout
                    success = self.panorama.check_software_updates(serial, timeout=software_check_timeout)
                    if not success:
                        self.logger.warning(
                            f"Software check failed or timed out on {serial}, continuing anyway"
                        )
                
                self._software_check_done.add(serial)
            
            # Phase 3: Download (skip if already downloaded)
            device_status.current_phase = UpgradePhase.DOWNLOAD.value
            device_status.upgrade_status = UpgradeStatus.DOWNLOADING.value
            device_status.progress = 30
            device_status.upgrade_message = f"Checking if version {target_version} is already downloaded"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would download version {target_version} to {serial}")
                device_status.upgrade_message = f"[DRY RUN] Would download version {target_version}"
                self._save_device_status(device_status)
                time.sleep(2)  # Simulate download
            else:
                # Check if version is already downloaded
                already_downloaded = self._is_version_downloaded(serial, target_version)
                
                if already_downloaded:
                    self.logger.info(
                        f"Version {target_version} already downloaded on {serial}, skipping download"
                    )
                    device_status.upgrade_message = f"Version {target_version} already downloaded, skipping to install"
                    device_status.skipped_versions.append(target_version)
                    self._save_device_status(device_status)
                else:
                    device_status.upgrade_message = f"Downloading version {target_version}"
                    self._save_device_status(device_status)
                    
                    success = self.panorama.download_software(serial, target_version)
                    if not success:
                        error = f"Failed to initiate download of {target_version}"
                        device_status.add_error(UpgradePhase.DOWNLOAD.value, error)
                        self._save_device_status(device_status)
                        return False
                    
                    # Wait for download to complete
                    self._wait_for_download(serial, device_status)
                    device_status.downloaded_versions.append(target_version)
            
            # Phase 3: Install
            device_status.current_phase = UpgradePhase.INSTALL.value
            device_status.upgrade_status = UpgradeStatus.INSTALLING.value
            device_status.progress = 60
            device_status.upgrade_message = f"Installing version {target_version}"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would install version {target_version} on {serial}")
                device_status.upgrade_message = f"[DRY RUN] Would install version {target_version}"
                self._save_device_status(device_status)
                time.sleep(2)  # Simulate install
            else:
                success = self.panorama.install_software(serial, target_version)
                if not success:
                    error = f"Failed to initiate installation of {target_version}"
                    device_status.add_error(UpgradePhase.INSTALL.value, error)
                    self._save_device_status(device_status)
                    return False
                
                # Wait for installation
                time.sleep(60)  # Installation takes time
            
            # Phase 4: Reboot
            device_status.current_phase = UpgradePhase.REBOOT.value
            device_status.upgrade_status = UpgradeStatus.REBOOTING.value
            device_status.progress = 75
            device_status.upgrade_message = f"Rebooting device to activate version {target_version}"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would reboot {serial}")
                device_status.upgrade_message = f"[DRY RUN] Would reboot device"
                self._save_device_status(device_status)
                time.sleep(2)  # Simulate reboot
            else:
                success = self.panorama.reboot_device(serial)
                if not success:
                    error = "Failed to initiate reboot"
                    device_status.add_error(UpgradePhase.REBOOT.value, error)
                    self._save_device_status(device_status)
                    return False
                
                # Wait for device to come back
                self.logger.info(f"Waiting for {serial} to reboot and come back online...")
                device_status.upgrade_message = f"Waiting for device to come back online after reboot"
                self._save_device_status(device_status)
                
                ready = self.panorama.check_device_ready(serial, timeout=600)
                if not ready:
                    error = "Device did not come back online after reboot"
                    device_status.add_error(UpgradePhase.REBOOT.value, error)
                    self._save_device_status(device_status)
                    return False
                
                # Additional wait to ensure device is fully ready
                self.logger.info(f"Device {serial} is back online, waiting for stabilization...")
                device_status.upgrade_message = f"Device is back online, stabilizing..."
                self._save_device_status(device_status)
                time.sleep(10)  # Give device time to fully initialize
            
            # Phase 5: Post-flight validation
            device_status.current_phase = UpgradePhase.POST_FLIGHT.value
            device_status.progress = 90
            device_status.upgrade_message = f"Running post-flight validation for version {target_version}"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would validate {serial} post-upgrade")
                device_status.upgrade_message = f"[DRY RUN] Would validate post-upgrade"
                self._save_device_status(device_status)
            else:
                # Get pre-flight metrics
                pre_metrics = self.validation.get_latest_pre_flight_metrics(serial)
                if pre_metrics:
                    passed, result = self.validation.run_post_flight_validation(serial, pre_metrics)
                    
                    if not passed:
                        self.logger.warning(
                            f"Post-flight validation failed for {serial}, but continuing"
                        )
            
            # Update current version
            device_status.current_version = target_version
            device_status.progress = 100
            device_status.upgrade_message = f"Successfully upgraded to version {target_version}"
            self._save_device_status(device_status)
            
            return True
            
        except Exception as e:
            error = f"Upgrade to {target_version} failed: {str(e)}"
            self.logger.error(error, exc_info=True, extra={'serial': serial})
            device_status.add_error(device_status.current_phase, error, str(e))
            self._save_device_status(device_status)
            return False
    
    def _wait_for_download(self, serial: str, device_status: DeviceStatus):
        """Wait for software download to complete."""
        max_wait = 1800  # 30 minutes
        start_time = time.time()
        
        while time.time() - start_time < max_wait:
            try:
                status = self.panorama.check_download_status(serial)
                downloading = status.get('downloading', 'no')
                
                if downloading.lower() == 'no':
                    self.logger.info(f"Download completed for {serial}")
                    return
                
                # Update progress if available
                progress_str = status.get('progress', '0')
                try:
                    progress = int(progress_str.rstrip('%'))
                    device_status.progress = 30 + int(progress * 0.3)  # 30-60% range
                    self._save_device_status(device_status)
                except ValueError:
                    pass
                
                time.sleep(30)
            except Exception as e:
                self.logger.warning(f"Error checking download status: {e}")
                time.sleep(30)
        
        raise TimeoutError(f"Download did not complete within {max_wait} seconds")
    
    def _is_version_downloaded(self, serial: str, version: str) -> bool:
        """
        Check if a software version is already downloaded on the device.
        
        Args:
            serial: Device serial number
            version: Software version to check
            
        Returns:
            True if version is already downloaded
        """
        try:
            software_info = self.panorama.get_software_info(serial)
            
            for sw in software_info.get("versions", []):
                if sw.get("version") == version and sw.get("downloaded", "no").lower() == "yes":
                    return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Could not check if {version} is downloaded on {serial}: {e}")
            # If we can't check, assume not downloaded and proceed with download
            return False
    
    def _init_device_status(self, serial: str, job_id: str) -> DeviceStatus:
        """Initialize device status."""
        return DeviceStatus(
            serial=serial,
            hostname=serial,
            ha_role=HARole.STANDALONE.value,
            current_version="",
            upgrade_status=UpgradeStatus.PENDING.value
        )
    
    def _save_device_status(self, device_status: DeviceStatus):
        """Save device status to file."""
        status_file = self.config.get_path(constants.DIR_STATUS_DEVICES) / f"{device_status.serial}.json"
        atomic_write_json(status_file, device_status.to_dict())
    
    def cancel_upgrade(self, job_id: Optional[str] = None, device_serial: Optional[str] = None):
        """
        Mark upgrade for cancellation.
        
        Args:
            job_id: Job ID to cancel
            device_serial: Device serial to cancel
        """
        with self._cancel_lock:
            if job_id:
                self._cancelled_jobs.add(job_id)
                self.logger.info(f"Marked job {job_id} for cancellation")
            if device_serial:
                self._cancelled_devices.add(device_serial)
                self.logger.info(f"Marked device {device_serial} for cancellation")
    
    def _is_cancelled(self, job_id: str, device_serial: str) -> bool:
        """Check if upgrade is cancelled."""
        with self._cancel_lock:
            return job_id in self._cancelled_jobs or device_serial in self._cancelled_devices
    
    def download_only_device(
        self,
        serial: str,
        job_id: str,
        dry_run: bool = False
    ) -> Tuple[bool, str]:
        """
        Download software images only (no install/reboot).
        
        Args:
            serial: Device serial number
            job_id: Job identifier
            dry_run: Whether this is a dry run
            
        Returns:
            Tuple of (success, message)
        """
        self.logger.info(
            f"Starting download-only for device {serial} (job: {job_id}, dry_run: {dry_run})"
        )
        
        # Initialize device status
        device_status = self._init_device_status(serial, job_id)
        
        try:
            # Reload inventory to get latest data
            self.inventory.reload()
            
            # Get device info from inventory
            device_info = self.inventory.get_device(serial)
            if not device_info:
                msg = f"Device {serial} not found in inventory. Run 'panos-upgrade device discover' first"
                self.logger.error(msg)
                device_status.upgrade_status = UpgradeStatus.FAILED.value
                device_status.upgrade_message = msg
                device_status.add_error("init", msg)
                self._save_device_status(device_status)
                return False, msg
            
            device_status.hostname = device_info.get("hostname", serial)
            device_status.current_version = device_info.get("current_version", "")
            mgmt_ip = device_info.get("mgmt_ip", "")
            
            if not mgmt_ip:
                msg = f"No management IP for device {serial}"
                self.logger.error(msg)
                device_status.upgrade_status = UpgradeStatus.FAILED.value
                device_status.upgrade_message = msg
                device_status.add_error("init", msg)
                self._save_device_status(device_status)
                return False, msg
            
            # Check for upgrade path
            upgrade_path = self.get_upgrade_path(device_status.current_version)
            
            if upgrade_path is None:
                msg = f"No upgrade path found for version {device_status.current_version}"
                self.logger.warning(msg, extra={'serial': serial})
                device_status.upgrade_status = UpgradeStatus.SKIPPED.value
                device_status.skip_reason = msg
                device_status.upgrade_message = f"Skipped: No upgrade path for version {device_status.current_version}"
                self._save_device_status(device_status)
                return False, msg
            
            device_status.upgrade_path = upgrade_path
            device_status.target_version = upgrade_path[-1] if upgrade_path else ""
            device_status.upgrade_message = f"Preparing to download {len(upgrade_path)} version(s)"
            self._save_device_status(device_status)
            
            # Create direct firewall client
            firewall_client = None
            existing_versions = {}
            
            if not dry_run:
                firewall_client = DirectFirewallClient(
                    mgmt_ip=mgmt_ip,
                    username=self.config.firewall_username,
                    password=self.config.firewall_password,
                    rate_limiter=None  # No rate limiting for direct connections
                )
            
            # Pre-flight: Check disk space only
            device_status.current_phase = "pre_flight_disk_check"
            device_status.upgrade_status = UpgradeStatus.VALIDATING.value
            device_status.progress = 5
            device_status.upgrade_message = "Checking available disk space"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would check disk space on {serial}")
                device_status.upgrade_message = "[DRY RUN] Would check disk space"
                self._save_device_status(device_status)
            else:
                disk_space_gb = firewall_client.check_disk_space()
                min_disk_gb = self.config.min_disk_gb
                
                # Store disk space info in device status
                device_status.disk_space = DiskSpaceInfo(
                    available_gb=disk_space_gb,
                    required_gb=min_disk_gb,
                    check_passed=disk_space_gb >= min_disk_gb
                )
                
                if disk_space_gb < min_disk_gb:
                    msg = f"Insufficient disk space: {disk_space_gb:.2f} GB available, {min_disk_gb:.2f} GB required"
                    self.logger.error(msg, extra={'serial': serial})
                    device_status.upgrade_status = UpgradeStatus.FAILED.value
                    device_status.upgrade_message = msg
                    device_status.add_error("pre_flight", msg)
                    self._save_device_status(device_status)
                    return False, msg
                
                self.logger.info(
                    f"Disk space check passed: {disk_space_gb:.2f} GB available"
                )
            
            # Refresh available software versions from Palo Alto servers
            device_status.upgrade_message = "Refreshing available software versions..."
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would refresh software version list on {serial}")
            else:
                software_check_timeout = self.config.software_check_timeout
                success = firewall_client.check_software_updates(timeout=software_check_timeout)
                if not success:
                    self.logger.warning(
                        f"Software check failed or timed out on {serial}, continuing anyway"
                    )
            
            # Check for already-downloaded versions
            device_status.upgrade_message = "Checking existing software on device"
            self._save_device_status(device_status)
            
            if not dry_run:
                software_info_timeout = self.config.software_info_timeout
                existing_versions = firewall_client.get_downloaded_versions(timeout=software_info_timeout)
                
                # Log what we found
                already_downloaded = [v for v in upgrade_path if existing_versions.get(v, {}).get("downloaded", False)]
                if already_downloaded:
                    self.logger.info(
                        f"Found {len(already_downloaded)} version(s) already downloaded on {serial}: {', '.join(already_downloaded)}"
                    )
            
            # Download each version in path (skip if already present)
            for idx, version in enumerate(upgrade_path):
                # Check for cancellation
                if self._is_cancelled(job_id, serial):
                    self.logger.info(f"Download cancelled for {serial}")
                    device_status.upgrade_status = UpgradeStatus.CANCELLED.value
                    device_status.upgrade_message = "Download cancelled by admin"
                    self._save_device_status(device_status)
                    return False, "Cancelled"
                
                device_status.current_path_index = idx
                device_status.current_phase = "download"
                device_status.upgrade_status = UpgradeStatus.DOWNLOADING.value
                progress_base = 10 + (idx * 80 // len(upgrade_path))
                device_status.progress = progress_base
                
                # Check if version is already downloaded
                version_info = existing_versions.get(version, {})
                already_downloaded = version_info.get("downloaded", False)
                
                if already_downloaded and not dry_run:
                    # Version already present - skip download
                    self.logger.info(
                        f"Version {version} already downloaded on {serial}, skipping"
                    )
                    device_status.upgrade_message = f"Version {version} already downloaded, skipping ({idx + 1}/{len(upgrade_path)})"
                    device_status.skipped_versions.append(version)
                    self._save_device_status(device_status)
                    continue
                
                device_status.upgrade_message = f"Downloading version {version} ({idx + 1}/{len(upgrade_path)})"
                self._save_device_status(device_status)
                
                if dry_run:
                    self.logger.info(f"[DRY RUN] Would download {version} to {serial}")
                    device_status.upgrade_message = f"[DRY RUN] Would download {version}"
                    self._save_device_status(device_status)
                    time.sleep(1)
                else:
                    # Initiate download - returns job ID
                    job_id_download = firewall_client.download_software(version)
                    if not job_id_download:
                        msg = f"Failed to initiate download of {version}"
                        device_status.add_error("download", msg)
                        device_status.upgrade_status = UpgradeStatus.FAILED.value
                        device_status.upgrade_message = msg
                        self._save_device_status(device_status)
                        return False, msg
                    
                    # Wait for download job to complete with progress updates
                    device_status.upgrade_message = f"Downloading {version} (job {job_id_download})..."
                    self._save_device_status(device_status)
                    
                    # Progress callback to update device status
                    def update_progress(download_progress: int):
                        # Map download progress (0-100) to overall progress range for this version
                        # Each version gets an equal slice of the 10-90 range
                        version_slice = 80 // len(upgrade_path)
                        base_progress = 10 + (idx * version_slice)
                        device_status.progress = base_progress + int(download_progress * version_slice / 100)
                        device_status.upgrade_message = f"Downloading {version}: {download_progress}%"
                        self._save_device_status(device_status)
                    
                    success = firewall_client.wait_for_download(
                        job_id_download,
                        version,
                        timeout=1800,
                        progress_callback=update_progress
                    )
                    if not success:
                        msg = f"Download of {version} failed or did not complete"
                        device_status.add_error("download", msg)
                        device_status.upgrade_status = UpgradeStatus.FAILED.value
                        device_status.upgrade_message = msg
                        self._save_device_status(device_status)
                        return False, msg
                    
                    # Mark as downloaded
                    device_status.downloaded_versions.append(version)
                    device_status.upgrade_message = f"Downloaded {version}"
                    self._save_device_status(device_status)
            
            # All downloads complete
            device_status.upgrade_status = constants.STATUS_DOWNLOAD_COMPLETE
            device_status.progress = 100
            device_status.ready_for_install = True
            
            # Build summary message
            downloaded_count = len(device_status.downloaded_versions)
            skipped_count = len(device_status.skipped_versions)
            
            if downloaded_count > 0 and skipped_count > 0:
                downloaded_str = ", ".join(device_status.downloaded_versions)
                skipped_str = ", ".join(device_status.skipped_versions)
                device_status.upgrade_message = (
                    f"Downloaded {downloaded_count} version(s): {downloaded_str}. "
                    f"Skipped {skipped_count} (already present): {skipped_str}"
                )
                msg = f"Download complete for {serial}: {downloaded_count} downloaded, {skipped_count} skipped (already present)"
            elif downloaded_count > 0:
                versions_str = ", ".join(device_status.downloaded_versions)
                device_status.upgrade_message = f"Downloaded {downloaded_count} version(s): {versions_str}"
                msg = f"Download complete for {serial}: {versions_str}"
            else:
                # All versions were already present
                skipped_str = ", ".join(device_status.skipped_versions)
                device_status.upgrade_message = f"All {skipped_count} version(s) already downloaded: {skipped_str}"
                msg = f"Download complete for {serial}: all versions already present"
            
            self._save_device_status(device_status)
            self.logger.info(msg, extra={'serial': serial})
            return True, msg
            
        except Exception as e:
            msg = f"Download error for {serial}: {str(e)}"
            self.logger.error(msg, exc_info=True, extra={'serial': serial})
            device_status.upgrade_status = UpgradeStatus.FAILED.value
            device_status.upgrade_message = f"Download failed: {str(e)}"
            device_status.add_error("download", msg, str(e))
            self._save_device_status(device_status)
            return False, msg
