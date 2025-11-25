"""Hash verification manager for PAN-OS software versions."""

from pathlib import Path
from typing import Dict, Optional, Any

from panos_upgrade.logging_config import get_logger
from panos_upgrade.utils.file_ops import safe_read_json, atomic_write_json
from panos_upgrade.exceptions import HashNotFoundError, HashMismatchError


class HashManager:
    """Manages PAN-OS software version hashes."""
    
    def __init__(self, hash_file_path: Path):
        """
        Initialize hash manager.
        
        Args:
            hash_file_path: Path to version_hashes.json
        """
        self.hash_file_path = Path(hash_file_path)
        self.logger = get_logger("panos_upgrade.hash_manager")
        self._hashes: Dict[str, Dict[str, Any]] = {}
        self._load_hashes()
    
    def _load_hashes(self):
        """Load hash database from file."""
        try:
            self._hashes = safe_read_json(self.hash_file_path, default={})
            self.logger.info(f"Loaded hashes for {len(self._hashes)} versions")
        except Exception as e:
            self.logger.error(f"Failed to load hash database: {e}")
            self._hashes = {}
    
    def get_expected_hash(self, version: str) -> Optional[str]:
        """
        Get expected SHA256 hash for a version.
        
        Args:
            version: Software version
            
        Returns:
            SHA256 hash string or None if not found
        """
        version_info = self._hashes.get(version, {})
        return version_info.get("sha256")
    
    def get_version_info(self, version: str) -> Optional[Dict[str, Any]]:
        """
        Get complete version information.
        
        Args:
            version: Software version
            
        Returns:
            Dictionary with version info or None
        """
        return self._hashes.get(version)
    
    def verify_hash(self, version: str, actual_hash: str, strict: bool = False) -> bool:
        """
        Verify actual hash against expected hash.
        
        Args:
            version: Software version
            actual_hash: Actual SHA256 hash from firewall
            strict: If True, raise exception on missing hash
            
        Returns:
            True if hash matches or no expected hash (when not strict)
            
        Raises:
            HashNotFoundError: If no expected hash and strict=True
            HashMismatchError: If hashes don't match
        """
        expected_hash = self.get_expected_hash(version)
        
        if not expected_hash:
            if strict:
                raise HashNotFoundError(version)
            else:
                self.logger.warning(
                    f"No expected hash for version {version}, skipping verification"
                )
                return True
        
        # Normalize hashes (lowercase, strip whitespace)
        expected = expected_hash.lower().strip()
        actual = actual_hash.lower().strip()
        
        if expected != actual:
            raise HashMismatchError(version, expected_hash, actual_hash)
        
        self.logger.info(f"Hash verification passed for version {version}")
        return True
    
    def add_hash(self, version: str, sha256: str, filename: str = "", 
                 size_mb: int = 0, release_date: str = ""):
        """
        Add or update hash in database.
        
        Args:
            version: Software version
            sha256: SHA256 hash
            filename: Software filename
            size_mb: File size in MB
            release_date: Release date
        """
        self._hashes[version] = {
            "sha256": sha256,
            "filename": filename,
            "size_mb": size_mb,
            "release_date": release_date
        }
        
        # Save to file
        atomic_write_json(self.hash_file_path, self._hashes)
        self.logger.info(f"Added/updated hash for version {version}")
    
    def list_versions(self) -> list[str]:
        """Get list of versions with known hashes."""
        return list(self._hashes.keys())
    
    def has_hash(self, version: str) -> bool:
        """Check if hash exists for version."""
        return version in self._hashes and "sha256" in self._hashes[version]

