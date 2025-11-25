# Mock Panorama Server

A stateful simulation server for testing PAN-OS upgrades without touching production firewalls.

## Features

- ✅ **Realistic API Responses** - XML responses matching PAN-OS format
- ✅ **Stateful Operations** - Tracks device state across operations
- ✅ **Async Operations** - Simulates downloads, installs, reboots with progress
- ✅ **HA Pair Support** - Simulates HA configurations
- ✅ **Failure Injection** - Configurable failure scenarios
- ✅ **Fast Testing** - Configurable timing (fast for tests, realistic for demos)
- ✅ **YAML Configuration** - Easy scenario setup
- ✅ **SQLite Persistence** - State persists across restarts

## Installation

```bash
cd tests/mock_panorama
pip install -r requirements.txt
```

## Quick Start

### 1. Start the Server

```bash
# Basic scenario (3 standalone devices)
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml

# HA pair scenario
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/ha_pair.yaml

# Failure injection scenario
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/failures.yaml

# Large scale (10 devices)
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/large_scale.yaml
```

Server will start on `http://localhost:8443`

### 2. Configure PAN-OS Upgrade Manager

```bash
panos-upgrade config set panorama.host localhost:8443
panos-upgrade config set panorama.api_key test-api-key
```

### 3. Run Upgrades

```bash
# Start daemon
panos-upgrade daemon start --workers 3

# Submit upgrade
panos-upgrade job submit --device 001234567890

# Monitor
panos-upgrade device status 001234567890
```

## Configuration

### Timing Configuration

Control operation duration via YAML or environment variables:

```yaml
timing:
  download_duration: 10   # seconds
  install_duration: 5
  reboot_duration: 15
```

Or via environment:

```bash
export DOWNLOAD_DURATION=10
export INSTALL_DURATION=5
export REBOOT_DURATION=15
```

**Recommended Settings:**
- **Fast Testing**: 10/5/15 seconds (default)
- **Realistic Demo**: 120/60/180 seconds
- **Production Simulation**: 600/300/600 seconds

### Device Configuration

```yaml
devices:
  - serial: "001234567890"
    hostname: "fw-test-1"
    model: "PA-3220"
    current_version: "10.0.2"
    ip_address: "192.168.1.10"
    ha_enabled: false
    metrics:
      tcp_sessions: 45000
      route_count: 1200
      arp_count: 500
      disk_space_gb: 15.0
    available_versions:
      - "10.1.0"
      - "10.5.1"
      - "11.1.0"
```

### Failure Injection

```yaml
failures:
  - device: "001234567890"
    operation: "download"  # download, install, reboot
    failure_rate: 0.5      # 50% chance of failure
    error: "Connection timeout"
```

## API Endpoints

### PAN-OS API (Compatible with pan-python)

```
GET /api/?type=op&cmd=<XML>&key=<API_KEY>&target=<SERIAL>
```

### Management Endpoints

```
GET  /                    # Server info
GET  /devices             # List all devices
GET  /devices/{serial}    # Get device details
GET  /operations          # List all operations
GET  /health              # Health check
```

## Scenarios

### Basic Scenario

3 standalone devices with different versions:
- `001234567890`: 10.0.2 → needs multi-step upgrade
- `001234567891`: 10.5.1 → single step to 11.1.0
- `001234567892`: 11.0.0 → needs intermediate version

```bash
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml
```

### HA Pair Scenario

HA pair with active/passive configuration:
- `001234567890`: Active member
- `001234567891`: Passive member

Tests passive-first upgrade logic.

```bash
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/ha_pair.yaml
```

### Failure Scenario

4 devices with different failure modes:
- `001234567890`: Download failure
- `001234567891`: Install failure
- `001234567892`: Reboot failure
- `001234567893`: Insufficient disk space

```bash
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/failures.yaml
```

### Large Scale Scenario

10 devices across multiple data centers for load testing.

```bash
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/large_scale.yaml
```

## Testing

