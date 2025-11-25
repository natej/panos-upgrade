# PAN-OS Upgrade Manager - Usage Guide

## Installation

```bash
# Install the package
pip install -e .

# Initialize the system
python scripts/init_system.py
```

## Configuration

### 1. Set Panorama Connection

```bash
panos-upgrade config set panorama.host panorama.example.com
panos-upgrade config set panorama.api_key YOUR_API_KEY
```

### 2. Configure Upgrade Paths

Edit `/var/lib/panos-upgrade/config/upgrade_paths.json`:

```json
{
  "10.0.2": ["10.1.0", "10.5.1", "11.1.0"],
  "10.5.1": ["11.1.0"]
}
```

### 3. Adjust Settings (Optional)

```bash
# Set number of worker threads (1-50)
panos-upgrade config set workers.max 10

# Set API rate limit (requests per minute)
panos-upgrade config set panorama.rate_limit 15

# Set minimum disk space requirement (GB)
panos-upgrade config set validation.min_disk_gb 5.0

# Set TCP session validation margin (percentage)
panos-upgrade config set validation.tcp_session_margin 5.0
```

## Starting the Daemon

```bash
# Start with default settings
panos-upgrade daemon start

# Start with custom worker count
panos-upgrade daemon start --workers 10

# Check daemon status
panos-upgrade daemon status

# Stop the daemon
panos-upgrade daemon stop
```

## Submitting Upgrade Jobs

### Standalone Firewall

```bash
# Submit upgrade job for a single device
panos-upgrade job submit --device 001234567890

# Dry run (no actual changes)
panos-upgrade job submit --device 001234567890 --dry-run
```

### HA Pair

```bash
# Submit upgrade job for HA pair
panos-upgrade job submit --ha-pair datacenter-1
```

## Monitoring Jobs

```bash
# List all jobs
panos-upgrade job list

# List jobs by status
panos-upgrade job list --status active
panos-upgrade job list --status completed
panos-upgrade job list --status failed

# Check specific job status
panos-upgrade job status job-001
```

## Device Operations

```bash
# List all devices
panos-upgrade device list

# List HA pairs
panos-upgrade device list --ha-pairs

# Check device status
panos-upgrade device status 001234567890

# Validate device readiness
panos-upgrade device validate 001234567890

# View device metrics
panos-upgrade device metrics 001234567890
```

## Cancelling Upgrades

### Via CLI

```bash
panos-upgrade job cancel job-001
```

### Via Web Application

Create a command file in `/var/lib/panos-upgrade/commands/incoming/`:

```json
{
  "command": "cancel_upgrade",
  "target": "job",
  "job_id": "job-001",
  "reason": "Admin takeover required",
  "timestamp": "2025-11-21T12:00:00Z"
}
```

The daemon will automatically process this command.

## Web Application Integration

### Reading Status

The web application can read JSON files from:

- **Daemon Status**: `/var/lib/panos-upgrade/status/daemon.json`
- **Worker Status**: `/var/lib/panos-upgrade/status/workers.json`
- **Device Status**: `/var/lib/panos-upgrade/status/devices/{serial}.json`
- **Validation Results**: `/var/lib/panos-upgrade/validation/post_flight/{serial}_{timestamp}.json`

### Submitting Jobs

Create a job file in `/var/lib/panos-upgrade/queue/pending/`:

```json
{
  "job_id": "unique-job-id",
  "type": "standalone",
  "devices": ["001234567890"],
  "dry_run": false,
  "created_at": "2025-11-21T12:00:00Z"
}
```

### Sending Commands

Create a command file in `/var/lib/panos-upgrade/commands/incoming/`:

```json
{
  "command": "cancel_upgrade",
  "target": "device",
  "device_serial": "001234567890",
  "reason": "Emergency maintenance",
  "timestamp": "2025-11-21T12:00:00Z"
}
```

## Upgrade Process Flow

1. **Pre-flight Validation**
   - Check disk space
   - Collect TCP sessions, routes, ARP entries
   - Verify minimum requirements

2. **Download**
   - Download software image
   - Monitor download progress

3. **Install**
   - Install software
   - Wait for installation to complete

4. **Reboot**
   - Reboot device
   - Wait for device to come online

5. **Post-flight Validation**
   - Collect metrics again
   - Compare with pre-flight
   - Log differences

## Logging

Logs are stored in two formats:

- **JSON Logs**: `/var/lib/panos-upgrade/logs/structured/`
- **Text Logs**: `/var/lib/panos-upgrade/logs/text/`

View logs:

```bash
# Text logs
tail -f /var/lib/panos-upgrade/logs/text/panos-upgrade-*.log

# JSON logs (for parsing)
tail -f /var/lib/panos-upgrade/logs/structured/panos-upgrade-*.json
```

## Troubleshooting

### Device Skipped

If a device is skipped, check:
- Device's current version exists in `upgrade_paths.json`
- Log files for skip reason

### Insufficient Disk Space

Increase available disk space on the firewall or adjust the minimum requirement:

```bash
panos-upgrade config set validation.min_disk_gb 3.0
```

### Validation Failed

Check validation results in:
```
/var/lib/panos-upgrade/validation/post_flight/{serial}_{timestamp}.json
```

Adjust validation margins if needed:

```bash
panos-upgrade config set validation.tcp_session_margin 10.0
```

### Rate Limiting

If experiencing rate limit issues with Panorama:

```bash
panos-upgrade config set panorama.rate_limit 5
```

## Best Practices

1. **Test with Dry Run**: Always test with `--dry-run` first
2. **Start Small**: Begin with a few devices to validate the process
3. **Monitor Logs**: Keep an eye on logs during upgrades
4. **Backup Configuration**: Ensure Panorama backups are current
5. **Maintenance Windows**: Schedule upgrades during maintenance windows
6. **HA Pairs**: Always upgrade HA pairs together to maintain consistency

