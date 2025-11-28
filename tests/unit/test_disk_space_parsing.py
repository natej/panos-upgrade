"""Tests for disk space parsing in both Panorama and direct firewall clients."""

import pytest
from pan.xapi import PanXapiError

from panos_upgrade.direct_firewall_client import DirectFirewallClient
from panos_upgrade.panorama_client import PanoramaClient
from tests.helpers import MockPanXapi
from tests.helpers.xml_loader import generate_disk_space_response


class TestDirectFirewallDiskSpaceParsing:
    """Test disk space parsing in DirectFirewallClient."""
    
    def test_parses_panrepo_partition(self, mock_xapi):
        """Should correctly parse /opt/pancfg available space."""
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=15.5)
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_disk_space()
        
        assert result == 15.5
        mock_xapi.assert_called_with("show.system.disk-space")
    
    def test_parses_small_disk_space(self, mock_xapi):
        """Should correctly parse small disk space values."""
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=0.5)
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_disk_space()
        
        assert result == 0.5
    
    def test_falls_back_to_root_partition(self, mock_xapi):
        """Should fall back to root partition if /opt/pancfg not present."""
        # Response without /opt/pancfg partition
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(
                panrepo_available_gb=15.0,
                include_panrepo=False,
                root_available_gb=3.7
            )
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_disk_space()
        
        # Should get root partition value
        assert result == 3.7
    
    def test_parses_megabyte_values(self, mock_xapi):
        """Should correctly parse values in MB."""
        # Custom response with MB values
        response = '''<response status="success">
  <result>Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2       5.1G  1.4G  3.7G  27% /
/dev/sda8       20G  19G  512M  96% /opt/pancfg</result>
</response>'''
        
        mock_xapi.add_response("show.system.disk-space", response)
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_disk_space()
        
        # 512M = 0.5 GB
        assert result == pytest.approx(0.5, rel=0.01)
    
    def test_handles_api_error(self, mock_xapi):
        """Should raise exception on API error."""
        mock_xapi.add_response(
            "show.system.disk-space",
            '<response status="error"><msg><line>Command failed</line></msg></response>'
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        with pytest.raises(PanXapiError):
            client.check_disk_space()
    
    def test_parses_terabyte_values(self, mock_xapi):
        """Should correctly parse values in TB."""
        response = '''<response status="success">
  <result>Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2       5.1G  1.4G  3.7G  27% /
/dev/sda8       2.0T  1.0T  1.0T  50% /opt/pancfg</result>
</response>'''
        
        mock_xapi.add_response("show.system.disk-space", response)
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_disk_space()
        
        # 1.0T = 1024 GB
        assert result == pytest.approx(1024.0, rel=0.01)


class TestPanoramaClientDiskSpaceParsing:
    """Test disk space parsing in PanoramaClient (via get_system_metrics)."""
    
    def test_parses_disk_space_in_metrics(self, mock_xapi, test_config):
        """Should correctly parse disk space from system metrics."""
        # Need to mock multiple commands for get_system_metrics
        mock_xapi.add_response(
            "show.system.info",
            '''<response status="success">
  <result>
    <system>
      <hostname>test-fw</hostname>
      <serial>001234567890</serial>
      <sw-version>10.1.0</sw-version>
    </system>
  </result>
</response>'''
        )
        mock_xapi.add_response(
            "show.session.info",
            '''<response status="success">
  <result>
    <num-active>1000</num-active>
    <num-tcp>800</num-tcp>
  </result>
</response>'''
        )
        mock_xapi.add_response(
            "show.routing.route",
            '''<response status="success">
  <result></result>
</response>'''
        )
        mock_xapi.add_response(
            "show.arp",
            '''<response status="success">
  <result></result>
</response>'''
        )
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=12.5)
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        metrics = client.get_system_metrics("001234567890")
        
        assert metrics['disk_available_gb'] == 12.5


class TestDiskSpaceParsingEdgeCases:
    """Test edge cases in disk space parsing."""
    
    def test_handles_empty_response(self, mock_xapi):
        """Should return 0 for empty response."""
        mock_xapi.add_response(
            "show.system.disk-space",
            '<response status="success"><result></result></response>'
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_disk_space()
        
        assert result == 0.0
    
    def test_handles_malformed_df_output(self, mock_xapi):
        """Should handle malformed df output gracefully."""
        response = '''<response status="success">
  <result>Some unexpected output format</result>
</response>'''
        
        mock_xapi.add_response("show.system.disk-space", response)
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_disk_space()
        
        # Should return 0 when parsing fails
        assert result == 0.0
    
    def test_handles_multiple_panrepo_like_paths(self, mock_xapi):
        """Should pick the correct /opt/pancfg path."""
        response = '''<response status="success">
  <result>Filesystem      Size  Used Avail Use% Mounted on
/dev/sda2       5.1G  1.4G  3.7G  27% /
/dev/sda7       10G  5G  5G  50% /opt/pancfg_backup
/dev/sda8       20G  5G  15G  25% /opt/pancfg</result>
</response>'''
        
        mock_xapi.add_response("show.system.disk-space", response)
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.check_disk_space()
        
        # Should get the actual /opt/pancfg, not /opt/pancfg_backup
        assert result == 15.0

