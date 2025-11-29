# PAN-OS Upgrade Manager - Architecture

## Overview

The PAN-OS Upgrade Manager is a daemon-based CLI application that orchestrates firmware upgrades for PAN-OS devices. It features concurrent processing, comprehensive validation, and web application integration through JSON file-based communication.

**Key Architecture Decision:** The application uses a two-tier connection model:
- **Panorama** is used only for device discovery (`show devices connected`)
- **Direct firewall connections** are used for all operations (upgrades, downloads, validation)

This design reduces Panorama load and provides more reliable, direct control over firewall operations.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLI Interface                            │
│  (Click-based commands: daemon, job, device, config, download)  │
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
│  │  • Download-Only Mode                                     │  │
│  │  • Cancellation Handling                                  │  │
│  │  • Dry-Run Mode                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┬──────────────┐
        │                │                │              │
┌───────┴──────┐  ┌──────┴──────┐  ┌─────┴──────┐  ┌────┴─────────┐
│  Panorama    │  │   Direct    │  │ Validation │  │   Logging    │
│   Client     │  │  Firewall   │  │   System   │  │   System     │
│              │  │   Client    │  │            │  │              │
│ • Discovery  │  │             │  │ • Pre-flight│ │ • JSON       │
│   only       │  │ • All ops   │  │ • Post-flight││ • Text       │
│              │  │ • Downloads │  │ • Comparison│ │              │
└──────────────┘  │ • Install   │  └────────────┘  └──────────────┘
        │         │ • Reboot    │         │
        │         │ • Metrics   │         │
        ▼         └──────┬──────┘         │
┌──────────────┐         │                │
│   Panorama   │         │                │
│   Server     │         │                │
│              │         │                │
│ show devices │         │                │
│ connected    │         │                │
└──────────────┘         │                │
                         ▼                │
              ┌──────────────────────┐    │
              │      Firewalls       │◄───┘
              │  (Direct mgmt_ip     │
              │   connections)       │
              └──────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     Device Inventory                             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  inventory.json                                           │  │
│  │  • serial → mgmt_ip mapping                               │  │
│  │  • Populated by device discovery                          │  │
│  │  • Consulted before all operations                        │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Connection Flow

### Device Discovery (Panorama)

```
1. CLI: panos-upgrade device discover
2. Panorama Client: show devices connected
3. Response: serial, hostname, mgmt_ip, version, model
4. Save to: inventory.json
```

### All Operations (Direct Firewall)

```
1. Job submitted with serial number
2. Lookup mgmt_ip from inventory.json
3. Create DirectFirewallClient(mgmt_ip, username, password)
4. Execute operations directly on firewall
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
1. Lookup mgmt_ip from inventory.json
2. Connect directly to firewall
3. Get device info and current version
4. Lookup upgrade path from configuration
5. Skip if version not found
6. For each version in path:
   - Pre-flight validation (direct)
   - Software check (direct)
   - Download software (direct, skip if present)
   - Install software (direct)
   - Reboot device (direct)
   - Wait for device ready (direct, exponential backoff)
   - Post-flight validation (direct)
7. Update status throughout

### 5. Panorama Client (`panorama_client.py`)

**Purpose**: Interface with Panorama API for device discovery only

**Key Methods**:
- `get_connected_devices()`: Query all connected devices

**Features**:
- Rate limiting integration
- XML response parsing
- Error handling

> **Note:** This client is now only used for device discovery. All other operations use the DirectFirewallClient.

### 6. Direct Firewall Client (`direct_firewall_client.py`)

**Purpose**: Direct connection to individual firewalls for all operations

**Key Methods**:
- `get_system_info()`: Device information (hostname, serial, version)
- `get_ha_state()`: HA status
- `get_system_metrics()`: Validation metrics (sessions, routes, ARP, disk)
- `check_software_updates()`: Refresh available software versions
- `get_software_info()`: Query downloaded/available versions
- `download_software()`: Initiate download (returns job ID)
- `wait_for_download()`: Monitor download progress
- `install_software()`: Initiate installation (returns job ID)
- `wait_for_install()`: Monitor installation progress
- `reboot_device()`: Reboot command
- `check_device_ready()`: Post-reboot check with exponential backoff
- `check_disk_space()`: Available disk space

**Features**:
- Username/password authentication
- Rate limiting integration
- XML response parsing
- Job-based async operation monitoring
- Progress callbacks for UI updates

### 7. Validation System (`validation.py`)

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

### 8. Configuration Management (`config.py`)

**Purpose**: Application configuration

**Features**:
- JSON-based configuration
- Dot-notation key access
- Automatic directory structure creation
- Default value handling
- Type conversion for known values

**Configuration Sections**:
- `panorama`: Panorama connection settings (for discovery)
- `firewall`: Firewall credentials (for direct connections)
- `workers`: Thread pool settings
- `validation`: Validation thresholds
- `logging`: Log settings
- `paths`: File system paths

### 9. Logging System (`logging_config.py`)

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
1. Lookup mgmt_ip for both devices from inventory
   → Connect directly to each firewall

2. Query HA state for both devices (direct)
   → Determine active and passive members

3. Upgrade passive member first
   → Full upgrade cycle (all operations direct)
   → Validation

4. Optional failover
   → Can be configured

5. Upgrade former active member
   → Full upgrade cycle (all operations direct)
   → Validation

6. Complete HA pair upgrade
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
- Direct firewall connections reduce Panorama load
- Rate limiting available for API calls
- Queue-based processing prevents memory issues

### Optimization
- Atomic file operations for consistency
- Minimal disk I/O
- Efficient XML parsing
- In-memory status tracking with periodic persistence

## Security Considerations

1. **Panorama API Key**: Stored in configuration (for discovery only)
2. **Firewall Credentials**: Username/password stored in configuration
3. **File Permissions**: Restricted to service user
4. **Audit Logging**: Complete operation trail
5. **Rate Limiting**: Prevents API abuse
6. **Input Validation**: All user inputs validated
7. **Direct Connections**: Firewall management IPs must be accessible

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

