"""Tests for software check (request system software check) functionality."""

import pytest
from pan.xapi import PanXapiError

from panos_upgrade.direct_firewall_client import DirectFirewallClient
from panos_upgrade.panorama_client import PanoramaClient
from tests.helpers import MockPanXapi


class TestDirectFirewallSoftwareCheck:
    """Test software check in DirectFirewallClient."""
    
    def test_software_check_success(self, mock_xapi):
        """Should return True when software check completes successfully."""
        mock_xapi.add_response(
            "request.system.software.check",
            '''<response status="success">
  <result>
    <sw-updates last-updated-at="2025-01-15 10:30:00">
      <msg>Software update check completed</msg>
    </sw-updates>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_software_updates(timeout=60)
        
        assert result == True
        mock_xapi.assert_called_with("request.system.software.check")
    
    def test_software_check_returns_error(self, mock_xapi):
        """Should return False when software check returns error in response."""
        mock_xapi.add_response(
            "request.system.software.check",
            '''<response status="success">
  <result>
    <msg>Error: Unable to connect to update server</msg>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_software_updates(timeout=60)
        
        assert result == False
    
    def test_software_check_api_error(self, mock_xapi):
        """Should return False on API error (not raise exception)."""
        mock_xapi.add_response(
            "request.system.software.check",
            '<response status="error"><msg><line>Command failed</line></msg></response>'
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        # Should not raise, just return False
        result = client.check_software_updates(timeout=60)
        
        assert result == False
    
    def test_software_check_empty_response(self, mock_xapi):
        """Should return False on empty response."""
        mock_xapi.add_response(
            "request.system.software.check",
            '<response status="success"><result></result></response>'
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_software_updates(timeout=60)
        
        # Empty result but no error - should succeed
        assert result == True


class TestPanoramaClientSoftwareCheck:
    """Test software check in PanoramaClient."""
    
    def test_software_check_success(self, mock_xapi, test_config):
        """Should return True when software check completes successfully."""
        mock_xapi.add_response(
            "request.system.software.check",
            '''<response status="success">
  <result>
    <sw-updates last-updated-at="2025-01-15 10:30:00">
      <msg>Software update check completed</msg>
    </sw-updates>
  </result>
</response>'''
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        result = client.check_software_updates("001234567890", timeout=60)
        
        assert result == True
        mock_xapi.assert_called_with("request.system.software.check")
    
    def test_software_check_returns_error(self, mock_xapi, test_config):
        """Should return False when software check returns error in response."""
        mock_xapi.add_response(
            "request.system.software.check",
            '''<response status="success">
  <result>
    <msg>Error: Unable to connect to update server</msg>
  </result>
</response>'''
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        result = client.check_software_updates("001234567890", timeout=60)
        
        assert result == False
    
    def test_software_check_api_error(self, mock_xapi, test_config):
        """Should return False on API error (not raise exception)."""
        mock_xapi.add_response(
            "request.system.software.check",
            '<response status="error"><msg><line>Command failed</line></msg></response>'
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        # Should not raise, just return False
        result = client.check_software_updates("001234567890", timeout=60)
        
        assert result == False
    
    def test_software_check_with_serial_target(self, mock_xapi, test_config):
        """Should pass serial number as target to command."""
        mock_xapi.add_response(
            "request.system.software.check",
            '''<response status="success">
  <result>
    <msg>Software update check completed</msg>
  </result>
</response>'''
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        result = client.check_software_updates("001234567890", timeout=60)
        
        assert result == True
        # Verify serial was passed as target
        assert mock_xapi.last_extra_qs.get('target') == '001234567890'


class TestSoftwareCheckTimeout:
    """Test timeout handling for software check."""
    
    def test_timeout_is_applied_direct_firewall(self, mock_xapi):
        """Should apply custom timeout to direct firewall client."""
        mock_xapi.add_response(
            "request.system.software.check",
            '''<response status="success">
  <result><msg>OK</msg></result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        # Set initial timeout
        mock_xapi.timeout = 300
        
        result = client.check_software_updates(timeout=120)
        
        assert result == True
        # Timeout should be restored after call
        assert mock_xapi.timeout == 300
    
    def test_timeout_is_applied_panorama(self, mock_xapi, test_config):
        """Should apply custom timeout to Panorama client."""
        mock_xapi.add_response(
            "request.system.software.check",
            '''<response status="success">
  <result><msg>OK</msg></result>
</response>'''
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        # Set initial timeout
        mock_xapi.timeout = 300
        
        result = client.check_software_updates("001234567890", timeout=120)
        
        assert result == True
        # Timeout should be restored after call
        assert mock_xapi.timeout == 300

