"""Tests for download progress and status checking."""

import pytest
from pan.xapi import PanXapiError

from panos_upgrade.direct_firewall_client import DirectFirewallClient
from panos_upgrade.panorama_client import PanoramaClient
from tests.helpers import MockPanXapi
from tests.helpers.xml_loader import generate_download_status_response


class TestDirectFirewallDownloadStatus:
    """Test download status checking in DirectFirewallClient."""
    
    def test_parses_download_in_progress(self, mock_xapi):
        """Should correctly parse active download status."""
        mock_xapi.add_response(
            "show.system.software.status",
            generate_download_status_response(downloading=True, progress=45)
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_download_status()
        
        assert result["downloading"] == "yes"
        assert result["progress"] == "45"
    
    def test_parses_download_complete(self, mock_xapi):
        """Should correctly parse completed download status."""
        mock_xapi.add_response(
            "show.system.software.status",
            generate_download_status_response(downloading=False, progress=100)
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_download_status()
        
        assert result["downloading"] == "no"
    
    def test_parses_no_download(self, mock_xapi):
        """Should correctly parse status when no download is active."""
        mock_xapi.add_response(
            "show.system.software.status",
            generate_download_status_response(downloading=False, progress=0)
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_download_status()
        
        assert result["downloading"] == "no"
        assert result["progress"] == "0"


class TestDownloadProgressSequence:
    """Test download progress over multiple polls."""
    
    def test_progress_sequence(self, mock_xapi):
        """Should correctly track progress through multiple status checks."""
        # Register a sequence of responses
        mock_xapi.add_sequence(
            "show.system.software.status",
            [
                generate_download_status_response(downloading=True, progress=10),
                generate_download_status_response(downloading=True, progress=50),
                generate_download_status_response(downloading=True, progress=90),
                generate_download_status_response(downloading=False, progress=100),
            ]
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        # First check - 10%
        result1 = client.check_download_status()
        assert result1["progress"] == "10"
        assert result1["downloading"] == "yes"
        
        # Second check - 50%
        result2 = client.check_download_status()
        assert result2["progress"] == "50"
        
        # Third check - 90%
        result3 = client.check_download_status()
        assert result3["progress"] == "90"
        
        # Fourth check - complete
        result4 = client.check_download_status()
        assert result4["downloading"] == "no"


class TestPanoramaDownloadStatus:
    """Test download status checking via Panorama."""
    
    def test_parses_download_status(self, mock_xapi, test_config):
        """Should correctly parse download status via Panorama."""
        mock_xapi.add_response(
            "show.system.software.status",
            generate_download_status_response(downloading=True, progress=75)
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        result = client.check_download_status("001234567890")
        
        assert result["downloading"] == "yes"
        assert result["progress"] == "75"


class TestDownloadInitiation:
    """Test software download initiation."""
    
    def test_initiates_download_successfully(self, mock_xapi):
        """Should successfully initiate download and return job ID."""
        mock_xapi.add_response(
            "request.system.software.download",
            '''<response status="success" code="19">
  <result>
    <msg>
      <line>Download job enqueued with jobid 42</line>
    </msg>
    <job>42</job>
  </result>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.download_software("11.0.0")
        
        assert result == "42"  # Returns job ID
        mock_xapi.assert_called_with("request.system.software.download")
    
    def test_handles_download_failure(self, mock_xapi):
        """Should handle download initiation failure."""
        mock_xapi.add_response(
            "request.system.software.download",
            '''<response status="error">
  <msg>
    <line>Version 99.0.0 not available</line>
  </msg>
</response>'''
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        with pytest.raises(PanXapiError):
            client.download_software("99.0.0")
    
    def test_download_via_panorama(self, mock_xapi, test_config):
        """Should successfully initiate download via Panorama."""
        mock_xapi.add_response(
            "request.system.software.download",
            '''<response status="success">
  <result>
    <status>success</status>
    <msg>Download job enqueued</msg>
  </result>
</response>'''
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        result = client.download_software("001234567890", "11.0.0")
        
        assert result == True


class TestJobStatusChecking:
    """Test job status checking for download jobs."""
    
    def test_parses_active_job(self, mock_xapi):
        """Should correctly parse active job status."""
        mock_xapi.add_response(
            "show.jobs.id",
            '''<response status="success">
  <result>
    <job>
      <tenq>2025/11/28 16:48:53</tenq>
      <id>42</id>
      <user>admin</user>
      <type>Downld</type>
      <status>ACT</status>
      <queued>NO</queued>
      <stoppable>yes</stoppable>
      <result>PEND</result>
      <progress>45</progress>
      <description>Download of software version 11.1.0</description>
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
        
        result = client.check_job_status("42")
        
        assert result["status"] == "ACT"
        assert result["result"] == "PEND"
        assert result["progress"] == "45"
    
    def test_parses_completed_job(self, mock_xapi):
        """Should correctly parse completed job status."""
        mock_xapi.add_response(
            "show.jobs.id",
            '''<response status="success">
  <result>
    <job>
      <tenq>2025/11/28 16:48:53</tenq>
      <id>42</id>
      <user>admin</user>
      <type>Downld</type>
      <status>FIN</status>
      <queued>NO</queued>
      <stoppable>no</stoppable>
      <result>OK</result>
      <tfin>2025/11/28 16:50:00</tfin>
      <description>Download of software version 11.1.0</description>
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
        
        result = client.check_job_status("42")
        
        assert result["status"] == "FIN"
        assert result["result"] == "OK"
    
    def test_parses_failed_job(self, mock_xapi):
        """Should correctly parse failed job status."""
        mock_xapi.add_response(
            "show.jobs.id",
            '''<response status="success">
  <result>
    <job>
      <tenq>2025/11/28 16:48:53</tenq>
      <id>42</id>
      <user>admin</user>
      <type>Downld</type>
      <status>FIN</status>
      <queued>NO</queued>
      <stoppable>no</stoppable>
      <result>FAIL</result>
      <tfin>2025/11/28 16:50:00</tfin>
      <details>Connection timeout to update server</details>
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
        
        result = client.check_job_status("42")
        
        assert result["status"] == "FIN"
        assert result["result"] == "FAIL"
        assert result["details"] == "Connection timeout to update server"

