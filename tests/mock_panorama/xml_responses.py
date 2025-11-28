"""XML response templates for PAN-OS API."""

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional


def create_response(status: str = "success") -> ET.Element:
    """Create base response element."""
    response = ET.Element("response")
    response.set("status", status)
    return response


def create_error_response(message: str) -> str:
    """
    Create error response XML.
    
    Args:
        message: Error message
        
    Returns:
        XML string
    """
    response = create_response("error")
    result = ET.SubElement(response, "result")
    msg = ET.SubElement(result, "msg")
    msg.text = message
    
    return ET.tostring(response, encoding="unicode")


def create_system_info_response(device: Dict) -> str:
    """
    Create system info response XML.
    
    Args:
        device: Device dict with info
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    system = ET.SubElement(result, "system")
    
    hostname = ET.SubElement(system, "hostname")
    hostname.text = device.get("hostname", "")
    
    serial = ET.SubElement(system, "serial")
    serial.text = device.get("serial", "")
    
    sw_version = ET.SubElement(system, "sw-version")
    sw_version.text = device.get("current_version", "")
    
    model = ET.SubElement(system, "model")
    model.text = device.get("model", "")
    
    ip_address = ET.SubElement(system, "ip-address")
    ip_address.text = device.get("ip_address", "")
    
    return ET.tostring(response, encoding="unicode")


def create_ha_state_response(device: Dict, peer: Optional[Dict] = None) -> str:
    """
    Create HA state response XML.
    
    Args:
        device: Device dict
        peer: Peer device dict (optional)
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    
    enabled = ET.SubElement(result, "enabled")
    enabled.text = "yes" if device.get("ha_enabled") else "no"
    
    # Local info
    local_info = ET.SubElement(result, "local-info")
    
    state = ET.SubElement(local_info, "state")
    state.text = device.get("ha_role", "standalone")
    
    serial_num = ET.SubElement(local_info, "serial-num")
    serial_num.text = device.get("serial", "")
    
    # Peer info (if HA enabled)
    if device.get("ha_enabled") and peer:
        peer_info = ET.SubElement(result, "peer-info")
        
        peer_state = ET.SubElement(peer_info, "state")
        peer_state.text = peer.get("ha_role", "")
        
        peer_serial = ET.SubElement(peer_info, "serial-num")
        peer_serial.text = peer.get("serial", "")
    
    return ET.tostring(response, encoding="unicode")


def create_session_info_response(tcp_sessions: int) -> str:
    """
    Create session info response XML.
    
    Args:
        tcp_sessions: Number of TCP sessions
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    
    num_active = ET.SubElement(result, "num-active")
    num_active.text = str(tcp_sessions)
    
    return ET.tostring(response, encoding="unicode")


def create_routing_table_response(routes: List[Dict]) -> str:
    """
    Create routing table response XML.
    
    Args:
        routes: List of route dicts
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    
    for route in routes:
        entry = ET.SubElement(result, "entry")
        
        destination = ET.SubElement(entry, "destination")
        destination.text = route.get("destination", "")
        
        nexthop = ET.SubElement(entry, "nexthop")
        nexthop.text = route.get("gateway", "")
        
        interface = ET.SubElement(entry, "interface")
        interface.text = route.get("interface", "")
    
    return ET.tostring(response, encoding="unicode")


def create_arp_table_response(arp_entries: List[Dict]) -> str:
    """
    Create ARP table response XML.
    
    Args:
        arp_entries: List of ARP entry dicts
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    
    for arp in arp_entries:
        entry = ET.SubElement(result, "entry")
        
        ip = ET.SubElement(entry, "ip")
        ip.text = arp.get("ip", "")
        
        mac = ET.SubElement(entry, "mac")
        mac.text = arp.get("mac", "")
        
        interface = ET.SubElement(entry, "interface")
        interface.text = arp.get("interface", "")
    
    return ET.tostring(response, encoding="unicode")


def create_disk_space_response(available_gb: float) -> str:
    """
    Create disk space response XML matching real PAN-OS format.
    
    Real PAN-OS returns df-like output as text content:
    Filesystem      Size  Used Avail Use% Mounted on
    /dev/sda2       5.1G  1.1G  3.7G  23% /
    /dev/sda5       7.6G  4.0G  3.3G  55% /opt/pancfg
    /dev/sda6        17G  7.5G  8.6G  47% /opt/panlogs
    /dev/sda8        20G  5.0G  15.0G 25% /opt/pancfg
    
    Args:
        available_gb: Available disk space in GB (for /opt/pancfg)
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    
    # Create realistic df-like output
    # Software downloads go to /opt/pancfg, so that's the partition to report
    total_gb = 20.0
    used_gb = max(1.0, total_gb - available_gb)  # Simulate some used space
    use_percent = int((used_gb / total_gb) * 100)
    
    df_output = f"""Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2       5.1G  1.1G  3.7G  23% /
/dev/sda5       7.6G  4.0G  3.3G  55% /opt/pancfg
/dev/sda6        17G  7.5G  8.6G  47% /opt/panlogs
/dev/sda8       {total_gb:.1f}G  {used_gb:.1f}G  {available_gb:.1f}G  {use_percent}% /opt/pancfg"""
    
    result.text = df_output
    
    return ET.tostring(response, encoding="unicode")


