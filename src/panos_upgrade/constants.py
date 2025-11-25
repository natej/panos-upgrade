"""Application-wide constants."""

import os
from pathlib import Path

# Default paths
DEFAULT_WORK_DIR = Path("/opt/panosupgrade")
DEFAULT_CONFIG_FILE = DEFAULT_WORK_DIR / "config" / "config.json"
DEFAULT_UPGRADE_PATHS_FILE = DEFAULT_WORK_DIR / "config" / "upgrade_paths.json"
DEFAULT_VERSION_HASHES_FILE = DEFAULT_WORK_DIR / "config" / "version_hashes.json"
DEFAULT_DEVICE_INVENTORY_FILE = DEFAULT_WORK_DIR / "devices" / "inventory.json"

# Directory structure
DIR_CONFIG = "config"
DIR_DEVICES = "devices"
DIR_QUEUE = "queue"
DIR_QUEUE_PENDING = "queue/pending"
DIR_QUEUE_ACTIVE = "queue/active"
DIR_QUEUE_COMPLETED = "queue/completed"
DIR_QUEUE_CANCELLED = "queue/cancelled"
DIR_STATUS = "status"
DIR_STATUS_DEVICES = "status/devices"
DIR_STATUS_HA_PAIRS = "status/devices/ha_pairs"
DIR_LOGS = "logs"
DIR_LOGS_STRUCTURED = "logs/structured"
DIR_LOGS_TEXT = "logs/text"
DIR_VALIDATION = "validation"
DIR_VALIDATION_PRE = "validation/pre_flight"
DIR_VALIDATION_POST = "validation/post_flight"
DIR_COMMANDS = "commands"
DIR_COMMANDS_INCOMING = "commands/incoming"
DIR_COMMANDS_PROCESSED = "commands/processed"

# Status files
STATUS_DAEMON_FILE = "status/daemon.json"
STATUS_WORKERS_FILE = "status/workers.json"

# Upgrade statuses
STATUS_PENDING = "pending"
STATUS_VALIDATING = "validating"
STATUS_DOWNLOADING = "downloading"
STATUS_INSTALLING = "installing"
STATUS_REBOOTING = "rebooting"
STATUS_COMPLETE = "complete"
STATUS_DOWNLOAD_COMPLETE = "download_complete"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_SKIPPED = "skipped"

# HA roles
HA_ROLE_ACTIVE = "active"
HA_ROLE_PASSIVE = "passive"
HA_ROLE_STANDALONE = "standalone"

# Job types
JOB_TYPE_STANDALONE = "standalone"
JOB_TYPE_HA_PAIR = "ha_pair"
JOB_TYPE_DOWNLOAD_ONLY = "download_only"

# Default configuration values
DEFAULT_WORKERS = 5
MAX_WORKERS = 50
DEFAULT_RATE_LIMIT = 10
DEFAULT_TIMEOUT = 300
DEFAULT_TCP_SESSION_MARGIN = 5.0
DEFAULT_ROUTE_MARGIN = 0.0
DEFAULT_ARP_MARGIN = 0.0
DEFAULT_MIN_DISK_GB = 5.0
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_MAX_SIZE_MB = 100
DEFAULT_LOG_RETENTION_DAYS = 30

