"""Tests for pre-flight and post-flight validation."""

import pytest
from unittest.mock import MagicMock, patch

from panos_upgrade.validation import ValidationSystem
from panos_upgrade.models import ValidationMetrics
from panos_upgrade.panorama_client import PanoramaClient
from panos_upgrade.direct_firewall_client import DirectFirewallClient
from tests.helpers import MockPanXapi
from tests.helpers.xml_loader import (
    generate_disk_space_response,
    generate_session_info_response,
    generate_routing_table_response,
    generate_arp_table_response,
)


class TestPreFlightValidation:
    """Test pre-flight validation checks."""
    
    @pytest.fixture
    def validation_system(self, mock_xapi, test_config, test_work_dir):
        """Create validation system with mocked panorama client."""
        panorama = PanoramaClient(config=test_config, xapi=mock_xapi)
        return ValidationSystem(test_config, panorama)
    
    def test_pre_flight_passes_with_sufficient_disk(self, mock_xapi, validation_system):
        """Should pass pre-flight when disk space is sufficient."""
        # Mock all required responses
        mock_xapi.add_response(
            "show.session.info",
            generate_session_info_response(tcp_sessions=1000)
        )
        mock_xapi.add_response(
            "show.routing.route",
            generate_routing_table_response()
        )
        mock_xapi.add_response(
            "show.arp",
            generate_arp_table_response()
        )
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=15.0)
        )
        
        passed, metrics, error = validation_system.run_pre_flight_validation("001234567890")
        
        assert passed == True
        assert not error  # Empty string or None
        assert metrics.disk_available_gb == 15.0
    
    def test_pre_flight_fails_with_insufficient_disk(self, mock_xapi, validation_system, test_config):
        """Should fail pre-flight when disk space is insufficient."""
        # Set minimum disk requirement
        test_config._config["validation"]["min_disk_gb"] = 10.0
        
        mock_xapi.add_response(
            "show.session.info",
            generate_session_info_response(tcp_sessions=1000)
        )
        mock_xapi.add_response(
            "show.routing.route",
            generate_routing_table_response()
        )
        mock_xapi.add_response(
            "show.arp",
            generate_arp_table_response()
        )
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=5.0)  # Less than 10.0 required
        )
        
        passed, metrics, error = validation_system.run_pre_flight_validation("001234567890")
        
        assert passed == False
        assert "disk space" in error.lower()
    
    def test_pre_flight_collects_route_count(self, mock_xapi, validation_system):
        """Should collect route count in pre-flight."""
        routes = [
            {"destination": "0.0.0.0/0", "nexthop": "10.0.0.1", "interface": "eth1/1", "metric": "10"},
            {"destination": "10.0.0.0/8", "nexthop": "10.0.0.1", "interface": "eth1/1", "metric": "10"},
            {"destination": "192.168.0.0/16", "nexthop": "10.0.1.1", "interface": "eth1/2", "metric": "10"},
        ]
        
        mock_xapi.add_response(
            "show.session.info",
            generate_session_info_response()
        )
        mock_xapi.add_response(
            "show.routing.route",
            generate_routing_table_response(routes=routes)
        )
        mock_xapi.add_response(
            "show.arp",
            generate_arp_table_response()
        )
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=15.0)
        )
        
        passed, metrics, error = validation_system.run_pre_flight_validation("001234567890")
        
        assert passed == True
        assert metrics.route_count == 3
    
    def test_pre_flight_collects_arp_count(self, mock_xapi, validation_system):
        """Should collect ARP entry count in pre-flight."""
        arp_entries = [
            {"ip": "10.0.0.1", "mac": "00:11:22:33:44:55", "interface": "eth1/1"},
            {"ip": "10.0.0.2", "mac": "00:11:22:33:44:56", "interface": "eth1/1"},
        ]
        
        mock_xapi.add_response(
            "show.session.info",
            generate_session_info_response()
        )
        mock_xapi.add_response(
            "show.routing.route",
            generate_routing_table_response()
        )
        mock_xapi.add_response(
            "show.arp",
            generate_arp_table_response(entries=arp_entries)
        )
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=15.0)
        )
        
        passed, metrics, error = validation_system.run_pre_flight_validation("001234567890")
        
        assert passed == True
        assert metrics.arp_count == 2


