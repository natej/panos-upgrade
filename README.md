# DO NOT USE THIS PROJECT OR ANY CODE IN THIS REPO IN ANY WAY!
# IT IS AI-GENERATED AND IS HERE ONLY TEMPORARILY!
# EVERYTHING HERE IS EXPERIMENTAL AND HAS NOT BEEN TESTED!

# PAN-OS Upgrade Manager

Advanced CLI application for managing PAN-OS device upgrades with daemon capabilities, concurrent processing, and comprehensive validation.

## Overview

This application provides a robust, production-ready solution for upgrading PAN-OS firewalls at scale. It manages ~230 devices with features designed for reliability, observability, and administrative control.

**Key Architecture:** The application uses a two-tier connection model:
- **Panorama** is used only for device discovery (`show devices connected`)
- **Direct firewall connections** are used for all operations (upgrades, downloads, validation)

## Key Features

### Core Capabilities
- **Daemon Service**: Runs as a background service with systemd integration
- **Concurrent Processing**: Configurable thread pool (1-50 workers) for parallel upgrades
- **HA Pair Support**: Intelligent HA pair upgrades (passive member first)
- **Version Path Management**: Configurable multi-step upgrade paths
- **Direct Firewall Connections**: All operations connect directly to firewalls for reliability
- **Download-Only Mode**: Pre-stage software images without performing upgrades

### Validation & Safety
- **Pre-flight Validation**: Disk space, TCP sessions, routes, ARP entries
- **Post-flight Validation**: Metric comparison with configurable margins
- **Dry-run Mode**: Test upgrade paths without making changes
- **Graceful Cancellation**: Admin takeover at any point

### Observability
- **Dual Logging**: JSON structured logs + traditional text logs
- **Real-time Status**: Device, job, and worker status tracking
- **Detailed Metrics**: Full routing and ARP table snapshots
- **Audit Trail**: Complete operation history

### Integration
- **Web Application Ready**: JSON file-based communication
- **Atomic Operations**: Race-condition-free file operations
- **Command Queue**: Web app can submit jobs and commands
- **Status Polling**: Real-time status via JSON files

## Architecture

```
                                    ┌─────────────────────────────────┐
                                    │         Device Discovery        │
                                    │   (Panorama: show devices       │
                                    │    connected + HA state query)  │
                                    └────────────┬────────────────────┘
                                                 │
                                                 ▼
                                    ┌─────────────────────────────────┐
                                    │        inventory.json           │
                                    │   (serial, hostname, mgmt_ip,   │
                                    │    device_type, peer_serial,    │
                                    │    ha_state)                    │
                                    └────────────┬────────────────────┘
                                                 │
CLI → Daemon → Worker Pool → Upgrade Manager ────┘
                    │              │
                    │              ▼
              Command Queue   Direct Firewall Connections
                    │         (mgmt_ip + credentials)
                    │              │
                    ▼              ▼
              Status Files    All Operations:
                              - System info, HA state
                              - Pre/post-flight validation
                              - Software check/download
                              - Install, reboot
```

**Connection Flow:**
1. **Discovery**: Panorama → `inventory.json` (one-time or periodic refresh)
2. **Operations**: Direct to firewalls using management IPs from inventory

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture documentation.

## Requirements

- **Python**: 3.11 or higher
- **Operating System**: Linux only
- **Panorama Access**: Username/password (preferred) or API key for device discovery
- **Firewall Access**: Username/password credentials for direct connections
- **Network**: Connectivity to Panorama (for discovery) and firewall management IPs (for operations)

## Installation

### 1. Install Package

```bash
# Clone or download the repository
cd panos-upgrade

# Install in development mode
pip install -e .
```

### 2. Initialize System

```bash
# For development/testing - initialize in home directory
python scripts/init_system.py --work-dir ~/opt/panosupgrade

# For production - initialize with default path (may require sudo)
sudo python scripts/init_system.py
```

The initialization script:
1. Creates the work directory structure
2. Writes `~/.panos-upgrade.config.json` to remember the work directory

