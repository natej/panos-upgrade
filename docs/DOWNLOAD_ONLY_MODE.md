# Download-Only Mode - Complete Guide

## Overview

Download-only mode allows you to pre-stage PAN-OS software images on firewalls without performing the actual upgrade. This is useful for:

- **Staging during business hours** - Download images when network is available
- **Faster maintenance windows** - Images already downloaded, only install/reboot needed
- **Reduced Panorama load** - Downloads go directly to firewalls
- **Bulk preparation** - Pre-stage 230+ devices efficiently

## Key Features

✅ **Direct Firewall Connections** - Downloads bypass Panorama  
✅ **Hash Verification** - Validates download integrity with SHA256  
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
   └─ For each version in upgrade path:
      ├─ Download software
      ├─ Wait for completion
      ├─ Query firewall for file hash
      ├─ Verify hash against expected
      └─ Store verified hash
   └─ Mark as download_complete

4. Later: Normal Upgrade
   └─ Images already present
   └─ Install → Reboot → Validate
```

## Setup

### 1. Configure Hash Database

Copy the example and customize with official PAN-OS hashes:

```bash
cp examples/version_hashes.json /var/lib/panos-upgrade/config/
```

Edit `/var/lib/panos-upgrade/config/version_hashes.json`:

```json
{
  "10.1.0": {
    "sha256": "OFFICIAL_SHA256_HASH_FROM_PALO_ALTO",
    "filename": "PanOS_3200-10.1.0",
    "size_mb": 460,
    "release_date": "2023-06-20"
  }
}
```

**Where to get official hashes:**
- Palo Alto Networks support portal
- Software release notes
- Customer support

### 2. Configure Hash Verification

```bash
# Enable hash verification (default: true)
panos-upgrade config set validation.verify_hashes true

# Fail if hash not in database (default: false)
panos-upgrade config set validation.fail_on_missing_hash false
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

Inventory saved to: /var/lib/panos-upgrade/devices/inventory.json
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
  "upgrade_message": "Downloaded and verified versions: 10.1.0, 10.5.1, 11.1.0",
  "downloaded_versions": ["10.1.0", "10.5.1", "11.1.0"],
  "version_hashes": {
    "10.1.0": "b2c3d4e5f6a7b8c9...",
    "10.5.1": "c3d4e5f6a7b8c9d0...",
    "11.1.0": "f6a7b8c9d0e1f2a3..."
  },
  "hash_verification": {
    "10.1.0": "passed",
    "10.5.1": "passed",
    "11.1.0": "passed"
  },
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

## Hash Verification

### How It Works

1. **Download completes** on firewall
2. **Query firewall** for software info: `show system software info`
3. **Extract SHA256** from firewall response
4. **Load expected hash** from `version_hashes.json`
5. **Compare hashes** - Must match exactly
6. **Log result** - Pass or fail with details
7. **Store hash** in device status for audit trail

### Verification Modes

**Strict Mode** (fail if hash not in database):
```bash
panos-upgrade config set validation.fail_on_missing_hash true
```

**Lenient Mode** (warn if hash not in database):
```bash
panos-upgrade config set validation.fail_on_missing_hash false
```

### Hash Mismatch Handling

If hash doesn't match:
```
2025-11-23 12:05:03 - ERROR - Hash verification FAILED for 10.1.0
2025-11-23 12:05:03 - ERROR - Expected: b2c3d4e5f6a7b8c9...
2025-11-23 12:05:03 - ERROR - Actual:   XXXXXXXXXXXXXXXX...
2025-11-23 12:05:03 - ERROR - Download may be corrupted or tampered!
2025-11-23 12:05:03 - ERROR - Upgrade aborted for security reasons
```

Device status:
```json
{
  "upgrade_status": "failed",
  "errors": [
    {
      "phase": "download",
      "message": "Hash verification failed for 10.1.0",
      "details": "Expected: b2c3..., Actual: XXXX..."
    }
  ]
}
```

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
- Hash verification results
- Ready for install flag

## Logs

### Successful Download

```
2025-11-23 12:00:00 - INFO - Starting download-only for device 001234567890
2025-11-23 12:00:01 - INFO - Connecting directly to firewall: 10.1.1.10
2025-11-23 12:00:02 - INFO - Disk space check passed: 15.50 GB available
2025-11-23 12:00:03 - INFO - Downloading version 10.1.0 (1/3)
2025-11-23 12:00:03 - INFO - Downloading version 10.1.0 to 10.1.1.10
2025-11-23 12:00:13 - INFO - Download completed for 10.1.0 on 10.1.1.10
2025-11-23 12:00:14 - INFO - Verifying download integrity for 10.1.0
2025-11-23 12:00:15 - INFO - Retrieved hash for 10.1.0: b2c3d4e5f6a7b8c9...
2025-11-23 12:00:15 - INFO - Hash verification passed for version 10.1.0
2025-11-23 12:00:15 - INFO - Downloaded and verified 10.1.0
2025-11-23 12:00:16 - INFO - Downloading version 10.5.1 (2/3)
...
2025-11-23 12:00:45 - INFO - Download complete for 001234567890: 10.1.0, 10.5.1, 11.1.0
```

