# Mock Panorama Server - Architecture

## Overview

The Mock Panorama Server is a stateful simulation system that mimics PAN-OS API behavior for testing firewall upgrades without production risk.

## Design Principles

1. **Realistic Behavior** - Accurate XML responses matching PAN-OS format
2. **Stateful Operations** - Tracks device state across operations
3. **Async Simulation** - Background workers for downloads, installs, reboots
4. **Configurable** - YAML-based scenarios and timing
5. **Testable** - Fast mode for CI/CD, realistic mode for demos
6. **Isolated** - No network dependencies, runs locally

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Server (server.py)                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  GET /api/                                             │  │
│  │    - type=op&cmd=<XML>&key=<KEY>&target=<SERIAL>     │  │
│  │    - Validates API key                                 │  │
│  │    - Routes to CommandHandler                          │  │
│  └────────────────────┬──────────────────────────────────┘  │
│                       │                                      │
│  ┌────────────────────┴──────────────────────────────────┐  │
│  │  CommandHandler (command_handlers.py)                  │  │
│  │    - Parses XML commands                               │  │
│  │    - Routes to specific handlers                       │  │
│  │    - Returns XML responses                             │  │
│  └────────────────────┬──────────────────────────────────┘  │
│                       │                                      │
│         ┌─────────────┼─────────────┐                       │
│         │             │             │                       │
│  ┌──────┴──────┐ ┌───┴────────┐ ┌─┴──────────────┐        │
│  │   Device    │ │ Operation  │ │  XML Responses │        │
│  │   Manager   │ │  Manager   │ │  (xml_responses│        │
│  │  (device_   │ │ (operation_│ │      .py)      │        │
│  │  manager.py)│ │ manager.py)│ │                │        │
│  └──────┬──────┘ └───┬────────┘ └────────────────┘        │
│         │            │                                      │
│         │    ┌───────┴────────┐                            │
│         │    │  Background    │                            │
│         │    │   Workers      │                            │
│         │    │  (Threading)   │                            │
│         │    └───────┬────────┘                            │
│         │            │                                      │
│  ┌──────┴────────────┴──────────────────────────────────┐  │
│  │         SQLite Database (models.py)                   │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │  │
│  │  │   Devices   │  │  Operations  │  │ API Calls  │  │  │
│  │  │   Table     │  │    Table     │  │   Table    │  │  │
│  │  └─────────────┘  └──────────────┘  └────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         ↑                                            ↑
         │                                            │
    YAML Config                               PanoramaClient
   (scenarios/)                            (from main app)
```

## Components

### 1. FastAPI Server (`server.py`)

**Responsibilities:**
- HTTP endpoint handling
- API key validation
- Request routing
- Configuration loading
- Database initialization

**Key Methods:**
- `api_endpoint()` - Main PAN-OS API endpoint
- `list_devices()` - Management endpoint
- `get_device()` - Device details endpoint

### 2. Database Models (`models.py`)

**Tables:**

**Device:**
- Serial, hostname, model, version
- HA configuration
- State (online, rebooting, downloading, installing)
- Metrics (TCP sessions, routes, ARP, disk space)
- Timestamps

**Operation:**
- Operation ID, device serial, type
- Status, progress, error message
- Timing information

**APICall:**
- Request logging for debugging

### 3. Device Manager (`device_manager.py`)

**Responsibilities:**
- Device CRUD operations
- State management
- Metric generation
- Version updates

**Key Methods:**
- `add_device()` - Add device to simulation
- `get_device()` - Retrieve device state
- `update_device_version()` - Update after upgrade
- `set_device_state()` - Change device state
- `reboot_device()` - Mark as rebooting
- `bring_device_online()` - Complete reboot

**State Transitions:**
```
online → downloading → online
online → installing → online
online → rebooting → online (with metric changes)
```

### 4. Operation Manager (`operation_manager.py`)

**Responsibilities:**
- Async operation simulation
- Progress tracking
- Background workers
- Failure injection

**Operations:**

**Download:**
- Duration: Configurable (default 10s)
- Progress: 0% → 100% in 10 steps
- Side effects: Consumes 2GB disk space
- Can fail: Connection timeout

**Install:**
- Duration: Configurable (default 5s)
- Progress: Instant completion
- Side effects: Updates version, frees disk space
- Can fail: Installation error

**Reboot:**
- Duration: Configurable (default 15s)
- Progress: Device offline then online
- Side effects: Metric variations
- Can fail: Device doesn't come back

### 5. Command Handler (`command_handlers.py`)

**Responsibilities:**
- XML command parsing
- Command routing
- Response generation
- Failure injection

**Supported Commands:**

**Show Commands:**
- `show system info` → Device information
- `show high-availability state` → HA status
- `show session info` → TCP session count
- `show routing route` → Routing table
- `show arp all` → ARP table
- `show system disk-space` → Disk space
- `show system software status` → Download status

**Request Commands:**
- `request system software download` → Start download
- `request system software install` → Start install
- `request restart system` → Reboot device

### 6. XML Responses (`xml_responses.py`)

**Responsibilities:**
- XML response generation
- PAN-OS format compliance
- Error responses

**Response Types:**
- Success responses with data
- Error responses with messages
- Progress responses

## Data Flow

### Upgrade Flow

```
1. Client sends: <request><system><software><download>
   ↓
2. CommandHandler parses XML
   ↓
3. Checks device state (must be online)
   ↓
4. Checks disk space (must be >= 2GB)
   ↓
