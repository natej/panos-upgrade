"""Database models for mock Panorama server."""

from datetime import datetime
from typing import Optional, Dict, List
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class Device(Base):
    """Device model."""
    
    __tablename__ = "devices"
    
    serial = Column(String, primary_key=True)
    hostname = Column(String, nullable=False)
    model = Column(String, nullable=False)
    current_version = Column(String, nullable=False)
    ip_address = Column(String, nullable=False)
    
    # HA configuration
    ha_enabled = Column(Boolean, default=False)
    ha_role = Column(String, default="standalone")  # active, passive, standalone
    ha_peer_serial = Column(String, nullable=True)
    
    # State
    state = Column(String, default="online")  # online, rebooting, downloading, installing, offline
    last_reboot = Column(DateTime, nullable=True)
    
    # Metrics (stored as JSON)
    tcp_sessions = Column(Integer, default=0)
    route_count = Column(Integer, default=0)
    routes = Column(JSON, default=list)
    arp_count = Column(Integer, default=0)
    arp_entries = Column(JSON, default=list)
    disk_space_gb = Column(Float, default=10.0)
    
    # Available versions for this device
    available_versions = Column(JSON, default=list)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Operation(Base):
    """Async operation model."""
    
    __tablename__ = "operations"
    
    operation_id = Column(String, primary_key=True)
    device_serial = Column(String, nullable=False)
    operation_type = Column(String, nullable=False)  # download, install, reboot
    target_version = Column(String, nullable=True)
    
    # Status
    status = Column(String, default="pending")  # pending, in_progress, complete, failed
    progress = Column(Integer, default=0)
    error_message = Column(String, nullable=True)
    
    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class APICall(Base):
    """API call log for debugging."""
    
    __tablename__ = "api_calls"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    device_serial = Column(String, nullable=True)
    command = Column(String, nullable=False)
    response_status = Column(String, nullable=False)
    duration_ms = Column(Integer, default=0)


# Database setup
def get_engine(db_path: str = "mock_panorama.db"):
    """Get database engine."""
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_database(db_path: str = "mock_panorama.db"):
    """Initialize database."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def get_session(engine):
    """Get database session."""
    Session = sessionmaker(bind=engine)
    return Session()

