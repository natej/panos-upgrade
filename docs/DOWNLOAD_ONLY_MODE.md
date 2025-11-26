# Download-Only Mode - Complete Guide

## Overview

Download-only mode allows you to pre-stage PAN-OS software images on firewalls without performing the actual upgrade. This is useful for:

- **Staging during business hours** - Download images when network is available
- **Faster maintenance windows** - Images already downloaded, only install/reboot needed
- **Reduced Panorama load** - Downloads go directly to firewalls
- **Bulk preparation** - Pre-stage 230+ devices efficiently

## Key Features

✅ **Direct Firewall Connections** - Downloads bypass Panorama  
✅ **Smart Skip Detection** - Automatically skips already-downloaded versions  
✅ **Bulk Queueing** - Queue all 230+ devices with one command  
✅ **Disk Space Validation** - Pre-checks before downloading  
✅ **Progress Tracking** - Monitor downloads across all devices  
✅ **Conflict Detection** - Prevents mixing with normal upgrades  

## Architecture

### Connection Flow

**Normal Upgrade:**
```
CLI → Daemon → Panorama → (proxy) → Firewall
```

**Download-Only:**
```
CLI → Daemon → Panorama (device discovery only)
              ↓
          Direct → Firewall (mgmt_ip) for downloads
```

### Workflow

```
1. Device Discovery
   └─ Query Panorama for all connected devices
   └─ Extract: serial, hostname, mgmt_ip, version, model
   └─ Save to inventory.json

2. Bulk Queue (optional)
   └─ Load inventory
   └─ Check upgrade paths
   └─ Create download_only jobs for all devices

3. Download Execution (per device)
   └─ Load device info from inventory
   └─ Connect directly to firewall mgmt_ip
   └─ Check disk space
   └─ Check for already-downloaded versions
   └─ For each version in upgrade path:
      ├─ Skip if already downloaded
      └─ Download if not present
   └─ Mark as download_complete

4. Later: Normal Upgrade
   └─ Images already present
   └─ Install → Reboot → Validate
```

## Setup

### Configure Firewall Credentials

Download-only mode connects directly to firewalls using username/password:

```bash
panos-upgrade config set firewall.username admin
panos-upgrade config set firewall.password YOUR_PASSWORD
```

## Usage

### Step 1: Discover Devices

```bash
panos-upgrade device discover
```

**Output:**
```
Discovering devices from Panorama...

✓ Discovery complete:
  Total devices: 230
  New devices: 230
  Updated devices: 0

Inventory saved to: /opt/panos-upgrade/devices/inventory.json
```

### Step 2: Queue All Devices for Download

```bash
# Dry run first to see what would happen
panos-upgrade download queue-all --dry-run

# Actually queue all devices
panos-upgrade download queue-all
```

**Output:**
```
Queueing devices for download...

Queued devices for download:

  001234567890 (fw-dc1-01): 10.0.2 → 10.1.0 → 10.5.1 → 11.1.0
  001234567891 (fw-dc1-02): 10.5.1 → 11.1.0
  001234567892 (fw-dc2-01): 11.0.0 → 11.0.3 → 11.1.0
  ... and 212 more

Skipped devices:

  001234567999 (fw-old): 9.1.0 (no upgrade path)
  ... and 14 more

Summary:
  ✓ Queued: 215 devices
  ⊘ Skipped (no upgrade path): 15 devices
  ⊘ Skipped (existing job): 0 devices
  ✗ Errors: 0 devices

Total: 230 devices processed

Monitor with:
  panos-upgrade daemon status
  panos-upgrade download status
```

### Step 3: Monitor Progress

```bash
# Overall daemon status
panos-upgrade daemon status

# Download-specific status
panos-upgrade download status

# Specific device
panos-upgrade device status 001234567890

# Watch in real-time
watch -n 5 'panos-upgrade download status'
```

### Step 4: Verify Downloads Complete

```bash
# Check device status
panos-upgrade device status 001234567890
```

**Status Output:**
```json
{
  "serial": "001234567890",
  "upgrade_status": "download_complete",
  "upgrade_message": "Downloaded 2 version(s): 10.5.1, 11.1.0. Skipped 1 (already present): 10.1.0",
  "downloaded_versions": ["10.5.1", "11.1.0"],
  "skipped_versions": ["10.1.0"],
  "ready_for_install": true
}
```

## Individual Device Download

### Submit Single Device

```bash
# Download only for one device
panos-upgrade job submit --device 001234567890 --download-only

# Dry run
panos-upgrade job submit --device 001234567890 --download-only --dry-run
```

## Smart Skip Detection

When you run download-only mode, the system automatically:

1. **Queries the firewall** for existing software versions
2. **Identifies already-downloaded** versions
3. **Skips downloads** for versions already present
4. **Tracks separately** what was downloaded vs skipped

