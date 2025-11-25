"""Daemon service for managing upgrades."""

import os
import signal
import sys
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from panos_upgrade.config import Config, get_config
from panos_upgrade.logging_config import setup_logging, get_logger
from panos_upgrade.worker_pool import WorkerPool
from panos_upgrade.models import DaemonStatus, WorkerStatus, Job, CancelCommand
from panos_upgrade.utils.file_ops import atomic_write_json, read_json, safe_read_json
from panos_upgrade.panorama_client import PanoramaClient
from panos_upgrade.validation import ValidationSystem
from panos_upgrade.upgrade_manager import UpgradeManager
from panos_upgrade.device_inventory import DeviceInventory
from panos_upgrade.hash_manager import HashManager
from panos_upgrade import constants


class CommandQueueHandler(FileSystemEventHandler):
    """Handler for command queue directory monitoring."""
    
    def __init__(self, daemon: 'UpgradeDaemon'):
        """
        Initialize handler.
        
        Args:
            daemon: Reference to daemon instance
        """
        self.daemon = daemon
        self.logger = get_logger("panos_upgrade.command_queue")
    
    def on_created(self, event: FileSystemEvent):
        """Handle file creation in command queue."""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        if file_path.suffix == '.json' and not file_path.name.startswith('.'):
            self.logger.info(f"New command file detected: {file_path.name}")
            self.daemon.process_command(file_path)


