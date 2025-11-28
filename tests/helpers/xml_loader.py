"""XML fixture loader with template substitution."""

import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Callable, Dict, Any


class XMLFixtureLoader:
    """
    Loads XML fixtures from files with optional placeholder substitution.
    
    Supports:
    - Simple {{placeholder}} substitution
    - Python functions for complex fixture generation
    """
    
    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize the loader.
        
        Args:
            base_path: Base directory for fixture files. 
                      Defaults to tests/fixtures relative to this file.
        """
        if base_path is None:
            # Default to tests/fixtures
            this_dir = Path(__file__).parent
            base_path = this_dir.parent / "fixtures"
        
        self.base_path = Path(base_path)
        self._generators: Dict[str, Callable[..., str]] = {}
    
    def register_generator(self, name: str, generator: Callable[..., str]):
        """
        Register a Python function for generating complex fixtures.
        
        Args:
            name: Generator name (used like a fixture path)
            generator: Function that returns XML string
        """
        self._generators[name] = generator
    
    def load(self, fixture_path: str, **kwargs) -> str:
        """
        Load an XML fixture file with placeholder substitution.
        
        Placeholders use {{name}} syntax and are replaced with kwargs values.
        
        Args:
            fixture_path: Path relative to base_path (e.g., "firewall/show_system_info.xml")
            **kwargs: Values to substitute for placeholders
            
        Returns:
            XML string with placeholders replaced
            
        Raises:
            FileNotFoundError: If fixture file doesn't exist
            ValueError: If required placeholder not provided
        """
        # Check if this is a registered generator
        if fixture_path in self._generators:
            return self._generators[fixture_path](**kwargs)
        
        full_path = self.base_path / fixture_path
        
        if not full_path.exists():
            raise FileNotFoundError(f"Fixture not found: {full_path}")
        
        with open(full_path, 'r') as f:
            content = f.read()
        
        # Find all placeholders
        placeholders = re.findall(r'\{\{(\w+)\}\}', content)
        
        # Substitute placeholders
        for placeholder in placeholders:
            if placeholder not in kwargs:
                raise ValueError(
                    f"Missing value for placeholder '{{{{{placeholder}}}}}' in {fixture_path}"
                )
            content = content.replace(f"{{{{{placeholder}}}}}", str(kwargs[placeholder]))
        
        return content
    
    def load_as_element(self, fixture_path: str, **kwargs) -> ET.Element:
        """
        Load fixture and parse as ElementTree Element.
        
        Args:
            fixture_path: Path relative to base_path
            **kwargs: Values to substitute for placeholders
            
        Returns:
            Parsed XML Element
        """
        xml_str = self.load(fixture_path, **kwargs)
        return ET.fromstring(xml_str)
    
    def load_result(self, fixture_path: str, **kwargs) -> Optional[ET.Element]:
        """
        Load fixture and return the <result> element (common pattern in PAN-OS responses).
        
        Args:
            fixture_path: Path relative to base_path
            **kwargs: Values to substitute for placeholders
            
        Returns:
            The <result> element, or None if not found
        """
        root = self.load_as_element(fixture_path, **kwargs)
        return root.find('.//result')
    
    def exists(self, fixture_path: str) -> bool:
        """
        Check if a fixture file exists.
        
        Args:
            fixture_path: Path relative to base_path
            
        Returns:
            True if fixture exists
        """
        if fixture_path in self._generators:
            return True
        return (self.base_path / fixture_path).exists()


# Common fixture generators for complex scenarios

def generate_disk_space_response(
    panrepo_available_gb: float = 15.0,
    panrepo_total_gb: float = 20.0,
    root_available_gb: float = 3.7,
    include_panrepo: bool = True
) -> str:
    """
    Generate disk space response with configurable values.
    
    Args:
        panrepo_available_gb: Available space on /opt/pancfg
        panrepo_total_gb: Total size of /opt/pancfg
        root_available_gb: Available space on root partition
        include_panrepo: Whether to include /opt/pancfg partition
        
    Returns:
        XML response string
    """
    panrepo_used = max(1.0, panrepo_total_gb - panrepo_available_gb)
    panrepo_percent = int((panrepo_used / panrepo_total_gb) * 100)
    
    lines = [
        "Filesystem      Size  Used Avail Use% Mounted on",
        f"/dev/sda2       5.1G  1.4G  {root_available_gb:.1f}G  27% /",
        "/dev/sda5       7.6G  4.0G  3.3G  55% /opt/panrepo",
        "/dev/sda6        17G  7.5G  8.6G  47% /opt/panlogs",
    ]
    
    if include_panrepo:
        lines.append(
            f"/dev/sda8       {panrepo_total_gb:.1f}G  {panrepo_used:.1f}G  "
            f"{panrepo_available_gb:.1f}G  {panrepo_percent}% /opt/pancfg"
        )
    
    df_output = "\n".join(lines)
    
    return f'''<response status="success">
  <result>{df_output}</result>
</response>'''


def generate_software_info_response(
    versions: list = None,
    current_version: str = "10.1.0"
) -> str:
    """
    Generate software info response with configurable versions.
    
    Args:
        versions: List of dicts with version info, or None for defaults
        current_version: Currently installed version
        
    Returns:
        XML response string
    """
    if versions is None:
        versions = [
            {"version": "10.1.0", "downloaded": "yes", "current": "yes"},
            {"version": "10.2.0", "downloaded": "yes", "current": "no"},
            {"version": "11.0.0", "downloaded": "no", "current": "no"},
            {"version": "11.1.0", "downloaded": "no", "current": "no"},
        ]
    
    entries = []
    for v in versions:
        is_current = v.get("current", "no")
        if v["version"] == current_version:
            is_current = "yes"
        
        entries.append(f'''    <sw-version>
      <version>{v["version"]}</version>
      <filename>PanOS_vm-{v["version"]}</filename>
      <size>500M</size>
      <downloaded>{v.get("downloaded", "no")}</downloaded>
      <current>{is_current}</current>
    </sw-version>''')
    
    entries_xml = "\n".join(entries)
    
    return f'''<response status="success">
  <result>
{entries_xml}
  </result>
</response>'''


def generate_routing_table_response(routes: list = None) -> str:
    """
    Generate routing table response.
    
    Args:
        routes: List of route dicts, or None for defaults
        
    Returns:
        XML response string
    """
    if routes is None:
        routes = [
            {"destination": "0.0.0.0/0", "nexthop": "10.0.0.1", "interface": "ethernet1/1", "metric": "10"},
            {"destination": "10.0.0.0/8", "nexthop": "10.0.0.1", "interface": "ethernet1/1", "metric": "10"},
            {"destination": "192.168.0.0/16", "nexthop": "10.0.1.1", "interface": "ethernet1/2", "metric": "10"},
        ]
    
    entries = []
    for r in routes:
        entries.append(f'''    <entry>
      <destination>{r["destination"]}</destination>
      <nexthop>{r["nexthop"]}</nexthop>
      <interface>{r["interface"]}</interface>
      <metric>{r.get("metric", "10")}</metric>
      <flags>A S</flags>
    </entry>''')
    
    entries_xml = "\n".join(entries)
    
    return f'''<response status="success">
  <result>
{entries_xml}
  </result>
</response>'''


def generate_arp_table_response(entries: list = None) -> str:
    """
    Generate ARP table response.
    
    Args:
        entries: List of ARP entry dicts, or None for defaults
        
    Returns:
        XML response string
    """
    if entries is None:
        entries = [
            {"ip": "10.0.0.1", "mac": "00:11:22:33:44:55", "interface": "ethernet1/1"},
            {"ip": "10.0.0.2", "mac": "00:11:22:33:44:56", "interface": "ethernet1/1"},
            {"ip": "10.0.1.1", "mac": "aa:bb:cc:dd:ee:ff", "interface": "ethernet1/2"},
        ]
    
    entry_xml = []
    for e in entries:
        entry_xml.append(f'''    <entry>
      <ip>{e["ip"]}</ip>
      <mac>{e["mac"]}</mac>
      <interface>{e["interface"]}</interface>
      <status>c</status>
    </entry>''')
    
    entries_str = "\n".join(entry_xml)
    
    return f'''<response status="success">
  <result>
{entries_str}
  </result>
</response>'''


def generate_session_info_response(
    tcp_sessions: int = 1000,
    udp_sessions: int = 500,
    icmp_sessions: int = 50
) -> str:
    """
    Generate session info response.
    
    Args:
        tcp_sessions: Number of TCP sessions
        udp_sessions: Number of UDP sessions
        icmp_sessions: Number of ICMP sessions
        
    Returns:
        XML response string
    """
    total = tcp_sessions + udp_sessions + icmp_sessions
    
    return f'''<response status="success">
  <result>
    <num-active>{total}</num-active>
    <num-tcp>{tcp_sessions}</num-tcp>
    <num-udp>{udp_sessions}</num-udp>
    <num-icmp>{icmp_sessions}</num-icmp>
    <num-max>262144</num-max>
  </result>
</response>'''


def generate_download_status_response(
    downloading: bool = False,
    progress: int = 0
) -> str:
    """
    Generate software download status response.
    
    Args:
        downloading: Whether download is in progress
        progress: Download progress percentage
        
    Returns:
        XML response string
    """
    downloading_str = "yes" if downloading else "no"
    
    return f'''<response status="success">
  <result>
    <downloading>{downloading_str}</downloading>
    <progress>{progress}</progress>
  </result>
</response>'''

