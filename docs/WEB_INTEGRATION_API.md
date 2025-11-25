# Web Integration API - Complete Guide

## Overview

The PAN-OS Upgrade Manager provides a file-based API for web application integration. All communication happens through JSON files with atomic write operations to ensure data consistency.

## Architecture

```
Web Application
    ↓ (writes)
Queue/Commands Directory
    ↓ (monitors)
Daemon Service
    ↓ (writes)
Status/Validation Directory
    ↑ (reads)
Web Application
```

## Directory Structure

```
/var/lib/panos-upgrade/
├── queue/
│   ├── pending/          # Write job files here
│   ├── active/           # Read active jobs
│   ├── completed/        # Read completed jobs
│   └── cancelled/        # Read cancelled jobs
├── status/
│   ├── daemon.json       # Read daemon status
│   ├── workers.json      # Read worker statuses
│   └── devices/
│       └── {serial}.json # Read device status
├── validation/
│   ├── pre_flight/       # Read pre-flight metrics
│   └── post_flight/      # Read validation results
└── commands/
    ├── incoming/         # Write command files here
    └── processed/        # Read processed commands
```

## File Permissions Setup

```bash
# Add web user to panos-upgrade group
sudo usermod -a -G panos-upgrade www-data

# Set directory permissions
sudo chmod 750 /var/lib/panos-upgrade/status
sudo chmod 750 /var/lib/panos-upgrade/validation
sudo chmod 770 /var/lib/panos-upgrade/queue/pending
sudo chmod 770 /var/lib/panos-upgrade/commands/incoming

# Verify
sudo -u www-data ls -la /var/lib/panos-upgrade/status/
```

---

## 1. Job Submission API

### Submit Standalone Device Upgrade

**File Location**: `/var/lib/panos-upgrade/queue/pending/{job_id}.json`

**Schema**:
```json
{
  "job_id": "string (unique identifier)",
  "type": "standalone",
  "devices": ["serial_number"],
  "ha_pair_name": "",
  "dry_run": false,
  "created_at": "ISO 8601 timestamp"
}
```

**Python Example**:
```python
import json
import uuid
import tempfile
import os
from datetime import datetime
from pathlib import Path


class PanosUpgradeClient:
    """Client for interacting with PAN-OS Upgrade Manager."""
    
    def __init__(self, base_path="/var/lib/panos-upgrade"):
        self.base_path = Path(base_path)
        self.pending_dir = self.base_path / "queue" / "pending"
        self.commands_dir = self.base_path / "commands" / "incoming"
        self.status_dir = self.base_path / "status"
        self.devices_dir = self.status_dir / "devices"
        self.validation_dir = self.base_path / "validation"
    
    def _atomic_write_json(self, file_path, data):
        """Write JSON file atomically."""
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write to temp file
        fd, temp_path = tempfile.mkstemp(
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp"
        )
        
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Atomic move
            os.replace(temp_path, file_path)
        except Exception:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise
    
    def submit_device_upgrade(self, serial, dry_run=False):
        """
        Submit upgrade job for a single device.
        
        Args:
            serial: Device serial number
            dry_run: Whether to perform dry run
            
        Returns:
            job_id: Unique job identifier
            
        Raises:
            PendingJobError: If device already has a pending job
            ActiveJobError: If device already has an active job
        """
        # Check for existing job
        self._check_for_existing_job(serial)
        
        job_id = f"web-{uuid.uuid4()}"
        
        job_data = {
            "job_id": job_id,
            "type": "standalone",
            "devices": [serial],
            "ha_pair_name": "",
            "dry_run": dry_run,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        
        job_file = self.pending_dir / f"{job_id}.json"
        self._atomic_write_json(job_file, job_data)
        
        return job_id
    
    def _check_for_existing_job(self, device_serial):
        """
        Check if device already has a pending or active job.
        
        Args:
            device_serial: Device serial number
            
        Raises:
            PendingJobError: If device has a pending job
            ActiveJobError: If device has an active job
        """
        # Import custom exceptions (you'll need to copy these from the main app)
        from panos_upgrade.exceptions import ActiveJobError, PendingJobError
        
        # Check pending queue
        pending_dir = self.base_path / "queue" / "pending"
        if pending_dir.exists():
            for job_file in pending_dir.glob("*.json"):
                try:
                    with open(job_file) as f:
                        job_data = json.load(f)
                        if device_serial in job_data.get("devices", []):
                            raise PendingJobError(
                                device_serial=device_serial,
                                job_id=job_data.get("job_id", "unknown"),
                                created_at=job_data.get("created_at", "")
                            )
                except (PendingJobError, ActiveJobError):
                    raise
                except Exception:
                    continue
        
        # Check active queue
        active_dir = self.base_path / "queue" / "active"
        if active_dir.exists():
            for job_file in active_dir.glob("*.json"):
                try:
                    with open(job_file) as f:
                        job_data = json.load(f)
                        if device_serial in job_data.get("devices", []):
                            raise ActiveJobError(
                                device_serial=device_serial,
                                job_id=job_data.get("job_id", "unknown"),
                                created_at=job_data.get("created_at", "")
                            )
                except (PendingJobError, ActiveJobError):
                    raise
                except Exception:
                    continue


# Usage
from panos_upgrade.exceptions import ActiveJobError, PendingJobError

client = PanosUpgradeClient()

try:
    job_id = client.submit_device_upgrade("001234567890", dry_run=False)
    print(f"Submitted job: {job_id}")
except PendingJobError as e:
    print(f"Cannot submit: Device has a pending job")
    print(f"  Job ID: {e.job_id}")
    print(f"  Created: {e.created_at}")
    print(f"  Action: Wait for job to start or cancel it")
except ActiveJobError as e:
    print(f"Cannot submit: Device is currently being upgraded")
    print(f"  Job ID: {e.job_id}")
    print(f"  Created: {e.created_at}")
    print(f"  Action: Wait for completion or cancel if needed")
```