**Work Directory Resolution Priority:**
1. CLI flag: `--work-dir`
2. Environment variable: `PANOS_UPGRADE_HOME`
3. User config file: `~/.panos-upgrade.config.json`
4. Default: `/opt/panos-upgrade`

This creates the directory structure:
- `{work_dir}/config/` - Configuration files
- `{work_dir}/queue/` - Job queue directories
- `{work_dir}/status/` - Status tracking
- `{work_dir}/logs/` - Log files
- `{work_dir}/validation/` - Validation results
- `{work_dir}/commands/` - Command queue

### 3. Configure

```bash
# Set Panorama connection (for device discovery)
panos-upgrade config set panorama.host panorama.example.com

# Option 1: Username/password authentication (preferred)
panos-upgrade config set panorama.username admin
panos-upgrade config set panorama.password YOUR_PANORAMA_PASSWORD

# Option 2: API key authentication (if username/password not set)
# panos-upgrade config set panorama.api_key YOUR_API_KEY_HERE

# Set firewall credentials (for direct connections)
panos-upgrade config set firewall.username admin
panos-upgrade config set firewall.password YOUR_FIREWALL_PASSWORD

# Configure workers (optional)
panos-upgrade config set workers.max 10

# Set rate limit (optional)
panos-upgrade config set panorama.rate_limit 10
```

### 4. Discover Devices

Before running any upgrades, you must discover devices from Panorama:

```bash
panos-upgrade device discover
panos-upgrade device discover --workers 20  # Use 20 parallel workers
```

This queries Panorama for connected devices, connects to each firewall in parallel to determine HA state, and saves the information to `inventory.json`. This step is required before any upgrade or download operations.

**Options:**
- `--workers N` - Number of parallel workers (default: `workers.max` from config)

**Discovery captures:**
- Serial number, hostname, management IP, software version, model
- Device type: `standalone`, `ha_pair`, or `unknown`
- HA state: `active`, `passive`, `standalone`, or `unknown`
- Peer serial (for HA pair members)

### 5. Export Devices to CSV (Optional)

After discovery, you can export devices to CSV files for use with bulk commands:

```bash
# Export to current directory
panos-upgrade device export

# Export to specific directory
panos-upgrade device export --output-dir /tmp

# Custom filenames
panos-upgrade device export --standalone-file standalone.csv --ha-pairs-file pairs.csv
```

This creates two CSV files:
- **standalone_devices.csv**: Standalone devices with columns: `serial`, `hostname`, `mgmt_ip`, `current_version`, `model`
- **ha_pairs.csv**: HA pairs with columns: `serial_1`, `serial_2`, `hostname_1`, `hostname_2`, `mgmt_ip_1`, `mgmt_ip_2`, `current_version_1`, `current_version_2`, `model`

The HA pairs CSV orders devices with the active member as `serial_1`.

### 6. Set Up Upgrade Paths

Copy the example and customize:

```bash
# Use your configured work directory
cp examples/upgrade_paths.json ~/opt/panosupgrade/config/
# OR for production
cp examples/upgrade_paths.json /opt/panos-upgrade/config/
```

Edit `{work_dir}/config/upgrade_paths.json`:

```json
{
  "10.0.2": ["10.1.0", "10.5.1", "11.1.0"],
  "10.5.1": ["11.1.0"],
  "11.0.0": ["11.0.3", "11.1.0"]
}
```

## Quick Start

### Start the Daemon

```bash
panos-upgrade daemon start --workers 5
```

### Submit Upgrade Jobs

**Bulk Upgrade from CSV:**
```bash
# Create a CSV file with serial numbers
cat > serials.csv << EOF
serial,hostname,notes
001234567890,fw-dc1-01,primary
001234567891,fw-dc1-02,secondary
EOF

# Queue all devices for upgrade
panos-upgrade upgrade serials.csv
```

**Single Device:**
```bash
panos-upgrade job submit --device 001234567890
```

