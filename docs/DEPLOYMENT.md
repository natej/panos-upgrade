# PAN-OS Upgrade Manager - Deployment Guide

## Production Deployment

This guide covers deploying the PAN-OS Upgrade Manager in a production environment.

## Prerequisites

### System Requirements

- **OS**: Linux (Ubuntu 20.04+, RHEL 8+, or similar)
- **Python**: 3.11 or higher
- **Memory**: Minimum 2GB RAM (4GB recommended for 50 workers)
- **Disk**: 10GB for application and logs
- **Network**: Connectivity to Panorama server

### Access Requirements

- **Panorama API key** (for device discovery only):
  - Device management read access
- **Firewall credentials** (for direct connections):
  - Username/password with API access on all firewalls
  - Software management permissions
- **Network connectivity**:
  - To Panorama server (for discovery)
  - To all firewall management IPs (for operations)
- SSH/console access to deployment server
- Sudo privileges for systemd service setup

## Installation Steps

### 1. Prepare System

```bash
# Update system
sudo apt update && sudo apt upgrade -y  # Ubuntu/Debian
# or
sudo yum update -y  # RHEL/CentOS

# Install Python 3.11+ if not available
sudo apt install python3.11 python3.11-venv python3-pip -y

# Create service user
sudo useradd -r -s /bin/bash -d /opt/panos-upgrade panos-upgrade
sudo mkdir -p /opt/panos-upgrade
sudo chown panos-upgrade:panos-upgrade /opt/panos-upgrade
```

### 2. Install Application

```bash
# Switch to service user
sudo su - panos-upgrade

# Clone/copy application
cd /opt/panos-upgrade
# [Copy application files here]

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install application
pip install --upgrade pip
pip install -e .

# Initialize system
python scripts/init_system.py
```

### 3. Configure Application

```bash
# Set Panorama connection (for device discovery)
panos-upgrade config set panorama.host panorama.example.com
panos-upgrade config set panorama.api_key YOUR_SECURE_API_KEY

# Set firewall credentials (for direct connections)
panos-upgrade config set firewall.username admin
panos-upgrade config set firewall.password YOUR_SECURE_PASSWORD

# Configure for production
panos-upgrade config set workers.max 10
panos-upgrade config set validation.min_disk_gb 5.0
panos-upgrade config set logging.level INFO

# Copy upgrade paths
cp examples/upgrade_paths.json /var/lib/panos-upgrade/config/
# Edit as needed
nano /var/lib/panos-upgrade/config/upgrade_paths.json

# Discover devices from Panorama
panos-upgrade device discover
```

### 4. Set Up Systemd Service

Create `/etc/systemd/system/panos-upgrade.service`:

```ini
[Unit]
Description=PAN-OS Upgrade Manager Daemon
After=network.target

[Service]
Type=simple
User=panos-upgrade
Group=panos-upgrade
WorkingDirectory=/opt/panos-upgrade
Environment="PATH=/opt/panos-upgrade/venv/bin"
ExecStart=/opt/panos-upgrade/venv/bin/python -m panos_upgrade.daemon
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=panos-upgrade

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/panos-upgrade

[Install]
WantedBy=multi-user.target
```

Enable and start service:

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable panos-upgrade

# Start service
sudo systemctl start panos-upgrade

# Check status
sudo systemctl status panos-upgrade
```

### 5. Configure Log Rotation

Create `/etc/logrotate.d/panos-upgrade`:

```
/var/lib/panos-upgrade/logs/text/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 panos-upgrade panos-upgrade
    sharedscripts
    postrotate
        systemctl reload panos-upgrade > /dev/null 2>&1 || true
    endscript
}

/var/lib/panos-upgrade/logs/structured/*.json {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 0640 panos-upgrade panos-upgrade
}
```

### 6. Set Up Monitoring (Optional)

#### Systemd Journal Monitoring

```bash
# View logs
sudo journalctl -u panos-upgrade -f

# View logs from today
sudo journalctl -u panos-upgrade --since today

# View errors only
sudo journalctl -u panos-upgrade -p err
```

#### Create Monitoring Script

Create `/opt/panos-upgrade/scripts/health_check.sh`:

```bash
#!/bin/bash

# Check if daemon is running
if ! systemctl is-active --quiet panos-upgrade; then
    echo "ERROR: Daemon is not running"
    exit 1
fi

# Check daemon status file
DAEMON_STATUS="/var/lib/panos-upgrade/status/daemon.json"
if [ ! -f "$DAEMON_STATUS" ]; then
    echo "ERROR: Daemon status file not found"
    exit 1
fi

# Check if daemon is marked as running
RUNNING=$(jq -r '.running' "$DAEMON_STATUS")
if [ "$RUNNING" != "true" ]; then
    echo "ERROR: Daemon not marked as running"
    exit 1
fi

# Check for recent updates (within last 60 seconds)
LAST_UPDATE=$(jq -r '.last_updated' "$DAEMON_STATUS")
CURRENT_TIME=$(date -u +%s)
LAST_UPDATE_TIME=$(date -d "$LAST_UPDATE" +%s 2>/dev/null || echo 0)
TIME_DIFF=$((CURRENT_TIME - LAST_UPDATE_TIME))

if [ $TIME_DIFF -gt 60 ]; then
    echo "WARNING: Daemon status not updated in $TIME_DIFF seconds"
    exit 1
fi

echo "OK: Daemon is healthy"
exit 0
```

Make executable:

```bash
chmod +x /opt/panos-upgrade/scripts/health_check.sh
```

Add to cron for monitoring:

```bash
# Add to crontab
sudo crontab -e -u panos-upgrade

# Add line:
*/5 * * * * /opt/panos-upgrade/scripts/health_check.sh >> /var/log/panos-upgrade-health.log 2>&1
```

## Web Application Integration

### Directory Permissions

Ensure web application user can access status files:

```bash
# Add web user to panos-upgrade group
sudo usermod -a -G panos-upgrade www-data