**JavaScript/Node.js Example**:
```javascript
const fs = require('fs').promises;
const path = require('path');
const { v4: uuidv4 } = require('uuid');

class PanosUpgradeClient {
    constructor(basePath = '/var/lib/panos-upgrade') {
        this.basePath = basePath;
        this.pendingDir = path.join(basePath, 'queue', 'pending');
        this.commandsDir = path.join(basePath, 'commands', 'incoming');
        this.statusDir = path.join(basePath, 'status');
        this.devicesDir = path.join(this.statusDir, 'devices');
    }
    
    async atomicWriteJson(filePath, data) {
        const dir = path.dirname(filePath);
        const tempPath = path.join(dir, `.${path.basename(filePath)}.tmp`);
        
        try {
            await fs.writeFile(tempPath, JSON.stringify(data, null, 2));
            await fs.rename(tempPath, filePath);
        } catch (error) {
            try {
                await fs.unlink(tempPath);
            } catch {}
            throw error;
        }
    }
    
    async submitDeviceUpgrade(serial, dryRun = false) {
        const jobId = `web-${uuidv4()}`;
        
        const jobData = {
            job_id: jobId,
            type: 'standalone',
            devices: [serial],
            ha_pair_name: '',
            dry_run: dryRun,
            created_at: new Date().toISOString()
        };
        
        const jobFile = path.join(this.pendingDir, `${jobId}.json`);
        await this.atomicWriteJson(jobFile, jobData);
        
        return jobId;
    }
}

// Usage
(async () => {
    const client = new PanosUpgradeClient();
    const jobId = await client.submitDeviceUpgrade('001234567890', false);
    console.log(`Submitted job: ${jobId}`);
})();
```

### Submit HA Pair Upgrade

**Schema**:
```json
{
  "job_id": "string (unique identifier)",
  "type": "ha_pair",
  "devices": ["primary_serial", "secondary_serial"],
  "ha_pair_name": "datacenter-1",
  "dry_run": false,
  "created_at": "ISO 8601 timestamp"
}
```

**Python Example**:
```python
def submit_ha_pair_upgrade(self, primary_serial, secondary_serial, 
                          pair_name, dry_run=False):
    """
    Submit upgrade job for HA pair.
    
    Args:
        primary_serial: Primary device serial
        secondary_serial: Secondary device serial
        pair_name: HA pair name
        dry_run: Whether to perform dry run
        
    Returns:
        job_id: Unique job identifier
    """
    job_id = f"web-ha-{uuid.uuid4()}"
    
    job_data = {
        "job_id": job_id,
        "type": "ha_pair",
        "devices": [primary_serial, secondary_serial],
        "ha_pair_name": pair_name,
        "dry_run": dry_run,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    
    job_file = self.pending_dir / f"{job_id}.json"
    self._atomic_write_json(job_file, job_data)
    
    return job_id

# Usage
job_id = client.submit_ha_pair_upgrade(
    "001234567890",
    "001234567891",
    "datacenter-1",
    dry_run=False
)
```

### Submit Bulk Upgrades

**Python Example**:
```python
def submit_bulk_upgrades(self, serials, dry_run=False):
    """
    Submit multiple device upgrades.
    
    Args:
        serials: List of device serial numbers
        dry_run: Whether to perform dry run
        
    Returns:
        List of job IDs
    """
    job_ids = []
    
    for serial in serials:
        try:
            job_id = self.submit_device_upgrade(serial, dry_run)
            job_ids.append(job_id)
        except Exception as e:
            print(f"Failed to submit {serial}: {e}")
    
    return job_ids

# Usage
serials = ["001234567890", "001234567891", "001234567892"]
job_ids = client.submit_bulk_upgrades(serials, dry_run=True)
print(f"Submitted {len(job_ids)} jobs")
```

---

## 2. Status Reading API

### Read Daemon Status

**File Location**: `/var/lib/panos-upgrade/status/daemon.json`

**Schema**:
```json
{
  "running": true,
  "workers": 10,
  "active_jobs": 5,
  "pending_jobs": 15,
  "completed_jobs": 120,
  "failed_jobs": 3,
  "cancelled_jobs": 2,
  "started_at": "2025-11-21T10:00:00Z",
  "last_updated": "2025-11-21T12:30:45Z"
}
```

**Python Example**:
```python
def get_daemon_status(self):
    """
    Get daemon status.
    
    Returns:
        dict: Daemon status information
    """
    status_file = self.status_dir / "daemon.json"
    
    try:
        with open(status_file) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid daemon status file: {e}")

# Usage
status = client.get_daemon_status()
if status:
    print(f"Daemon running: {status['running']}")
    print(f"Active jobs: {status['active_jobs']}")
    print(f"Workers: {status['workers']}")
```

