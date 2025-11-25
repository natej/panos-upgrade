"""Data models for status tracking."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum


class UpgradeStatus(Enum):
    """Upgrade status enumeration."""
    PENDING = "pending"
    VALIDATING = "validating"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    REBOOTING = "rebooting"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class HARole(Enum):
    """HA role enumeration."""
    ACTIVE = "active"
    PASSIVE = "passive"
    STANDALONE = "standalone"


class JobType(Enum):
    """Job type enumeration."""
    STANDALONE = "standalone"
    HA_PAIR = "ha_pair"


@dataclass
class ErrorRecord:
    """Error record."""
    timestamp: str
    phase: str
    message: str
    details: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class DiskSpaceInfo:
    """Disk space information."""
    available_gb: float
    required_gb: float
    check_passed: bool
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ValidationMetrics:
    """Validation metrics."""
    tcp_sessions: int
    route_count: int
    routes: List[Dict[str, str]]
    arp_count: int
    arp_entries: List[Dict[str, str]]
    disk_available_gb: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class MetricComparison:
    """Metric comparison result."""
    difference: float
    percentage: float
    within_margin: bool
    added: List[Any] = field(default_factory=list)
    removed: List[Any] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ValidationResult:
    """Validation result."""
    serial: str
    timestamp: str
    pre_flight: ValidationMetrics
    post_flight: Optional[ValidationMetrics] = None
    comparison: Optional[Dict[str, MetricComparison]] = None
    validation_passed: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "serial": self.serial,
            "timestamp": self.timestamp,
            "pre_flight": self.pre_flight.to_dict(),
            "validation_passed": self.validation_passed
        }
        
        if self.post_flight:
            result["post_flight"] = self.post_flight.to_dict()
        
        if self.comparison:
            result["comparison"] = {k: v.to_dict() for k, v in self.comparison.items()}
        
        return result


@dataclass
class DeviceStatus:
    """Device status."""
    serial: str
    hostname: str
    ha_role: str
    current_version: str
    target_version: str = ""
    upgrade_path: List[str] = field(default_factory=list)
    current_path_index: int = 0
    upgrade_status: str = UpgradeStatus.PENDING.value
    progress: int = 0
    current_phase: str = ""
    upgrade_message: str = ""
    disk_space: Optional[DiskSpaceInfo] = None
    downloaded_versions: List[str] = field(default_factory=list)
    version_hashes: Dict[str, str] = field(default_factory=dict)
    hash_verification: Dict[str, str] = field(default_factory=dict)
    ready_for_install: bool = False
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    skip_reason: str = ""
    errors: List[ErrorRecord] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = asdict(self)
        if self.disk_space:
            result["disk_space"] = self.disk_space.to_dict()
        result["errors"] = [e.to_dict() for e in self.errors]
        return result
    
    def add_error(self, phase: str, message: str, details: str = "") -> None:
        """Add an error record."""
        error = ErrorRecord(
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase=phase,
            message=message,
            details=details
        )
        self.errors.append(error)
        self.last_updated = datetime.utcnow().isoformat() + "Z"


@dataclass
class Job:
    """Upgrade job."""
    job_id: str
    type: str
    devices: List[str]
    ha_pair_name: str = ""
    dry_run: bool = False
    download_only: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    started_at: str = ""
    completed_at: str = ""
    status: str = UpgradeStatus.PENDING.value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class CancelCommand:
    """Cancellation command."""
    command: str = "cancel_upgrade"
    target: str = "job"  # "job" or "device"
    job_id: str = ""
    device_serial: str = ""
    reason: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class DaemonStatus:
    """Daemon status."""
    running: bool
    workers: int
    active_jobs: int
    pending_jobs: int
    completed_jobs: int
    failed_jobs: int
    cancelled_jobs: int
    started_at: str = ""
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class WorkerStatus:
    """Worker status."""
    worker_id: int
    status: str  # "idle", "busy", "error"
    current_job_id: str = ""
    current_device: str = ""
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

