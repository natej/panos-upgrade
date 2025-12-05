"""Configuration management."""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from panos_upgrade import constants
from panos_upgrade.utils.file_ops import atomic_write_json, safe_read_json, ensure_directory_structure


class Config:
    """Application configuration manager."""
    
    def __init__(self, config_file: Optional[Path] = None, work_dir: Optional[Path] = None):
        """
        Initialize configuration.
        
        Args:
            config_file: Path to config file (if not provided, uses work_dir/config/config.json)
            work_dir: Working directory (should be resolved via work_dir_resolver before calling)
        """
        # Work dir should be provided (resolved by CLI or caller)
        # Fall back to default only as last resort
        self.work_dir = Path(work_dir) if work_dir else constants.DEFAULT_WORK_DIR
        
        # Config file is relative to work_dir unless explicitly provided
        if config_file:
            self.config_file = Path(config_file)
        else:
            self.config_file = self.work_dir / constants.CONFIG_SUBDIR / constants.CONFIG_FILE_NAME
        
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self) -> None:
        """Load configuration from file or create default."""
        self._config = safe_read_json(self.config_file, self._get_default_config())
        
        # Ensure work directory structure exists
        self._ensure_directories()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            "panorama": {
                "host": "",
                "username": "",
                "password": "",
                "api_key": "",
                "rate_limit": constants.DEFAULT_RATE_LIMIT,
                "timeout": constants.DEFAULT_TIMEOUT
            },
            "firewall": {
                "username": "",
                "password": "",
                "timeout": constants.DEFAULT_TIMEOUT,
                "software_check_timeout": constants.DEFAULT_SOFTWARE_CHECK_TIMEOUT,
                "software_info_timeout": constants.DEFAULT_SOFTWARE_INFO_TIMEOUT,
                "download_timeout": constants.DEFAULT_DOWNLOAD_TIMEOUT,
                "upgrade_timeout": constants.DEFAULT_UPGRADE_TIMEOUT,
                "max_reboot_poll_interval": constants.DEFAULT_MAX_REBOOT_POLL_INTERVAL
            },
            "workers": {
                "max": constants.DEFAULT_WORKERS,
                "queue_size": 1000
            },
            "discovery": {
                "retry_attempts": constants.DEFAULT_DISCOVERY_RETRY_ATTEMPTS
            },
            "validation": {
                "tcp_session_margin": constants.DEFAULT_TCP_SESSION_MARGIN,
                "route_margin": constants.DEFAULT_ROUTE_MARGIN,
                "arp_margin": constants.DEFAULT_ARP_MARGIN,
                "min_disk_gb": constants.DEFAULT_MIN_DISK_GB,
                "custom_metrics": []
            },
            "logging": {
                "level": constants.DEFAULT_LOG_LEVEL,
                "max_size_mb": constants.DEFAULT_LOG_MAX_SIZE_MB,
                "retention_days": constants.DEFAULT_LOG_RETENTION_DAYS
            },
            "paths": {
                "upgrade_paths": str(self.work_dir / "config" / "upgrade_paths.json"),
                "work_dir": str(self.work_dir)
            }
        }
    
    def _ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        directories = [
            constants.DIR_CONFIG,
            constants.DIR_DEVICES,
            constants.DIR_QUEUE_PENDING,
            constants.DIR_QUEUE_ACTIVE,
            constants.DIR_QUEUE_COMPLETED,
            constants.DIR_QUEUE_CANCELLED,
            constants.DIR_STATUS,
            constants.DIR_STATUS_DEVICES,
            constants.DIR_STATUS_HA_PAIRS,
            constants.DIR_LOGS_STRUCTURED,
            constants.DIR_LOGS_TEXT,
            constants.DIR_VALIDATION_PRE,
            constants.DIR_VALIDATION_POST,
            constants.DIR_COMMANDS_INCOMING,
            constants.DIR_COMMANDS_PROCESSED,
        ]
        ensure_directory_structure(self.work_dir, directories)
    
    def save(self) -> None:
        """Save configuration to file."""
        atomic_write_json(self.config_file, self._config)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation key.
        
        Args:
            key: Configuration key (e.g., "panorama.host")
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value by dot-notation key.
        
        Args:
            key: Configuration key (e.g., "panorama.host")
            value: Value to set
        """
        keys = key.split('.')
        config = self._config
        
        # Navigate to the parent dictionary
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # Set the value
        config[keys[-1]] = value
        self.save()
    
    def get_path(self, relative_path: str) -> Path:
        """
        Get absolute path for a relative path within work directory.
        
        Args:
            relative_path: Relative path from work directory
            
        Returns:
            Absolute Path object
        """
        return self.work_dir / relative_path
    
    @property
    def panorama_host(self) -> str:
        """Get Panorama host."""
        return self.get("panorama.host", "")
    
    @property
    def panorama_username(self) -> str:
        """Get Panorama username."""
        return self.get("panorama.username", "")
    
    @property
    def panorama_password(self) -> str:
        """Get Panorama password."""
        return self.get("panorama.password", "")
    
    @property
    def panorama_api_key(self) -> str:
        """Get Panorama API key."""
        return self.get("panorama.api_key", "")
    
    @property
    def max_workers(self) -> int:
        """Get maximum number of workers."""
        return min(self.get("workers.max", constants.DEFAULT_WORKERS), constants.MAX_WORKERS)
    
    @property
    def rate_limit(self) -> int:
        """Get API rate limit."""
        return self.get("panorama.rate_limit", constants.DEFAULT_RATE_LIMIT)
    
    @property
    def min_disk_gb(self) -> float:
        """Get minimum required disk space in GB."""
        return self.get("validation.min_disk_gb", constants.DEFAULT_MIN_DISK_GB)
    
    @property
    def upgrade_paths_file(self) -> Path:
        """Get upgrade paths file path."""
        default_path = self.work_dir / constants.CONFIG_SUBDIR / constants.UPGRADE_PATHS_FILE_NAME
        return Path(self.get("paths.upgrade_paths", str(default_path)))
    
    @property
    def firewall_username(self) -> str:
        """Get firewall username."""
        return self.get("firewall.username", "")
    
    @property
    def firewall_password(self) -> str:
        """Get firewall password."""
        return self.get("firewall.password", "")
    
    @property
    def software_check_timeout(self) -> int:
        """Get timeout for software check command in seconds."""
        return self.get("firewall.software_check_timeout", constants.DEFAULT_SOFTWARE_CHECK_TIMEOUT)
    
    @property
    def software_info_timeout(self) -> int:
        """Get timeout for software info command in seconds."""
        return self.get("firewall.software_info_timeout", constants.DEFAULT_SOFTWARE_INFO_TIMEOUT)
    
    @property
    def download_timeout(self) -> int:
        """Get timeout for download jobs in seconds."""
        return self.get("firewall.download_timeout", constants.DEFAULT_DOWNLOAD_TIMEOUT)
    
    @property
    def upgrade_timeout(self) -> int:
        """Get timeout for upgrade/install jobs in seconds."""
        return self.get("firewall.upgrade_timeout", constants.DEFAULT_UPGRADE_TIMEOUT)
    
    @property
    def max_reboot_poll_interval(self) -> int:
        """Get maximum poll interval when waiting for device reboot in seconds."""
        return self.get("firewall.max_reboot_poll_interval", constants.DEFAULT_MAX_REBOOT_POLL_INTERVAL)
    
    @property
    def discovery_retry_attempts(self) -> int:
        """Get number of retry attempts for device discovery HA queries."""
        return self.get("discovery.retry_attempts", constants.DEFAULT_DISCOVERY_RETRY_ATTEMPTS)


# Global config instance
_config: Optional[Config] = None


def get_config(config_file: Optional[Path] = None, work_dir: Optional[Path] = None) -> Config:
    """
    Get global configuration instance.
    
    Args:
        config_file: Path to config file (only used on first call)
        work_dir: Working directory (only used on first call)
        
    Returns:
        Config instance
    """
    global _config
    if _config is None:
        _config = Config(config_file, work_dir)
    return _config

