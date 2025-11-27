"""Tests for software info parsing in both Panorama and direct firewall clients."""

import pytest
from pan.xapi import PanXapiError

from panos_upgrade.direct_firewall_client import DirectFirewallClient
from panos_upgrade.panorama_client import PanoramaClient
from tests.helpers import MockPanXapi
from tests.helpers.xml_loader import generate_software_info_response


class TestDirectFirewallSoftwareInfoParsing:
    """Test software info parsing in DirectFirewallClient."""
    
    def test_parses_software_versions(self, mock_xapi):
        """Should correctly parse available software versions."""
        mock_xapi.add_response(
            "request.system.software.info",
            generate_software_info_response(
                versions=[
                    {"version": "10.1.0", "downloaded": "yes", "current": "yes"},
                    {"version": "10.2.0", "downloaded": "yes", "current": "no"},
                    {"version": "11.0.0", "downloaded": "no", "current": "no"},
                ],
                current_version="10.1.0"
            )
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.get_software_info()
        
        assert "versions" in result
        assert len(result["versions"]) == 3
        
        # Check first version
        v1 = result["versions"][0]
        assert v1["version"] == "10.1.0"
        assert v1["downloaded"] == "yes"
        assert v1["current"] == "yes"
    
    def test_get_downloaded_versions(self, mock_xapi):
        """Should return dictionary of downloaded versions."""
        mock_xapi.add_response(
            "request.system.software.info",
            generate_software_info_response(
                versions=[
                    {"version": "10.1.0", "downloaded": "yes", "current": "yes"},
                    {"version": "10.2.0", "downloaded": "yes", "current": "no"},
                    {"version": "11.0.0", "downloaded": "no", "current": "no"},
                ]
            )
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.get_downloaded_versions()
        
        assert "10.1.0" in result
        assert result["10.1.0"]["downloaded"] == True
        assert result["10.1.0"]["current"] == True
        
        assert "10.2.0" in result
        assert result["10.2.0"]["downloaded"] == True
        assert result["10.2.0"]["current"] == False
        
        assert "11.0.0" in result
        assert result["11.0.0"]["downloaded"] == False
    
    def test_handles_empty_version_list(self, mock_xapi):
        """Should handle empty version list."""
        mock_xapi.add_response(
            "request.system.software.info",
            '<response status="success"><result></result></response>'
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        result = client.get_software_info()
        
        assert result["versions"] == []
    
    def test_handles_api_error(self, mock_xapi):
        """Should raise exception on API error."""
        mock_xapi.add_response(
            "request.system.software.info",
            '<response status="error"><msg><line>Command failed</line></msg></response>'
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        with pytest.raises(PanXapiError):
            client.get_software_info()


class TestPanoramaClientSoftwareInfoParsing:
    """Test software info parsing in PanoramaClient."""
    
    def test_parses_software_versions(self, mock_xapi, test_config):
        """Should correctly parse software versions via Panorama."""
        mock_xapi.add_response(
            "request.system.software.info",
            generate_software_info_response(
                versions=[
                    {"version": "10.1.0", "downloaded": "yes", "current": "yes"},
                    {"version": "11.0.0", "downloaded": "no", "current": "no"},
                ]
            )
        )
        
        client = PanoramaClient(config=test_config, xapi=mock_xapi)
        
        result = client.get_software_info("001234567890")
        
        assert "versions" in result
        assert len(result["versions"]) == 2


class TestVersionDownloadedCheck:
    """Test checking if specific version is downloaded."""
    
    def test_version_is_downloaded(self, mock_xapi):
        """Should correctly identify downloaded version."""
        mock_xapi.add_response(
            "request.system.software.info",
            generate_software_info_response(
                versions=[
                    {"version": "10.1.0", "downloaded": "yes", "current": "yes"},
                    {"version": "10.2.0", "downloaded": "yes", "current": "no"},
                    {"version": "11.0.0", "downloaded": "no", "current": "no"},
                ]
            )
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        versions = client.get_downloaded_versions()
        
        # 10.2.0 is downloaded
        assert versions.get("10.2.0", {}).get("downloaded") == True
        
        # 11.0.0 is not downloaded
        assert versions.get("11.0.0", {}).get("downloaded") == False
    
    def test_version_not_in_list(self, mock_xapi):
        """Should handle version not in list."""
        mock_xapi.add_response(
            "request.system.software.info",
            generate_software_info_response(
                versions=[
                    {"version": "10.1.0", "downloaded": "yes", "current": "yes"},
                ]
            )
        )
        
        client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        versions = client.get_downloaded_versions()
        
        # Version not in list should not be in result
        assert "99.0.0" not in versions

