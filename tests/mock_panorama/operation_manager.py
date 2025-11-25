"""Background operation management."""

import uuid
import time
import threading
from datetime import datetime
from typing import Optional, Dict
from sqlalchemy.orm import Session

from .models import Operation
from .device_manager import DeviceManager


class OperationManager:
    """Manages async operations like downloads, installs, reboots."""
    
    def __init__(self, db_session: Session, device_manager: DeviceManager, config: Dict):
        """
        Initialize operation manager.
        
        Args:
            db_session: SQLAlchemy session
            device_manager: Device manager instance
            config: Configuration dict with timing settings
        """
        self.db = db_session
        self.device_manager = device_manager
        self.config = config
        self._workers = {}
    
    def start_download(
        self,
        device_serial: str,
        version: str,
        should_fail: bool = False
    ) -> str:
        """
        Start software download operation.
        
        Args:
            device_serial: Device serial number
            version: Software version to download
            should_fail: Whether to simulate failure
            
        Returns:
            Operation ID
        """
        operation_id = str(uuid.uuid4())
        duration = self.config.get("download_duration", 120)
        
        operation = Operation(
            operation_id=operation_id,
            device_serial=device_serial,
            operation_type="download",
            target_version=version,
            status="in_progress",
            started_at=datetime.utcnow(),
            duration_seconds=duration
        )
        
        self.db.add(operation)
        self.db.commit()
        
        # Update device state
        self.device_manager.set_device_state(device_serial, "downloading")
        
        # Start background worker
        worker = threading.Thread(
            target=self._download_worker,
            args=(operation_id, device_serial, version, duration, should_fail),
            daemon=True
        )
        worker.start()
        self._workers[operation_id] = worker
        
        return operation_id
    
    def start_install(
        self,
        device_serial: str,
        version: str,
        should_fail: bool = False
    ) -> str:
        """
        Start software install operation.
        
        Args:
            device_serial: Device serial number
            version: Software version to install
            should_fail: Whether to simulate failure
            
        Returns:
            Operation ID
        """
        operation_id = str(uuid.uuid4())
        duration = self.config.get("install_duration", 60)
        
        operation = Operation(
            operation_id=operation_id,
            device_serial=device_serial,
            operation_type="install",
            target_version=version,
            status="in_progress",
            started_at=datetime.utcnow(),
            duration_seconds=duration
        )
        
        self.db.add(operation)
        self.db.commit()
        
        # Update device state
        self.device_manager.set_device_state(device_serial, "installing")
        
        # Start background worker
        worker = threading.Thread(
            target=self._install_worker,
            args=(operation_id, device_serial, version, duration, should_fail),
            daemon=True
        )
        worker.start()
        self._workers[operation_id] = worker
        
        return operation_id
    
    def start_reboot(
        self,
        device_serial: str,
        should_fail: bool = False
    ) -> str:
        """
        Start device reboot operation.
        
        Args:
            device_serial: Device serial number
            should_fail: Whether to simulate failure
            
        Returns:
            Operation ID
        """
        operation_id = str(uuid.uuid4())
        duration = self.config.get("reboot_duration", 180)
        
        operation = Operation(
            operation_id=operation_id,
            device_serial=device_serial,
            operation_type="reboot",
            status="in_progress",
            started_at=datetime.utcnow(),
            duration_seconds=duration
        )
        
        self.db.add(operation)
        self.db.commit()
        
        # Mark device as rebooting
        self.device_manager.reboot_device(device_serial)
        
        # Start background worker
        worker = threading.Thread(
            target=self._reboot_worker,
            args=(operation_id, device_serial, duration, should_fail),
            daemon=True
        )
        worker.start()
        self._workers[operation_id] = worker
        
        return operation_id
    
    def get_operation(self, operation_id: str) -> Optional[Operation]:
        """Get operation by ID."""
        return self.db.query(Operation).filter(
            Operation.operation_id == operation_id
        ).first()
    
    def get_active_operation(self, device_serial: str, operation_type: str) -> Optional[Operation]:
        """Get active operation for device."""
        return self.db.query(Operation).filter(
            Operation.device_serial == device_serial,
            Operation.operation_type == operation_type,
            Operation.status.in_(["pending", "in_progress"])
        ).first()
    
    def _download_worker(
        self,
        operation_id: str,
        device_serial: str,
        version: str,
        duration: int,
        should_fail: bool
    ):
        """Background worker for download operation."""
        try:
            # Simulate download with progress updates
            steps = 10
            step_duration = duration / steps
            
            for i in range(steps):
                time.sleep(step_duration)
                
                # Update progress
                operation = self.get_operation(operation_id)
                if operation:
                    operation.progress = int((i + 1) * 10)
                    operation.updated_at = datetime.utcnow()
                    self.db.commit()
                
                # Simulate failure midway
                if should_fail and i == 5:
                    operation = self.get_operation(operation_id)
                    if operation:
                        operation.status = "failed"
                        operation.error_message = "Connection timeout during download"
                        operation.completed_at = datetime.utcnow()
                        self.db.commit()
                    
                    self.device_manager.set_device_state(device_serial, "online")
                    return
            
            # Complete successfully
            operation = self.get_operation(operation_id)
            if operation:
                operation.status = "complete"
                operation.progress = 100
                operation.completed_at = datetime.utcnow()
                self.db.commit()
            
            # Consume disk space for downloaded image (2GB)
            self.device_manager.consume_disk_space(device_serial, 2.0)
            
            # Set device back online
            self.device_manager.set_device_state(device_serial, "online")
            
        except Exception as e:
            print(f"Download worker error: {e}")
    
    def _install_worker(
        self,
        operation_id: str,
        device_serial: str,
        version: str,
        duration: int,
        should_fail: bool
    ):
        """Background worker for install operation."""
        try:
            time.sleep(duration)
            
            operation = self.get_operation(operation_id)
            if not operation:
                return
            
            if should_fail:
                operation.status = "failed"
                operation.error_message = "Installation failed: insufficient space"
                operation.completed_at = datetime.utcnow()
                self.db.commit()
                
                self.device_manager.set_device_state(device_serial, "online")
                return
            
            # Complete successfully
            operation.status = "complete"
            operation.progress = 100
            operation.completed_at = datetime.utcnow()
            self.db.commit()
            
            # Update device version
            self.device_manager.update_device_version(device_serial, version)
            
            # Free disk space (image no longer needed after install)
            self.device_manager.free_disk_space(device_serial, 2.0)
            
            # Set device back online
            self.device_manager.set_device_state(device_serial, "online")
            
        except Exception as e:
            print(f"Install worker error: {e}")
    
    def _reboot_worker(
        self,
        operation_id: str,
        device_serial: str,
        duration: int,
        should_fail: bool
    ):
        """Background worker for reboot operation."""
        try:
            time.sleep(duration)
            
            operation = self.get_operation(operation_id)
            if not operation:
                return
            
            if should_fail:
                operation.status = "failed"
                operation.error_message = "Device did not come back online"
                operation.completed_at = datetime.utcnow()
                self.db.commit()
                
                self.device_manager.set_device_state(device_serial, "offline")
                return
            
            # Complete successfully
            operation.status = "complete"
            operation.progress = 100
            operation.completed_at = datetime.utcnow()
            self.db.commit()
            
            # Bring device back online
            self.device_manager.bring_device_online(device_serial)
            
        except Exception as e:
            print(f"Reboot worker error: {e}")