### Read Device Status

**File Location**: `/var/lib/panos-upgrade/status/devices/{serial}.json`

**Schema**:
```json
{
  "serial": "001234567890",
  "hostname": "fw-datacenter-1",
  "ha_role": "standalone",
  "current_version": "10.5.1",
  "target_version": "11.1.0",
  "upgrade_path": ["11.1.0"],
  "current_path_index": 0,
  "upgrade_status": "downloading",
  "progress": 45,
  "current_phase": "download",
  "disk_space": {
    "available_gb": 12.5,
    "required_gb": 5.0,
    "check_passed": true
  },
  "last_updated": "2025-11-21T12:30:45Z",
  "skip_reason": "",
  "errors": [
    {
      "timestamp": "2025-11-21T12:15:00Z",
      "phase": "download",
      "message": "Connection timeout",
      "details": "Retrying..."
    }
  ]
}
```

**Python Example**:
```python
def get_device_status(self, serial):
    """
    Get device status.
    
    Args:
        serial: Device serial number
        
    Returns:
        dict: Device status information or None
    """
    status_file = self.devices_dir / f"{serial}.json"
    
    try:
        with open(status_file) as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def get_device_progress(self, serial):
    """
    Get simplified device progress.
    
    Args:
        serial: Device serial number
        
    Returns:
        dict: Progress information
    """
    status = self.get_device_status(serial)
    
    if not status:
        return {
            "status": "unknown",
            "progress": 0,
            "message": "Device not found"
        }
    
    return {
        "status": status["upgrade_status"],
        "progress": status["progress"],
        "phase": status["current_phase"],
        "current_version": status["current_version"],
        "target_version": status["target_version"],
        "errors": len(status["errors"])
    }

# Usage
status = client.get_device_status("001234567890")
if status:
    print(f"Status: {status['upgrade_status']}")
    print(f"Progress: {status['progress']}%")
    print(f"Phase: {status['current_phase']}")
    
    if status['errors']:
        print(f"Errors: {len(status['errors'])}")
        for error in status['errors']:
            print(f"  - {error['message']}")
```

### Read Worker Status

**File Location**: `/var/lib/panos-upgrade/status/workers.json`

**Schema**:
```json
{
  "workers": [
    {
      "worker_id": 0,
      "status": "busy",
      "current_job_id": "web-abc123",
      "current_device": "001234567890",
      "last_updated": "2025-11-21T12:30:45Z"
    },
    {
      "worker_id": 1,
      "status": "idle",
      "current_job_id": "",
      "current_device": "",
      "last_updated": "2025-11-21T12:30:45Z"
    }
  ]
}
```

**Python Example**:
```python
def get_worker_status(self):
    """
    Get worker status.
    
    Returns:
        dict: Worker status information
    """
    status_file = self.status_dir / "workers.json"
    
    try:
        with open(status_file) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"workers": []}

def get_worker_utilization(self):
    """
    Calculate worker utilization.
    
    Returns:
        dict: Utilization statistics
    """
    workers = self.get_worker_status().get("workers", [])
    
    if not workers:
        return {"total": 0, "busy": 0, "idle": 0, "utilization": 0}
    
    busy = sum(1 for w in workers if w["status"] == "busy")
    idle = sum(1 for w in workers if w["status"] == "idle")
    
    return {
        "total": len(workers),
        "busy": busy,
        "idle": idle,
        "utilization": (busy / len(workers)) * 100
    }

# Usage
utilization = client.get_worker_utilization()
print(f"Workers: {utilization['busy']}/{utilization['total']} busy")
print(f"Utilization: {utilization['utilization']:.1f}%")
```

### List Jobs by Status

**Python Example**:
```python
def list_jobs(self, status="all"):
    """
    List jobs by status.
    
    Args:
        status: Job status (pending, active, completed, cancelled, failed, all)
        
    Returns:
        list: List of job files
    """
    if status == "all":
        dirs = ["pending", "active", "completed", "cancelled"]
    else:
        dirs = [status]
    
    jobs = []
    for dir_name in dirs:
        job_dir = self.base_path / "queue" / dir_name
        if job_dir.exists():
            for job_file in job_dir.glob("*.json"):
                try:
                    with open(job_file) as f:
                        job_data = json.load(f)
                        job_data["_status"] = dir_name
                        job_data["_file"] = str(job_file)
                        jobs.append(job_data)
                except Exception as e:
                    print(f"Error reading {job_file}: {e}")
    
    return jobs

def get_job_summary(self):
    """
    Get summary of all jobs.
    
    Returns:
        dict: Job summary statistics
    """
    jobs = self.list_jobs("all")
    
    summary = {
        "total": len(jobs),
        "pending": 0,
        "active": 0,
        "completed": 0,
        "cancelled": 0,
        "failed": 0
    }
    
    for job in jobs:
        status = job.get("_status", "unknown")
        if status in summary:
            summary[status] += 1
    
    return summary

# Usage
jobs = client.list_jobs("active")
print(f"Active jobs: {len(jobs)}")
for job in jobs:
    print(f"  {job['job_id']}: {len(job['devices'])} devices")

summary = client.get_job_summary()
print(f"Total jobs: {summary['total']}")
print(f"  Pending: {summary['pending']}")
print(f"  Active: {summary['active']}")
print(f"  Completed: {summary['completed']}")
```

