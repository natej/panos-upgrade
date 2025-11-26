"""CLI interface for PAN-OS upgrade manager."""

import click
import sys
from pathlib import Path

from panos_upgrade import __version__
from panos_upgrade.config import get_config
from panos_upgrade.logging_config import setup_logging, get_logger
from panos_upgrade.work_dir_resolver import resolve_work_dir, ENV_VAR_NAME


@click.group()
@click.version_option(version=__version__)
@click.option('--work-dir', type=click.Path(), 
              help=f'Working directory. Priority: CLI flag > {ENV_VAR_NAME} env var > ~/.panos-upgrade.config.json > /opt/panos-upgrade')
@click.pass_context
def main(ctx, work_dir):
    """PAN-OS Upgrade Manager - Advanced device upgrade orchestration."""
    ctx.ensure_object(dict)
    
    # Resolve work directory with source tracking
    resolution = resolve_work_dir(cli_work_dir=work_dir)
    
    # Initialize configuration with resolved work directory
    config = get_config(work_dir=resolution.path)
    ctx.obj['config'] = config
    ctx.obj['work_dir_resolution'] = resolution
    
    # Initialize logging
    log_dir = config.get_path("logs")
    log_level = config.get("logging.level", "INFO")
    logger = setup_logging(log_dir, log_level, console_output=True)
    ctx.obj['logger'] = logger
    
    # Log the work directory source at INFO level (always visible)
    logger.info(resolution.log_message())
    logger.info(f"Configuration loaded: {config.config_file}")


# ============================================================================
# Daemon Commands
# ============================================================================

@main.group()
def daemon():
    """Manage the upgrade daemon."""
    pass


@daemon.command()
@click.option('--workers', type=int, help='Number of worker threads')
@click.option('--rate-limit', type=int, help='API rate limit (requests per minute)')
@click.pass_context
def start(ctx, workers, rate_limit):
    """Start the upgrade daemon."""
    from panos_upgrade.daemon import UpgradeDaemon
    
    config = ctx.obj['config']
    logger = ctx.obj['logger']
    
    # Update configuration if provided
    if workers is not None:
        config.set('workers.max', workers)
    if rate_limit is not None:
        config.set('panorama.rate_limit', rate_limit)
    
    logger.info(f"Starting daemon with {config.max_workers} workers")
    click.echo(f"Starting PAN-OS upgrade daemon with {config.max_workers} workers...")
    
    try:
        # Create and start daemon
        daemon = UpgradeDaemon(config)
        daemon.start()
    except KeyboardInterrupt:
        click.echo("\nShutting down daemon...")
    except Exception as e:
        click.echo(f"Error starting daemon: {e}", err=True)
        logger.error(f"Daemon startup error: {e}", exc_info=True)
        sys.exit(1)


@daemon.command()
@click.pass_context
def stop(ctx):
    """Stop the upgrade daemon."""
    import signal
    from pathlib import Path
    
    config = ctx.obj['config']
    logger = ctx.obj['logger']
    
    logger.info("Stopping daemon")
    click.echo("Stopping PAN-OS upgrade daemon...")
    
    # Read daemon status to get PID (if we were tracking it)
    # For now, just provide instructions
    click.echo("To stop the daemon, press Ctrl+C in the terminal where it's running")
    click.echo("Or use: pkill -f 'panos_upgrade.daemon'")


@daemon.command()
@click.pass_context
def restart(ctx):
    """Restart the upgrade daemon."""
    logger = ctx.obj['logger']
    logger.info("Restarting daemon")
    click.echo("Restarting PAN-OS upgrade daemon...")
    
    # TODO: Restart daemon service
    click.echo("Daemon restart functionality will be implemented")