class UpgradeDaemon:
    """Main daemon service for managing PAN-OS upgrades."""
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize daemon.
        
        Args:
            config: Configuration instance
        """
        self.config = config or get_config()
        self.logger = get_logger("panos_upgrade.daemon")
        
        # Initialize worker pool
        self.worker_pool = WorkerPool(
            num_workers=self.config.max_workers,
            max_queue_size=self.config.get("workers.queue_size", 1000)
        )
        
        # State tracking
        self._running = False
        self._stop_event = threading.Event()
        self._status_lock = threading.Lock()
        self._daemon_status = DaemonStatus(
            running=False,
            workers=self.config.max_workers,
            active_jobs=0,
            pending_jobs=0,
            completed_jobs=0,
            failed_jobs=0,
            cancelled_jobs=0
        )
        
        # Command queue monitoring
        self._observer: Optional[Observer] = None
        
        # Rate limiting
        self._rate_limiter = RateLimiter(self.config.rate_limit)
        
        # Initialize Panorama client and managers
        self.panorama_client = PanoramaClient(self.config, self._rate_limiter)
        self.validation_system = ValidationSystem(self.config, self.panorama_client)
        
        # Initialize device inventory
        inventory_file = self.config.get_path("devices/inventory.json")
        self.device_inventory = DeviceInventory(inventory_file, self.panorama_client)
        
        # Initialize hash manager
        hash_file = self.config.get("paths.version_hashes", str(constants.DEFAULT_VERSION_HASHES_FILE))
        self.hash_manager = HashManager(Path(hash_file))
        
        # Initialize upgrade manager
        self.upgrade_manager = UpgradeManager(
            self.config,
            self.panorama_client,
            self.validation_system,
            self.device_inventory,
            self.hash_manager
        )
        
        # Signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def start(self):
        """Start the daemon service."""
        if self._running:
            self.logger.warning("Daemon already running")
            return
        
        self.logger.info("Starting PAN-OS upgrade daemon")
        self._running = True
        self._daemon_status.running = True
        self._daemon_status.started_at = datetime.utcnow().isoformat() + "Z"
        
        # Start worker pool
        self.worker_pool.start(status_callback=self._worker_status_callback)
        
        # Start command queue monitoring
        self._start_command_queue_monitor()
        
        # Start job queue processor
        self._job_processor_thread = threading.Thread(
            target=self._process_job_queue,
            daemon=True,
            name="JobProcessor"
        )
        self._job_processor_thread.start()
        
        # Start status updater
        self._status_updater_thread = threading.Thread(
            target=self._update_status_loop,
            daemon=True,
            name="StatusUpdater"
        )
        self._status_updater_thread.start()
        
        self._save_daemon_status()
        self.logger.info("Daemon started successfully")
        
        # Main loop
        try:
            while not self._stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the daemon service."""
        if not self._running:
            return
        
        self.logger.info("Stopping PAN-OS upgrade daemon")
        self._running = False
        self._stop_event.set()
        
        # Stop command queue monitoring
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        
        # Stop worker pool
        self.worker_pool.stop(timeout=30)
        
        # Update status
        self._daemon_status.running = False
        self._save_daemon_status()
        
        self.logger.info("Daemon stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        self.logger.info(f"Received signal {signum}")
        self.stop()
        sys.exit(0)
    
    def _start_command_queue_monitor(self):
        """Start monitoring the command queue directory."""
        command_dir = self.config.get_path(constants.DIR_COMMANDS_INCOMING)
        
        self.logger.info(f"Starting command queue monitor: {command_dir}")
        
        event_handler = CommandQueueHandler(self)
        self._observer = Observer()
        self._observer.schedule(event_handler, str(command_dir), recursive=False)
        self._observer.start()
        
        # Process any existing commands
        for file_path in command_dir.glob("*.json"):
            if not file_path.name.startswith('.'):
                self.process_command(file_path)
    
    def process_command(self, command_file: Path):
        """
        Process a command from the queue.
        
        Args:
            command_file: Path to command file
        """
        try:
            command_data = read_json(command_file)
            command_type = command_data.get("command")
            
            self.logger.info(f"Processing command: {command_type}")
            
            if command_type == "cancel_upgrade":
                self._handle_cancel_command(command_data)
            else:
                self.logger.warning(f"Unknown command type: {command_type}")
            
            # Move to processed directory
            processed_dir = self.config.get_path(constants.DIR_COMMANDS_PROCESSED)
            processed_file = processed_dir / command_file.name
            command_file.rename(processed_file)
            
        except Exception as e:
            self.logger.error(f"Error processing command {command_file}: {e}", exc_info=True)
    
    def _handle_cancel_command(self, command_data: dict):
        """Handle cancellation command."""
        job_id = command_data.get("job_id", "")
        device_serial = command_data.get("device_serial", "")
        reason = command_data.get("reason", "Admin requested")
        
        self.logger.info(f"Cancellation requested - job: {job_id}, device: {device_serial}, reason: {reason}")
        
        # Cancel via upgrade manager
        self.upgrade_manager.cancel_upgrade(job_id=job_id, device_serial=device_serial)
    
    def _process_job_queue(self):
        """Process pending jobs from the queue."""
        self.logger.info("Job queue processor started")
        
        while not self._stop_event.is_set():
            try:
                # Check for pending jobs
                pending_dir = self.config.get_path(constants.DIR_QUEUE_PENDING)
                job_files = sorted(pending_dir.glob("*.json"))
                
                for job_file in job_files:
                    if self._stop_event.is_set():
                        break
                    
                    try:
                        job_data = read_json(job_file)
                        job = Job(**job_data)
                        
                        self.logger.info(f"Submitting job {job.job_id} to worker pool")
                        
                        # Move to active directory
                        active_dir = self.config.get_path(constants.DIR_QUEUE_ACTIVE)
                        active_file = active_dir / job_file.name
                        job_file.rename(active_file)
                        
                        # Submit to worker pool based on job type
                        if job.type == constants.JOB_TYPE_STANDALONE:
                            for device_serial in job.devices:
                                submitted = self.worker_pool.submit(
                                    job.job_id,
                                    device_serial,
                                    self._execute_upgrade_with_completion,
                                    job.job_id,
                                    self.upgrade_manager.upgrade_device,
                                    device_serial,
                                    job.job_id,
                                    job.dry_run
                                )
                                if not submitted:
                                    self.logger.error(f"Failed to submit device {device_serial} to worker pool")
                        
                        elif job.type == constants.JOB_TYPE_HA_PAIR:
                            if len(job.devices) >= 2:
                                submitted = self.worker_pool.submit(
                                    job.job_id,
                                    job.devices[0],
                                    self._execute_upgrade_with_completion,
                                    job.job_id,
                                    self.upgrade_manager.upgrade_ha_pair,
                                    job.devices[0],
                                    job.devices[1],
                                    job.job_id,
                                    job.dry_run
                                )
                                if not submitted:
                                    self.logger.error(f"Failed to submit HA pair to worker pool")
                        
                        elif job.type == constants.JOB_TYPE_DOWNLOAD_ONLY:
                            for device_serial in job.devices:
                                submitted = self.worker_pool.submit(
                                    job.job_id,
                                    device_serial,
                                    self._execute_upgrade_with_completion,
                                    job.job_id,
                                    self.upgrade_manager.download_only_device,
                                    device_serial,
                                    job.job_id,
                                    job.dry_run
                                )
                                if not submitted:
                                    self.logger.error(f"Failed to submit download-only for {device_serial}")
                        
                    except Exception as e:
                        self.logger.error(f"Error processing job {job_file}: {e}", exc_info=True)
                
                # Sleep before next check
                time.sleep(5)
                
            except Exception as e:
                self.logger.error(f"Error in job queue processor: {e}", exc_info=True)
                time.sleep(5)
        
        self.logger.info("Job queue processor stopped")
    
    def _update_status_loop(self):
        """Periodically update daemon status."""
        while not self._stop_event.is_set():
            try:
                self._update_queue_counts()
                self._save_daemon_status()
                self._save_worker_statuses()
                time.sleep(5)
            except Exception as e:
                self.logger.error(f"Error updating status: {e}", exc_info=True)
    
    def _update_queue_counts(self):
        """Update job queue counts."""
        with self._status_lock:
            pending_dir = self.config.get_path(constants.DIR_QUEUE_PENDING)
            active_dir = self.config.get_path(constants.DIR_QUEUE_ACTIVE)
            completed_dir = self.config.get_path(constants.DIR_QUEUE_COMPLETED)
            cancelled_dir = self.config.get_path(constants.DIR_QUEUE_CANCELLED)
            
            self._daemon_status.pending_jobs = len(list(pending_dir.glob("*.json")))
            self._daemon_status.active_jobs = len(list(active_dir.glob("*.json")))
            self._daemon_status.completed_jobs = len(list(completed_dir.glob("*.json")))
            self._daemon_status.cancelled_jobs = len(list(cancelled_dir.glob("*.json")))
            self._daemon_status.last_updated = datetime.utcnow().isoformat() + "Z"
    
    def _save_daemon_status(self):
        """Save daemon status to file."""
        status_file = self.config.get_path(constants.STATUS_DAEMON_FILE)
        with self._status_lock:
            atomic_write_json(status_file, self._daemon_status.to_dict())
    
    def _save_worker_statuses(self):
        """Save worker statuses to file."""
        status_file = self.config.get_path(constants.STATUS_WORKERS_FILE)
        statuses = [ws.to_dict() for ws in self.worker_pool.get_worker_statuses()]
        atomic_write_json(status_file, {"workers": statuses})
    
    def _execute_upgrade_with_completion(self, job_id: str, upgrade_func, *args, **kwargs):
        """
        Execute upgrade and handle job completion.
        
        Args:
            job_id: Job identifier
            upgrade_func: Upgrade function to execute
            *args: Arguments for upgrade function
            **kwargs: Keyword arguments for upgrade function
        """
        try:
            # Execute the upgrade
            success, message = upgrade_func(*args, **kwargs)
            
            # Move job file based on result
            active_dir = self.config.get_path(constants.DIR_QUEUE_ACTIVE)
            job_file = active_dir / f"{job_id}.json"
            
            if not job_file.exists():
                self.logger.warning(f"Job file not found in active directory: {job_id}")
                return
            
            # Determine destination based on success
            if success:
                dest_dir = self.config.get_path(constants.DIR_QUEUE_COMPLETED)
                self.logger.info(f"Job {job_id} completed successfully")
            else:
                # Check if it was cancelled
                with self._status_lock:
                    if job_id in self.upgrade_manager._cancelled_jobs:
                        dest_dir = self.config.get_path(constants.DIR_QUEUE_CANCELLED)
                        self.logger.info(f"Job {job_id} was cancelled")
                    else:
                        dest_dir = self.config.get_path(constants.DIR_QUEUE_COMPLETED)
                        self.logger.info(f"Job {job_id} failed: {message}")
            
            # Move job file
            dest_file = dest_dir / job_file.name
            job_file.rename(dest_file)
            
            # Update job data with completion info
            from panos_upgrade.utils.file_ops import read_json, atomic_write_json
            from datetime import datetime
            
            job_data = read_json(dest_file)
            job_data["completed_at"] = datetime.utcnow().isoformat() + "Z"
            job_data["status"] = "complete" if success else "failed"
            atomic_write_json(dest_file, job_data)
            
        except Exception as e:
            self.logger.error(f"Error in job completion handler: {e}", exc_info=True)
    
    def _worker_status_callback(self, worker_status: WorkerStatus):
        """Callback for worker status updates."""
        # This is called frequently, so we don't save to disk here
        # The status updater thread will handle periodic saves
        pass


class RateLimiter:
    """Simple token bucket rate limiter."""
    
    def __init__(self, requests_per_minute: int):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_minute: Maximum requests per minute
        """
        self.requests_per_minute = requests_per_minute
        self.tokens = requests_per_minute
        self.last_update = time.time()
        self.lock = threading.Lock()
    
    def acquire(self, blocking: bool = True) -> bool:
        """
        Acquire a token for making a request.
        
        Args:
            blocking: Whether to block until a token is available
            
        Returns:
            True if token acquired, False otherwise
        """
        while True:
            with self.lock:
                now = time.time()
                elapsed = now - self.last_update
                
                # Add tokens based on elapsed time
                self.tokens = min(
                    self.requests_per_minute,
                    self.tokens + (elapsed * self.requests_per_minute / 60.0)
                )
                self.last_update = now
                
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True
                
                if not blocking:
                    return False
            
            # Wait a bit before trying again
            time.sleep(0.1)


def run_daemon():
    """Run the daemon service."""
    daemon = UpgradeDaemon()
    daemon.start()


if __name__ == "__main__":
    run_daemon()

