"""Tests for DirectFirewallClient operations (system info, HA, install, reboot, etc.)."""

import pytest
from pan.xapi import PanXapiError

from panos_upgrade.direct_firewall_client import DirectFirewallClient
from tests.helpers import MockPanXapi


class TestGetSystemInfo:
    """Test get_system_info() method."""
    
    def test_parses_system_info(self, mock_xapi):
        """Should correctly parse system info response."""
        mock_xapi.add_response(
            "show.system.info",
            '''<response status="success">
  <result>
    <system>
      <hostname>fw-datacenter-01</hostname>
      <serial>001234567890</serial>
      <sw-version>10.1.0</sw-version>
      <model>PA-VM</model>
      <ip-address>10.0.0.1</ip-address>
    </system>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.get_system_info()
        
        assert result["hostname"] == "fw-datacenter-01"
        assert result["serial"] == "001234567890"
        assert result["sw_version"] == "10.1.0"
        assert result["model"] == "PA-VM"
        assert result["ip_address"] == "10.0.0.1"
    
    def test_handles_empty_fields(self, mock_xapi):
        """Should handle missing fields gracefully."""
        mock_xapi.add_response(
            "show.system.info",
            '''<response status="success">
  <result>
    <system>
      <hostname>fw-01</hostname>
    </system>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.get_system_info()
        
        assert result["hostname"] == "fw-01"
        assert result["serial"] == ""
        assert result["sw_version"] == ""


class TestGetHAState:
    """Test get_ha_state() method."""
    
    def test_parses_active_ha_state(self, mock_xapi):
        """Should correctly parse active HA state."""
        mock_xapi.add_response(
            "show.high-availability.state",
            '''<response status="success">
  <result>
    <enabled>yes</enabled>
    <local-info>
      <state>active</state>
      <serial-num>001234567890</serial-num>
    </local-info>
    <peer-info>
      <state>passive</state>
      <serial-num>001234567891</serial-num>
    </peer-info>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.get_ha_state()
        
        assert result["enabled"] == "yes"
        assert result["local_state"] == "active"
        assert result["peer_state"] == "passive"
        assert result["local_serial"] == "001234567890"
        assert result["peer_serial"] == "001234567891"
    
    def test_parses_standalone_state(self, mock_xapi):
        """Should correctly parse standalone (no HA) state."""
        mock_xapi.add_response(
            "show.high-availability.state",
            '''<response status="success">
  <result>
    <enabled>no</enabled>
    <local-info>
      <state>standalone</state>
    </local-info>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.get_ha_state()
        
        assert result["enabled"] == "no"
        assert result["local_state"] == "standalone"


class TestInstallSoftware:
    """Test install_software() method."""
    
    def test_initiates_install_successfully(self, mock_xapi):
        """Should successfully initiate install and return job ID."""
        mock_xapi.add_response(
            "request.system.software.install",
            '''<response status="success" code="19">
  <result>
    <msg>
      <line>Software install job enqueued with jobid 55</line>
    </msg>
    <job>55</job>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.install_software("11.0.0")
        
        assert result == "55"
        mock_xapi.assert_called_with("request.system.software.install")
    
    def test_returns_none_on_failure(self, mock_xapi):
        """Should return None when install fails to initiate."""
        mock_xapi.add_response(
            "request.system.software.install",
            '''<response status="success">
  <result>
    <msg>Version 11.0.0 is not downloaded</msg>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.install_software("11.0.0")
        
        assert result is None


class TestRebootDevice:
    """Test reboot_device() method."""
    
    def test_initiates_reboot_successfully(self, mock_xapi):
        """Should successfully initiate reboot."""
        mock_xapi.add_response(
            "request.restart.system",
            '''<response status="success">
  <result>Restarting system...</result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.reboot_device()
        
        assert result == True
        mock_xapi.assert_called_with("request.restart.system")


class TestGetSystemMetrics:
    """Test get_system_metrics() method."""
    
    def test_collects_all_metrics(self, mock_xapi):
        """Should collect TCP sessions, routes, ARP, and disk space."""
        # Session info
        mock_xapi.add_response(
            "show.session.info",
            '''<response status="success">
  <result>
    <num-active>5000</num-active>
    <num-tcp>4000</num-tcp>
  </result>
</response>'''
        )
        
        # Routing table
        mock_xapi.add_response(
            "show.routing.route",
            '''<response status="success">
  <result>
    <entry>
      <destination>0.0.0.0/0</destination>
      <nexthop>10.0.0.1</nexthop>
      <interface>ethernet1/1</interface>
    </entry>
    <entry>
      <destination>10.0.0.0/8</destination>
      <nexthop>10.0.0.1</nexthop>
      <interface>ethernet1/1</interface>
    </entry>
  </result>
</response>'''
        )
        
        # ARP table
        mock_xapi.add_response(
            "show.arp",
            '''<response status="success">
  <result>
    <entry>
      <ip>10.0.0.1</ip>
      <mac>00:11:22:33:44:55</mac>
      <interface>ethernet1/1</interface>
    </entry>
  </result>
</response>'''
        )
        
        # Disk space
        mock_xapi.add_response(
            "show.system.disk-space",
            '''<response status="success">
  <result>Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2       5.1G  1.4G  3.7G  27% /
/dev/sda5       7.6G  4.0G  3.3G  55% /opt/panrepo
/dev/sda8       20G  5G  15G  25% /opt/pancfg</result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.get_system_metrics()
        
        assert result["tcp_sessions"] == 5000
        assert result["route_count"] == 2
        assert len(result["routes"]) == 2
        assert result["arp_count"] == 1
        assert len(result["arp_entries"]) == 1
        assert result["disk_available_gb"] == 15.0


class TestWaitForInstall:
    """Test wait_for_install() method."""
    
    def test_returns_true_on_success(self, mock_xapi):
        """Should return True when install completes successfully."""
        mock_xapi.add_response(
            "show.jobs.id",
            '''<response status="success">
  <result>
    <job>
      <id>55</id>
      <type>Install</type>
      <status>FIN</status>
      <result>OK</result>
      <progress>100</progress>
    </job>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.wait_for_install("55", "11.0.0", stall_timeout=5)
        
        assert result == True
    
    def test_returns_false_on_failure(self, mock_xapi):
        """Should return False when install fails."""
        mock_xapi.add_response(
            "show.jobs.id",
            '''<response status="success">
  <result>
    <job>
      <id>55</id>
      <type>Install</type>
      <status>FIN</status>
      <result>FAIL</result>
      <details>Installation failed: disk space</details>
    </job>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.wait_for_install("55", "11.0.0", stall_timeout=5)
        
        assert result == False