def create_software_download_response(success: bool = True, message: str = "") -> str:
    """
    Create software download response XML.
    
    Args:
        success: Whether download started successfully
        message: Optional message
        
    Returns:
        XML string
    """
    if success:
        response = create_response("success")
        result = ET.SubElement(response, "result")
        status = ET.SubElement(result, "status")
        status.text = "success"
        if message:
            msg = ET.SubElement(result, "msg")
            msg.text = message
    else:
        return create_error_response(message or "Download failed")
    
    return ET.tostring(response, encoding="unicode")


def create_software_status_response(downloading: bool, progress: int = 0) -> str:
    """
    Create software status response XML.
    
    Args:
        downloading: Whether currently downloading
        progress: Download progress (0-100)
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    
    downloading_elem = ET.SubElement(result, "downloading")
    downloading_elem.text = "yes" if downloading else "no"
    
    if downloading:
        progress_elem = ET.SubElement(result, "progress")
        progress_elem.text = f"{progress}%"
    
    return ET.tostring(response, encoding="unicode")


def create_software_install_response(success: bool = True, message: str = "") -> str:
    """
    Create software install response XML.
    
    Args:
        success: Whether install started successfully
        message: Optional message
        
    Returns:
        XML string
    """
    if success:
        response = create_response("success")
        result = ET.SubElement(response, "result")
        status = ET.SubElement(result, "status")
        status.text = "success"
        if message:
            msg = ET.SubElement(result, "msg")
            msg.text = message
    else:
        return create_error_response(message or "Install failed")
    
    return ET.tostring(response, encoding="unicode")


def create_reboot_response(success: bool = True, message: str = "") -> str:
    """
    Create reboot response XML.
    
    Args:
        success: Whether reboot started successfully
        message: Optional message
        
    Returns:
        XML string
    """
    if success:
        response = create_response("success")
        result = ET.SubElement(response, "result")
        msg = ET.SubElement(result, "msg")
        msg.text = message or "Reboot initiated"
    else:
        return create_error_response(message or "Reboot failed")
    
    return ET.tostring(response, encoding="unicode")


def create_connected_devices_response(devices: List[Dict]) -> str:
    """
    Create connected devices response XML.
    
    Args:
        devices: List of device dicts
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    
    for device in devices:
        entry = ET.SubElement(result, "entry")
        
        serial = ET.SubElement(entry, "serial")
        serial.text = device.get("serial", "")
        
        hostname = ET.SubElement(entry, "hostname")
        hostname.text = device.get("hostname", "")
        
        ip_address = ET.SubElement(entry, "ip-address")
        ip_address.text = device.get("ip_address", "")
        
        sw_version = ET.SubElement(entry, "sw-version")
        sw_version.text = device.get("current_version", "")
        
        model = ET.SubElement(entry, "model")
        model.text = device.get("model", "")
    
    return ET.tostring(response, encoding="unicode")


def create_software_info_response(versions: List[Dict]) -> str:
    """
    Create software info response XML.
    
    Args:
        versions: List of software version dicts with hashes
        
    Returns:
        XML string
    """
    response = create_response("success")
    result = ET.SubElement(response, "result")
    
    for ver in versions:
        sw_version = ET.SubElement(result, "sw-version")
        
        version = ET.SubElement(sw_version, "version")
        version.text = ver.get("version", "")
        
        filename = ET.SubElement(sw_version, "filename")
        filename.text = ver.get("filename", "")
        
        size = ET.SubElement(sw_version, "size")
        size.text = ver.get("size", "")
        
        downloaded = ET.SubElement(sw_version, "downloaded")
        downloaded.text = ver.get("downloaded", "no")
        
        current = ET.SubElement(sw_version, "current")
        current.text = ver.get("current", "no")
        
        sha256 = ET.SubElement(sw_version, "sha256")
        sha256.text = ver.get("sha256", "")
    
    return ET.tostring(response, encoding="unicode")