# Set appropriate permissions
sudo chmod 750 /var/lib/panos-upgrade/status
sudo chmod 750 /var/lib/panos-upgrade/validation
sudo chmod 770 /var/lib/panos-upgrade/queue/pending
sudo chmod 770 /var/lib/panos-upgrade/commands/incoming
```

### Web App Job Submission

Python example:

```python
import json
import uuid
import tempfile
import os
from datetime import datetime
from pathlib import Path

def submit_upgrade_job(device_serial, dry_run=False):
    """Submit upgrade job from web application."""
    
    job_id = f"web-{uuid.uuid4()}"
    job_data = {
        "job_id": job_id,
        "type": "standalone",
        "devices": [device_serial],
        "dry_run": dry_run,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    
    # Atomic write
    pending_dir = Path("/var/lib/panos-upgrade/queue/pending")
    
    # Write to temp file
    fd, temp_path = tempfile.mkstemp(
        dir=pending_dir,
        prefix=".job.",
        suffix=".tmp"
    )
    
    with os.fdopen(fd, 'w') as f:
        json.dump(job_data, f, indent=2)
    
    # Move to final location
    final_path = pending_dir / f"{job_id}.json"
    os.replace(temp_path, final_path)
    
    return job_id
```

### Web App Status Reading

```python
import json
from pathlib import Path

def get_device_status(serial):
    """Get device status from web application."""
    
    status_file = Path(f"/var/lib/panos-upgrade/status/devices/{serial}.json")
    
    if not status_file.exists():
        return None
    
    with open(status_file) as f:
        return json.load(f)

def get_daemon_status():
    """Get daemon status."""
    
    status_file = Path("/var/lib/panos-upgrade/status/daemon.json")
    
    with open(status_file) as f:
        return json.load(f)
```

## Security Hardening

### 1. File Permissions

```bash
# Restrict access to configuration
sudo chmod 600 /var/lib/panos-upgrade/config/config.json
sudo chown panos-upgrade:panos-upgrade /var/lib/panos-upgrade/config/config.json

# Restrict work directory
sudo chmod 750 /var/lib/panos-upgrade
sudo chown -R panos-upgrade:panos-upgrade /var/lib/panos-upgrade
```

### 2. Firewall Rules

```bash
# Allow outbound HTTPS to Panorama (for discovery)
sudo ufw allow out to PANORAMA_IP port 443 proto tcp

# Allow outbound HTTPS to all firewall management IPs (for operations)
# This may require a range or multiple rules depending on your network
sudo ufw allow out to FIREWALL_MGMT_NETWORK/24 port 443 proto tcp
```

### 3. API Key Management

Consider using a secrets management system:

```bash
# Example with HashiCorp Vault
export PANORAMA_API_KEY=$(vault kv get -field=api_key secret/panos-upgrade)
panos-upgrade config set panorama.api_key "$PANORAMA_API_KEY"
```

### 4. Audit Logging

Enable audit logging for file access:

```bash
# Install auditd
sudo apt install auditd

# Add audit rules
sudo auditctl -w /var/lib/panos-upgrade/config/ -p wa -k panos-config
sudo auditctl -w /var/lib/panos-upgrade/queue/ -p wa -k panos-queue
```

## Backup and Recovery

### Backup Configuration

```bash
#!/bin/bash
# /opt/panos-upgrade/scripts/backup.sh

BACKUP_DIR="/backup/panos-upgrade"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup configuration
tar -czf "$BACKUP_DIR/config-$DATE.tar.gz" \
    /var/lib/panos-upgrade/config/

# Backup status (for recovery)
tar -czf "$BACKUP_DIR/status-$DATE.tar.gz" \
    /var/lib/panos-upgrade/status/ \
    /var/lib/panos-upgrade/queue/

# Keep last 30 days
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete
```

Add to cron:

```bash
0 2 * * * /opt/panos-upgrade/scripts/backup.sh
```

### Recovery Procedure

```bash
# Stop service
sudo systemctl stop panos-upgrade

# Restore configuration
cd /
sudo tar -xzf /backup/panos-upgrade/config-YYYYMMDD_HHMMSS.tar.gz

# Restore status if needed
sudo tar -xzf /backup/panos-upgrade/status-YYYYMMDD_HHMMSS.tar.gz

# Fix permissions
sudo chown -R panos-upgrade:panos-upgrade /var/lib/panos-upgrade

# Start service
sudo systemctl start panos-upgrade
```

## Performance Tuning

### For Large Deployments (200+ devices)

```bash
# Increase worker threads
panos-upgrade config set workers.max 20

# Increase queue size
panos-upgrade config set workers.queue_size 2000

# Adjust rate limit based on Panorama capacity
panos-upgrade config set panorama.rate_limit 20

# Increase timeout for slow networks
panos-upgrade config set panorama.timeout 600
```

### System Resources

```bash
# Increase file descriptor limits
echo "panos-upgrade soft nofile 4096" | sudo tee -a /etc/security/limits.conf
echo "panos-upgrade hard nofile 8192" | sudo tee -a /etc/security/limits.conf
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u panos-upgrade -n 100

# Check permissions
ls -la /var/lib/panos-upgrade
ls -la /opt/panos-upgrade

# Test manually
sudo su - panos-upgrade
cd /opt/panos-upgrade
source venv/bin/activate
python -m panos_upgrade.daemon
```

### High Memory Usage

```bash
# Check worker count
panos-upgrade config show | grep workers

# Reduce workers if needed
panos-upgrade config set workers.max 5

# Restart service
sudo systemctl restart panos-upgrade
```

### Slow Upgrades

```bash
# Check worker utilization
cat /var/lib/panos-upgrade/status/workers.json | jq

# Check firewall connectivity (operations use direct connections)
ping FIREWALL_MGMT_IP

# Check if inventory is populated
cat /var/lib/panos-upgrade/devices/inventory.json | jq '.devices | length'
```

### Cannot Connect to Firewalls

```bash
# Verify firewall credentials
panos-upgrade config show | grep firewall

# Test connectivity to firewall management IP
curl -k https://FIREWALL_MGMT_IP/api/

# Re-discover devices if inventory is stale
panos-upgrade device discover
```

## Maintenance

### Regular Tasks

**Daily**:
- Review logs for errors
- Check daemon status
- Monitor disk space

**Weekly**:
- Review completed upgrades
- Clean old validation files
- Check backup integrity

**Monthly**:
- Review and update upgrade paths
- Update application if needed
- Review security settings

### Cleanup Script

```bash
#!/bin/bash
# /opt/panos-upgrade/scripts/cleanup.sh

# Remove old completed jobs (>30 days)
find /var/lib/panos-upgrade/queue/completed -name "*.json" -mtime +30 -delete

# Remove old validation files (>60 days)
find /var/lib/panos-upgrade/validation -name "*.json" -mtime +60 -delete

# Remove old processed commands (>7 days)
find /var/lib/panos-upgrade/commands/processed -name "*.json" -mtime +7 -delete

echo "Cleanup completed: $(date)"
```

## Upgrading the Application

```bash
# Stop service
sudo systemctl stop panos-upgrade

# Backup current version
sudo su - panos-upgrade
cd /opt/panos-upgrade
tar -czf ~/panos-upgrade-backup-$(date +%Y%m%d).tar.gz .

# Update code
git pull  # or copy new files

# Update dependencies
source venv/bin/activate
pip install --upgrade -e .

# Test configuration
panos-upgrade config show

# Start service
exit
sudo systemctl start panos-upgrade

# Verify
sudo systemctl status panos-upgrade
```

## Production Checklist

- [ ] Service user created with limited permissions
- [ ] Application installed in /opt/panos-upgrade
- [ ] Virtual environment configured
- [ ] Configuration files secured (600 permissions)
- [ ] Panorama connection configured (for discovery)
- [ ] Firewall credentials configured (for operations)
- [ ] Device discovery completed (`panos-upgrade device discover`)
- [ ] Upgrade paths configured and tested
- [ ] Network connectivity verified to all firewall management IPs
- [ ] Systemd service configured and enabled
- [ ] Log rotation configured
- [ ] Monitoring/health checks in place
- [ ] Backup script configured
- [ ] Web application integration tested
- [ ] Firewall rules configured (Panorama + firewall mgmt IPs)
- [ ] Documentation accessible to team
- [ ] Tested with dry-run mode
- [ ] Emergency procedures documented

## Support and Escalation

### Log Collection for Support

```bash
# Collect diagnostic information
sudo tar -czf panos-upgrade-diag-$(date +%Y%m%d).tar.gz \
    /var/lib/panos-upgrade/logs/ \
    /var/lib/panos-upgrade/config/ \
    /var/lib/panos-upgrade/status/ \
    /var/log/syslog \
    /etc/systemd/system/panos-upgrade.service

# Sanitize API keys before sharing!
```

### Emergency Stop

```bash
# Stop daemon immediately
sudo systemctl stop panos-upgrade

# Prevent auto-restart
sudo systemctl disable panos-upgrade

# Check for running upgrades
ls /var/lib/panos-upgrade/queue/active/
```

