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
from panos_upgrade.direct_firewall_client import DirectFirewallClient, JobResult
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
    
    def _get_mgmt_ip_from_inventory(self, serial: str) -> Optional[str]:
        """
        Get management IP for a device from inventory.
        
        Args:
            serial: Device serial number
            
        Returns:
            Management IP address or None if not found
        """
        self.inventory.reload()
        device_info = self.inventory.get_device(serial)
        if device_info:
            return device_info.get("mgmt_ip", "")
        return None
    
    def _create_firewall_client(self, mgmt_ip: str) -> DirectFirewallClient:
        """
        Create a new DirectFirewallClient for the given management IP.
        
        Args:
            mgmt_ip: Firewall management IP address
            
        Returns:
            DirectFirewallClient instance
        """
        return DirectFirewallClient(
            mgmt_ip=mgmt_ip,
            username=self.config.firewall_username,
            password=self.config.firewall_password,
            rate_limiter=None
        )
    
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
        
        # Check for existing in-progress upgrade (daemon restart recovery)
        existing_status = self._load_existing_device_status(serial)
        
        if existing_status and existing_status.starting_version:
            # Resume from existing status
            device_status = existing_status
            self.logger.info(
                f"Resuming upgrade for {serial} from starting_version {device_status.starting_version}"
            )
        else:
            # Initialize new device status
            device_status = self._init_device_status(serial, job_id)
        
        try:
            # Get management IP from inventory
            mgmt_ip = self._get_mgmt_ip_from_inventory(serial)
            if not mgmt_ip:
                msg = f"Device {serial} not found in inventory or has no management IP. Run 'panos-upgrade device discover' first"
                self.logger.error(msg)
                device_status.upgrade_status = UpgradeStatus.FAILED.value
                device_status.upgrade_message = msg
                device_status.add_error("init", msg)
                self._save_device_status(device_status)
                return False, msg
            
            # Create direct firewall client
            firewall_client = self._create_firewall_client(mgmt_ip)
            
            # Get device info via direct connection
            device_info = firewall_client.get_system_info()
            device_status.hostname = device_info.get('hostname', serial)
            live_version = device_info.get('sw_version', '')
            device_status.current_version = live_version
            device_status.ha_role = HARole.STANDALONE.value
            
            # Determine which version to use for upgrade path lookup
            # If resuming, use starting_version; otherwise use current live version
            if device_status.starting_version:
                version_for_path_lookup = device_status.starting_version
                self.logger.info(
                    f"Using starting_version {version_for_path_lookup} for path lookup "
                    f"(device is currently at {live_version})"
                )
            else:
                version_for_path_lookup = live_version
                device_status.starting_version = live_version  # Store for future recovery
            
            # Check for upgrade path using the appropriate version
            upgrade_path = self.get_upgrade_path(version_for_path_lookup)
            
            if upgrade_path is None:
                msg = f"No upgrade path found for version {version_for_path_lookup}"
                self.logger.warning(msg, extra={'serial': serial})
                device_status.upgrade_status = UpgradeStatus.SKIPPED.value
                device_status.skip_reason = msg
                device_status.upgrade_message = f"Skipped: No upgrade path for version {version_for_path_lookup}"
                self._save_device_status(device_status)
                return False, msg
            
            device_status.upgrade_path = upgrade_path
            device_status.target_version = upgrade_path[-1] if upgrade_path else ""
            
            # Calculate current_path_index based on where we are in the path
            # If device is already at a version in the path, skip to that point
            if live_version in upgrade_path:
                device_status.current_path_index = upgrade_path.index(live_version) + 1
                self.logger.info(
                    f"Device {serial} is at {live_version}, resuming from path index {device_status.current_path_index}"
                )
            elif live_version == device_status.target_version:
                # Already at target version
                device_status.upgrade_status = UpgradeStatus.COMPLETE.value
                device_status.upgrade_message = f"Device already at target version {live_version}"
                self._save_device_status(device_status)
                return True, device_status.upgrade_message
            
            self._save_device_status(device_status)
            
            # Execute upgrade through path (pass mgmt_ip for direct connections)
            success = self._execute_upgrade_path(device_status, job_id, dry_run, mgmt_ip)
            
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
        
        This method determines the target version first by checking upgrade paths
        for both members. If a member is already at the target version, it is
        skipped (treated as success) and the other member is upgraded.
        
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
            # Get management IPs from inventory
            primary_mgmt_ip = self._get_mgmt_ip_from_inventory(primary_serial)
            secondary_mgmt_ip = self._get_mgmt_ip_from_inventory(secondary_serial)
            
            if not primary_mgmt_ip:
                msg = f"Device {primary_serial} not found in inventory or has no management IP"
                self.logger.error(msg)
                return False, msg
            
            if not secondary_mgmt_ip:
                msg = f"Device {secondary_serial} not found in inventory or has no management IP"
                self.logger.error(msg)
                return False, msg
            
            # Connect to both firewalls and get system info
            primary_client = self._create_firewall_client(primary_mgmt_ip)
            secondary_client = self._create_firewall_client(secondary_mgmt_ip)
            
            primary_info = primary_client.get_system_info()
            secondary_info = secondary_client.get_system_info()
            
            primary_version = primary_info.get('sw_version', '')
            secondary_version = secondary_info.get('sw_version', '')
            
            self.logger.info(
                f"HA pair versions - {primary_serial}: {primary_version}, "
                f"{secondary_serial}: {secondary_version}"
            )
            
            # Determine the target version by checking upgrade paths for both members
            primary_path = self.get_upgrade_path(primary_version)
            secondary_path = self.get_upgrade_path(secondary_version)
            
            target_version = None
            if primary_path:
                target_version = primary_path[-1]
            elif secondary_path:
                target_version = secondary_path[-1]
            else:
                # Neither has an upgrade path - check if they're at the same version
                if primary_version == secondary_version:
                    msg = f"Both HA members already at version {primary_version}, no upgrade path defined"
                    self.logger.info(msg)
                    return True, msg
                else:
                    msg = (
                        f"No upgrade path found for either HA member: "
                        f"{primary_serial} at {primary_version}, {secondary_serial} at {secondary_version}"
                    )
                    self.logger.error(msg)
                    return False, msg
            
            self.logger.info(f"HA pair target version: {target_version}")
            
            # Determine HA state to know upgrade order
            ha_state_primary = primary_client.get_ha_state()
            ha_state_secondary = secondary_client.get_ha_state()
            
            primary_state = ha_state_primary.get('local_state', 'unknown')
            secondary_state = ha_state_secondary.get('local_state', 'unknown')
            
            # Determine upgrade order (passive first)
            if 'passive' in primary_state.lower():
                passive_serial, active_serial = primary_serial, secondary_serial
                passive_version, active_version = primary_version, secondary_version
            elif 'passive' in secondary_state.lower():
                passive_serial, active_serial = secondary_serial, primary_serial
                passive_version, active_version = secondary_version, primary_version
            else:
                msg = f"Could not determine passive member for HA pair"
                self.logger.error(msg)
                return False, msg
            
            # Upgrade passive member (or skip if already at target)
            if passive_version == target_version:
                self.logger.info(
                    f"Passive member {passive_serial} already at target version {target_version}, skipping"
                )
            else:
                self.logger.info(f"Upgrading passive member first: {passive_serial}")
                success, msg = self.upgrade_device(passive_serial, job_id, dry_run)
                if not success:
                    return False, f"Failed to upgrade passive member: {msg}"
            
            # Check for cancellation
            if self._is_cancelled(job_id, passive_serial):
                return False, "Upgrade cancelled"
            
            # Upgrade active member (or skip if already at target)
            if active_version == target_version:
                self.logger.info(
                    f"Active member {active_serial} already at target version {target_version}, skipping"
                )
            else:
                self.logger.info(f"Upgrading active member: {active_serial}")
                success, msg = self.upgrade_device(active_serial, job_id, dry_run)
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
        dry_run: bool,
        mgmt_ip: str
    ) -> bool:
        """
        Execute upgrade through version path.
        
        New flow (for multi-step upgrades):
        1. Download ALL images in the upgrade path
        2. Verify ALL images are downloaded (hard requirement)
        3. Install ONLY the final version (PAN-OS handles intermediate steps)
        4. Reboot and wait
        5. Post-flight validation
        
        Args:
            device_status: Device status object
            job_id: Job identifier
            dry_run: Whether this is a dry run
            mgmt_ip: Management IP for direct firewall connection
            
        Returns:
            True if successful
        """
        serial = device_status.serial
        upgrade_path = device_status.upgrade_path
        final_version = upgrade_path[-1] if upgrade_path else ""
        
        # Create direct firewall client for this operation
        firewall_client = self._create_firewall_client(mgmt_ip)
        
        try:
            # Phase 1: Pre-flight validation
            device_status.current_phase = UpgradePhase.PRE_FLIGHT.value
            device_status.upgrade_status = UpgradeStatus.VALIDATING.value
            device_status.progress = 5
            device_status.upgrade_message = "Running pre-flight validation"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would validate {serial}")
            else:
                passed, metrics, error = self.validation.run_pre_flight_validation_direct(
                    serial, firewall_client
                )
                
                if not passed:
                    device_status.add_error(UpgradePhase.PRE_FLIGHT.value, error)
                    self._save_device_status(device_status)
                    return False
                
                device_status.disk_space = DiskSpaceInfo(
                    available_gb=metrics.disk_available_gb,
                    required_gb=self.config.min_disk_gb,
                    check_passed=True
                )
            
            # Phase 2: Refresh software list (only once per device)
            if serial not in self._software_check_done:
                device_status.progress = 10
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
                
                self._software_check_done.add(serial)
            
            # Phase 3: Download ALL images in the upgrade path
            device_status.current_phase = UpgradePhase.DOWNLOAD.value
            device_status.upgrade_status = UpgradeStatus.DOWNLOADING.value
            device_status.progress = 15
            device_status.upgrade_message = f"Preparing to download {len(upgrade_path)} image(s)"
            self._save_device_status(device_status)
            
            success = self._download_all_images(
                device_status, firewall_client, job_id, dry_run
            )
            if not success:
                return False
            
            # Phase 4: Verify ALL images are downloaded (hard requirement)
            device_status.progress = 55
            device_status.upgrade_message = "Verifying all images are downloaded..."
            self._save_device_status(device_status)
            
            if not dry_run:
                missing_images = self._verify_all_images_downloaded(
                    firewall_client, upgrade_path
                )
                if missing_images:
                    error = f"Verification failed: missing images: {', '.join(missing_images)}"
                    self.logger.error(error, extra={'serial': serial})
                    device_status.upgrade_status = UpgradeStatus.FAILED.value
                    device_status.upgrade_message = error
                    device_status.add_error(UpgradePhase.DOWNLOAD.value, error)
                    self._save_device_status(device_status)
                    return False
                
                self.logger.info(f"All {len(upgrade_path)} images verified on {serial}")
            
            # Phase 5: Install ONLY the final version
            device_status.current_phase = UpgradePhase.INSTALL.value
            device_status.upgrade_status = UpgradeStatus.INSTALLING.value
            device_status.progress = 60
            device_status.upgrade_message = f"Installing final version {final_version}"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would install version {final_version} on {serial}")
                time.sleep(2)
            else:
                job_id_install = firewall_client.install_software(final_version)
                if not job_id_install:
                    error = f"Failed to initiate installation of {final_version}"
                    device_status.add_error(UpgradePhase.INSTALL.value, error)
                    self._save_device_status(device_status)
                    return False
                
                device_status.upgrade_message = f"Installing {final_version} (job {job_id_install})..."
                self._save_device_status(device_status)
                
                def update_install_progress(progress: int):
                    device_status.progress = 60 + int(progress * 0.15)  # 60-75% range
                    device_status.upgrade_message = f"Installing {final_version}: {progress}%"
                    self._save_device_status(device_status)
                
                result = firewall_client.wait_for_install(
                    job_id_install, final_version,
                    stall_timeout=self.config.job_stall_timeout,
                    progress_callback=update_install_progress
                )
                if not result.success:
                    if result.stalled:
                        error = f"Installation of {final_version} stalled: {result.details}"
                        device_status.upgrade_message = f"Job stalled: Installation of {final_version}"
                    else:
                        error = f"Installation of {final_version} failed: {result.details}"
                        device_status.upgrade_message = f"Install failed: {result.details}"
                    device_status.add_error(UpgradePhase.INSTALL.value, error)
                    self._save_device_status(device_status)
                    return False
            
            # Phase 6: Reboot
            device_status.current_phase = UpgradePhase.REBOOT.value
            device_status.upgrade_status = UpgradeStatus.REBOOTING.value
            device_status.progress = 75
            device_status.upgrade_message = f"Rebooting device to activate version {final_version}"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would reboot {serial}")
                time.sleep(2)
            else:
                success = firewall_client.reboot_device()
                if not success:
                    error = "Failed to initiate reboot"
                    device_status.add_error(UpgradePhase.REBOOT.value, error)
                    self._save_device_status(device_status)
                    return False
                
                # Wait for device to shut down before polling for readiness
                initial_delay = self.config.reboot_initial_delay
                self.logger.info(
                    f"Reboot initiated for {serial}, waiting {initial_delay} seconds for device to shut down..."
                )
                device_status.upgrade_message = f"Reboot initiated, waiting {initial_delay}s for shutdown..."
                self._save_device_status(device_status)
                time.sleep(initial_delay)
                
                self.logger.info(f"Polling for {serial} to come back online...")
                device_status.upgrade_message = "Waiting for device to come back online after reboot"
                self._save_device_status(device_status)
                
                reboot_client = self._create_firewall_client(mgmt_ip)
                max_poll_interval = self.config.max_reboot_poll_interval
                reboot_timeout = self.config.reboot_ready_timeout
                ready = reboot_client.check_device_ready(timeout=reboot_timeout, max_poll_interval=max_poll_interval)
                if not ready:
                    error = "Device did not come back online after reboot"
                    device_status.add_error(UpgradePhase.REBOOT.value, error)
                    self._save_device_status(device_status)
                    return False
                
                stabilization_delay = self.config.reboot_stabilization_delay
                self.logger.info(
                    f"Device {serial} is back online, waiting {stabilization_delay} seconds for stabilization..."
                )
                device_status.upgrade_message = f"Device is back online, stabilizing ({stabilization_delay}s)..."
                self._save_device_status(device_status)
                time.sleep(stabilization_delay)
                
                firewall_client = reboot_client
            
            # Phase 7: Post-flight validation
            device_status.current_phase = UpgradePhase.POST_FLIGHT.value
            device_status.progress = 90
            device_status.upgrade_message = f"Running post-flight validation for version {final_version}"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would validate {serial} post-upgrade")
            else:
                pre_metrics = self.validation.get_latest_pre_flight_metrics(serial)
                if pre_metrics:
                    passed, result = self.validation.run_post_flight_validation_direct(
                        serial, firewall_client, pre_metrics
                    )
                    if not passed:
                        self.logger.warning(
                            f"Post-flight validation failed for {serial}, but continuing"
                        )
            
            # Update current version
            device_status.current_version = final_version
            device_status.progress = 100
            device_status.upgrade_message = f"Successfully upgraded to version {final_version}"
            self._save_device_status(device_status)
            
            return True
            
        except Exception as e:
            error = f"Upgrade failed: {str(e)}"
            self.logger.error(error, exc_info=True, extra={'serial': serial})
            device_status.add_error(device_status.current_phase, error, str(e))
            self._save_device_status(device_status)
            return False
    
    def _download_all_images(
        self,
        device_status: DeviceStatus,
        firewall_client: DirectFirewallClient,
        job_id: str,
        dry_run: bool
    ) -> bool:
        """
        Download all images in the upgrade path.
        
        Args:
            device_status: Device status object
            firewall_client: Direct firewall client
            job_id: Job identifier
            dry_run: Whether this is a dry run
            
        Returns:
            True if all downloads successful
        """
        serial = device_status.serial
        upgrade_path = device_status.upgrade_path
        total_images = len(upgrade_path)
        retry_attempts = self.config.download_retry_attempts
        
        for idx, target_version in enumerate(upgrade_path):
            # Check for cancellation
            if self._is_cancelled(job_id, serial):
                self.logger.info(f"Upgrade cancelled for {serial}")
                device_status.upgrade_status = UpgradeStatus.CANCELLED.value
                device_status.upgrade_message = "Upgrade cancelled by admin"
                self._save_device_status(device_status)
                return False
            
            device_status.current_path_index = idx
            progress_base = 15 + (idx * 35 // max(total_images, 1))  # 15-50% range for downloads
            device_status.progress = progress_base
            device_status.upgrade_message = f"Processing image {idx + 1}/{total_images}: {target_version}"
            self._save_device_status(device_status)
            
            if dry_run:
                self.logger.info(f"[DRY RUN] Would download version {target_version} to {serial}")
                device_status.upgrade_message = f"[DRY RUN] Would download version {target_version}"
                self._save_device_status(device_status)
                time.sleep(1)
                continue
            
            # Check if version is already downloaded
            software_info = firewall_client.get_software_info(
                timeout=self.config.software_info_timeout
            )
            already_downloaded = False
            for sw in software_info.get("versions", []):
                if sw.get("version") == target_version and sw.get("downloaded", "no").lower() == "yes":
                    already_downloaded = True
                    break
            
            if already_downloaded:
                self.logger.info(
                    f"Version {target_version} already downloaded on {serial}, skipping download"
                )
                device_status.upgrade_message = f"Version {target_version} already downloaded"
                device_status.skipped_versions.append(target_version)
                self._save_device_status(device_status)
                continue
            
            # Check disk space before download
            disk_space_gb = firewall_client.check_disk_space()
            min_disk_gb = self.config.min_disk_gb
            
            device_status.disk_space = DiskSpaceInfo(
                available_gb=disk_space_gb,
                required_gb=min_disk_gb,
                check_passed=disk_space_gb >= min_disk_gb
            )
            
            if disk_space_gb < min_disk_gb:
                error = f"Insufficient disk space before downloading {target_version}: {disk_space_gb:.2f} GB available, {min_disk_gb:.2f} GB required"
                self.logger.error(error, extra={'serial': serial})
                device_status.upgrade_status = UpgradeStatus.FAILED.value
                device_status.upgrade_message = error
                device_status.add_error(UpgradePhase.DOWNLOAD.value, error)
                self._save_device_status(device_status)
                return False
            
            # Download with retry logic
            download_success = False
            last_error = ""
            
            for attempt in range(1, retry_attempts + 1):
                if attempt > 1:
                    self.logger.info(f"Retry attempt {attempt}/{retry_attempts} for {target_version} on {serial}")
                    device_status.upgrade_message = f"Retry {attempt}/{retry_attempts}: Downloading {target_version}"
                    self._save_device_status(device_status)
                
                device_status.upgrade_message = f"Downloading {target_version} ({idx + 1}/{total_images})"
                self._save_device_status(device_status)
                
                job_id_download = firewall_client.download_software(target_version)
                if not job_id_download:
                    last_error = f"Failed to initiate download of {target_version}"
                    self.logger.warning(f"{last_error} (attempt {attempt}/{retry_attempts})")
                    continue
                
                device_status.upgrade_message = f"Downloading {target_version} (job {job_id_download})..."
                self._save_device_status(device_status)
                
                def update_download_progress(progress: int):
                    version_slice = 35 // max(total_images, 1)
                    base_progress = 15 + (idx * version_slice)
                    device_status.progress = base_progress + int(progress * version_slice / 100)
                    device_status.upgrade_message = f"Downloading {target_version}: {progress}%"
                    self._save_device_status(device_status)
                
                result = firewall_client.wait_for_download(
                    job_id_download, target_version,
                    stall_timeout=self.config.job_stall_timeout,
                    progress_callback=update_download_progress
                )
                
                if result.success:
                    download_success = True
                    device_status.downloaded_versions.append(target_version)
                    self.logger.info(f"Successfully downloaded {target_version} on {serial}")
                    break
                else:
                    if result.stalled:
                        last_error = f"Download of {target_version} stalled: {result.details}"
                    else:
                        last_error = f"Download of {target_version} failed: {result.details}"
                    self.logger.warning(f"{last_error} (attempt {attempt}/{retry_attempts})")
            
            if not download_success:
                error = f"{last_error} after {retry_attempts} attempts"
                device_status.upgrade_status = UpgradeStatus.FAILED.value
                device_status.upgrade_message = error
                device_status.add_error(UpgradePhase.DOWNLOAD.value, error)
                self._save_device_status(device_status)
                return False
        
        self.logger.info(f"All {total_images} images downloaded/verified on {serial}")
        return True
    
    def _verify_all_images_downloaded(
        self,
        firewall_client: DirectFirewallClient,
        upgrade_path: List[str]
    ) -> List[str]:
        """
        Verify all images in the upgrade path are downloaded on the device.
        
        Args:
            firewall_client: Direct firewall client
            upgrade_path: List of versions that should be downloaded
            
        Returns:
            List of missing image versions (empty if all present)
        """
        software_info = firewall_client.get_software_info(
            timeout=self.config.software_info_timeout
        )
        
        downloaded_versions = set()
        for sw in software_info.get("versions", []):
            if sw.get("downloaded", "no").lower() == "yes":
                downloaded_versions.add(sw.get("version", ""))
        
        missing = []
        for version in upgrade_path:
            if version not in downloaded_versions:
                missing.append(version)
        
        return missing
    
    
    
    def _init_device_status(self, serial: str, job_id: str) -> DeviceStatus:
        """Initialize device status."""
        return DeviceStatus(
            serial=serial,
            hostname=serial,
            ha_role=HARole.STANDALONE.value,
            current_version="",
            upgrade_status=UpgradeStatus.PENDING.value
        )
    
    def _load_existing_device_status(self, serial: str) -> Optional[DeviceStatus]:
        """
        Load existing device status from file if it exists and is in-progress.
        
        Args:
            serial: Device serial number
            
        Returns:
            DeviceStatus if an in-progress status exists, None otherwise
        """
        status_file = self.config.get_path(constants.DIR_STATUS_DEVICES) / f"{serial}.json"
        
        if not status_file.exists():
            return None
        
        try:
            data = safe_read_json(status_file)
            if not data:
                return None
            
            # Check if this is an in-progress upgrade that we should resume
            status = data.get("upgrade_status", "")
            in_progress_statuses = [
                UpgradeStatus.PENDING.value,
                UpgradeStatus.VALIDATING.value,
                UpgradeStatus.DOWNLOADING.value,
                UpgradeStatus.INSTALLING.value,
                UpgradeStatus.REBOOTING.value
            ]
            
            if status not in in_progress_statuses:
                return None
            
            # Check if we have a starting_version to resume from
            starting_version = data.get("starting_version", "")
            if not starting_version:
                return None
            
            self.logger.info(
                f"Found existing in-progress upgrade for {serial} "
                f"(starting_version: {starting_version}, status: {status})"
            )
            
            # Reconstruct DeviceStatus from saved data
            device_status = DeviceStatus(
                serial=data.get("serial", serial),
                hostname=data.get("hostname", serial),
                ha_role=data.get("ha_role", HARole.STANDALONE.value),
                current_version=data.get("current_version", ""),
                starting_version=starting_version,
                target_version=data.get("target_version", ""),
                upgrade_path=data.get("upgrade_path", []),
                current_path_index=data.get("current_path_index", 0),
                upgrade_status=status,
                progress=data.get("progress", 0),
                current_phase=data.get("current_phase", ""),
                upgrade_message=data.get("upgrade_message", ""),
                downloaded_versions=data.get("downloaded_versions", []),
                skipped_versions=data.get("skipped_versions", []),
                ready_for_install=data.get("ready_for_install", False),
                skip_reason=data.get("skip_reason", "")
            )
            
            return device_status
            
        except Exception as e:
            self.logger.warning(f"Failed to load existing device status for {serial}: {e}")
            return None
    
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
        
        # Check for existing in-progress download (daemon restart recovery)
        existing_status = self._load_existing_device_status(serial)
        
        if existing_status and existing_status.starting_version:
            # Resume from existing status
            device_status = existing_status
            self.logger.info(
                f"Resuming download for {serial} from starting_version {device_status.starting_version}"
            )
        else:
            # Initialize new device status
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
            inventory_version = device_info.get("current_version", "")
            mgmt_ip = device_info.get("mgmt_ip", "")
            
            if not mgmt_ip:
                msg = f"No management IP for device {serial}"
                self.logger.error(msg)
                device_status.upgrade_status = UpgradeStatus.FAILED.value
                device_status.upgrade_message = msg
                device_status.add_error("init", msg)
                self._save_device_status(device_status)
                return False, msg
            
            # Determine which version to use for upgrade path lookup
            # If resuming, use starting_version; otherwise use inventory version
            if device_status.starting_version:
                version_for_path_lookup = device_status.starting_version
                self.logger.info(
                    f"Using starting_version {version_for_path_lookup} for path lookup"
                )
            else:
                version_for_path_lookup = inventory_version
                device_status.starting_version = inventory_version  # Store for future recovery
                device_status.current_version = inventory_version
            
            # Check for upgrade path using the appropriate version
            upgrade_path = self.get_upgrade_path(version_for_path_lookup)
            
            if upgrade_path is None:
                msg = f"No upgrade path found for version {version_for_path_lookup}"
                self.logger.warning(msg, extra={'serial': serial})
                device_status.upgrade_status = UpgradeStatus.SKIPPED.value
                device_status.skip_reason = msg
                device_status.upgrade_message = f"Skipped: No upgrade path for version {version_for_path_lookup}"
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
            
            # Step 1: Refresh available software versions from Palo Alto servers
            device_status.current_phase = "software_check"
            device_status.upgrade_status = UpgradeStatus.VALIDATING.value
            device_status.progress = 5
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
            
            # Step 2: Check for already-downloaded versions
            device_status.upgrade_message = "Checking existing software on device"
            self._save_device_status(device_status)
            
            versions_to_download = []
            if dry_run:
                self.logger.info(f"[DRY RUN] Would check existing software on {serial}")
                versions_to_download = upgrade_path  # Assume all need download in dry run
            else:
                software_info_timeout = self.config.software_info_timeout
                existing_versions = firewall_client.get_downloaded_versions(timeout=software_info_timeout)
                
                # Determine which versions need to be downloaded
                for version in upgrade_path:
                    if existing_versions.get(version, {}).get("downloaded", False):
                        self.logger.info(f"Version {version} already downloaded on {serial}")
                        device_status.skipped_versions.append(version)
                    else:
                        versions_to_download.append(version)
                
                if device_status.skipped_versions:
                    self.logger.info(
                        f"Found {len(device_status.skipped_versions)} version(s) already downloaded on {serial}: "
                        f"{', '.join(device_status.skipped_versions)}"
                    )
            
            # Step 3: If all versions already downloaded, skip disk space check
            if not versions_to_download and not dry_run:
                self.logger.info(f"All versions already downloaded on {serial}, skipping disk space check")
                device_status.upgrade_status = constants.STATUS_DOWNLOAD_COMPLETE
                device_status.progress = 100
                device_status.ready_for_install = True
                skipped_str = ", ".join(device_status.skipped_versions)
                device_status.upgrade_message = f"All {len(device_status.skipped_versions)} version(s) already downloaded: {skipped_str}"
                self._save_device_status(device_status)
                msg = f"Download complete for {serial}: all versions already present"
                self.logger.info(msg, extra={'serial': serial})
                return True, msg
            
            # Step 4: Check disk space (only if we need to download something)
            device_status.current_phase = "pre_flight_disk_check"
            device_status.progress = 8
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
            
            # Download each version that needs downloading
            total_to_download = len(versions_to_download)
            for idx, version in enumerate(versions_to_download):
                # Check for cancellation
                if self._is_cancelled(job_id, serial):
                    self.logger.info(f"Download cancelled for {serial}")
                    device_status.upgrade_status = UpgradeStatus.CANCELLED.value
                    device_status.upgrade_message = "Download cancelled by admin"
                    self._save_device_status(device_status)
                    return False, "Cancelled"
                
                device_status.current_path_index = upgrade_path.index(version)
                device_status.current_phase = "download"
                device_status.upgrade_status = UpgradeStatus.DOWNLOADING.value
                progress_base = 10 + (idx * 80 // max(total_to_download, 1))
                device_status.progress = progress_base
                
                device_status.upgrade_message = f"Downloading version {version} ({idx + 1}/{total_to_download})"
                self._save_device_status(device_status)
                
                if dry_run:
                    self.logger.info(f"[DRY RUN] Would download {version} to {serial}")
                    device_status.upgrade_message = f"[DRY RUN] Would download {version}"
                    self._save_device_status(device_status)
                    time.sleep(1)
                else:
                    # Check disk space before each download
                    device_status.upgrade_message = f"Checking disk space before downloading {version}..."
                    self._save_device_status(device_status)
                    
                    disk_space_gb = firewall_client.check_disk_space()
                    min_disk_gb = self.config.min_disk_gb
                    
                    device_status.disk_space = DiskSpaceInfo(
                        available_gb=disk_space_gb,
                        required_gb=min_disk_gb,
                        check_passed=disk_space_gb >= min_disk_gb
                    )
                    
                    if disk_space_gb < min_disk_gb:
                        msg = f"Insufficient disk space before downloading {version}: {disk_space_gb:.2f} GB available, {min_disk_gb:.2f} GB required"
                        self.logger.error(msg, extra={'serial': serial})
                        device_status.upgrade_status = UpgradeStatus.FAILED.value
                        device_status.upgrade_message = msg
                        device_status.add_error("download", msg)
                        self._save_device_status(device_status)
                        return False, msg
                    
                    self.logger.debug(f"Disk space check passed before {version}: {disk_space_gb:.2f} GB available")
                    
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
                        version_slice = 80 // max(total_to_download, 1)
                        base_progress = 10 + (idx * version_slice)
                        device_status.progress = base_progress + int(download_progress * version_slice / 100)
                        device_status.upgrade_message = f"Downloading {version}: {download_progress}%"
                        self._save_device_status(device_status)
                    
                    result = firewall_client.wait_for_download(
                        job_id_download,
                        version,
                        stall_timeout=self.config.job_stall_timeout,
                        progress_callback=update_progress
                    )
                    if not result.success:
                        if result.stalled:
                            msg = f"Download of {version} stalled: {result.details}"
                            device_status.upgrade_message = f"Job stalled: Download of {version}"
                        else:
                            msg = f"Download of {version} failed: {result.details}"
                            device_status.upgrade_message = f"Download failed: {result.details}"
                        device_status.add_error("download", msg)
                        device_status.upgrade_status = UpgradeStatus.FAILED.value
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