### Hash Verification Failure

```
2025-11-23 12:00:15 - ERROR - Hash mismatch for 10.1.0: HashMismatchError(...)
2025-11-23 12:00:15 - ERROR - Expected: b2c3d4e5f6a7b8c9...
2025-11-23 12:00:15 - ERROR - Actual:   XXXXXXXXXXXXXXXX...
2025-11-23 12:00:15 - ERROR - Download may be corrupted or tampered!
2025-11-23 12:00:15 - ERROR - Download error for 001234567890: Hash verification failed
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

### 4. Verify Hashes

Ensure `version_hashes.json` contains official hashes from Palo Alto Networks.

### 5. Check Disk Space

Devices need space for all versions in upgrade path (typically 2-3 GB per version).

### 6. Stagger Downloads

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

### Hash Not Found

```
WARNING: No expected hash for version 10.1.0, accepting firewall hash
```

**Solution:** Add hash to `version_hashes.json`:
```bash
# Manually add (future enhancement: CLI command)
# Edit /var/lib/panos-upgrade/config/version_hashes.json
```

### Hash Mismatch

```
ERROR: Hash verification FAILED for 10.1.0
```

**Possible causes:**
- Corrupted download
- Network issue
- Wrong hash in database
- Tampering (security concern)

**Solution:**
1. Check logs for details
2. Verify hash in `version_hashes.json` is correct
3. Re-download if corrupted
4. Investigate if tampering suspected

### Connection Failed

```
ERROR: Failed to connect to firewall 10.1.1.10
```

**Solution:**
- Verify firewall management IP is reachable
- Check firewall API is enabled
- Verify API key is correct
- Check firewall firewall rules

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
  "validation": {
    "min_disk_gb": 5.0,
    "verify_hashes": true,
    "fail_on_missing_hash": false
  },
  "paths": {
    "upgrade_paths": "/var/lib/panos-upgrade/config/upgrade_paths.json",
    "version_hashes": "/var/lib/panos-upgrade/config/version_hashes.json"
  }
}
```

### Hash Database Format

```json
{
  "10.1.0": {
    "sha256": "FULL_64_CHARACTER_SHA256_HASH",
    "filename": "PanOS_3200-10.1.0",
    "size_mb": 460,
    "release_date": "2023-06-20"
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
status = read_json(f"/var/lib/panos-upgrade/status/devices/001234567890.json")

if status["upgrade_status"] == "download_complete":
    print(f"Ready for install!")
    print(f"Downloaded: {', '.join(status['downloaded_versions'])}")
    print(f"Hashes verified: {status['hash_verification']}")
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
tail -f /var/lib/panos-upgrade/logs/text/panos-upgrade-*.log

# Step 6: Verify all complete
panos-upgrade download status
```

Expected time: ~10-15 minutes for 230 devices with 20 workers (assuming 10s download time in mock mode)

### Later: Perform Actual Upgrades

Once downloads are complete, perform normal upgrades (images already present):

```bash
# Upgrades will be faster since images are pre-staged
panos-upgrade job submit --device 001234567890
```

## Security

### Hash Verification Benefits

1. **Integrity** - Detect corrupted downloads
2. **Security** - Detect tampering
3. **Compliance** - Audit trail of verified hashes
4. **Trust** - Verify against official Palo Alto hashes

### Audit Trail

All hashes are logged:
- JSON logs: `/var/lib/panos-upgrade/logs/structured/`
- Text logs: `/var/lib/panos-upgrade/logs/text/`
- Device status: `/var/lib/panos-upgrade/status/devices/`

### Best Practices

1. **Verify hash database** - Ensure hashes are from official source
2. **Monitor logs** - Watch for hash mismatches
3. **Investigate failures** - Hash mismatches may indicate security issues
4. **Keep database updated** - Add hashes for new versions

## Comparison: Normal vs Download-Only

| Feature | Normal Upgrade | Download-Only |
|---------|---------------|---------------|
| Connection | Via Panorama | Direct to firewall |
| Operations | Download + Install + Reboot | Download only |
| Validation | Full (sessions, routes, ARP) | Disk space only |
| Hash Check | Yes | Yes |
| Duration | ~25 min per device | ~5 min per device |
| Panorama Load | High | Low (discovery only) |
| Use Case | Complete upgrade | Pre-staging |

## FAQ

**Q: Can I run download-only and normal upgrades at the same time?**  
A: No, they are mutually exclusive per device to prevent conflicts.

**Q: What happens if hash is not in database?**  
A: By default, it logs a warning and accepts the firewall's hash. Set `fail_on_missing_hash: true` to fail instead.

**Q: Do I need to download again for normal upgrade?**  
A: Future enhancement will detect pre-downloaded images. Currently, normal upgrade will re-download.

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
- Logs: `/var/lib/panos-upgrade/logs/`

