# DO NOT USE THIS PROJECT OR ANY CODE IN THIS REPO IN ANY WAY!
# IT IS AI-GENERATED AND IS HERE ONLY TEMPORARILY!
# EVERYTHING HERE IS EXPERIMENTAL AND HAS NOT BEEN TESTED!

# PAN-OS Upgrade Manager

Advanced CLI application for managing PAN-OS device upgrades through Panorama with daemon capabilities, concurrent processing, and comprehensive validation.

## Overview

This application provides a robust, production-ready solution for upgrading PAN-OS firewalls at scale. It manages ~230 devices through Panorama with features designed for reliability, observability, and administrative control.

## Key Features

### Core Capabilities
- **Daemon Service**: Runs as a background service with systemd integration
- **Concurrent Processing**: Configurable thread pool (1-50 workers) for parallel upgrades
- **HA Pair Support**: Intelligent HA pair upgrades (passive member first)
- **Version Path Management**: Configurable multi-step upgrade paths
- **Rate Limiting**: Prevents Panorama API overload

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
CLI → Daemon → Worker Pool → Upgrade Manager → Panorama → Firewalls
                    ↓              ↓
              Command Queue   Validation System
                    ↓              ↓
              Status Files    Metric Comparison
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed architecture documentation.

## Requirements

- **Python**: 3.11 or higher
- **Operating System**: Linux only
- **Access**: Panorama API key with appropriate permissions
- **Network**: Connectivity to Panorama server

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
# Run initialization script
python scripts/init_system.py
```

This creates the directory structure:
- `/var/lib/panos-upgrade/config/` - Configuration files
- `/var/lib/panos-upgrade/queue/` - Job queue directories
- `/var/lib/panos-upgrade/status/` - Status tracking
- `/var/lib/panos-upgrade/logs/` - Log files
- `/var/lib/panos-upgrade/validation/` - Validation results
- `/var/lib/panos-upgrade/commands/` - Command queue

### 3. Configure

```bash
# Set Panorama connection
panos-upgrade config set panorama.host panorama.example.com
panos-upgrade config set panorama.api_key YOUR_API_KEY_HERE

# Configure workers (optional)
panos-upgrade config set workers.max 10

# Set rate limit (optional)
panos-upgrade config set panorama.rate_limit 10
```

### 4. Set Up Upgrade Paths

Copy the example and customize:

```bash
cp examples/upgrade_paths.json /var/lib/panos-upgrade/config/
```

Edit `/var/lib/panos-upgrade/config/upgrade_paths.json`:

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

### Submit an Upgrade Job

**Standalone Firewall:**
```bash
panos-upgrade job submit --device 001234567890
```

**HA Pair:**
```bash
panos-upgrade job submit --ha-pair datacenter-1
```

**Dry Run (Test Mode):**
```bash
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

# View logs
tail -f /var/lib/panos-upgrade/logs/text/panos-upgrade-*.log
```

### Cancel an Upgrade

```bash
panos-upgrade job cancel job-001
```

## Usage Examples

### Upgrade Multiple Devices

```bash
# Submit jobs for multiple devices
for serial in 001234567890 001234567891 001234567892; do
  panos-upgrade job submit --device $serial
done

# Monitor progress
watch -n 5 'panos-upgrade job list --status active'
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

Create file in `/var/lib/panos-upgrade/queue/pending/`:

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

# Read daemon status
with open('/var/lib/panos-upgrade/status/daemon.json') as f:
    daemon_status = json.load(f)

# Read device status
with open('/var/lib/panos-upgrade/status/devices/001234567890.json') as f:
    device_status = json.load(f)
```

**Cancel from Web App:**

Create file in `/var/lib/panos-upgrade/commands/incoming/`:

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

### Panorama Settings
- `panorama.host` - Panorama hostname
- `panorama.api_key` - API key for authentication
- `panorama.rate_limit` - API requests per minute (default: 10)
- `panorama.timeout` - API timeout in seconds (default: 300)

### Worker Settings
- `workers.max` - Maximum worker threads (1-50, default: 5)
- `workers.queue_size` - Maximum queue size (default: 1000)

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

1. **Pre-flight Validation**
   - Check available disk space (must meet minimum)
   - Collect baseline metrics (TCP sessions, routes, ARP)
   - Skip if current version not in upgrade paths

2. **Download**
   - Download software image to device
   - Monitor download progress
   - Verify download completion

3. **Install**
   - Install software on device
   - Wait for installation to complete

4. **Reboot**
   - Reboot device
   - Wait for device to come back online (up to 10 minutes)

5. **Post-flight Validation**
   - Collect metrics again
   - Compare with pre-flight baseline
   - Log differences for admin review

6. **Multi-version Path**
   - Repeat steps 1-5 for each version in upgrade path
   - Update device status after each version

## Documentation

- [Usage Guide](docs/USAGE.md) - Detailed usage instructions
- [Architecture](docs/ARCHITECTURE.md) - System architecture and design
- [Examples](examples/) - Configuration and job examples

## Troubleshooting

### Device Skipped
**Cause**: Current version not found in upgrade_paths.json  
**Solution**: Add version to upgrade paths or update device manually

### Insufficient Disk Space
**Cause**: Available disk space below minimum threshold  
**Solution**: Free up space on firewall or adjust `validation.min_disk_gb`

### Validation Failed
**Cause**: Metrics outside acceptable margins  
**Solution**: Review validation results, adjust margins if appropriate

### Rate Limiting
**Cause**: Too many API requests to Panorama  
**Solution**: Reduce `panorama.rate_limit` or `workers.max`

### Daemon Won't Start
**Cause**: Permission issues or missing directories  
**Solution**: Run `python scripts/init_system.py` and check permissions

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
│   ├── logging_config.py      # Logging system
│   ├── models.py              # Data models
│   ├── constants.py           # Constants
│   └── utils/
│       └── file_ops.py        # File operations
├── examples/                  # Example configurations
├── docs/                      # Documentation
├── scripts/                   # Utility scripts
└── tests/                     # Test suite (future)
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

