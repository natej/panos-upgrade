# PAN-OS Upgrade Manager - Quick Reference

## Installation

```bash
pip install -e .
python scripts/init_system.py
```

## Initial Configuration

```bash
panos-upgrade config set panorama.host panorama.example.com
panos-upgrade config set panorama.api_key YOUR_API_KEY
cp examples/upgrade_paths.json /var/lib/panos-upgrade/config/
```

## Daemon Commands

```bash
# Start daemon
panos-upgrade daemon start --workers 10

# Stop daemon
panos-upgrade daemon stop

# Restart daemon
panos-upgrade daemon restart

# Check status
panos-upgrade daemon status
```

## Job Commands

```bash
# Submit standalone device
panos-upgrade job submit --device 001234567890

# Submit HA pair
panos-upgrade job submit --ha-pair datacenter-1

# Dry run
panos-upgrade job submit --device 001234567890 --dry-run

# List all jobs
panos-upgrade job list

# List by status
panos-upgrade job list --status active
panos-upgrade job list --status completed
panos-upgrade job list --status failed

# Check job status
panos-upgrade job status job-001

# Cancel job
panos-upgrade job cancel job-001
```

## Device Commands

```bash
# List devices
panos-upgrade device list

# List HA pairs
panos-upgrade device list --ha-pairs

# Check device status
panos-upgrade device status 001234567890

# Validate device
panos-upgrade device validate 001234567890

# View metrics
panos-upgrade device metrics 001234567890
```

## Configuration Commands

```bash
# Set value
panos-upgrade config set KEY VALUE

# Show configuration
panos-upgrade config show

# Common settings
panos-upgrade config set workers.max 20
panos-upgrade config set panorama.rate_limit 15
panos-upgrade config set validation.min_disk_gb 5.0
panos-upgrade config set validation.tcp_session_margin 5.0
```

## Upgrade Path Commands

```bash
# Show all paths
panos-upgrade path show

# Show specific version
panos-upgrade path show --version 10.0.2

# Validate paths file
panos-upgrade path validate
```

## File Locations

### Configuration
- Main config: `/var/lib/panos-upgrade/config/config.json`
- Upgrade paths: `/var/lib/panos-upgrade/config/upgrade_paths.json`

### Status Files
- Daemon: `/var/lib/panos-upgrade/status/daemon.json`
- Workers: `/var/lib/panos-upgrade/status/workers.json`
- Devices: `/var/lib/panos-upgrade/status/devices/{serial}.json`

### Logs
- JSON: `/var/lib/panos-upgrade/logs/structured/`
- Text: `/var/lib/panos-upgrade/logs/text/`

### Queues
- Pending: `/var/lib/panos-upgrade/queue/pending/`
- Active: `/var/lib/panos-upgrade/queue/active/`
- Completed: `/var/lib/panos-upgrade/queue/completed/`
- Cancelled: `/var/lib/panos-upgrade/queue/cancelled/`

### Validation
- Pre-flight: `/var/lib/panos-upgrade/validation/pre_flight/`
- Post-flight: `/var/lib/panos-upgrade/validation/post_flight/`

### Commands
- Incoming: `/var/lib/panos-upgrade/commands/incoming/`
- Processed: `/var/lib/panos-upgrade/commands/processed/`

## Web App Integration

### Submit Job (Python)

```python
import json
import uuid
from pathlib import Path
from datetime import datetime

job_id = f"web-{uuid.uuid4()}"
job_data = {
    "job_id": job_id,
    "type": "standalone",
    "devices": ["001234567890"],
    "dry_run": False,
    "created_at": datetime.utcnow().isoformat() + "Z"
}

# Write atomically
pending_dir = Path("/var/lib/panos-upgrade/queue/pending")
temp_file = pending_dir / f".{job_id}.tmp"
final_file = pending_dir / f"{job_id}.json"

with open(temp_file, 'w') as f:
    json.dump(job_data, f, indent=2)

temp_file.rename(final_file)
```

### Read Status (Python)

```python
import json
from pathlib import Path

# Read device status
status_file = Path(f"/var/lib/panos-upgrade/status/devices/001234567890.json")
with open(status_file) as f:
    device_status = json.load(f)

print(f"Status: {device_status['upgrade_status']}")
print(f"Progress: {device_status['progress']}%")
print(f"Phase: {device_status['current_phase']}")
```

### Cancel Job (Python)

```python
import json
import uuid
from pathlib import Path
from datetime import datetime

command_data = {
    "command": "cancel_upgrade",
    "target": "job",
    "job_id": "job-001",
    "reason": "Admin takeover",
    "timestamp": datetime.utcnow().isoformat() + "Z"
}

# Write atomically
commands_dir = Path("/var/lib/panos-upgrade/commands/incoming")
command_id = f"cancel-{uuid.uuid4()}"
temp_file = commands_dir / f".{command_id}.tmp"
final_file = commands_dir / f"{command_id}.json"

with open(temp_file, 'w') as f:
    json.dump(command_data, f, indent=2)

temp_file.rename(final_file)
```

