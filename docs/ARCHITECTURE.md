# PAN-OS Upgrade Manager - Architecture

## Overview

The PAN-OS Upgrade Manager is a daemon-based CLI application that orchestrates firmware upgrades for PAN-OS devices through Panorama. It features concurrent processing, comprehensive validation, and web application integration through JSON file-based communication.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI Interface                            │
│  (Click-based commands: daemon, job, device, config, path)      │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────────┐
│                      Daemon Service                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   Worker     │  │   Command    │  │    Status    │         │
│  │   Pool       │  │   Queue      │  │   Updater    │         │
│  │  Manager     │  │   Monitor    │  │              │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────┴────────────────────────────────────────┐
│                   Upgrade Manager                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  • Version Path Management                                │  │
│  │  • Standalone Device Upgrades                             │  │
│  │  • HA Pair Upgrades (Passive First)                       │  │
│  │  • Cancellation Handling                                  │  │
│  │  • Dry-Run Mode                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────┴──────┐  ┌──────┴──────┐  ┌─────┴──────┐
│  Panorama    │  │ Validation  │  │   Logging  │
│   Client     │  │   System    │  │   System   │
│              │  │             │  │            │
│ • API Calls  │  │ • Pre-flight│  │ • JSON     │
│ • Rate Limit │  │ • Post-flight│ │ • Text     │
│ • Serial#    │  │ • Comparison│  │            │
└──────────────┘  └─────────────┘  └────────────┘
        │
        │
┌───────┴──────────────────────────────────────────┐
│              Panorama Server                      │
│  (Proxies commands to individual firewalls)      │
└──────────────────────────────────────────────────┘
```

## Core Components

### 1. CLI Interface (`cli.py`)

**Purpose**: User-facing command-line interface

**Key Features**:
- Click-based command structure
- Command groups: daemon, job, device, config, path
- Context management for configuration and logging
- Input validation and error handling

**Commands**:
- `daemon start/stop/restart/status`
- `job submit/list/status/cancel`
- `device list/status/validate/metrics`
- `config set/show`
- `path show/validate`

### 2. Daemon Service (`daemon.py`)

**Purpose**: Background service that manages the upgrade process

**Key Responsibilities**:
- Worker pool management
- Job queue processing
- Command queue monitoring
- Status updates and persistence
- Rate limiting coordination

**Threading Model**:
- Main thread: Daemon control loop
- Worker threads: Process upgrade jobs (1-50 configurable)
- Job processor thread: Monitors pending queue
- Status updater thread: Periodic status persistence
- Command monitor thread: Watches for incoming commands

### 3. Worker Pool (`worker_pool.py`)

**Purpose**: Manages concurrent upgrade processing

**Features**:
- Configurable worker threads (1-50)
- Queue-based work distribution
- Individual failure isolation
- Status callbacks
- Graceful shutdown

**Design Pattern**: Thread pool with work queue

### 4. Upgrade Manager (`upgrade_manager.py`)

**Purpose**: Orchestrates the upgrade process

**Key Functions**:
- `upgrade_device()`: Standalone firewall upgrade
- `upgrade_ha_pair()`: HA pair upgrade (passive first)
- `get_upgrade_path()`: Version path lookup
- `cancel_upgrade()`: Graceful cancellation

**Upgrade Flow**:
1. Load device info and current version
2. Lookup upgrade path from configuration
3. Skip if version not found
4. For each version in path:
   - Pre-flight validation
   - Download software
   - Install software
   - Reboot device
   - Post-flight validation
5. Update status throughout

### 5. Panorama Client (`panorama_client.py`)

**Purpose**: Interface with Panorama API

**Key Methods**:
- `get_device_info()`: Device information
- `get_ha_state()`: HA status
- `get_system_metrics()`: Validation metrics
- `download_software()`: Initiate download
- `install_software()`: Initiate installation
- `reboot_device()`: Reboot command
- `check_device_ready()`: Post-reboot check

**Features**:
- Rate limiting integration
- Serial number targeting
- XML response parsing
- Error handling and retries

### 6. Validation System (`validation.py`)

**Purpose**: Pre-flight and post-flight validation

**Metrics Collected**:
- TCP session count
- Full routing table with individual routes
- Full ARP table with MAC addresses
- Available disk space

**Validation Process**:
1. **Pre-flight**: Collect baseline metrics, check disk space
2. **Post-flight**: Collect metrics again
3. **Comparison**: Calculate differences and changes
4. **Reporting**: Log detailed comparison results

**Comparison Logic**:
- TCP sessions: Percentage change within margin
- Routes: Added/removed route detection
- ARP entries: Added/removed entry detection

### 7. Configuration Management (`config.py`)

**Purpose**: Application configuration

**Features**:
- JSON-based configuration
- Dot-notation key access
- Automatic directory structure creation
- Default value handling
- Type conversion for known values

**Configuration Sections**:
- `panorama`: Connection settings
- `workers`: Thread pool settings
- `validation`: Validation thresholds
- `logging`: Log settings
- `paths`: File system paths

### 8. Logging System (`logging_config.py`)

**Purpose**: Dual logging (JSON + text)

**Features**:
- Structured JSON logs for machine parsing
- Traditional text logs for human reading
- Contextual logging with device/job metadata
- Daily log rotation
- Console output support

**Log Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL

## Data Flow

### Job Submission Flow

```
1. User/Web App creates job file
   → /var/lib/panos-upgrade/queue/pending/{uuid}.json