5. OperationManager.start_download()
   ↓
6. Background worker starts
   ↓
7. Device state → "downloading"
   ↓
8. Progress updates every N seconds
   ↓
9. Download completes
   ↓
10. Disk space reduced by 2GB
    ↓
11. Device state → "online"
    ↓
12. Returns success response
```

### State Persistence

```
Operation Start
    ↓
Write to Database
    ↓
Background Worker
    ↓
Periodic Progress Updates → Database
    ↓
Operation Complete
    ↓
Final State Update → Database
```

## Configuration System

### YAML Structure

```yaml
api_key: "test-api-key"

timing:
  download_duration: 10
  install_duration: 5
  reboot_duration: 15

devices:
  - serial: "..."
    hostname: "..."
    current_version: "..."
    metrics:
      tcp_sessions: 45000
      route_count: 1200
      arp_count: 500
      disk_space_gb: 15.0
    available_versions: [...]

failures:
  - device: "..."
    operation: "download"
    failure_rate: 0.5
```

### Loading Process

1. Server starts
2. Loads YAML configuration
3. Initializes database
4. Creates DeviceManager
5. Loads devices from config
6. Creates OperationManager with timing
7. Creates CommandHandler with failures
8. Starts FastAPI server

## Timing System

### Configurable Modes

**Fast (Default):**
- Download: 10s
- Install: 5s
- Reboot: 15s
- Use: Testing, CI/CD

**Realistic:**
- Download: 60-120s
- Install: 30-60s
- Reboot: 90-180s
- Use: Demos, training

**Production Simulation:**
- Download: 600s (10 min)
- Install: 300s (5 min)
- Reboot: 600s (10 min)
- Use: Stress testing

### Environment Variables

```bash
export DOWNLOAD_DURATION=10
export INSTALL_DURATION=5
export REBOOT_DURATION=15
```

Override YAML settings for quick adjustments.

## Failure Injection

### Configuration

```yaml
failures:
  - device: "001234567890"
    operation: "download"
    failure_rate: 0.3  # 30% chance
    error: "Connection timeout"
```

### Implementation

1. CommandHandler checks failure config
2. Random number < failure_rate → fail
3. Operation marked as failed
4. Error message returned
5. Device state restored

### Use Cases

- Test retry logic
- Test error handling
- Test queue continuation
- Test manual takeover

## Concurrency

### Thread Safety

- SQLite with WAL mode
- Session per request
- Background workers in separate threads
- No shared mutable state

### Concurrent Operations

- Multiple devices can upgrade simultaneously
- Each device has independent state
- Operations tracked separately
- No inter-device dependencies

## Testing Strategy

### Unit Tests

Test individual components:
- Device manager operations
- Operation manager workers
- XML response generation
- Command parsing

### Integration Tests

Test full flow:
- API endpoint → Command handler → Response
- Device state transitions
- Operation completion
- Failure scenarios

### End-to-End Tests

Test with real client:
- PanoramaClient integration
- Full upgrade flow
- HA pair coordination
- Validation system

## Performance

### Metrics

- Handles 50+ concurrent devices
- Sub-100ms response time
- Minimal memory footprint (~50MB)
- SQLite scales to thousands of devices

### Optimization

- Indexed database queries
- Efficient XML parsing
- Async background workers
- Connection pooling

## Extensibility

### Adding New Commands

1. Add handler in `command_handlers.py`
2. Add XML response in `xml_responses.py`
3. Update routing logic
4. Add tests

### Adding New Metrics

1. Update Device model
2. Update device_manager generation
3. Update XML responses
4. Update scenarios

### Adding New Operations

1. Add operation type to models
2. Add worker in operation_manager
3. Add command handler
4. Add XML responses

## Limitations

### Not Simulated

- Actual PAN-OS software
- Configuration management
- Commit operations
- Log files
- Threat/content updates
- Certificate management
- VPN tunnels
- User authentication

### Simplified Behavior

- HA failover (instant, no split-brain)
- Metric changes (random, not realistic)
- Network conditions (no latency simulation)
- Resource constraints (no CPU/memory limits)

## Future Enhancements

1. **SSL/TLS Support** - HTTPS endpoints
2. **More Realistic Metrics** - Pattern-based changes
3. **Log Simulation** - Generate log files
4. **Config Management** - Commit simulation
5. **Multi-Panorama** - Multiple server instances
6. **Web UI** - Visual monitoring
7. **Replay Mode** - Record/replay API calls
8. **Performance Metrics** - Built-in profiling

## Security Considerations

### Current Implementation

- Simple API key validation
- No encryption
- Local-only by default
- No authentication beyond API key

### Production Recommendations

- Use HTTPS in production
- Implement proper authentication
- Rate limiting
- Input validation
- Audit logging

## Deployment

### Development

```bash
python -m tests.mock_panorama.server --config scenarios/basic.yaml
```

### CI/CD

```bash
# Start in background
python -m tests.mock_panorama.server --config scenarios/basic.yaml &
SERVER_PID=$!

# Run tests
pytest tests/

# Cleanup
kill $SERVER_PID
```

### Docker (Future)

```dockerfile
FROM python:3.11
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python", "-m", "tests.mock_panorama.server"]
```

## Conclusion

The Mock Panorama Server provides a complete, stateful simulation environment for testing PAN-OS upgrades. Its modular architecture, configurable timing, and failure injection capabilities make it suitable for development, testing, demos, and training.