### Example: Re-running After Partial Download

If a previous download was interrupted or you're running queue-all again:

**First run:**
```
Downloaded 3 version(s): 10.1.0, 10.5.1, 11.1.0
```

**Second run (same device):**
```
All 3 version(s) already downloaded: 10.1.0, 10.5.1, 11.1.0
```

The job completes successfully without re-downloading.

## Conflict Detection

Download-only and normal upgrades cannot run concurrently on the same device.

### Scenario 1: Download-only job exists, try normal upgrade

```bash
$ panos-upgrade job submit --device 001234567890
Error: Device 001234567890 has an existing download_only job. 
Cannot submit standalone job. Download-only and normal upgrades 
cannot run concurrently. (Job ID: bulk-download-abc123)

Cannot mix download-only and normal upgrades
Cancel existing job first: panos-upgrade job cancel bulk-download-abc123
```

### Scenario 2: Normal upgrade exists, try download-only

```bash
$ panos-upgrade job submit --device 001234567890 --download-only
Error: Device 001234567890 has an existing standalone job...
```

## Monitoring

### Daemon Status

```bash
$ panos-upgrade daemon status

Daemon Status:
  Running: True
  Workers: 10/10 busy
  Active Jobs: 10
  Pending Jobs: 205
  Completed Jobs: 15
```

### Download Status

```bash
$ panos-upgrade download status

Download Status Summary:
  Total devices tracked: 230
  Download complete: 150
  Currently downloading: 10
  Failed: 5
```

### Device Status

```bash
$ panos-upgrade device status 001234567890
```

Shows:
- Current download phase
- Progress percentage
- Downloaded versions list
- Skipped versions list
- Ready for install flag

## Logs

### Successful Download

```
2025-11-23 12:00:00 - INFO - Starting download-only for device 001234567890
2025-11-23 12:00:01 - INFO - Connecting directly to firewall: 10.1.1.10
2025-11-23 12:00:02 - INFO - Disk space check passed: 15.50 GB available
2025-11-23 12:00:03 - INFO - Found 1 version(s) already downloaded on 001234567890: 10.1.0
2025-11-23 12:00:03 - INFO - Version 10.1.0 already downloaded on 001234567890, skipping
2025-11-23 12:00:04 - INFO - Downloading version 10.5.1 (2/3)
2025-11-23 12:00:14 - INFO - Download completed for 10.5.1 on 10.1.1.10
2025-11-23 12:00:15 - INFO - Downloaded 10.5.1
2025-11-23 12:00:16 - INFO - Downloading version 11.1.0 (3/3)
2025-11-23 12:00:26 - INFO - Download completed for 11.1.0 on 10.1.1.10
2025-11-23 12:00:27 - INFO - Downloaded 11.1.0
2025-11-23 12:00:27 - INFO - Download complete for 001234567890: 2 downloaded, 1 skipped (already present)
```

### All Versions Already Present

```
2025-11-23 12:00:00 - INFO - Starting download-only for device 001234567890
2025-11-23 12:00:01 - INFO - Connecting directly to firewall: 10.1.1.10
2025-11-23 12:00:02 - INFO - Disk space check passed: 15.50 GB available
2025-11-23 12:00:03 - INFO - Found 3 version(s) already downloaded on 001234567890: 10.1.0, 10.5.1, 11.1.0
2025-11-23 12:00:03 - INFO - Version 10.1.0 already downloaded on 001234567890, skipping
2025-11-23 12:00:03 - INFO - Version 10.5.1 already downloaded on 001234567890, skipping
2025-11-23 12:00:03 - INFO - Version 11.1.0 already downloaded on 001234567890, skipping
2025-11-23 12:00:03 - INFO - Download complete for 001234567890: all versions already present
```

## Best Practices

### 1. Always Discover First

```bash
# Refresh device inventory before bulk operations
panos-upgrade device discover
panos-upgrade download queue-all
```

### 2. Test with Dry Run

```bash
# See what would be queued
panos-upgrade download queue-all --dry-run
```

### 3. Monitor Progress

```bash
# Real-time monitoring
watch -n 10 'panos-upgrade download status'
```

### 4. Check Disk Space

Devices need space for all versions in upgrade path (typically 2-3 GB per version).

### 5. Stagger Downloads

Use worker configuration to control concurrent downloads:

```bash
# Limit to 20 concurrent downloads
panos-upgrade config set workers.max 20
panos-upgrade daemon restart
```

## Troubleshooting

### Device Not in Inventory

```
Error: Device 001234567890 not found in inventory. 
Run 'panos-upgrade device discover' first
```

**Solution:**
```bash
panos-upgrade device discover
```

### No Management IP

```
Error: No management IP for device 001234567890
```

**Solution:** Check Panorama - device might not have management IP configured

### Connection Failed

```
ERROR: Failed to connect to firewall 10.1.1.10
```