---

## 3. Validation Results API

### Read Pre-flight Metrics

**File Location**: `/var/lib/panos-upgrade/validation/pre_flight/{serial}_{timestamp}.json`

**Schema**:
```json
{
  "serial": "001234567890",
  "timestamp": "2025-11-21T12:00:00Z",
  "metrics": {
    "tcp_sessions": 45632,
    "route_count": 1234,
    "routes": [
      {
        "destination": "10.0.0.0/8",
        "gateway": "192.168.1.1",
        "interface": "ethernet1/1"
      }
    ],
    "arp_count": 567,
    "arp_entries": [
      {
        "ip": "192.168.1.1",
        "mac": "00:11:22:33:44:55",
        "interface": "ethernet1/1"
      }
    ],
    "disk_available_gb": 15.2
  }
}
```

**Python Example**:
```python
def get_latest_pre_flight(self, serial):
    """
    Get latest pre-flight validation for device.
    
    Args:
        serial: Device serial number
        
    Returns:
        dict: Pre-flight metrics or None
    """
    pre_flight_dir = self.validation_dir / "pre_flight"
    
    # Find latest file for this serial
    files = sorted(
        pre_flight_dir.glob(f"{serial}_*.json"),
        reverse=True
    )
    
    if not files:
        return None
    
    with open(files[0]) as f:
        return json.load(f)

# Usage
pre_flight = client.get_latest_pre_flight("001234567890")
if pre_flight:
    metrics = pre_flight["metrics"]
    print(f"TCP Sessions: {metrics['tcp_sessions']}")
    print(f"Routes: {metrics['route_count']}")
    print(f"ARP Entries: {metrics['arp_count']}")
    print(f"Disk Space: {metrics['disk_available_gb']} GB")
```

### Read Post-flight Validation

**File Location**: `/var/lib/panos-upgrade/validation/post_flight/{serial}_{timestamp}.json`

**Schema**:
```json
{
  "serial": "001234567890",
  "timestamp": "2025-11-21T12:45:00Z",
  "pre_flight": { /* metrics */ },
  "post_flight": { /* metrics */ },
  "comparison": {
    "tcp_sessions": {
      "difference": -43,
      "percentage": -0.09,
      "within_margin": true
    },
    "routes": {
      "count_difference": 1,
      "added": [
        {
          "destination": "172.16.0.0/12",
          "gateway": "10.1.1.2",
          "interface": "ethernet1/2"
        }
      ],
      "removed": [],
      "validation_passed": true
    },
    "arp_entries": {
      "count_difference": 1,
      "added": [ /* ... */ ],
      "removed": [],
      "validation_passed": true
    }
  },
  "validation_passed": true
}
```

**Python Example**:
```python
def get_latest_post_flight(self, serial):
    """
    Get latest post-flight validation for device.
    
    Args:
        serial: Device serial number
        
    Returns:
        dict: Post-flight validation or None
    """
    post_flight_dir = self.validation_dir / "post_flight"
    
    files = sorted(
        post_flight_dir.glob(f"{serial}_*.json"),
        reverse=True
    )
    
    if not files:
        return None
    
    with open(files[0]) as f:
        return json.load(f)

def get_validation_summary(self, serial):
    """
    Get validation summary for device.
    
    Args:
        serial: Device serial number
        
    Returns:
        dict: Validation summary
    """
    post_flight = self.get_latest_post_flight(serial)
    
    if not post_flight:
        return {"available": False}
    
    comparison = post_flight.get("comparison", {})
    
    return {
        "available": True,
        "passed": post_flight.get("validation_passed", False),
        "tcp_sessions_change": comparison.get("tcp_sessions", {}).get("difference", 0),
        "routes_added": len(comparison.get("routes", {}).get("added", [])),
        "routes_removed": len(comparison.get("routes", {}).get("removed", [])),
        "arp_added": len(comparison.get("arp_entries", {}).get("added", [])),
        "arp_removed": len(comparison.get("arp_entries", {}).get("removed", []))
    }

# Usage
validation = client.get_validation_summary("001234567890")
if validation["available"]:
    print(f"Validation passed: {validation['passed']}")
    print(f"TCP sessions change: {validation['tcp_sessions_change']}")
    print(f"Routes added: {validation['routes_added']}")
    print(f"Routes removed: {validation['routes_removed']}")
```

---

## 4. Command API

### Cancel Job

**File Location**: `/var/lib/panos-upgrade/commands/incoming/{timestamp}_{uuid}.json`

**Schema**:
```json
{
  "command": "cancel_upgrade",
  "target": "job",
  "job_id": "web-abc123",
  "device_serial": "",
  "reason": "Admin takeover required",
  "timestamp": "2025-11-21T12:30:00Z"
}
```