@daemon.command()
@click.pass_context
def status(ctx):
    """Show daemon status."""
    from panos_upgrade.utils.file_ops import safe_read_json
    from panos_upgrade import constants
    
    config = ctx.obj['config']
    
    # Read daemon status from file
    status_file = config.get_path(constants.STATUS_DAEMON_FILE)
    daemon_status = safe_read_json(status_file)
    
    if not daemon_status:
        click.echo("Daemon Status: Not running or status file not found")
        click.echo(f"  Expected status file: {status_file}")
        return
    
    click.echo("Daemon Status:")
    click.echo(f"  Running: {daemon_status.get('running', False)}")
    click.echo(f"  Workers: {daemon_status.get('workers', 0)}")
    click.echo(f"  Active Jobs: {daemon_status.get('active_jobs', 0)}")
    click.echo(f"  Pending Jobs: {daemon_status.get('pending_jobs', 0)}")
    click.echo(f"  Completed Jobs: {daemon_status.get('completed_jobs', 0)}")
    click.echo(f"  Failed Jobs: {daemon_status.get('failed_jobs', 0)}")
    click.echo(f"  Cancelled Jobs: {daemon_status.get('cancelled_jobs', 0)}")
    click.echo(f"  Started At: {daemon_status.get('started_at', 'N/A')}")
    click.echo(f"  Last Updated: {daemon_status.get('last_updated', 'N/A')}")


# ============================================================================
# Job Commands
# ============================================================================

@main.group()
def job():
    """Manage upgrade jobs."""
    pass


