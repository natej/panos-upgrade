# Mock Panorama Server - Quick Start Guide

## 5-Minute Setup

### 1. Install Dependencies

```bash
cd /Users/nathan/projects/panos-upgrade
pip install -r tests/mock_panorama/requirements.txt
```

### 2. Start Mock Server

```bash
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml
```

You should see:
```
Starting Mock Panorama Server on 0.0.0.0:8443
Loading configuration from: tests/mock_panorama/scenarios/basic.yaml
INFO:     Started server process
INFO:     Uvicorn running on http://0.0.0.0:8443
```

### 3. Configure PAN-OS Upgrade Manager

In a new terminal:

```bash
# Point to mock server
panos-upgrade config set panorama.host localhost:8443
panos-upgrade config set panorama.api_key test-api-key

# Copy upgrade paths
cp tests/mock_panorama/test_upgrade_paths.json /var/lib/panos-upgrade/config/upgrade_paths.json
```

### 4. Start Daemon

```bash
panos-upgrade daemon start --workers 3
```

### 5. Submit Test Upgrade

```bash
# Dry run first
panos-upgrade job submit --device 001234567890 --dry-run

# Real upgrade (against mock)
panos-upgrade job submit --device 001234567890
```

### 6. Monitor Progress

```bash
# Watch device status
watch -n 2 'panos-upgrade device status 001234567890'

# View logs
tail -f /var/lib/panos-upgrade/logs/text/panos-upgrade-*.log
```

## Test Scenarios

### Scenario 1: Single Device (Fast)

```bash
# Terminal 1: Start mock server
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml

# Terminal 2: Run upgrade
panos-upgrade job submit --device 001234567890
```

**Expected**: Complete upgrade in ~30 seconds (10s download + 5s install + 15s reboot)

### Scenario 2: HA Pair

```bash
# Terminal 1: Start mock server
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/ha_pair.yaml

# Terminal 2: Submit HA pair upgrade
panos-upgrade job submit --ha-pair datacenter-1
```

**Expected**: Passive upgraded first, then active

### Scenario 3: Failure Testing

```bash
# Terminal 1: Start mock server with failures
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/failures.yaml

# Terminal 2: Submit multiple devices
panos-upgrade job submit --device 001234567890  # Will fail at download
panos-upgrade job submit --device 001234567891  # Will fail at install
panos-upgrade job submit --device 001234567892  # Will fail at reboot
panos-upgrade job submit --device 001234567893  # Will fail pre-flight (low disk)
```

**Expected**: Different failure modes, queue continues processing

### Scenario 4: Load Test

```bash
# Terminal 1: Start mock server with 10 devices
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/large_scale.yaml

# Terminal 2: Start daemon with more workers
panos-upgrade daemon start --workers 10

# Terminal 3: Submit all devices
for serial in 001234567890 001234567891 001234567892 001234567893 001234567894 \
              001234567895 001234567896 001234567897 001234567898 001234567899; do
  panos-upgrade job submit --device $serial
done

# Monitor
watch -n 2 'panos-upgrade daemon status'
```

**Expected**: 10 concurrent upgrades

## Timing Modes

### Fast Mode (Default - for testing)

```bash
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml
```

- Download: 10 seconds
- Install: 5 seconds
- Reboot: 15 seconds
- **Total per device**: ~30 seconds

### Realistic Mode (for demos)

```bash
export DOWNLOAD_DURATION=60
export INSTALL_DURATION=30
export REBOOT_DURATION=90

python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml
```

- Download: 60 seconds
- Install: 30 seconds
- Reboot: 90 seconds
- **Total per device**: ~3 minutes

### Production Simulation

```bash
export DOWNLOAD_DURATION=600
export INSTALL_DURATION=300
export REBOOT_DURATION=600

python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml
```

- Download: 10 minutes
- Install: 5 minutes
- Reboot: 10 minutes
- **Total per device**: ~25 minutes

## Verify Setup

### Check Server

```bash
# Server info
curl http://localhost:8443/

# List devices
curl http://localhost:8443/devices

# Get device details
curl http://localhost:8443/devices/001234567890
```

### Check PAN-OS Client

```bash
# List devices
panos-upgrade device list

# Check device status
panos-upgrade device status 001234567890

# Validate device
panos-upgrade device validate 001234567890
```

## Common Issues

### Port Already in Use

```bash
# Use different port
python -m tests.mock_panorama.server --config scenarios/basic.yaml --port 9443

# Update config
panos-upgrade config set panorama.host localhost:9443
```

### Database Locked

```bash
# Remove old database
rm mock_panorama.db

# Restart server
python -m tests.mock_panorama.server --config scenarios/basic.yaml
```

### Connection Refused

Make sure you're using `localhost:8443` not `https://localhost:8443`:

```bash
# Correct
panos-upgrade config set panorama.host localhost:8443

# Wrong
panos-upgrade config set panorama.host https://localhost:8443
```

## Next Steps

1. **Run Test Suite**: `python tests/mock_panorama/test_example.py`
2. **Create Custom Scenario**: Copy and modify a YAML file
3. **Test Web Integration**: Use the web API examples
4. **Load Testing**: Test with 50+ devices

## Clean Up

```bash
# Stop daemon
panos-upgrade daemon stop

# Stop mock server (Ctrl+C in terminal)

# Remove database
rm mock_panorama.db

# Reset config
panos-upgrade config set panorama.host panorama.example.com
panos-upgrade config set panorama.api_key YOUR_REAL_KEY
```

## Tips

- Use `--dry-run` flag to test without state changes
- Monitor logs in real-time: `tail -f /var/lib/panos-upgrade/logs/text/*.log`
- Check worker utilization: `panos-upgrade daemon status`
- View validation results: `ls -la /var/lib/panos-upgrade/validation/post_flight/`
- Inspect database: `sqlite3 mock_panorama.db "SELECT * FROM devices;"`

## Help

For more information:
- Full README: `tests/mock_panorama/README.md`
- Test examples: `tests/mock_panorama/test_example.py`
- Scenarios: `tests/mock_panorama/scenarios/`