**HA Pair (specify both serials):**
```bash
panos-upgrade job submit --ha-pair 001234567890 001234567891
```

**Bulk HA Pairs from CSV:**
```bash
# Create a CSV with both serials for each pair
# Note: Column order doesn't matter - active/passive is discovered dynamically
cat > ha_pairs.csv << EOF
serial_1,serial_2,pair_name
001234567890,001234567891,dc1-pair
001234567892,001234567893,dc2-pair
EOF

# Queue all HA pairs
panos-upgrade upgrade-ha-pairs ha_pairs.csv
```

**Dry Run (Test Mode):**
```bash
panos-upgrade upgrade serials.csv --dry-run
panos-upgrade job submit --device 001234567890 --dry-run
```

### Monitor Progress

```bash
# Check daemon status
panos-upgrade daemon status

# List jobs
panos-upgrade job list

# Check device status
panos-upgrade device status 001234567890

# View logs (use your configured work directory)
tail -f ~/opt/panosupgrade/logs/text/panos-upgrade-*.log
```

### Cancel an Upgrade

```bash
panos-upgrade job cancel job-001
```

## Usage Examples

### Upgrade Multiple Devices

```bash
# Create CSV with device serials
echo "serial" > devices.csv
echo "001234567890" >> devices.csv
echo "001234567891" >> devices.csv
echo "001234567892" >> devices.csv

# Queue all devices for upgrade
panos-upgrade upgrade devices.csv

# Monitor progress
watch -n 5 'panos-upgrade job list --status active'
```

### Download-Only Mode (Pre-stage Images)

```bash
# Download software images for standalone devices
panos-upgrade download serials.csv

# Download software images for HA pairs (both members)
panos-upgrade download-ha-pairs ha_pairs.csv

# Check download status
panos-upgrade download-status

# Verify downloads across all devices in inventory
panos-upgrade verify-download
panos-upgrade verify-download --output my_report.csv
panos-upgrade verify-download --workers 10
```

### Validate Before Upgrading

```bash
# Check device readiness
panos-upgrade device validate 001234567890

# View current metrics
panos-upgrade device metrics 001234567890
```

### Web Application Integration

**Submit Job from Web App:**

Create file in `{work_dir}/queue/pending/`:

```json
{
  "job_id": "web-job-123",
  "type": "standalone",
  "devices": ["001234567890"],
  "dry_run": false,
  "created_at": "2025-11-21T12:00:00Z"
}
```

**Read Status in Web App:**

```python
import json
from pathlib import Path

# Get work_dir from ~/.panos-upgrade.config.json
user_config = Path.home() / ".panos-upgrade.config.json"
with open(user_config) as f:
    work_dir = Path(json.load(f)["work_dir"])

# Read daemon status
with open(work_dir / "status/daemon.json") as f:
    daemon_status = json.load(f)

# Read device status
with open(work_dir / "status/devices/001234567890.json") as f:
    device_status = json.load(f)
```

**Cancel from Web App:**

Create file in `{work_dir}/commands/incoming/`:

```json
{
  "command": "cancel_upgrade",
  "target": "job",
  "job_id": "web-job-123",
  "reason": "Admin takeover",
  "timestamp": "2025-11-21T12:30:00Z"
}
```

## Configuration Reference

### Work Directory

The work directory can be configured via multiple sources (in priority order):

| Source | Example |
|--------|---------|
| CLI flag | `panos-upgrade --work-dir ~/opt/panosupgrade daemon start` |
| Environment variable | `export PANOS_UPGRADE_HOME=~/opt/panosupgrade` |
| User config file | `~/.panos-upgrade.config.json` |
| Default | `/opt/panos-upgrade` |

The user config file (`~/.panos-upgrade.config.json`) is created automatically by `init_system.py`:

```json
{
  "work_dir": "/home/user/opt/panosupgrade",
  "created_at": "2025-11-26T10:00:00Z",
  "created_by": "panos-upgrade init"
}
```

