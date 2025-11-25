"""Atomic file operations for JSON data."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


def atomic_write_json(file_path: Path, data: Dict[str, Any]) -> None:
    """
    Write JSON data to a file atomically.
    
    Writes to a temporary file first, then moves it to the final location.
    This ensures atomic visibility for file reads.
    
    Args:
        file_path: Destination file path
        data: Dictionary to write as JSON
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temporary file in the same directory
    fd, temp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=f".{file_path.name}.",
        suffix=".tmp"
    )
    
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        
        # Atomic move
        os.replace(temp_path, file_path)
    except Exception:
        # Clean up temp file on error
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def read_json(file_path: Path) -> Dict[str, Any]:
    """
    Read JSON data from a file.
    
    Args:
        file_path: Path to JSON file
        
    Returns:
        Dictionary containing JSON data
        
    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
    """
    with open(file_path, 'r') as f:
        return json.load(f)


def safe_read_json(file_path: Path, default: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Read JSON data from a file, returning default if file doesn't exist.
    
    Args:
        file_path: Path to JSON file
        default: Default value to return if file doesn't exist
        
    Returns:
        Dictionary containing JSON data or default value
    """
    if default is None:
        default = {}
    
    try:
        return read_json(file_path)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_path}: {e}")


def ensure_directory_structure(base_path: Path, directories: list[str]) -> None:
    """
    Ensure all required directories exist.
    
    Args:
        base_path: Base directory path
        directories: List of subdirectory paths relative to base_path
    """
    for directory in directories:
        dir_path = base_path / directory
        dir_path.mkdir(parents=True, exist_ok=True)