@job.command()
@click.option('--device', help='Device serial number')
@click.option('--ha-pair', help='HA pair name')
@click.option('--dry-run', is_flag=True, help='Perform dry run without actual upgrade')
@click.option('--download-only', is_flag=True, help='Download images only (no install/reboot)')
@click.pass_context
def submit(ctx, device, ha_pair, dry_run, download_only):
    """Submit an upgrade job."""
    import uuid
    from datetime import datetime
    from pathlib import Path
    from panos_upgrade.utils.file_ops import atomic_write_json, read_json
    from panos_upgrade import constants
    
    config = ctx.obj['config']
    logger = ctx.obj['logger']
    
    if not device and not ha_pair:
        click.echo("Error: Must specify either --device or --ha-pair", err=True)
        sys.exit(1)
    
    if device and ha_pair:
        click.echo("Error: Cannot specify both --device and --ha-pair", err=True)
        sys.exit(1)
    
    # Check if device already has a pending or active job
    if device:
        try:
            requested_type = constants.JOB_TYPE_DOWNLOAD_ONLY if download_only else constants.JOB_TYPE_STANDALONE
            _check_for_existing_job(config, device, requested_type)
        except Exception as e:
            from panos_upgrade.exceptions import ActiveJobError, PendingJobError, ConflictingJobTypeError
            
            if isinstance(e, ConflictingJobTypeError):
                click.echo(f"Error: {e}", err=True)
                click.echo(f"\nCannot mix download-only and normal upgrades", err=True)
                click.echo(f"Cancel existing job first: panos-upgrade job cancel {e.existing_job_id}", err=True)
                logger.warning(f"Rejected conflicting job type for device {device}")
                sys.exit(1)
            elif isinstance(e, (ActiveJobError, PendingJobError)):
                click.echo(f"Error: {e}", err=True)
                click.echo(f"\nUse 'panos-upgrade job cancel {e.job_id}' to cancel it first", err=True)
                logger.warning(f"Rejected duplicate job submission for device {device}")
                sys.exit(1)
            else:
                raise
    
    # Generate job ID
    job_id = f"cli-{uuid.uuid4()}"
    
    # Create job data
    if device:
        job_type = constants.JOB_TYPE_DOWNLOAD_ONLY if download_only else constants.JOB_TYPE_STANDALONE
        
        if download_only:
            logger.info(f"Submitting download-only job for device {device}", extra={'serial': device})
            click.echo(f"Submitting download-only job for device: {device}")
        else:
            logger.info(f"Submitting job for device {device}", extra={'serial': device})
            click.echo(f"Submitting upgrade job for device: {device}")
        
        job_data = {
            "job_id": job_id,
            "type": job_type,
            "devices": [device],
            "ha_pair_name": "",
            "dry_run": dry_run,
            "download_only": download_only,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
    else:
        logger.info(f"Submitting job for HA pair {ha_pair}")
        click.echo(f"Submitting upgrade job for HA pair: {ha_pair}")
        
        # For HA pair, we need to specify both device serials
        # This is a simplified version - in production you'd look up the pair
        click.echo("Error: HA pair submission requires device serials", err=True)
        click.echo("Use: --device PRIMARY_SERIAL --device SECONDARY_SERIAL", err=True)
        sys.exit(1)
    
    if dry_run:
        click.echo("  Mode: DRY RUN")
    if download_only:
        click.echo("  Mode: DOWNLOAD ONLY")
    
    # Write job file to pending queue
    pending_dir = config.get_path(constants.DIR_QUEUE_PENDING)
    job_file = pending_dir / f"{job_id}.json"
    
    try:
        atomic_write_json(job_file, job_data)
        click.echo(f"  Job ID: {job_id}")
        click.echo(f"  Status: Queued")
        click.echo(f"\nMonitor with: panos-upgrade device status {device}")
        logger.info(f"Job {job_id} submitted successfully")
    except Exception as e:
        click.echo(f"Error submitting job: {e}", err=True)
        logger.error(f"Failed to submit job: {e}", exc_info=True)
        sys.exit(1)


def _check_for_existing_job(config, device_serial, requested_type=None):
    """
    Check if device already has a pending or active job.
    
    Args:
        config: Configuration instance
        device_serial: Device serial number
        requested_type: Type of job being requested (for conflict detection)
        
    Raises:
        PendingJobError: If device has a pending job
        ActiveJobError: If device has an active job
        ConflictingJobTypeError: If job type conflicts
    """
    from panos_upgrade.utils.file_ops import safe_read_json
    from panos_upgrade.exceptions import ActiveJobError, PendingJobError, ConflictingJobTypeError
    from panos_upgrade import constants
    
    # Check pending queue first
    pending_dir = config.get_path(constants.DIR_QUEUE_PENDING)
    if pending_dir.exists():
        for job_file in pending_dir.glob("*.json"):
            try:
                job_data = safe_read_json(job_file)
                if job_data and device_serial in job_data.get("devices", []):
                    existing_type = job_data.get("type", "unknown")
                    
                    # Check for job type conflict
                    if requested_type and existing_type != requested_type:
                        raise ConflictingJobTypeError(
                            device_serial=device_serial,
                            existing_type=existing_type,
                            requested_type=requested_type,
                            existing_job_id=job_data.get("job_id", "unknown")
                        )
                    
                    raise PendingJobError(
                        device_serial=device_serial,
                        job_id=job_data.get("job_id", "unknown"),
                        created_at=job_data.get("created_at", "")
                    )
            except (PendingJobError, ActiveJobError, ConflictingJobTypeError):
                raise
            except Exception:
                # Skip malformed files
                continue
    
    # Check active queue
    active_dir = config.get_path(constants.DIR_QUEUE_ACTIVE)
    if active_dir.exists():
        for job_file in active_dir.glob("*.json"):
            try:
                job_data = safe_read_json(job_file)
                if job_data and device_serial in job_data.get("devices", []):
                    existing_type = job_data.get("type", "unknown")
                    
                    # Check for job type conflict
                    if requested_type and existing_type != requested_type:
                        raise ConflictingJobTypeError(
                            device_serial=device_serial,
                            existing_type=existing_type,
                            requested_type=requested_type,
                            existing_job_id=job_data.get("job_id", "unknown")
                        )
                    
                    raise ActiveJobError(
                        device_serial=device_serial,
                        job_id=job_data.get("job_id", "unknown"),
                        created_at=job_data.get("created_at", "")
                    )
            except (PendingJobError, ActiveJobError, ConflictingJobTypeError):
                raise
            except Exception:
                # Skip malformed files
                continue


@job.command()
@click.option('--status', type=click.Choice(['pending', 'active', 'completed', 'failed', 'cancelled']),
              help='Filter by status')
@click.pass_context
def list(ctx, status):
    """List upgrade jobs."""
    logger = ctx.obj['logger']
    
    if status:
        click.echo(f"Jobs with status: {status}")
    else:
        click.echo("All jobs:")
    
    # TODO: List jobs from queue directories
    click.echo("Job list functionality will be implemented")


@job.command(name='status')
@click.argument('job_id')
@click.pass_context
def job_status(ctx, job_id):
    """Show job status."""
    click.echo(f"Status for job: {job_id}")
    
    # TODO: Read job status
    click.echo("Job status functionality will be implemented")


@job.command()
@click.argument('job_id')
@click.pass_context
def cancel(ctx, job_id):
    """Cancel an upgrade job."""
    logger = ctx.obj['logger']
    logger.info(f"Cancelling job {job_id}", extra={'job_id': job_id})
    click.echo(f"Cancelling job: {job_id}")
    
    # TODO: Create cancellation command file
    click.echo("Job cancellation functionality will be implemented")


# ============================================================================
# Device Commands
# ============================================================================

@main.group()
def device():
    """Manage devices."""
    pass


@device.command(name='list')
@click.option('--ha-pairs', is_flag=True, help='Show HA pairs')
@click.pass_context
def list_devices(ctx, ha_pairs):
    """List devices."""
    if ha_pairs:
        click.echo("HA Pairs:")
    else:
        click.echo("Devices:")
    
    # TODO: List devices from Panorama
    click.echo("Device list functionality will be implemented")


@device.command(name='status')
@click.argument('serial')
@click.pass_context
def status_device(ctx, serial):
    """Show device status."""
    click.echo(f"Status for device: {serial}")
    
    # TODO: Read device status from file
    click.echo("Device status functionality will be implemented")


@device.command()
@click.argument('serial')
@click.pass_context
def validate(ctx, serial):
    """Validate device readiness for upgrade."""
    logger = ctx.obj['logger']
    logger.info(f"Validating device {serial}", extra={'serial': serial})
    click.echo(f"Validating device: {serial}")
    
    # TODO: Run pre-flight validation
    click.echo("Device validation functionality will be implemented")


@device.command()
@click.argument('serial')
@click.pass_context
def metrics(ctx, serial):
    """Show device metrics."""
    click.echo(f"Metrics for device: {serial}")
    
    # TODO: Show device metrics
    click.echo("Device metrics functionality will be implemented")


@device.command()
@click.pass_context
def discover(ctx):
    """Discover devices from Panorama and update inventory."""
    from panos_upgrade.device_inventory import DeviceInventory
    from panos_upgrade.panorama_client import PanoramaClient
    from panos_upgrade import constants
    
    config = ctx.obj['config']
    logger = ctx.obj['logger']
    
    click.echo("Discovering devices from Panorama...")
    
    try:
        # Create clients
        panorama = PanoramaClient(config)
        inventory_file = config.get_path("devices/inventory.json")
        inventory = DeviceInventory(inventory_file, panorama)
        
        # Discover devices
        stats = inventory.discover_devices()
        
        click.echo(f"\n✓ Discovery complete:")
        click.echo(f"  Total devices: {stats['total']}")
        click.echo(f"  New devices: {stats['new']}")
        click.echo(f"  Updated devices: {stats['updated']}")
        click.echo(f"\nInventory saved to: {inventory_file}")
        
        logger.info(f"Device discovery complete: {stats['total']} devices")
        
    except Exception as e:
        click.echo(f"Error discovering devices: {e}", err=True)
        logger.error(f"Device discovery failed: {e}", exc_info=True)
        sys.exit(1)


# ============================================================================
# Configuration Commands
# ============================================================================

@main.group()
def config():
    """Manage configuration."""
    pass


@config.command(name='set')
@click.argument('key')
@click.argument('value')
@click.pass_context
def set_config(ctx, key, value):
    """Set configuration value."""
    config = ctx.obj['config']
    logger = ctx.obj['logger']
    
    # Type conversion for known numeric values
    if key in ['workers.max', 'panorama.rate_limit', 'panorama.timeout']:
        value = int(value)
    elif key in ['validation.tcp_session_margin', 'validation.route_margin', 
                 'validation.arp_margin', 'validation.min_disk_gb']:
        value = float(value)
    
    config.set(key, value)
    logger.info(f"Configuration updated: {key} = {value}")
    click.echo(f"Set {key} = {value}")


@config.command()
@click.pass_context
def show(ctx):
    """Show current configuration."""
    config = ctx.obj['config']
    
    click.echo("Current Configuration:")
    click.echo(f"  Panorama Host: {config.panorama_host}")
    click.echo(f"  API Key: {'*' * 20 if config.panorama_api_key else '(not set)'}")
    click.echo(f"  Max Workers: {config.max_workers}")
    click.echo(f"  Rate Limit: {config.rate_limit} req/min")
    click.echo(f"  Min Disk Space: {config.min_disk_gb} GB")
    click.echo(f"  Work Directory: {config.work_dir}")
    click.echo(f"  Upgrade Paths File: {config.upgrade_paths_file}")


# ============================================================================
# Upgrade Path Commands
# ============================================================================

@main.group()
def path():
    """Manage upgrade paths."""
    pass


@path.command(name='show')
@click.option('--version', help='Show path for specific version')
@click.pass_context
def show_path(ctx, version):
    """Show upgrade paths."""
    config = ctx.obj['config']
    
    if version:
        click.echo(f"Upgrade path for version {version}:")
    else:
        click.echo("All upgrade paths:")
    
    # TODO: Read and display upgrade paths
    click.echo(f"Reading from: {config.upgrade_paths_file}")
    click.echo("Path display functionality will be implemented")


@path.command(name='validate')
@click.pass_context
def validate_path(ctx):
    """Validate upgrade paths configuration."""
    config = ctx.obj['config']
    logger = ctx.obj['logger']
    
    click.echo("Validating upgrade paths configuration...")
    
    # TODO: Validate upgrade paths file
    click.echo("Path validation functionality will be implemented")


# ============================================================================
# Download Commands
# ============================================================================

@main.group()
def download():
    """Manage software downloads."""
    pass


@download.command(name='queue-all')
@click.option('--dry-run', is_flag=True, help='Show what would be queued without creating jobs')
@click.pass_context
def queue_all(ctx, dry_run):
    """Queue all discovered devices for download-only."""
    import uuid
    from datetime import datetime
    from panos_upgrade.device_inventory import DeviceInventory
    from panos_upgrade.panorama_client import PanoramaClient
    from panos_upgrade.utils.file_ops import atomic_write_json, safe_read_json
    from panos_upgrade.exceptions import ActiveJobError, PendingJobError
    from panos_upgrade import constants
    
    config = ctx.obj['config']
    logger = ctx.obj['logger']
    
    click.echo("Queueing devices for download...")
    
    try:
        # Load inventory
        inventory_file = config.get_path("devices/inventory.json")
        panorama = PanoramaClient(config)
        inventory = DeviceInventory(inventory_file, panorama)
        
        devices = inventory.list_devices()
        if not devices:
            click.echo("No devices in inventory. Run 'panos-upgrade device discover' first", err=True)
            sys.exit(1)
        
        # Load upgrade paths
        upgrade_paths = safe_read_json(config.upgrade_paths_file, default={})
        
        # Track results
        results = {
            "total": len(devices),
            "queued": 0,
            "skipped_no_path": 0,
            "skipped_existing_job": 0,
            "errors": 0
        }
        
        queued_devices = []
        skipped_devices = []
        
        for device in devices:
            serial = device["serial"]
            hostname = device["hostname"]
            current_version = device["current_version"]
            
            # Check upgrade path
            if current_version not in upgrade_paths:
                results["skipped_no_path"] += 1
                skipped_devices.append(f"  {serial} ({hostname}): {current_version} (no upgrade path)")
                logger.info(f"Skipping {serial}: No path for {current_version}")
                continue
            
            # Check for existing job
            try:
                _check_for_existing_job(config, serial, constants.JOB_TYPE_DOWNLOAD_ONLY)
            except (ActiveJobError, PendingJobError, Exception):
                results["skipped_existing_job"] += 1
                skipped_devices.append(f"  {serial} ({hostname}): has existing job")
                logger.info(f"Skipping {serial}: Already has job")
                continue
            
            # Create job
            if not dry_run:
                try:
                    job_id = f"bulk-download-{uuid.uuid4()}"
                    job_data = {
                        "job_id": job_id,
                        "type": constants.JOB_TYPE_DOWNLOAD_ONLY,
                        "devices": [serial],
                        "ha_pair_name": "",
                        "dry_run": False,
                        "download_only": True,
                        "created_at": datetime.utcnow().isoformat() + "Z"
                    }
                    
                    pending_dir = config.get_path(constants.DIR_QUEUE_PENDING)
                    job_file = pending_dir / f"{job_id}.json"
                    atomic_write_json(job_file, job_data)
                    
                    results["queued"] += 1
                    path_str = " → ".join(upgrade_paths[current_version])
                    queued_devices.append(f"  {serial} ({hostname}): {current_version} → {path_str}")
                    logger.info(f"Queued {serial} for download")
                    
                except Exception as e:
                    results["errors"] += 1
                    logger.error(f"Failed to queue {serial}: {e}")
            else:
                results["queued"] += 1
                path_str = " → ".join(upgrade_paths[current_version])
                queued_devices.append(f"  {serial} ({hostname}): {current_version} → {path_str}")
        
        # Display results
        if dry_run:
            click.echo("\n[DRY RUN] Would queue devices for download:\n")
        else:
            click.echo("\nQueued devices for download:\n")
        
        if queued_devices:
            for device in queued_devices[:10]:  # Show first 10
                click.echo(device)
            if len(queued_devices) > 10:
                click.echo(f"  ... and {len(queued_devices) - 10} more")
        
        if skipped_devices:
            click.echo("\nSkipped devices:\n")
            for device in skipped_devices[:10]:  # Show first 10
                click.echo(device)
            if len(skipped_devices) > 10:
                click.echo(f"  ... and {len(skipped_devices) - 10} more")
        
        click.echo(f"\nSummary:")
        click.echo(f"  ✓ Queued: {results['queued']} devices")
        click.echo(f"  ⊘ Skipped (no upgrade path): {results['skipped_no_path']} devices")
        click.echo(f"  ⊘ Skipped (existing job): {results['skipped_existing_job']} devices")
        click.echo(f"  ✗ Errors: {results['errors']} devices")
        click.echo(f"\nTotal: {results['total']} devices processed")
        
        if not dry_run and results["queued"] > 0:
            click.echo(f"\nMonitor with:")
            click.echo(f"  panos-upgrade daemon status")
            click.echo(f"  panos-upgrade download status")
        
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        logger.error(f"Bulk queue failed: {e}", exc_info=True)
        sys.exit(1)


@download.command(name='status')
@click.pass_context
def download_status_cmd(ctx):
    """Show download progress summary."""
    from panos_upgrade.utils.file_ops import safe_read_json
    from panos_upgrade import constants
    
    config = ctx.obj['config']
    
    click.echo("Download Status Summary:")
    
    # Count devices by status
    devices_dir = config.get_path(constants.DIR_STATUS_DEVICES)
    
    if not devices_dir.exists():
        click.echo("No device status files found")
        return
    
    total = 0
    download_complete = 0
    downloading = 0
    failed = 0
    
    for status_file in devices_dir.glob("*.json"):
        device_status = safe_read_json(status_file)
        if device_status:
            total += 1
            status = device_status.get("upgrade_status", "")
            
            if status == constants.STATUS_DOWNLOAD_COMPLETE:
                download_complete += 1
            elif status == constants.STATUS_DOWNLOADING:
                downloading += 1
            elif status == constants.STATUS_FAILED:
                failed += 1
    
    click.echo(f"  Total devices tracked: {total}")
    click.echo(f"  Download complete: {download_complete}")
    click.echo(f"  Currently downloading: {downloading}")
    click.echo(f"  Failed: {failed}")


if __name__ == '__main__':
    main()