**Python Example**:
```python
def cancel_job(self, job_id, reason="Web app cancellation"):
    """
    Cancel a job.
    
    Args:
        job_id: Job identifier
        reason: Cancellation reason
        
    Returns:
        command_id: Command identifier
    """
    command_id = f"cancel-{uuid.uuid4()}"
    
    command_data = {
        "command": "cancel_upgrade",
        "target": "job",
        "job_id": job_id,
        "device_serial": "",
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    command_file = self.commands_dir / f"{command_id}.json"
    self._atomic_write_json(command_file, command_data)
    
    return command_id

def cancel_device(self, serial, reason="Web app cancellation"):
    """
    Cancel upgrade for a specific device.
    
    Args:
        serial: Device serial number
        reason: Cancellation reason
        
    Returns:
        command_id: Command identifier
    """
    command_id = f"cancel-{uuid.uuid4()}"
    
    command_data = {
        "command": "cancel_upgrade",
        "target": "device",
        "job_id": "",
        "device_serial": serial,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    
    command_file = self.commands_dir / f"{command_id}.json"
    self._atomic_write_json(command_file, command_data)
    
    return command_id

# Usage
command_id = client.cancel_job("web-abc123", "Emergency maintenance")
print(f"Cancellation command sent: {command_id}")
```

---

## 5. Real-time Monitoring

### Poll for Status Updates

**Python Example**:
```python
import time

def monitor_device_upgrade(self, serial, interval=5, timeout=3600):
    """
    Monitor device upgrade in real-time.
    
    Args:
        serial: Device serial number
        interval: Polling interval in seconds
        timeout: Maximum time to monitor in seconds
        
    Yields:
        dict: Device status updates
    """
    start_time = time.time()
    last_status = None
    
    while time.time() - start_time < timeout:
        status = self.get_device_status(serial)
        
        if status and status != last_status:
            yield status
            last_status = status
            
            # Check if complete or failed
            if status["upgrade_status"] in ["complete", "failed", "cancelled", "skipped"]:
                break
        
        time.sleep(interval)

# Usage
print(f"Monitoring device 001234567890...")
for status in client.monitor_device_upgrade("001234567890", interval=5):
    print(f"[{status['upgrade_status']}] {status['progress']}% - {status['current_phase']}")
    
    if status['errors']:
        print(f"  Errors: {len(status['errors'])}")
```

### Dashboard Data Aggregation

**Python Example**:
```python
def get_dashboard_data(self):
    """
    Get aggregated dashboard data.
    
    Returns:
        dict: Dashboard data
    """
    daemon = self.get_daemon_status()
    workers = self.get_worker_utilization()
    jobs = self.get_job_summary()
    
    # Get active device statuses
    active_jobs = self.list_jobs("active")
    active_devices = []
    
    for job in active_jobs:
        for serial in job.get("devices", []):
            device_status = self.get_device_status(serial)
            if device_status:
                active_devices.append({
                    "serial": serial,
                    "hostname": device_status.get("hostname", ""),
                    "status": device_status.get("upgrade_status", ""),
                    "progress": device_status.get("progress", 0),
                    "phase": device_status.get("current_phase", "")
                })
    
    return {
        "daemon": {
            "running": daemon.get("running", False) if daemon else False,
            "workers": daemon.get("workers", 0) if daemon else 0,
            "last_updated": daemon.get("last_updated", "") if daemon else ""
        },
        "workers": workers,
        "jobs": jobs,
        "active_devices": active_devices
    }

# Usage
dashboard = client.get_dashboard_data()
print(f"Daemon: {'Running' if dashboard['daemon']['running'] else 'Stopped'}")
print(f"Workers: {dashboard['workers']['busy']}/{dashboard['workers']['total']}")
print(f"Jobs: {dashboard['jobs']['active']} active, {dashboard['jobs']['pending']} pending")
print(f"Active devices: {len(dashboard['active_devices'])}")
```

---

## 6. Complete Web Application Example

### Flask REST API