Every command logs which source was used at INFO level:
```
2025-11-26 10:00:00 - panos_upgrade - INFO - Work directory: /home/user/opt/panosupgrade (from ~/.panos-upgrade.config.json)
```

### Panorama Settings (for device discovery)
- `panorama.host` - Panorama hostname
- `panorama.username` - Username for authentication (preferred)
- `panorama.password` - Password for authentication (preferred)
- `panorama.api_key` - API key for authentication (used if username/password not set)
- `panorama.rate_limit` - API requests per minute (default: 10)
- `panorama.timeout` - API timeout in seconds (default: 300)

**Note:** If both `panorama.username/password` and `panorama.api_key` are configured, username/password takes priority.

### Firewall Settings (for direct connections)
- `firewall.username` - Username for firewall authentication
- `firewall.password` - Password for firewall authentication
- `firewall.timeout` - API timeout in seconds (default: 300)
- `firewall.software_check_timeout` - Timeout for software check command (default: 90)
- `firewall.software_info_timeout` - Timeout for software info command (default: 120)
- `firewall.job_stall_timeout` - Timeout when download/install jobs show no progress (default: 1800)
- `firewall.max_reboot_poll_interval` - Max interval between reboot status checks (default: 300)

### Worker Settings
- `workers.max` - Maximum worker threads (1-50, default: 5)
- `workers.queue_size` - Maximum queue size (default: 1000)

### Discovery Settings
- `discovery.retry_attempts` - Retry attempts for HA state queries (default: 3)

### Validation Settings
- `validation.tcp_session_margin` - TCP session change tolerance % (default: 5.0)
- `validation.route_margin` - Route count change tolerance (default: 0.0)
- `validation.arp_margin` - ARP entry change tolerance (default: 0.0)
- `validation.min_disk_gb` - Minimum required disk space GB (default: 5.0)

### Logging Settings
- `logging.level` - Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `logging.max_size_mb` - Maximum log file size (default: 100)
- `logging.retention_days` - Log retention period (default: 30)

## Upgrade Process

All operations connect **directly to firewalls** using management IPs from the device inventory.

1. **Lookup Device**
   - Get management IP from `inventory.json`
   - Connect directly to firewall using firewall credentials

2. **Pre-flight Validation**
   - Check available disk space (must meet minimum)
   - Collect baseline metrics (TCP sessions, routes, ARP)
   - Skip if current version not in upgrade paths

3. **Software Check**
   - Run `request system software check` to refresh available versions

4. **Download**
   - Check if image already downloaded (skip if present)
   - Download software image directly to firewall if needed
   - Monitor download progress via job status

5. **Install**
   - Install software on device
   - Wait for installation to complete

6. **Reboot**
   - Reboot device
   - Wait for device to come back online (up to 10 minutes)
   - Uses exponential backoff polling

7. **Post-flight Validation**
   - Collect metrics again
   - Compare with pre-flight baseline
   - Log differences for admin review

8. **Multi-version Path**
   - Repeat steps 2-7 for each version in upgrade path
   - Update device status after each version

## Documentation

- [Usage Guide](docs/USAGE.md) - Detailed usage instructions
- [Architecture](docs/ARCHITECTURE.md) - System architecture and design
- [Examples](examples/) - Configuration and job examples

## Troubleshooting

### Device Not Found in Inventory
**Cause**: Device discovery hasn't been run or device not connected to Panorama  
**Solution**: Run `panos-upgrade device discover` to refresh inventory

### Cannot Connect to Firewall
**Cause**: Firewall management IP not reachable or credentials incorrect  
**Solution**: 
- Verify firewall management IP is accessible from the daemon host
- Check `firewall.username` and `firewall.password` settings
- Ensure firewall API access is enabled

### Device Skipped
**Cause**: Current version not found in upgrade_paths.json  
**Solution**: Add version to upgrade paths or update device manually

### Insufficient Disk Space
**Cause**: Available disk space below minimum threshold  
**Solution**: Free up space on firewall or adjust `validation.min_disk_gb`

