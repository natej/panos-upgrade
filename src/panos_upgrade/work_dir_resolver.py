"""Work directory resolution with source tracking."""

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class ConfigSource(Enum):
    """Source of work directory configuration."""
    CLI_FLAG = "from --work-dir flag"
    ENV_VAR = "from PANOS_UPGRADE_HOME environment variable"
    USER_CONFIG = "from ~/.panos-upgrade.config.json"
    DEFAULT = "default"


@dataclass
class WorkDirResolution:
    """Result of work directory resolution."""
    path: Path
    source: ConfigSource
    
    def log_message(self) -> str:
        """Get log message describing the resolution."""
        return f"Work directory: {self.path} ({self.source.value})"


# Environment variable name
ENV_VAR_NAME = "PANOS_UPGRADE_HOME"

# User config file name
USER_CONFIG_FILE = ".panos-upgrade.config.json"

# Default work directory
DEFAULT_WORK_DIR = Path("/opt/panos-upgrade")


def get_user_config_path() -> Path:
    """Get path to user config file in home directory."""
    return Path.home() / USER_CONFIG_FILE


def read_user_config() -> Optional[dict]:
    """
    Read user config file from home directory.
    
    Returns:
        Config dict or None if file doesn't exist or is invalid
    """
    user_config_path = get_user_config_path()
    
    if not user_config_path.exists():
        return None
    
    try:
        with open(user_config_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError, OSError):
        return None


def write_user_config(work_dir: Path) -> Path:
    """
    Write user config file to home directory.
    
    Args:
        work_dir: Work directory path to store
        
    Returns:
        Path to the created config file
    """
    from datetime import datetime, timezone
    
    user_config_path = get_user_config_path()
    
    config_data = {
        "work_dir": str(work_dir),
        "created_at": datetime.now(timezone.utc).isoformat() + "Z",
        "created_by": "panos-upgrade init"
    }
    
    # Write atomically
    temp_path = user_config_path.with_suffix('.tmp')
    try:
        with open(temp_path, 'w') as f:
            json.dump(config_data, f, indent=2)
        temp_path.rename(user_config_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    
    return user_config_path


def resolve_work_dir(cli_work_dir: Optional[str] = None) -> WorkDirResolution:
    """
    Resolve work directory from multiple sources.
    
    Priority order:
    1. CLI flag --work-dir (highest priority)
    2. Environment variable PANOS_UPGRADE_HOME
    3. User config file ~/.panos-upgrade.config.json
    4. Default /opt/panos-upgrade
    
    Args:
        cli_work_dir: Work directory from CLI flag (if provided)
        
    Returns:
        WorkDirResolution with path and source for logging
    """
    # 1. CLI flag (highest priority)
    if cli_work_dir:
        return WorkDirResolution(
            path=Path(cli_work_dir).expanduser().resolve(),
            source=ConfigSource.CLI_FLAG
        )
    
    # 2. Environment variable
    env_work_dir = os.getenv(ENV_VAR_NAME)
    if env_work_dir:
        return WorkDirResolution(
            path=Path(env_work_dir).expanduser().resolve(),
            source=ConfigSource.ENV_VAR
        )
    
    # 3. User config file
    user_config = read_user_config()
    if user_config and "work_dir" in user_config:
        return WorkDirResolution(
            path=Path(user_config["work_dir"]).expanduser().resolve(),
            source=ConfigSource.USER_CONFIG
        )
    
    # 4. Default
    return WorkDirResolution(
        path=DEFAULT_WORK_DIR,
        source=ConfigSource.DEFAULT
    )

