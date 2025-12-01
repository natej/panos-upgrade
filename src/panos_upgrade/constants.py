"""Application-wide constants."""

import os
from pathlib import Path

# Default work directory (used as fallback when no other source specifies it)
# Priority order: CLI flag > ENV var > ~/.panos-upgrade.config.json > this default
DEFAULT_WORK_DIR = Path("/opt/panos-upgrade")

# Note: These are relative paths within work_dir, not absolute paths
# The actual paths are constructed at runtime based on resolved work_dir
CONFIG_SUBDIR = "config"
CONFIG_FILE_NAME = "config.json"
UPGRADE_PATHS_FILE_NAME = "upgrade_paths.json"
DEVICE_INVENTORY_FILE_NAME = "inventory.json"

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
DEFAULT_SOFTWARE_CHECK_TIMEOUT = 90
DEFAULT_SOFTWARE_INFO_TIMEOUT = 120
DEFAULT_MAX_REBOOT_POLL_INTERVAL = 300
DEFAULT_DISCOVERY_RETRY_ATTEMPTS = 3
DEFAULT_TCP_SESSION_MARGIN = 5.0
DEFAULT_ROUTE_MARGIN = 0.0
DEFAULT_ARP_MARGIN = 0.0
DEFAULT_MIN_DISK_GB = 5.0
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_MAX_SIZE_MB = 100
DEFAULT_LOG_RETENTION_DAYS = 30

