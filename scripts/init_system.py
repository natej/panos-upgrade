#!/usr/bin/env python3
"""Initialize the PAN-OS upgrade system."""

import argparse
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panos_upgrade.config import get_config
from panos_upgrade.logging_config import setup_logging, get_logger
from panos_upgrade.work_dir_resolver import (
    resolve_work_dir, 
    write_user_config, 
    get_user_config_path,
    ConfigSource,
    ENV_VAR_NAME,
    DEFAULT_WORK_DIR
)


def main():
    """Initialize system directories and configuration."""
    parser = argparse.ArgumentParser(
        description="Initialize PAN-OS Upgrade System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Work directory resolution priority:
  1. --work-dir flag (this script)
  2. {ENV_VAR_NAME} environment variable
  3. ~/.panos-upgrade.config.json (created by this script)
  4. Default: {DEFAULT_WORK_DIR}

Examples:
  # Initialize in home directory (development/testing)
  python scripts/init_system.py --work-dir ~/opt/panosupgrade

  # Initialize with default path (production)
  sudo python scripts/init_system.py

  # Use environment variable
  export {ENV_VAR_NAME}=~/opt/panosupgrade
  python scripts/init_system.py
"""
    )
    parser.add_argument(
        '--work-dir', 
        type=str,
        help='Working directory for all data and config'
    )
    parser.add_argument(
        '--no-user-config',
        action='store_true',
        help='Do not write ~/.panos-upgrade.config.json'
    )
    args = parser.parse_args()
    
    print("Initializing PAN-OS Upgrade System...")
    print()
    
    # Resolve work directory
    resolution = resolve_work_dir(cli_work_dir=args.work_dir)
    
    # If using default and CLI flag was provided, use CLI flag
    if args.work_dir:
        work_dir = Path(args.work_dir).expanduser().resolve()
        source_msg = "from --work-dir flag"
    else:
        work_dir = resolution.path
        source_msg = resolution.source.value
    
    print(f"Work directory: {work_dir} ({source_msg})")
    print()
    
    # Initialize configuration (this creates directories)
    config = get_config(work_dir=work_dir)
    
    print(f"✓ Created work directory: {config.work_dir}")
    print(f"✓ Created configuration directories")
    print(f"✓ Created queue directories")
    print(f"✓ Created status directories")
    print(f"✓ Created log directories")
    print(f"✓ Created validation directories")
    print(f"✓ Created command directories")
    
    # Write user config file (unless disabled)
    if not args.no_user_config:
        try:
            user_config_path = write_user_config(work_dir)
            print(f"✓ Wrote user config: {user_config_path}")
        except PermissionError as e:
            print(f"⚠ Could not write user config: {e}")
        except Exception as e:
            print(f"⚠ Could not write user config: {e}")
    else:
        print(f"⊘ Skipped writing user config (--no-user-config)")
    
    # Initialize logging
    log_dir = config.get_path("logs")
    logger = setup_logging(log_dir, "INFO", console_output=False)
    logger.info("System initialized")
    
    print()
    print(f"Configuration file: {config.config_file}")
    print(f"Upgrade paths file: {config.upgrade_paths_file}")
    print(f"User config file: {get_user_config_path()}")
    
    print()
    print("Next steps:")
    print("1. Edit configuration file to set Panorama host and API key:")
    print(f"   panos-upgrade config set panorama.host YOUR_PANORAMA_HOST")
    print(f"   panos-upgrade config set panorama.api_key YOUR_API_KEY")
    print()
    print("2. Copy upgrade_paths.json to the config directory:")
    print(f"   cp examples/upgrade_paths.json {config.work_dir}/config/")
    print()
    
    # Warn about paths if not using default
    if work_dir != DEFAULT_WORK_DIR:
        print("3. IMPORTANT: Update the 'paths' section in your config file!")
        print(f"   The config file may have paths pointing to /opt/panos-upgrade")
        print(f"   but your work directory is: {work_dir}")
        print(f"   Edit: {config.config_file}")
        print(f"   Update paths.work_dir and paths.upgrade_paths")
        print()
        print("4. Start the daemon:")
    else:
        print("3. Start the daemon:")
    print(f"   panos-upgrade daemon start")
    
    print()
    print("System initialization complete!")


if __name__ == "__main__":
    main()