```python
from flask import Flask, jsonify, request
from panos_upgrade_client import PanosUpgradeClient

app = Flask(__name__)
client = PanosUpgradeClient()


@app.route('/api/daemon/status', methods=['GET'])
def daemon_status():
    """Get daemon status."""
    status = client.get_daemon_status()
    if status:
        return jsonify(status)
    return jsonify({"error": "Daemon status not available"}), 503


@app.route('/api/jobs', methods=['GET'])
def list_jobs():
    """List jobs."""
    status = request.args.get('status', 'all')
    jobs = client.list_jobs(status)
    return jsonify({"jobs": jobs, "count": len(jobs)})


@app.route('/api/jobs', methods=['POST'])
def submit_job():
    """Submit new job."""
    from panos_upgrade.exceptions import ActiveJobError, PendingJobError
    
    data = request.json
    
    job_type = data.get('type', 'standalone')
    dry_run = data.get('dry_run', False)
    
    try:
        if job_type == 'standalone':
            serial = data.get('serial')
            if not serial:
                return jsonify({"error": "Serial required"}), 400
            
            job_id = client.submit_device_upgrade(serial, dry_run)
            
        elif job_type == 'ha_pair':
            primary = data.get('primary_serial')
            secondary = data.get('secondary_serial')
            pair_name = data.get('pair_name')
            
            if not all([primary, secondary, pair_name]):
                return jsonify({"error": "Missing required fields"}), 400
            
            job_id = client.submit_ha_pair_upgrade(
                primary, secondary, pair_name, dry_run
            )
        else:
            return jsonify({"error": "Invalid job type"}), 400
        
        return jsonify({"job_id": job_id}), 201
    
    except PendingJobError as e:
        return jsonify({
            "error": "Device has a pending job",
            "error_type": "pending_job",
            "device_serial": e.device_serial,
            "existing_job_id": e.job_id,
            "created_at": e.created_at
        }), 409  # Conflict
    
    except ActiveJobError as e:
        return jsonify({
            "error": "Device has an active job",
            "error_type": "active_job",
            "device_serial": e.device_serial,
            "existing_job_id": e.job_id,
            "created_at": e.created_at
        }), 409  # Conflict
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
def cancel_job(job_id):
    """Cancel job."""
    data = request.json
    reason = data.get('reason', 'Web app cancellation')
    
    try:
        command_id = client.cancel_job(job_id, reason)
        return jsonify({"command_id": command_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/devices/<serial>/status', methods=['GET'])
def device_status(serial):
    """Get device status."""
    status = client.get_device_status(serial)
    if status:
        return jsonify(status)
    return jsonify({"error": "Device not found"}), 404


@app.route('/api/devices/<serial>/validation', methods=['GET'])
def device_validation(serial):
    """Get device validation results."""
    validation = client.get_validation_summary(serial)
    return jsonify(validation)


@app.route('/api/dashboard', methods=['GET'])
def dashboard():
    """Get dashboard data."""
    data = client.get_dashboard_data()
    return jsonify(data)


@app.route('/api/workers', methods=['GET'])
def workers():
    """Get worker status."""
    status = client.get_worker_status()
    utilization = client.get_worker_utilization()
    return jsonify({
        "workers": status.get("workers", []),
        "utilization": utilization
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

### React Frontend Example

```javascript
import React, { useState, useEffect } from 'react';