### Run Test Suite

```bash
# Start server
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml

# In another terminal, run tests
python tests/mock_panorama/test_example.py
```

### Manual Testing

```bash
# Start server
python -m tests.mock_panorama.server --config tests/mock_panorama/scenarios/basic.yaml

# Test API endpoint
curl "http://localhost:8443/devices"

# Test device info
curl "http://localhost:8443/api/?type=op&cmd=<show><system><info></info></system></show>&key=test-api-key&target=001234567890"
```

## Development

### Project Structure

```
tests/mock_panorama/
├── __init__.py
├── server.py              # FastAPI server
├── models.py              # SQLAlchemy models
├── device_manager.py      # Device state management
├── operation_manager.py   # Async operations
├── command_handlers.py    # Command processing
├── xml_responses.py       # XML response templates
├── scenarios/
│   ├── basic.yaml
│   ├── ha_pair.yaml
│   ├── failures.yaml
│   └── large_scale.yaml
├── test_example.py        # Test examples
└── README.md
```

### Adding New Scenarios

1. Create YAML file in `scenarios/`
2. Define devices, timing, and failures
3. Start server with new config

Example:

```yaml
api_key: "test-api-key"

timing:
  download_duration: 10
  install_duration: 5
  reboot_duration: 15

devices:
  - serial: "YOUR_SERIAL"
    hostname: "your-hostname"
    current_version: "10.0.2"
    # ... other fields

failures: []
```

### Extending Functionality

**Add New Commands:**
1. Add handler in `command_handlers.py`
2. Add XML response in `xml_responses.py`
3. Update routing logic

**Add New Metrics:**
1. Update `Device` model in `models.py`
2. Update `device_manager.py` generation
3. Update XML responses

## Troubleshooting

### Server Won't Start

```bash
# Check if port is in use
lsof -i :8443

# Use different port
python -m tests.mock_panorama.server --port 9443
```

### Database Issues

```bash
# Delete and recreate database
rm mock_panorama.db
python -m tests.mock_panorama.server --config scenarios/basic.yaml
```

### Connection Refused

Make sure to use `localhost:8443` not `https://localhost:8443`:

```bash
panos-upgrade config set panorama.host localhost:8443
```

## Use Cases

### 1. Development

Test upgrade logic without Panorama access:

```bash
# Fast timing for quick iteration
export DOWNLOAD_DURATION=5
export INSTALL_DURATION=2
export REBOOT_DURATION=10

python -m tests.mock_panorama.server --config scenarios/basic.yaml
```

### 2. CI/CD Pipeline

Automated testing in CI:

```yaml
# .github/workflows/test.yml
- name: Start Mock Panorama
  run: |
    python -m tests.mock_panorama.server --config scenarios/basic.yaml &
    sleep 5

- name: Run Tests
  run: python tests/mock_panorama/test_example.py
```

### 3. Demos

Realistic timing for demonstrations:

```bash
export DOWNLOAD_DURATION=60
export INSTALL_DURATION=30
export REBOOT_DURATION=90

python -m tests.mock_panorama.server --config scenarios/ha_pair.yaml
```

### 4. Training

Safe environment for learning:

```bash
# Students can practice without risk
python -m tests.mock_panorama.server --config scenarios/large_scale.yaml
```

### 5. Load Testing

Test with many concurrent upgrades:

```bash
python -m tests.mock_panorama.server --config scenarios/large_scale.yaml
panos-upgrade daemon start --workers 10
```

## Limitations

- No actual PAN-OS software images
- Simplified HA behavior (no split-brain scenarios)
- No configuration management
- No commit operations
- No log file simulation
- No threat/content updates

## Future Enhancements

- [ ] SSL/TLS support
- [ ] More realistic metric variations
- [ ] Log file simulation
- [ ] Configuration commit simulation
- [ ] Multi-Panorama support
- [ ] REST API for easier testing
- [ ] Web UI for monitoring

## License

Same as main project.

