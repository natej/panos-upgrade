"""Custom exceptions for PAN-OS Upgrade Manager."""


class PanosUpgradeError(Exception):
    """Base exception for all PAN-OS upgrade errors."""
    pass


class JobError(PanosUpgradeError):
    """Base exception for job-related errors."""
    pass


class DuplicateJobError(JobError):
    """Exception raised when a device already has a job."""
    
    def __init__(self, device_serial: str, job_id: str, status: str, created_at: str = ""):
        """
        Initialize duplicate job error.
        
        Args:
            device_serial: Device serial number
            job_id: Existing job ID
            status: Job status (pending, active)
            created_at: When job was created
        """
        self.device_serial = device_serial
        self.job_id = job_id
        self.status = status
        self.created_at = created_at
        
        message = (
            f"Device {device_serial} already has a {status} job "
            f"(Job ID: {job_id})"
        )
        if created_at:
            message += f" created at {created_at}"
        
        super().__init__(message)


class ActiveJobError(DuplicateJobError):
    """Exception raised when a device has an active job."""
    
    def __init__(self, device_serial: str, job_id: str, created_at: str = ""):
        """
        Initialize active job error.
        
        Args:
            device_serial: Device serial number
            job_id: Existing job ID
            created_at: When job was created
        """
        super().__init__(device_serial, job_id, "active", created_at)


class PendingJobError(DuplicateJobError):
    """Exception raised when a device has a pending job."""
    
    def __init__(self, device_serial: str, job_id: str, created_at: str = ""):
        """
        Initialize pending job error.
        
        Args:
            device_serial: Device serial number
            job_id: Existing job ID
            created_at: When job was created
        """
        super().__init__(device_serial, job_id, "pending", created_at)


class ValidationError(PanosUpgradeError):
    """Exception raised when validation fails."""
    pass


class InsufficientDiskSpaceError(ValidationError):
    """Exception raised when device has insufficient disk space."""
    
    def __init__(self, device_serial: str, available_gb: float, required_gb: float):
        """
        Initialize insufficient disk space error.
        
        Args:
            device_serial: Device serial number
            available_gb: Available disk space
            required_gb: Required disk space
        """
        self.device_serial = device_serial
        self.available_gb = available_gb
        self.required_gb = required_gb
        
        message = (
            f"Device {device_serial} has insufficient disk space: "
            f"{available_gb:.2f} GB available, {required_gb:.2f} GB required"
        )
        super().__init__(message)


class VersionNotFoundError(PanosUpgradeError):
    """Exception raised when version is not found in upgrade paths."""
    
    def __init__(self, device_serial: str, current_version: str):
        """
        Initialize version not found error.
        
        Args:
            device_serial: Device serial number
            current_version: Current device version
        """
        self.device_serial = device_serial
        self.current_version = current_version
        
        message = (
            f"No upgrade path found for device {device_serial} "
            f"with version {current_version}"
        )
        super().__init__(message)


class DeviceNotFoundError(PanosUpgradeError):
    """Exception raised when device is not found."""
    
    def __init__(self, device_serial: str):
        """
        Initialize device not found error.
        
        Args:
            device_serial: Device serial number
        """
        self.device_serial = device_serial
        message = f"Device not found: {device_serial}"
        super().__init__(message)


class PanoramaConnectionError(PanosUpgradeError):
    """Exception raised when cannot connect to Panorama."""
    
    def __init__(self, host: str, reason: str):
        """
        Initialize Panorama connection error.
        
        Args:
            host: Panorama host
            reason: Error reason
        """
        self.host = host
        self.reason = reason
        message = f"Failed to connect to Panorama {host}: {reason}"
        super().__init__(message)


class UpgradeFailedError(PanosUpgradeError):
    """Exception raised when upgrade fails."""
    
    def __init__(self, device_serial: str, phase: str, reason: str):
        """
        Initialize upgrade failed error.
        
        Args:
            device_serial: Device serial number
            phase: Upgrade phase where failure occurred
            reason: Failure reason
        """
        self.device_serial = device_serial
        self.phase = phase
        self.reason = reason
        message = f"Upgrade failed for {device_serial} during {phase}: {reason}"
        super().__init__(message)


class CancellationError(PanosUpgradeError):
    """Exception raised when cancellation fails."""
    pass


class ConfigurationError(PanosUpgradeError):
    """Exception raised for configuration errors."""
    pass


class HashError(PanosUpgradeError):
    """Base exception for hash-related errors."""
    pass


class HashNotFoundError(HashError):
    """Exception raised when expected hash is not in database."""
    
    def __init__(self, version: str):
        """
        Initialize hash not found error.
        
        Args:
            version: Software version
        """
        self.version = version
        message = f"No expected hash found for version {version} in hash database"
        super().__init__(message)


class HashMismatchError(HashError):
    """Exception raised when hash doesn't match expected value."""
    
    def __init__(self, version: str, expected_hash: str, actual_hash: str):
        """
        Initialize hash mismatch error.
        
        Args:
            version: Software version
            expected_hash: Expected SHA256 hash
            actual_hash: Actual SHA256 hash from firewall
        """
        self.version = version
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash
        
        message = (
            f"Hash mismatch for version {version}! "
            f"Expected: {expected_hash[:16]}..., "
            f"Actual: {actual_hash[:16]}... "
            f"Download may be corrupted or tampered!"
        )
        super().__init__(message)


class DownloadVerificationError(PanosUpgradeError):
    """Exception raised when download verification fails."""
    
    def __init__(self, device_serial: str, version: str, reason: str):
        """
        Initialize download verification error.
        
        Args:
            device_serial: Device serial number
            version: Software version
            reason: Verification failure reason
        """
        self.device_serial = device_serial
        self.version = version
        self.reason = reason
        
        message = f"Download verification failed for {device_serial} version {version}: {reason}"
        super().__init__(message)


class ConflictingJobTypeError(JobError):
    """Exception raised when job type conflicts with existing job."""
    
    def __init__(self, device_serial: str, existing_type: str, requested_type: str, existing_job_id: str = ""):
        """
        Initialize conflicting job type error.
        
        Args:
            device_serial: Device serial number
            existing_type: Type of existing job
            requested_type: Type of requested job
            existing_job_id: Existing job ID
        """
        self.device_serial = device_serial
        self.existing_type = existing_type
        self.requested_type = requested_type
        self.existing_job_id = existing_job_id
        
        message = (
            f"Device {device_serial} has an existing {existing_type} job. "
            f"Cannot submit {requested_type} job. "
            f"Download-only and normal upgrades cannot run concurrently."
        )
        if existing_job_id:
            message += f" (Job ID: {existing_job_id})"
        
        super().__init__(message)