function Dashboard() {
    const [dashboard, setDashboard] = useState(null);
    const [loading, setLoading] = useState(true);
    
    useEffect(() => {
        const fetchDashboard = async () => {
            try {
                const response = await fetch('/api/dashboard');
                const data = await response.json();
                setDashboard(data);
                setLoading(false);
            } catch (error) {
                console.error('Error fetching dashboard:', error);
                setLoading(false);
            }
        };
        
        fetchDashboard();
        const interval = setInterval(fetchDashboard, 5000);
        
        return () => clearInterval(interval);
    }, []);
    
    if (loading) return <div>Loading...</div>;
    if (!dashboard) return <div>Error loading dashboard</div>;
    
    return (
        <div className="dashboard">
            <h1>PAN-OS Upgrade Manager</h1>
            
            <div className="status-cards">
                <div className="card">
                    <h3>Daemon</h3>
                    <p>Status: {dashboard.daemon.running ? 'Running' : 'Stopped'}</p>
                    <p>Workers: {dashboard.daemon.workers}</p>
                </div>
                
                <div className="card">
                    <h3>Worker Utilization</h3>
                    <p>{dashboard.workers.busy} / {dashboard.workers.total} busy</p>
                    <p>{dashboard.workers.utilization.toFixed(1)}%</p>
                </div>
                
                <div className="card">
                    <h3>Jobs</h3>
                    <p>Active: {dashboard.jobs.active}</p>
                    <p>Pending: {dashboard.jobs.pending}</p>
                    <p>Completed: {dashboard.jobs.completed}</p>
                </div>
            </div>
            
            <div className="active-devices">
                <h2>Active Upgrades</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Serial</th>
                            <th>Hostname</th>
                            <th>Status</th>
                            <th>Progress</th>
                            <th>Phase</th>
                        </tr>
                    </thead>
                    <tbody>
                        {dashboard.active_devices.map(device => (
                            <tr key={device.serial}>
                                <td>{device.serial}</td>
                                <td>{device.hostname}</td>
                                <td>{device.status}</td>
                                <td>{device.progress}%</td>
                                <td>{device.phase}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

function SubmitJob() {
    const [serial, setSerial] = useState('');
    const [dryRun, setDryRun] = useState(false);
    const [message, setMessage] = useState('');
    
    const handleSubmit = async (e) => {
        e.preventDefault();
        
        try {
            const response = await fetch('/api/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    type: 'standalone',
                    serial: serial,
                    dry_run: dryRun
                })
            });
            
            const data = await response.json();
            
            if (response.ok) {
                setMessage(`Job submitted: ${data.job_id}`);
                setSerial('');
            } else {
                setMessage(`Error: ${data.error}`);
            }
        } catch (error) {
            setMessage(`Error: ${error.message}`);
        }
    };
    
    return (
        <div className="submit-job">
            <h2>Submit Upgrade Job</h2>
            <form onSubmit={handleSubmit}>
                <input
                    type="text"
                    placeholder="Device Serial Number"
                    value={serial}
                    onChange={(e) => setSerial(e.target.value)}
                    required
                />
                <label>
                    <input
                        type="checkbox"
                        checked={dryRun}
                        onChange={(e) => setDryRun(e.target.checked)}
                    />
                    Dry Run
                </label>
                <button type="submit">Submit</button>
            </form>
            {message && <p className="message">{message}</p>}
        </div>
    );
}

export { Dashboard, SubmitJob };
```

---

## 7. Exception Handling

### Custom Exceptions

The system provides specific exceptions for different error scenarios:

```python
from panos_upgrade.exceptions import (
    ActiveJobError,      # Device has an active (running) job
    PendingJobError,     # Device has a pending (queued) job
    InsufficientDiskSpaceError,  # Not enough disk space
    VersionNotFoundError,        # Version not in upgrade paths
    DeviceNotFoundError,         # Device doesn't exist
    UpgradeFailedError,          # Upgrade failed
    ValidationError              # Validation failed
)
```

### Exception Attributes

**ActiveJobError / PendingJobError:**
- `device_serial` - Device serial number
- `job_id` - Existing job ID
- `status` - Job status ("active" or "pending")
- `created_at` - When job was created

**InsufficientDiskSpaceError:**
- `device_serial` - Device serial number
- `available_gb` - Available disk space
- `required_gb` - Required disk space

**VersionNotFoundError:**
- `device_serial` - Device serial number
- `current_version` - Current device version

### Handling Duplicate Jobs

**Python Example:**
```python
from panos_upgrade.exceptions import ActiveJobError, PendingJobError

def submit_with_error_handling(serial):
    """Submit job with proper error handling."""
    try:
        job_id = client.submit_device_upgrade(serial)
        return {
            "success": True,
            "job_id": job_id,
            "message": f"Job submitted for {serial}"
        }
    
    except PendingJobError as e:
        return {
            "success": False,
            "error_type": "pending_job",
            "message": str(e),
            "existing_job_id": e.job_id,
            "device_serial": e.device_serial,
            "created_at": e.created_at,
            "action": "Wait for job to start or cancel existing job"
        }
    
    except ActiveJobError as e:
        return {
            "success": False,
            "error_type": "active_job",
            "message": str(e),
            "existing_job_id": e.job_id,
            "device_serial": e.device_serial,
            "created_at": e.created_at,
            "action": "Wait for upgrade to complete or cancel if needed"
        }
    
    except Exception as e:
        return {
            "success": False,
            "error_type": "unknown",
            "message": str(e)
        }

# Usage
result = submit_with_error_handling("001234567890")
if result["success"]:
    print(f"Success: {result['job_id']}")
else:
    print(f"Error ({result['error_type']}): {result['message']}")
    if result.get("existing_job_id"):
        print(f"Existing job: {result['existing_job_id']}")
```

**Flask API Example:**
```python
from panos_upgrade.exceptions import ActiveJobError, PendingJobError

@app.route('/api/jobs', methods=['POST'])
def submit_job():
    """Submit new job with proper exception handling."""
    data = request.json
    serial = data.get('serial')
    
    try:
        job_id = client.submit_device_upgrade(serial)
        return jsonify({
            "success": True,
            "job_id": job_id
        }), 201
    
    except PendingJobError as e:
        return jsonify({
            "success": False,
            "error": "Device has a pending job",
            "error_type": "pending_job",
            "device_serial": e.device_serial,
            "existing_job_id": e.job_id,
            "created_at": e.created_at,
            "action": "wait_or_cancel"
        }), 409  # HTTP 409 Conflict
    
    except ActiveJobError as e:
        return jsonify({
            "success": False,
            "error": "Device upgrade in progress",
            "error_type": "active_job",
            "device_serial": e.device_serial,
            "existing_job_id": e.job_id,
            "created_at": e.created_at,
            "action": "wait_or_cancel"
        }), 409  # HTTP 409 Conflict
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "error_type": "server_error"
        }), 500
```

**JavaScript/React Example:**
```javascript
async function submitUpgrade(serial) {
    try {
        const response = await fetch('/api/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                type: 'standalone',
                serial: serial,
                dry_run: false
            })
        });
        
        const data = await response.json();
        
        if (response.status === 409) {
            // Duplicate job error
            if (data.error_type === 'active_job') {
                alert(`Device is currently being upgraded\nJob ID: ${data.existing_job_id}\n\nPlease wait for completion or cancel the existing job.`);
            } else if (data.error_type === 'pending_job') {
                alert(`Device already has a queued upgrade\nJob ID: ${data.existing_job_id}\n\nPlease wait or cancel the existing job.`);
            }
            return null;
        }
        
        if (!response.ok) {
            throw new Error(data.error || 'Unknown error');
        }
        
        return data.job_id;
        
    } catch (error) {
        console.error('Error submitting job:', error);
        alert(`Error: ${error.message}`);
        return null;
    }
}
```

## 7. Error Handling

### Robust Error Handling Example

```python
import logging
from pathlib import Path