### Validation Failed
**Cause**: Metrics outside acceptable margins  
**Solution**: Review validation results, adjust margins if appropriate

### Daemon Won't Start
**Cause**: Permission issues or missing directories  
**Solution**: Run `python scripts/init_system.py --work-dir YOUR_PATH` and check permissions

### Wrong Work Directory
**Cause**: Multiple configuration sources or stale user config  
**Solution**: Check log output for "Work directory: ... (from ...)" message. Update `~/.panos-upgrade.config.json` or use `--work-dir` flag to override.

## Daemon Restart Recovery

The daemon is designed to safely recover from crashes or restarts during upgrade operations.

### How It Works

When an upgrade begins, the daemon stores the device's **starting version** in the device status file. This ensures that if the daemon crashes mid-upgrade, upon restart it will:

1. **Use the original upgrade path**: The path is looked up using the `starting_version`, not the device's current version
2. **Resume from the correct position**: The daemon detects where the device is in the upgrade path and continues from there
3. **Avoid path confusion**: Even if the device has already upgraded to an intermediate version, the original intended path is followed

### Example Scenario

Given `upgrade_paths.json`:
```json
{
  "10.1.0": ["10.5.1", "11.1.0"],
  "10.5.1": ["11.1.0"]
}
```

**Without recovery (bug):**
1. Device starts at `10.1.0`, upgrade path is `10.1.0 → 10.5.1 → 11.1.0`
2. Device upgrades to `10.5.1`, daemon crashes
3. Daemon restarts, queries device, sees `10.5.1`
4. Looks up path for `10.5.1` → gets `["11.1.0"]` (different path!)

**With recovery (correct):**
1. Device starts at `10.1.0`, `starting_version = "10.1.0"` saved
2. Device upgrades to `10.5.1`, daemon crashes
3. Daemon restarts, loads existing status with `starting_version = "10.1.0"`
4. Looks up path for `10.1.0` → gets `["10.5.1", "11.1.0"]` (original path)
5. Sees device is at `10.5.1` (position 1 in path), continues to `11.1.0`

### Device Status File

The device status is stored in `{work_dir}/status/devices/{serial}.json` and includes:
- `starting_version`: The version when the upgrade was first initiated
- `current_version`: The device's current live version
- `upgrade_path`: The full upgrade path being followed
- `current_path_index`: Current position in the upgrade path
- `upgrade_status`: Current status (pending, downloading, installing, etc.)

This file persists across daemon restarts and enables safe recovery.

## Development

### Project Structure

```
panos-upgrade/
├── src/panos_upgrade/
│   ├── cli.py                 # CLI interface
│   ├── daemon.py              # Daemon service
│   ├── worker_pool.py         # Thread pool manager
│   ├── upgrade_manager.py     # Upgrade orchestration
│   ├── panorama_client.py     # Panorama API client
│   ├── validation.py          # Validation system
│   ├── config.py              # Configuration management
│   ├── work_dir_resolver.py   # Work directory resolution
│   ├── logging_config.py      # Logging system
│   ├── models.py              # Data models
│   ├── constants.py           # Constants
│   ├── device_inventory.py    # Device discovery/inventory
│   ├── direct_firewall_client.py  # Direct firewall connections
│   ├── exceptions.py          # Custom exceptions
│   └── utils/
│       └── file_ops.py        # File operations
├── examples/                  # Example configurations
├── docs/                      # Documentation
├── scripts/                   # Utility scripts
└── tests/                     # Test suite (including mock Panorama)
```

### Running from Source

```bash
# Install in development mode
pip install -e .

# Run CLI
panos-upgrade --help

# Run daemon directly
python -m panos_upgrade.daemon
```

## Contributing

This is a production tool for managing critical infrastructure. Changes should be:
- Well-tested
- Documented
- Backwards compatible
- Reviewed for security implications

## License

[Add your license here]

## Support

For issues, questions, or contributions, please [add contact information or issue tracker].

