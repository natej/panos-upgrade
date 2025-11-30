# PAN-OS Upgrade Manager - Usage Guide

## Installation

```bash
# Install the package
pip install -e .

# Initialize the system
python scripts/init_system.py
```

## Configuration

### 1. Set Panorama Connection (for device discovery)

```bash
panos-upgrade config set panorama.host panorama.example.com
panos-upgrade config set panorama.api_key YOUR_API_KEY
```

### 2. Set Firewall Credentials (for direct connections)

```bash
panos-upgrade config set firewall.username admin
panos-upgrade config set firewall.password YOUR_PASSWORD
```

### 3. Configure Upgrade Paths

Edit `/var/lib/panos-upgrade/config/upgrade_paths.json`:

```json
{
  "10.0.2": ["10.1.0", "10.5.1", "11.1.0"],
  "10.5.1": ["11.1.0"]
}
```

### 4. Discover Devices

Before running any upgrades, discover devices from Panorama:

```bash
panos-upgrade device discover
```

This queries Panorama for connected devices, connects to each firewall to determine HA state, and saves the information to `inventory.json`. This step is **required** before any upgrade or download operations.

Discovery captures for each device:
- Serial number, hostname, management IP, software version, model
- Device type: `standalone`, `ha_pair`, or `unknown`
- HA state: `active`, `passive`, `standalone`, or `unknown`
- Peer serial (for HA pair members)

### 5. Export Devices to CSV (Optional)

After discovery, export devices to CSV files for use with bulk commands:

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

Note: The `serial_1` and `serial_2` columns are just labels - the column order doesn't determine HA role. The active member is placed in `serial_1` based on the `ha_state` captured during discovery.

### 6. Adjust Settings (Optional)

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

### Bulk Upgrade from CSV

```bash
# Create CSV with device serials
cat > devices.csv << EOF
serial,hostname
001234567890,fw-dc1-01
001234567891,fw-dc1-02
EOF

# Queue all devices for upgrade
panos-upgrade upgrade devices.csv

# Dry run first
panos-upgrade upgrade devices.csv --dry-run
```

### Standalone Firewall

```bash
# Submit upgrade job for a single device
panos-upgrade job submit --device 001234567890

# Dry run (no actual changes)
panos-upgrade job submit --device 001234567890 --dry-run
```

### HA Pair

```bash
# Submit upgrade job for HA pair (specify both serials)
panos-upgrade job submit --ha-pair 001234567890 001234567891
```

### Bulk HA Pairs from CSV

```bash
# Create CSV with both serials for each pair
# Note: Column order doesn't matter - active/passive is discovered dynamically
cat > ha_pairs.csv << EOF
serial_1,serial_2
001234567890,001234567891
001234567892,001234567893
EOF

# Queue all HA pairs
panos-upgrade upgrade-ha-pairs ha_pairs.csv
```

### Download-Only Mode

```bash
# Pre-stage images for standalone devices
panos-upgrade download devices.csv

# Pre-stage images for HA pairs (both members)
panos-upgrade download-ha-pairs ha_pairs.csv

# Single device download-only
panos-upgrade job submit --device 001234567890 --download-only
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

All operations connect **directly to firewalls** using management IPs from the device inventory.

1. **Lookup Device**
   - Get management IP from `inventory.json`
   - Connect directly to firewall

2. **Pre-flight Validation**
   - Check disk space
   - Collect TCP sessions, routes, ARP entries
   - Verify minimum requirements

3. **Software Check**
   - Refresh available software versions

4. **Download**
   - Check if image already downloaded (skip if present)
   - Download software image directly to firewall
   - Monitor download progress

5. **Install**
   - Install software
   - Wait for installation to complete

6. **Reboot**
   - Reboot device
   - Wait for device to come online (exponential backoff)

7. **Post-flight Validation**
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

### Cannot Connect to Firewall

If experiencing connection issues to firewalls:

1. Verify firewall management IP is accessible from the daemon host
2. Check firewall credentials are correct:
   ```bash
   panos-upgrade config set firewall.username admin
   panos-upgrade config set firewall.password YOUR_PASSWORD
   ```
3. Ensure firewall API access is enabled
4. Check network/firewall rules between daemon host and firewall management IPs

### Device Not Found in Inventory

If you see "Device not found in inventory" errors:

```bash
panos-upgrade device discover
```

This refreshes the inventory from Panorama.

## Best Practices

1. **Discover First**: Always run `panos-upgrade device discover` before upgrades
2. **Test with Dry Run**: Always test with `--dry-run` first
3. **Start Small**: Begin with a few devices to validate the process
4. **Monitor Logs**: Keep an eye on logs during upgrades
5. **Backup Configuration**: Ensure Panorama backups are current
6. **Maintenance Windows**: Schedule upgrades during maintenance windows
7. **HA Pairs**: Always upgrade HA pairs together to maintain consistency
8. **Network Access**: Ensure daemon host can reach all firewall management IPs