class TestMetricsComparison:
    """Test metrics comparison logic."""
    
    @pytest.fixture
    def validation_system(self, mock_xapi, test_config, test_work_dir):
        """Create validation system with mocked panorama client."""
        panorama = PanoramaClient(config=test_config, xapi=mock_xapi)
        return ValidationSystem(test_config, panorama)
    
    def test_session_count_within_margin(self, validation_system):
        """Should pass when session count is within configured margin."""
        # Pre-flight: 1000 sessions
        # Post-flight: 950 sessions (5% decrease, within default 5% margin)
        
        pre_metrics = ValidationMetrics(
            tcp_sessions=1000,
            route_count=10,
            routes=[],
            arp_count=5,
            arp_entries=[],
            disk_available_gb=15.0
        )
        
        post_metrics = ValidationMetrics(
            tcp_sessions=950,
            route_count=10,
            routes=[],
            arp_count=5,
            arp_entries=[],
            disk_available_gb=12.0
        )
        
        result = validation_system._compare_metrics(pre_metrics, post_metrics)
        
        assert result["tcp_sessions"].within_margin == True
    
    def test_session_count_outside_margin(self, validation_system, test_config):
        """Should flag when session count is outside configured margin."""
        # Set a tight margin
        test_config._config["validation"]["tcp_session_margin"] = 1.0  # 1%
        
        pre_metrics = ValidationMetrics(
            tcp_sessions=1000,
            route_count=10,
            routes=[],
            arp_count=5,
            arp_entries=[],
            disk_available_gb=15.0
        )
        
        post_metrics = ValidationMetrics(
            tcp_sessions=800,  # 20% decrease, outside 1% margin
            route_count=10,
            routes=[],
            arp_count=5,
            arp_entries=[],
            disk_available_gb=12.0
        )
        
        result = validation_system._compare_metrics(pre_metrics, post_metrics)
        
        assert result["tcp_sessions"].within_margin == False
    
    def test_route_count_comparison(self, validation_system):
        """Should compare route counts and detect differences."""
        pre_metrics = ValidationMetrics(
            tcp_sessions=1000,
            route_count=10,
            routes=[
                {"destination": "10.0.0.0/8", "nexthop": "10.0.0.1", "interface": "eth1/1"}
            ],
            arp_count=5,
            arp_entries=[],
            disk_available_gb=15.0
        )
        
        post_metrics = ValidationMetrics(
            tcp_sessions=1000,
            route_count=11,  # One route added
            routes=[
                {"destination": "10.0.0.0/8", "nexthop": "10.0.0.1", "interface": "eth1/1"},
                {"destination": "172.16.0.0/12", "nexthop": "10.0.0.2", "interface": "eth1/2"}
            ],
            arp_count=5,
            arp_entries=[],
            disk_available_gb=12.0
        )
        
        result = validation_system._compare_metrics(pre_metrics, post_metrics)
        
        assert result["routes"].difference == 1


class TestDirectValidation:
    """Test validation using direct firewall connections."""
    
    @pytest.fixture
    def validation_system(self, mock_xapi, test_config, test_work_dir):
        """Create validation system with mocked panorama client."""
        panorama = PanoramaClient(config=test_config, xapi=mock_xapi)
        return ValidationSystem(test_config, panorama)
    
    def test_pre_flight_direct_passes_with_sufficient_disk(self, mock_xapi, validation_system, test_config):
        """Should pass pre-flight via direct connection when disk space is sufficient."""
        # Create a direct firewall client with mock
        firewall_client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        # Mock all required responses for direct connection
        mock_xapi.add_response(
            "show.session.info",
            generate_session_info_response(tcp_sessions=1000)
        )
        mock_xapi.add_response(
            "show.routing.route",
            generate_routing_table_response()
        )
        mock_xapi.add_response(
            "show.arp",
            generate_arp_table_response()
        )
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=15.0)
        )
        
        passed, metrics, error = validation_system.run_pre_flight_validation_direct(
            "001234567890", firewall_client
        )
        
        assert passed == True
        assert not error
        assert metrics.disk_available_gb == 15.0
    
    def test_pre_flight_direct_fails_with_insufficient_disk(self, mock_xapi, validation_system, test_config):
        """Should fail pre-flight via direct connection when disk space is insufficient."""
        # Set minimum disk requirement
        test_config._config["validation"]["min_disk_gb"] = 10.0
        
        firewall_client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        mock_xapi.add_response(
            "show.session.info",
            generate_session_info_response(tcp_sessions=1000)
        )
        mock_xapi.add_response(
            "show.routing.route",
            generate_routing_table_response()
        )
        mock_xapi.add_response(
            "show.arp",
            generate_arp_table_response()
        )
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=5.0)  # Less than 10.0 required
        )
        
        passed, metrics, error = validation_system.run_pre_flight_validation_direct(
            "001234567890", firewall_client
        )
        
        assert passed == False
        assert "disk space" in error.lower()
    
    def test_post_flight_direct_compares_metrics(self, mock_xapi, validation_system):
        """Should run post-flight validation via direct connection and compare metrics."""
        firewall_client = DirectFirewallClient(
            mgmt_ip="10.0.0.1",
            username="test",
            password="test",
            xapi=mock_xapi
        )
        
        # Pre-flight metrics (stored earlier)
        # Note: tcp_sessions comes from num-active which includes TCP+UDP+ICMP
        # Default generate_session_info_response gives: tcp=1000 + udp=500 + icmp=50 = 1550
        # Default generate_routing_table_response gives 3 routes
        # Default generate_arp_table_response gives 3 entries
        pre_metrics = ValidationMetrics(
            tcp_sessions=1550,  # Matches default total from generate_session_info_response
            route_count=3,      # Matches default from generate_routing_table_response
            routes=[],
            arp_count=3,        # Matches default from generate_arp_table_response
            arp_entries=[],
            disk_available_gb=15.0
        )
        
        # Mock post-flight responses - use default values which match pre_metrics
        mock_xapi.add_response(
            "show.session.info",
            generate_session_info_response()  # Default: 1000+500+50 = 1550 total
        )
        mock_xapi.add_response(
            "show.routing.route",
            generate_routing_table_response()  # Default: 3 routes
        )
        mock_xapi.add_response(
            "show.arp",
            generate_arp_table_response()  # Default: 3 entries
        )
        mock_xapi.add_response(
            "show.system.disk-space",
            generate_disk_space_response(panrepo_available_gb=12.0)
        )
        
        passed, result = validation_system.run_post_flight_validation_direct(
            "001234567890", firewall_client, pre_metrics
        )
        
        assert passed == True
        assert result.post_flight is not None
        assert result.comparison is not None