**Solution:**
- Verify firewall management IP is reachable
- Check firewall API is enabled
- Verify credentials are correct
- Check firewall rules

### Insufficient Disk Space

```
ERROR: Insufficient disk space: 1.50 GB available, 5.00 GB required
```

**Solution:**
- Free up space on firewall
- Adjust `validation.min_disk_gb` setting

## Advanced Usage

### Download Specific Devices

Create a file with serials:

```bash
# serials.txt
001234567890
001234567891
001234567892
```

Then queue them:

```bash
for serial in $(cat serials.txt); do
  panos-upgrade job submit --device $serial --download-only
done
```

### Monitor Specific Group

```bash
# Check all devices in a version group
for serial in 001234567890 001234567891 001234567892; do
  echo "Device: $serial"
  panos-upgrade device status $serial | grep upgrade_status
  echo
done
```

### Resume Failed Downloads

Failed downloads can be retried:

```bash
# Find failed devices
panos-upgrade job list --status failed

# Resubmit
panos-upgrade job submit --device FAILED_SERIAL --download-only
```

## Configuration

### Required Settings

```json
{
  "panorama": {
    "host": "panorama.example.com",
    "api_key": "YOUR_API_KEY"
  },
  "firewall": {
    "username": "admin",
    "password": "YOUR_PASSWORD"
  },
  "validation": {
    "min_disk_gb": 5.0
  },
  "paths": {
    "upgrade_paths": "/opt/panos-upgrade/config/upgrade_paths.json"
  }
}
```

## Web Integration

### Submit Download-Only Job

```python
job_data = {
    "job_id": f"web-{uuid.uuid4()}",
    "type": "download_only",
    "devices": ["001234567890"],
    "dry_run": False,
    "download_only": True,
    "created_at": datetime.utcnow().isoformat() + "Z"
}

atomic_write_json(pending_dir / f"{job_id}.json", job_data)
```

### Check Download Status

```python
status = read_json(f"/opt/panos-upgrade/status/devices/001234567890.json")

if status["upgrade_status"] == "download_complete":
    print(f"Ready for install!")
    print(f"Downloaded: {', '.join(status['downloaded_versions'])}")
    print(f"Skipped: {', '.join(status['skipped_versions'])}")
```

## Complete Example

### Bulk Download All Devices

```bash
# Step 1: Discover devices
panos-upgrade device discover

# Step 2: Start daemon with appropriate workers
panos-upgrade daemon start --workers 20

# Step 3: Queue all devices
panos-upgrade download queue-all

# Step 4: Monitor progress
watch -n 10 'panos-upgrade download status'

# Step 5: Wait for completion (check logs)
tail -f /opt/panos-upgrade/logs/text/panos-upgrade-*.log

# Step 6: Verify all complete
panos-upgrade download status
```

### Later: Perform Actual Upgrades

Once downloads are complete, perform normal upgrades (images already present):

```bash
# Upgrades will be faster since images are pre-staged
panos-upgrade job submit --device 001234567890
```

## Comparison: Normal vs Download-Only

| Feature | Normal Upgrade | Download-Only |
|---------|---------------|---------------|
| Connection | Via Panorama | Direct to firewall |
| Operations | Download + Install + Reboot | Download only |
| Validation | Full (sessions, routes, ARP) | Disk space only |
| Skip Detection | Yes (skips existing) | Yes (skips existing) |
| Duration | ~25 min per device | ~5 min per device |
| Panorama Load | High | Low (discovery only) |
| Use Case | Complete upgrade | Pre-staging |

## FAQ

**Q: Can I run download-only and normal upgrades at the same time?**  
A: No, they are mutually exclusive per device to prevent conflicts.

**Q: What happens if I run queue-all again?**  
A: Already-downloaded versions are automatically skipped. Only missing versions are downloaded.

**Q: Do I need to download again for normal upgrade?**  
A: No! Normal upgrades now detect pre-downloaded images and skip the download phase automatically.

**Q: Can I cancel a download-only job?**  
A: Yes, same as normal jobs: `panos-upgrade job cancel JOB_ID`

**Q: How much disk space is needed?**  
A: Typically 2-3 GB per version. For a 3-version path, need ~6-9 GB free.

**Q: What if firewall management IP is not reachable?**  
A: Job will fail. Check network connectivity and firewall configuration.

## Next Steps

After successful downloads:
1. Verify all devices show `download_complete` status
2. Schedule maintenance window
3. Run normal upgrades (will be faster with pre-staged images)
4. Monitor and validate

## Reference

- Device Discovery: `panos-upgrade device discover`
- Bulk Queue: `panos-upgrade download queue-all`
- Single Device: `panos-upgrade job submit --device SERIAL --download-only`
- Monitor: `panos-upgrade download status`
- Logs: `/opt/panos-upgrade/logs/`
