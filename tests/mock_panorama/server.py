"""Mock Panorama FastAPI server."""

import os
import yaml
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import Response
import uvicorn

from .models import init_database, get_session
from .device_manager import DeviceManager
from .operation_manager import OperationManager
from .command_handlers import CommandHandler


class MockPanoramaServer:
    """Mock Panorama server."""
    
    def __init__(self, config_file: Optional[str] = None, db_path: str = "mock_panorama.db"):
        """
        Initialize mock Panorama server.
        
        Args:
            config_file: Path to YAML configuration file
            db_path: Path to SQLite database
        """
        self.app = FastAPI(title="Mock Panorama Server", version="1.0.0")
        self.db_path = db_path
        
        # Initialize database
        self.engine = init_database(db_path)
        self.db_session = get_session(self.engine)
        
        # Load configuration
        self.config = self._load_config(config_file)
        
        # Initialize managers
        self.device_manager = DeviceManager(self.db_session)
        self.operation_manager = OperationManager(
            self.db_session,
            self.device_manager,
            self.config.get("timing", {})
        )
        self.command_handler = CommandHandler(
            self.device_manager,
            self.operation_manager,
            self.config
        )
        
        # Load devices from config
        self._load_devices()
        
        # Set up routes
        self._setup_routes()
    
    def _load_config(self, config_file: Optional[str]) -> dict:
        """Load configuration from YAML file."""
        if not config_file:
            # Return default config
            return {
                "timing": {
                    "download_duration": int(os.getenv("DOWNLOAD_DURATION", "10")),
                    "install_duration": int(os.getenv("INSTALL_DURATION", "5")),
                    "reboot_duration": int(os.getenv("REBOOT_DURATION", "15"))
                },
                "devices": [],
                "failures": []
            }
        
        config_path = Path(config_file)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
        
        with open(config_path) as f:
            return yaml.safe_load(f)
    
    def _load_devices(self):
        """Load devices from configuration."""
        for device_config in self.config.get("devices", []):
            # Check if device already exists
            existing = self.device_manager.get_device(device_config["serial"])
            if existing:
                continue
            
            # Add device
            self.device_manager.add_device(
                serial=device_config["serial"],
                hostname=device_config["hostname"],
                model=device_config.get("model", "PA-3220"),
                current_version=device_config["current_version"],
                ip_address=device_config.get("ip_address", "192.168.1.1"),
                ha_enabled=device_config.get("ha_enabled", False),
                ha_role=device_config.get("ha_role", "standalone"),
                ha_peer_serial=device_config.get("ha_peer"),
                tcp_sessions=device_config.get("metrics", {}).get("tcp_sessions", 45000),
                route_count=device_config.get("metrics", {}).get("route_count", 1200),
                arp_count=device_config.get("metrics", {}).get("arp_count", 500),
                disk_space_gb=device_config.get("metrics", {}).get("disk_space_gb", 15.0),
                available_versions=device_config.get("available_versions", [])
            )
    
    def _setup_routes(self):
        """Set up FastAPI routes."""
        
        @self.app.get("/")
        async def root():
            """Root endpoint."""
            return {
                "service": "Mock Panorama Server",
                "version": "1.0.0",
                "devices": len(self.device_manager.list_devices())
            }
        
        @self.app.api_route("/api/", methods=["GET", "POST"])
        async def api_endpoint(
            request: Request,
            type: str = Query(None, description="API type"),
            action: str = Query(None, description="API action"),
            cmd: str = Query(None, description="XML command"),
            key: str = Query(None, description="API key"),
            target: str = Query(None, description="Target device serial")
        ):
            """
            Main API endpoint mimicking PAN-OS API.
            
            Query parameters:
                type: API type (op, commit, etc.)
                action: API action
                cmd: XML command
                key: API key
                target: Target device serial number
            """
            # For POST requests, get parameters from form data
            if request.method == "POST":
                form_data = await request.form()
                type = form_data.get("type", type)
                action = form_data.get("action", action)
                cmd = form_data.get("cmd", cmd)
                key = form_data.get("key", key)
                target = form_data.get("target", target)
            
            # Validate required parameters
            if not type or not key:
                return Response(
                    content='<response status="error"><result><msg>Missing required parameters</msg></result></response>',
                    media_type="application/xml"
                )
            
            # Validate API key
            expected_key = self.config.get("api_key", "test-api-key")
            if key != expected_key:
                return Response(
                    content='<response status="error"><result><msg>Invalid API key</msg></result></response>',
                    media_type="application/xml"
                )
            
            # Handle operational commands
            if type == "op":
                if not cmd:
                    return Response(
                        content='<response status="error"><result><msg>No command specified</msg></result></response>',
                        media_type="application/xml"
                    )
                
                # Handle command
                response_xml = self.command_handler.handle_command(cmd, target)
                return Response(content=response_xml, media_type="application/xml")
            
            else:
                return Response(
                    content=f'<response status="error"><result><msg>Unsupported API type: {type}</msg></result></response>',
                    media_type="application/xml"
                )
        
        @self.app.get("/devices")
        async def list_devices():
            """List all devices."""
            devices = self.device_manager.list_devices()
            return {
                "devices": [
                    {
                        "serial": d.serial,
                        "hostname": d.hostname,
                        "model": d.model,
                        "current_version": d.current_version,
                        "state": d.state,
                        "ha_enabled": d.ha_enabled,
                        "ha_role": d.ha_role
                    }
                    for d in devices
                ]
            }
        
        @self.app.get("/devices/{serial}")
        async def get_device(serial: str):
            """Get device details."""
            device = self.device_manager.get_device(serial)
            if not device:
                raise HTTPException(status_code=404, detail="Device not found")
            
            return {
                "serial": device.serial,
                "hostname": device.hostname,
                "model": device.model,
                "current_version": device.current_version,
                "ip_address": device.ip_address,
                "state": device.state,
                "ha_enabled": device.ha_enabled,
                "ha_role": device.ha_role,
                "ha_peer_serial": device.ha_peer_serial,
                "tcp_sessions": device.tcp_sessions,
                "route_count": device.route_count,
                "arp_count": device.arp_count,
                "disk_space_gb": device.disk_space_gb,
                "last_reboot": device.last_reboot.isoformat() if device.last_reboot else None
            }
        
        @self.app.get("/operations")
        async def list_operations():
            """List all operations."""
            operations = self.db_session.query(self.operation_manager.db.query(Operation).all())
            return {"operations": [op.__dict__ for op in operations]}
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint."""
            return {
                "status": "healthy",
                "devices": len(self.device_manager.list_devices()),
                "database": self.db_path
            }
    
    def run(self, host: str = "0.0.0.0", port: int = 8443):
        """
        Run the server.
        
        Args:
            host: Host to bind to
            port: Port to bind to
        """
        uvicorn.run(self.app, host=host, port=port)


def create_server(config_file: Optional[str] = None, db_path: str = "mock_panorama.db") -> MockPanoramaServer:
    """
    Create mock Panorama server instance.
    
    Args:
        config_file: Path to YAML configuration file
        db_path: Path to SQLite database
        
    Returns:
        MockPanoramaServer instance
    """
    return MockPanoramaServer(config_file, db_path)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Mock Panorama Server")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to YAML configuration file"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8443,
        help="Port to bind to (default: 8443)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="mock_panorama.db",
        help="Database file path (default: mock_panorama.db)"
    )
    
    args = parser.parse_args()
    
    print(f"Starting Mock Panorama Server on {args.host}:{args.port}")
    if args.config:
        print(f"Loading configuration from: {args.config}")
    
    server = create_server(args.config, args.db)
    server.run(args.host, args.port)


if __name__ == "__main__":
    main()

