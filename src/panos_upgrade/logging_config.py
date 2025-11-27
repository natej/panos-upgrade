"""Dual logging system - JSON structured and traditional text logs."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """Format log records as JSON."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string."""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields if present
        if hasattr(record, 'device'):
            log_data['device'] = record.device
        if hasattr(record, 'serial'):
            log_data['serial'] = record.serial
        if hasattr(record, 'phase'):
            log_data['phase'] = record.phase
        if hasattr(record, 'job_id'):
            log_data['job_id'] = record.job_id
        if hasattr(record, 'details'):
            log_data['details'] = record.details
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class TextFormatter(logging.Formatter):
    """Format log records as traditional text."""
    
    def __init__(self):
        super().__init__(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


def setup_logging(
    log_dir: Path,
    log_level: str = "INFO",
    console_output: bool = True
) -> logging.Logger:
    """
    Set up dual logging system.
    
    Args:
        log_dir: Directory for log files
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        console_output: Whether to output to console
        
    Returns:
        Configured logger instance
    """
    # Create log directories
    structured_dir = log_dir / "structured"
    text_dir = log_dir / "text"
    structured_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    
    # Get root logger
    logger = logging.getLogger("panos_upgrade")
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()
    
    # JSON structured log handler
    json_log_file = structured_dir / f"panos-upgrade-{datetime.now().strftime('%Y%m%d')}.json"
    json_handler = logging.FileHandler(json_log_file)
    json_handler.setFormatter(JSONFormatter())
    logger.addHandler(json_handler)
    
    # Text log handler
    text_log_file = text_dir / f"panos-upgrade-{datetime.now().strftime('%Y%m%d')}.log"
    text_handler = logging.FileHandler(text_log_file)
    text_handler.setFormatter(TextFormatter())
    logger.addHandler(text_handler)
    
    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(TextFormatter())
        logger.addHandler(console_handler)
    
    return logger


def get_logger(name: str = "panos_upgrade") -> logging.Logger:
    """
    Get logger instance.
    
    Args:
        name: Logger name
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def log_with_context(
    logger: logging.Logger,
    level: str,
    message: str,
    device: Optional[str] = None,
    serial: Optional[str] = None,
    phase: Optional[str] = None,
    job_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    exc_info: bool = False
) -> None:
    """
    Log message with contextual information.
    
    Args:
        logger: Logger instance
        level: Log level (debug, info, warning, error, critical)
        message: Log message
        device: Device hostname
        serial: Device serial number
        phase: Current upgrade phase
        job_id: Job ID
        details: Additional details dictionary
        exc_info: Include exception information
    """
    extra = {}
    if device:
        extra['device'] = device
    if serial:
        extra['serial'] = serial
    if phase:
        extra['phase'] = phase
    if job_id:
        extra['job_id'] = job_id
    if details:
        extra['details'] = details
    
    log_func = getattr(logger, level.lower())
    log_func(message, extra=extra, exc_info=exc_info)