## Upgrade Paths Format

```json
{
  "10.0.2": ["10.1.0", "10.5.1", "11.1.0"],
  "10.5.1": ["11.1.0"],
  "11.0.0": ["11.0.3", "11.1.0"]
}
```

## Job Status Values

- `pending` - Waiting to start
- `validating` - Running pre-flight validation
- `downloading` - Downloading software
- `installing` - Installing software
- `rebooting` - Device rebooting
- `complete` - Successfully completed
- `failed` - Failed with errors
- `cancelled` - Cancelled by admin
- `skipped` - Skipped (version not in paths)

## Log Viewing

```bash
# Text logs
tail -f /var/lib/panos-upgrade/logs/text/panos-upgrade-*.log

# JSON logs
tail -f /var/lib/panos-upgrade/logs/structured/panos-upgrade-*.json | jq

# Systemd journal
sudo journalctl -u panos-upgrade -f
```

## Troubleshooting

### Check daemon is running
```bash
panos-upgrade daemon status
systemctl status panos-upgrade
```

### Check for errors
```bash
grep ERROR /var/lib/panos-upgrade/logs/text/panos-upgrade-*.log
```

### Check device status
```bash
cat /var/lib/panos-upgrade/status/devices/SERIAL.json | jq
```

### Check worker status
```bash
cat /var/lib/panos-upgrade/status/workers.json | jq
```

### Manual cleanup
```bash
# Clear pending queue
rm /var/lib/panos-upgrade/queue/pending/*.json

# Clear old completed jobs
find /var/lib/panos-upgrade/queue/completed -mtime +30 -delete
```

## Configuration Values

### Workers
- `workers.max` - Max worker threads (1-50, default: 5)
- `workers.queue_size` - Queue size (default: 1000)

### Panorama
- `panorama.host` - Panorama hostname
- `panorama.api_key` - API key
- `panorama.rate_limit` - Requests/min (default: 10)
- `panorama.timeout` - Timeout seconds (default: 300)

### Validation
- `validation.tcp_session_margin` - TCP % margin (default: 5.0)
- `validation.route_margin` - Route count margin (default: 0.0)
- `validation.arp_margin` - ARP count margin (default: 0.0)
- `validation.min_disk_gb` - Min disk GB before each image download; set to largest image size (default: 5.0)

### Logging
- `logging.level` - Log level (default: INFO)
- `logging.max_size_mb` - Max log size (default: 100)
- `logging.retention_days` - Retention days (default: 30)

## Common Workflows

### Test Before Production
```bash
# 1. Dry run
panos-upgrade job submit --device TEST_SERIAL --dry-run

# 2. Check logs
tail -f /var/lib/panos-upgrade/logs/text/*.log

# 3. Review status
panos-upgrade device status TEST_SERIAL
```

### Upgrade Single Device
```bash
# 1. Validate
panos-upgrade device validate 001234567890

# 2. Submit
panos-upgrade job submit --device 001234567890

# 3. Monitor
watch -n 5 'panos-upgrade device status 001234567890'
```

### Upgrade HA Pair
```bash
# 1. Submit pair
panos-upgrade job submit --ha-pair datacenter-1

# 2. Monitor both devices
watch -n 5 'panos-upgrade job list --status active'
```

### Bulk Upgrade
```bash
# Create job files
for serial in $(cat device_list.txt); do
  panos-upgrade job submit --device $serial
done

# Monitor progress
watch -n 10 'panos-upgrade daemon status'
```

## Emergency Procedures

### Stop All Upgrades
```bash
sudo systemctl stop panos-upgrade
```

### Cancel Specific Job
```bash
panos-upgrade job cancel JOB_ID
```

### Manual Takeover
1. Cancel the job: `panos-upgrade job cancel JOB_ID`
2. Check device status: `panos-upgrade device status SERIAL`
3. Review validation results in `/var/lib/panos-upgrade/validation/`
4. Take manual action via Panorama GUI

## Performance Tuning

### For 200+ Devices
```bash
panos-upgrade config set workers.max 20
panos-upgrade config set panorama.rate_limit 20
panos-upgrade config set workers.queue_size 2000
panos-upgrade daemon restart
```

### For Slow Networks
```bash
panos-upgrade config set panorama.timeout 600
panos-upgrade daemon restart
```

## Documentation Links

- Full Usage Guide: `docs/USAGE.md`
- Architecture Details: `docs/ARCHITECTURE.md`
- Deployment Guide: `docs/DEPLOYMENT.md`
- Project Summary: `PROJECT_SUMMARY.md`