2. Daemon job processor detects file
   → Reads job configuration
   → Moves to active directory

3. Job submitted to worker pool
   → Worker picks up job
   → Calls upgrade_manager

4. Upgrade manager executes upgrade
   → Updates device status throughout
   → Saves validation results

5. Job completion
   → Moves to completed/failed/cancelled directory
   → Final status update
```

### Status Update Flow

```
1. Upgrade manager updates DeviceStatus object
   → In-memory state change

2. Status saved atomically
   → Write to temp file
   → Move to final location
   → /var/lib/panos-upgrade/status/devices/{serial}.json

3. Web app polls status file
   → Reads current state
   → Updates UI

4. Daemon status updater
   → Periodic updates every 5 seconds
   → Updates daemon.json and workers.json
```

### Cancellation Flow

```
1. Web app creates cancel command
   → /var/lib/panos-upgrade/commands/incoming/{timestamp}_{uuid}.json

2. Command queue monitor detects file
   → Reads command
   → Calls upgrade_manager.cancel_upgrade()

3. Upgrade manager marks for cancellation
   → Adds to cancelled set
   → Thread-safe operation

4. Worker checks cancellation status
   → Between upgrade phases
   → Graceful exit if cancelled

5. Command moved to processed
   → /var/lib/panos-upgrade/commands/processed/
```

## File System Structure

```
/var/lib/panos-upgrade/
├── config/
│   ├── config.json                    # Main configuration
│   └── upgrade_paths.json             # Version upgrade paths
├── queue/
│   ├── pending/                       # Jobs waiting to start
│   ├── active/                        # Jobs currently running
│   ├── completed/                     # Successfully completed jobs
│   └── cancelled/                     # Cancelled jobs
├── status/
│   ├── daemon.json                    # Daemon status
│   ├── workers.json                   # Worker thread statuses
│   └── devices/
│       ├── {serial}.json              # Individual device status
│       └── ha_pairs/
│           └── {pair_name}.json       # HA pair status
├── logs/
│   ├── structured/                    # JSON logs
│   │   └── panos-upgrade-YYYYMMDD.json
│   └── text/                          # Text logs
│       └── panos-upgrade-YYYYMMDD.log
├── validation/
│   ├── pre_flight/                    # Pre-upgrade metrics
│   │   └── {serial}_{timestamp}.json
│   └── post_flight/                   # Post-upgrade validation
│       └── {serial}_{timestamp}.json
└── commands/
    ├── incoming/                      # Commands from web app
    └── processed/                     # Processed commands
```

## Concurrency and Thread Safety

### Thread-Safe Operations

1. **Configuration**: Read-only after initialization
2. **Worker Pool**: Thread-safe queue operations
3. **Cancellation**: Lock-protected set operations
4. **File I/O**: Atomic write operations (temp + move)
5. **Status Updates**: Lock-protected daemon status

### Rate Limiting

**Token Bucket Algorithm**:
- Tokens replenish at configured rate
- Each API call consumes one token
- Blocks if no tokens available
- Thread-safe token management

### Isolation

- Individual job failures don't affect other jobs
- Worker thread failures are logged and recovered
- Queue continues processing on errors

## HA Pair Upgrade Logic

```
1. Query HA state for both devices
   → Determine active and passive members

2. Upgrade passive member first
   → Full upgrade cycle
   → Validation

3. Optional failover
   → Can be configured

4. Upgrade former active member
   → Full upgrade cycle
   → Validation

5. Complete HA pair upgrade
   → Both members on target version
```

## Dry-Run Mode

When `dry_run=True`:
- All validation steps are logged but not executed
- API calls are simulated with delays
- Status updates occur normally
- Useful for testing upgrade paths

## Error Handling Strategy

### Recoverable Errors
- Retry with exponential backoff
- Log detailed error information
- Continue with other devices

### Non-Recoverable Errors
- Mark device/job as failed
- Log comprehensive error details
- Provide manual takeover information
- Skip to next device in queue

### Critical Errors
- Attempt graceful degradation
- Preserve state to disk
- Alert via logs
- Allow manual intervention

## Performance Considerations

### Scalability
- Handles 230+ devices efficiently
- Configurable worker threads (up to 50)
- Rate limiting prevents Panorama overload
- Queue-based processing prevents memory issues

### Optimization
- Atomic file operations for consistency
- Minimal disk I/O
- Efficient XML parsing
- In-memory status tracking with periodic persistence

## Security Considerations

1. **API Key Storage**: Encrypted in configuration
2. **File Permissions**: Restricted to service user
3. **Audit Logging**: Complete operation trail
4. **Rate Limiting**: Prevents API abuse
5. **Input Validation**: All user inputs validated

## Extension Points

### Adding Custom Metrics
Edit `panorama_client.py` `get_system_metrics()` method

### Custom Validation Rules
Edit `validation.py` `_compare_metrics()` method

### Additional Commands
Add to `cli.py` command groups

### New Job Types
Extend `upgrade_manager.py` with new orchestration logic

## Monitoring and Observability

### Metrics Available
- Active/pending/completed job counts
- Worker utilization
- Queue depth
- Upgrade success rate
- Validation pass rate

### Log Analysis
- Structured JSON logs for automated parsing
- Text logs for manual review
- Contextual information (device, job, phase)

### Status Endpoints
- Daemon status
- Worker status
- Device status
- Validation results