class PanosUpgradeClientWithErrorHandling(PanosUpgradeClient):
    """Enhanced client with error handling."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)
    
    def safe_submit_device_upgrade(self, serial, dry_run=False):
        """Submit device upgrade with error handling."""
        try:
            # Validate serial
            if not serial or not isinstance(serial, str):
                raise ValueError("Invalid serial number")
            
            # Check if already queued
            existing = self._find_existing_job(serial)
            if existing:
                self.logger.warning(f"Device {serial} already has job: {existing}")
                return None
            
            # Submit job
            job_id = self.submit_device_upgrade(serial, dry_run)
            self.logger.info(f"Submitted job {job_id} for device {serial}")
            return job_id
            
        except PermissionError as e:
            self.logger.error(f"Permission denied: {e}")
            raise
        except OSError as e:
            self.logger.error(f"File system error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}", exc_info=True)
            raise
    
    def _find_existing_job(self, serial):
        """Check if device already has a job."""
        for status in ["pending", "active"]:
            jobs = self.list_jobs(status)
            for job in jobs:
                if serial in job.get("devices", []):
                    return job.get("job_id")
        return None
    
    def safe_get_device_status(self, serial, default=None):
        """Get device status with error handling."""
        try:
            return self.get_device_status(serial)
        except FileNotFoundError:
            self.logger.debug(f"Status file not found for {serial}")
            return default
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in status file for {serial}: {e}")
            return default
        except Exception as e:
            self.logger.error(f"Error reading status for {serial}: {e}")
            return default
```

---

## 8. Testing

### Unit Tests

```python
import unittest
import tempfile
import shutil
from pathlib import Path

class TestPanosUpgradeClient(unittest.TestCase):
    
    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.client = PanosUpgradeClient(base_path=self.test_dir)
        
        # Create directory structure
        for subdir in ["queue/pending", "status/devices", "commands/incoming"]:
            (Path(self.test_dir) / subdir).mkdir(parents=True, exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)
    
    def test_submit_device_upgrade(self):
        """Test device upgrade submission."""
        job_id = self.client.submit_device_upgrade("001234567890")
        
        self.assertIsNotNone(job_id)
        self.assertTrue(job_id.startswith("web-"))
        
        # Verify file was created
        job_file = Path(self.test_dir) / "queue" / "pending" / f"{job_id}.json"
        self.assertTrue(job_file.exists())
        
        # Verify content
        with open(job_file) as f:
            data = json.load(f)
            self.assertEqual(data["type"], "standalone")
            self.assertEqual(data["devices"], ["001234567890"])
    
    def test_cancel_job(self):
        """Test job cancellation."""
        command_id = self.client.cancel_job("test-job-123", "Test cancellation")
        
        self.assertIsNotNone(command_id)
        
        # Verify command file was created
        command_file = Path(self.test_dir) / "commands" / "incoming" / f"{command_id}.json"
        self.assertTrue(command_file.exists())

if __name__ == '__main__':
    unittest.main()
```

---

## 9. Best Practices

### 1. Always Use Atomic Writes

```python
# ✅ Good - Atomic write
client._atomic_write_json(file_path, data)

# ❌ Bad - Non-atomic write
with open(file_path, 'w') as f:
    json.dump(data, f)
```

### 2. Handle Missing Files Gracefully

```python
# ✅ Good
status = client.get_device_status(serial)
if status:
    process_status(status)
else:
    logger.info(f"No status available for {serial}")

# ❌ Bad
status = client.get_device_status(serial)
process_status(status)  # Will fail if None
```

### 3. Poll with Reasonable Intervals

```python
# ✅ Good - 5 second intervals
while True:
    status = client.get_device_status(serial)
    time.sleep(5)

# ❌ Bad - Too frequent
while True:
    status = client.get_device_status(serial)
    time.sleep(0.1)  # Excessive I/O
```

### 4. Validate Input

```python
# ✅ Good
def submit_upgrade(serial):
    if not serial or not isinstance(serial, str):
        raise ValueError("Invalid serial")
    if len(serial) != 12:
        raise ValueError("Serial must be 12 characters")
    return client.submit_device_upgrade(serial)
```

### 5. Log Operations

```python
# ✅ Good
logger.info(f"Submitting upgrade for {serial}")
job_id = client.submit_device_upgrade(serial)
logger.info(f"Job submitted: {job_id}")
```

---

## 10. Troubleshooting

### Permission Denied

```bash
# Check permissions
ls -la /var/lib/panos-upgrade/queue/pending/

# Add web user to group
sudo usermod -a -G panos-upgrade www-data

# Restart web server
sudo systemctl restart apache2
```

### Files Not Appearing

```python
# Verify directory exists
assert Path("/var/lib/panos-upgrade/queue/pending").exists()

# Check file was written
job_file = Path(f"/var/lib/panos-upgrade/queue/pending/{job_id}.json")
assert job_file.exists()

# Verify daemon is running
daemon_status = client.get_daemon_status()
assert daemon_status["running"]
```

### Stale Status Data

```python
# Check last update time
status = client.get_device_status(serial)
last_updated = datetime.fromisoformat(status["last_updated"].rstrip("Z"))
age = datetime.utcnow() - last_updated

if age.total_seconds() > 60:
    logger.warning(f"Status is {age.total_seconds()}s old")
```

---

## Summary

This API provides a complete file-based integration interface for web applications to:

1. **Submit Jobs** - Queue device and HA pair upgrades
2. **Monitor Status** - Real-time device, job, and daemon status
3. **Read Validation** - Access pre/post-flight validation results
4. **Send Commands** - Cancel jobs and devices
5. **Aggregate Data** - Build dashboards and reports

All operations use atomic file writes to ensure data consistency and prevent race conditions. The API is language-agnostic and can be implemented in any language that can read/write JSON files.

