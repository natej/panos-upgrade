#!/usr/bin/env python3
"""Initialize the PAN-OS upgrade system."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from panos_upgrade.config import get_config
from panos_upgrade.logging_config import setup_logging, get_logger


def main():
    """Initialize system directories and configuration."""
    print("Initializing PAN-OS Upgrade System...")
    
    # Initialize configuration (this creates directories)
    config = get_config()
    
    print(f"✓ Created work directory: {config.work_dir}")
    print(f"✓ Created configuration directories")
    print(f"✓ Created queue directories")
    print(f"✓ Created status directories")
    print(f"✓ Created log directories")
    print(f"✓ Created validation directories")
    print(f"✓ Created command directories")
    
    # Initialize logging
    log_dir = config.get_path("logs")
    logger = setup_logging(log_dir, "INFO", console_output=False)
    logger.info("System initialized")
    
    print(f"\nConfiguration file: {config.config_file}")
    print(f"Upgrade paths file: {config.upgrade_paths_file}")
    
    print("\nNext steps:")
    print("1. Edit configuration file to set Panorama host and API key")
    print("2. Copy upgrade_paths.json to the config directory")
    print("3. Start the daemon: panos-upgrade daemon start")
    
    print("\nSystem initialization complete!")


if __name__ == "__main__":
    main()

