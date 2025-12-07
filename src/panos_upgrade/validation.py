"""Pre-flight and post-flight validation system."""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from panos_upgrade.config import Config
from panos_upgrade.logging_config import get_logger
from panos_upgrade.models import ValidationMetrics, ValidationResult, MetricComparison
from panos_upgrade.panorama_client import PanoramaClient
from panos_upgrade.direct_firewall_client import DirectFirewallClient
from panos_upgrade.utils.file_ops import atomic_write_json
from panos_upgrade import constants


class ValidationSystem:
    """System for pre-flight and post-flight validation."""
    
    def __init__(self, config: Config, panorama_client: PanoramaClient):
        """
        Initialize validation system.
        
        Args:
            config: Configuration instance
            panorama_client: Panorama client instance
        """
        self.config = config
        self.panorama = panorama_client
        self.logger = get_logger("panos_upgrade.validation")
    
    def run_pre_flight_validation(self, serial: str) -> Tuple[bool, ValidationMetrics, str]:
        """
        Run pre-flight validation checks.
        
        Args:
            serial: Device serial number
            
        Returns:
            Tuple of (passed, metrics, error_message)
        """
        self.logger.info(f"Running pre-flight validation for {serial}")
        
        try:
            # Get system metrics
            metrics_data = self.panorama.get_system_metrics(serial)
            
            metrics = ValidationMetrics(
                tcp_sessions=metrics_data.get('tcp_sessions', 0),
                route_count=metrics_data.get('route_count', 0),
                routes=metrics_data.get('routes', []),
                arp_count=metrics_data.get('arp_count', 0),
                arp_entries=metrics_data.get('arp_entries', []),
                disk_available_gb=metrics_data.get('disk_available_gb', 0.0)
            )
            
            # Check disk space requirement
            min_disk_gb = self.config.min_disk_gb
            if metrics.disk_available_gb < min_disk_gb:
                error_msg = (
                    f"Insufficient disk space: {metrics.disk_available_gb:.2f} GB available, "
                    f"{min_disk_gb:.2f} GB required"
                )
                self.logger.error(f"Pre-flight validation failed for {serial}: {error_msg}")
                
                # Save pre-flight metrics even on failure
                self._save_pre_flight_metrics(serial, metrics)
                
                return False, metrics, error_msg
            
            # Save pre-flight metrics
            self._save_pre_flight_metrics(serial, metrics)
            
            self.logger.info(
                f"Pre-flight validation passed for {serial}: "
                f"{metrics.tcp_sessions} sessions, {metrics.route_count} routes, "
                f"{metrics.arp_count} ARP entries, {metrics.disk_available_gb:.2f} GB disk"
            )
            
            return True, metrics, ""
            
        except Exception as e:
            error_msg = f"Pre-flight validation error: {str(e)}"
            self.logger.error(f"Pre-flight validation failed for {serial}: {error_msg}", exc_info=True)
            # Return empty metrics on exception
            empty_metrics = ValidationMetrics(
                tcp_sessions=0,
                route_count=0,
                routes=[],
                arp_count=0,
                arp_entries=[],
                disk_available_gb=0.0
            )
            return False, empty_metrics, error_msg
    
    def run_pre_flight_validation_direct(
        self,
        serial: str,
        firewall_client: DirectFirewallClient
    ) -> Tuple[bool, ValidationMetrics, str]:
        """
        Run pre-flight validation checks using direct firewall connection.
        
        Includes retry logic for connection errors with configurable backoff.
        
        Args:
            serial: Device serial number
            firewall_client: Direct firewall client instance
            
        Returns:
            Tuple of (passed, metrics, error_message)
        """
        self.logger.info(f"Running pre-flight validation for {serial} (direct connection)")
        
        retry_attempts = self.config.validation_retry_attempts
        retry_delay = self.config.validation_retry_delay
        retry_backoff = self.config.validation_retry_backoff
        
        last_error = ""
        current_delay = retry_delay
        
        for attempt in range(1, retry_attempts + 1):
            try:
                # Get system metrics via direct connection
                metrics_data = firewall_client.get_system_metrics()
                
                metrics = ValidationMetrics(
                    tcp_sessions=metrics_data.get('tcp_sessions', 0),
                    route_count=metrics_data.get('route_count', 0),
                    routes=metrics_data.get('routes', []),
                    arp_count=metrics_data.get('arp_count', 0),
                    arp_entries=metrics_data.get('arp_entries', []),
                    disk_available_gb=metrics_data.get('disk_available_gb', 0.0)
                )
                
                # Check disk space requirement
                min_disk_gb = self.config.min_disk_gb
                if metrics.disk_available_gb < min_disk_gb:
                    error_msg = (
                        f"Insufficient disk space: {metrics.disk_available_gb:.2f} GB available, "
                        f"{min_disk_gb:.2f} GB required"
                    )
                    self.logger.error(f"Pre-flight validation failed for {serial}: {error_msg}")
                    
                    # Save pre-flight metrics even on failure
                    self._save_pre_flight_metrics(serial, metrics)
                    
                    return False, metrics, error_msg
                
                # Save pre-flight metrics
                self._save_pre_flight_metrics(serial, metrics)
                
                self.logger.info(
                    f"Pre-flight validation passed for {serial}: "
                    f"{metrics.tcp_sessions} sessions, {metrics.route_count} routes, "
                    f"{metrics.arp_count} ARP entries, {metrics.disk_available_gb:.2f} GB disk"
                )
                
                return True, metrics, ""
                
            except Exception as e:
                last_error = str(e)
                if attempt < retry_attempts:
                    self.logger.warning(
                        f"Pre-flight validation attempt {attempt}/{retry_attempts} failed for {serial}: {last_error}. "
                        f"Retrying in {current_delay} seconds..."
                    )
                    time.sleep(current_delay)
                    current_delay = int(current_delay * retry_backoff)
                else:
                    self.logger.error(
                        f"Pre-flight validation failed for {serial} after {retry_attempts} attempts: {last_error}",
                        exc_info=True
                    )
        
        # All retries exhausted
        error_msg = f"Pre-flight validation error after {retry_attempts} attempts: {last_error}"
        empty_metrics = ValidationMetrics(
            tcp_sessions=0,
            route_count=0,
            routes=[],
            arp_count=0,
            arp_entries=[],
            disk_available_gb=0.0
        )
        return False, empty_metrics, error_msg
    
    def run_post_flight_validation(
        self,
        serial: str,
        pre_flight_metrics: ValidationMetrics
    ) -> Tuple[bool, ValidationResult]:
        """
        Run post-flight validation and compare with pre-flight.
        
        Args:
            serial: Device serial number
            pre_flight_metrics: Pre-flight metrics for comparison
            
        Returns:
            Tuple of (passed, validation_result)
        """
        self.logger.info(f"Running post-flight validation for {serial}")
        
        try:
            # Get current system metrics
            metrics_data = self.panorama.get_system_metrics(serial)
            
            post_flight_metrics = ValidationMetrics(
                tcp_sessions=metrics_data.get('tcp_sessions', 0),
                route_count=metrics_data.get('route_count', 0),
                routes=metrics_data.get('routes', []),
                arp_count=metrics_data.get('arp_count', 0),
                arp_entries=metrics_data.get('arp_entries', []),
                disk_available_gb=metrics_data.get('disk_available_gb', 0.0)
            )
            
            # Compare metrics
            comparison = self._compare_metrics(pre_flight_metrics, post_flight_metrics)
            
            # Determine if validation passed
            validation_passed = all(
                comp.within_margin for comp in comparison.values()
            )
            
            # Create validation result
            result = ValidationResult(
                serial=serial,
                timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                pre_flight=pre_flight_metrics,
                post_flight=post_flight_metrics,
                comparison=comparison,
                validation_passed=validation_passed
            )
            
            # Save post-flight validation result
            self._save_post_flight_validation(serial, result)
            
            if validation_passed:
                self.logger.info(f"Post-flight validation passed for {serial}")
            else:
                self.logger.warning(f"Post-flight validation failed for {serial}")
                self._log_validation_differences(serial, comparison)
            
            return validation_passed, result
            
        except Exception as e:
            self.logger.error(f"Post-flight validation error for {serial}: {e}", exc_info=True)
            
            # Create failed result
            result = ValidationResult(
                serial=serial,
                timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                pre_flight=pre_flight_metrics,
                validation_passed=False
            )
            
            return False, result
    
    def run_post_flight_validation_direct(
        self,
        serial: str,
        firewall_client: DirectFirewallClient,
        pre_flight_metrics: ValidationMetrics
    ) -> Tuple[bool, ValidationResult]:
        """
        Run post-flight validation using direct firewall connection.
        
        Includes retry logic for connection errors with configurable backoff.
        
        Args:
            serial: Device serial number
            firewall_client: Direct firewall client instance
            pre_flight_metrics: Pre-flight metrics for comparison
            
        Returns:
            Tuple of (passed, validation_result)
        """
        self.logger.info(f"Running post-flight validation for {serial} (direct connection)")
        
        retry_attempts = self.config.validation_retry_attempts
        retry_delay = self.config.validation_retry_delay
        retry_backoff = self.config.validation_retry_backoff
        
        last_error = ""
        current_delay = retry_delay
        
        for attempt in range(1, retry_attempts + 1):
            try:
                # Get current system metrics via direct connection
                metrics_data = firewall_client.get_system_metrics()
                
                post_flight_metrics = ValidationMetrics(
                    tcp_sessions=metrics_data.get('tcp_sessions', 0),
                    route_count=metrics_data.get('route_count', 0),
                    routes=metrics_data.get('routes', []),
                    arp_count=metrics_data.get('arp_count', 0),
                    arp_entries=metrics_data.get('arp_entries', []),
                    disk_available_gb=metrics_data.get('disk_available_gb', 0.0)
                )
                
                # Compare metrics
                comparison = self._compare_metrics(pre_flight_metrics, post_flight_metrics)
                
                # Determine if validation passed
                validation_passed = all(
                    comp.within_margin for comp in comparison.values()
                )
                
                # Create validation result
                result = ValidationResult(
                    serial=serial,
                    timestamp=datetime.now(timezone.utc).isoformat() + "Z",
                    pre_flight=pre_flight_metrics,
                    post_flight=post_flight_metrics,
                    comparison=comparison,
                    validation_passed=validation_passed
                )
                
                # Save post-flight validation result
                self._save_post_flight_validation(serial, result)
                
                if validation_passed:
                    self.logger.info(f"Post-flight validation passed for {serial}")
                else:
                    self.logger.warning(f"Post-flight validation failed for {serial}")
                    self._log_validation_differences(serial, comparison)
                
                return validation_passed, result
                
            except Exception as e:
                last_error = str(e)
                if attempt < retry_attempts:
                    self.logger.warning(
                        f"Post-flight validation attempt {attempt}/{retry_attempts} failed for {serial}: {last_error}. "
                        f"Retrying in {current_delay} seconds..."
                    )
                    time.sleep(current_delay)
                    current_delay = int(current_delay * retry_backoff)
                else:
                    self.logger.error(
                        f"Post-flight validation failed for {serial} after {retry_attempts} attempts: {last_error}",
                        exc_info=True
                    )
        
        # All retries exhausted - create failed result
        result = ValidationResult(
            serial=serial,
            timestamp=datetime.now(timezone.utc).isoformat() + "Z",
            pre_flight=pre_flight_metrics,
            validation_passed=False
        )
        
        return False, result
    
    def _compare_metrics(
        self,
        pre: ValidationMetrics,
        post: ValidationMetrics
    ) -> Dict[str, MetricComparison]:
        """
        Compare pre-flight and post-flight metrics.
        
        Args:
            pre: Pre-flight metrics
            post: Post-flight metrics
            
        Returns:
            Dictionary of metric comparisons
        """
        comparison = {}
        
        # TCP sessions comparison
        tcp_diff = post.tcp_sessions - pre.tcp_sessions
        tcp_pct = (tcp_diff / pre.tcp_sessions * 100) if pre.tcp_sessions > 0 else 0
        tcp_margin = self.config.get("validation.tcp_session_margin", 5.0)
        
        comparison['tcp_sessions'] = MetricComparison(
            difference=tcp_diff,
            percentage=tcp_pct,
            within_margin=abs(tcp_pct) <= tcp_margin
        )
        
        # Routes comparison
        route_diff = post.route_count - pre.route_count
        route_margin = self.config.get("validation.route_margin", 0.0)
        
        # Find added and removed routes
        pre_routes_set = {self._route_key(r) for r in pre.routes}
        post_routes_set = {self._route_key(r) for r in post.routes}
        
        added_routes = [
            r for r in post.routes
            if self._route_key(r) not in pre_routes_set
        ]
        removed_routes = [
            r for r in pre.routes
            if self._route_key(r) not in post_routes_set
        ]
        
        comparison['routes'] = MetricComparison(
            difference=route_diff,
            percentage=0.0,
            within_margin=abs(route_diff) <= route_margin,
            added=added_routes,
            removed=removed_routes
        )
        
        # ARP entries comparison
        arp_diff = post.arp_count - pre.arp_count
        arp_margin = self.config.get("validation.arp_margin", 0.0)
        
        # Find added and removed ARP entries
        pre_arp_set = {self._arp_key(a) for a in pre.arp_entries}
        post_arp_set = {self._arp_key(a) for a in post.arp_entries}
        
        added_arp = [
            a for a in post.arp_entries
            if self._arp_key(a) not in pre_arp_set
        ]
        removed_arp = [
            a for a in pre.arp_entries
            if self._arp_key(a) not in post_arp_set
        ]
        
        comparison['arp_entries'] = MetricComparison(
            difference=arp_diff,
            percentage=0.0,
            within_margin=abs(arp_diff) <= arp_margin,
            added=added_arp,
            removed=removed_arp
        )
        
        return comparison
    
    def _route_key(self, route: Dict[str, str]) -> str:
        """Generate unique key for route."""
        return f"{route.get('destination', '')}|{route.get('gateway', '')}|{route.get('interface', '')}"
    
    def _arp_key(self, arp: Dict[str, str]) -> str:
        """Generate unique key for ARP entry."""
        return f"{arp.get('ip', '')}|{arp.get('mac', '')}"
    
    def _save_pre_flight_metrics(self, serial: str, metrics: ValidationMetrics):
        """Save pre-flight metrics to file."""
        pre_flight_dir = self.config.get_path(constants.DIR_VALIDATION_PRE)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_path = pre_flight_dir / f"{serial}_{timestamp}.json"
        
        data = {
            "serial": serial,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "metrics": metrics.to_dict()
        }
        
        atomic_write_json(file_path, data)
        self.logger.debug(f"Saved pre-flight metrics for {serial}")
    
    def _save_post_flight_validation(self, serial: str, result: ValidationResult):
        """Save post-flight validation result to file."""
        post_flight_dir = self.config.get_path(constants.DIR_VALIDATION_POST)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_path = post_flight_dir / f"{serial}_{timestamp}.json"
        
        atomic_write_json(file_path, result.to_dict())
        self.logger.debug(f"Saved post-flight validation for {serial}")
    
    def _log_validation_differences(self, serial: str, comparison: Dict[str, MetricComparison]):
        """Log validation differences for admin review."""
        self.logger.info(f"Validation differences for {serial}:")
        
        # TCP sessions
        tcp = comparison.get('tcp_sessions')
        if tcp and not tcp.within_margin:
            self.logger.warning(
                f"  TCP sessions: {tcp.difference:+d} ({tcp.percentage:+.2f}%) - "
                f"OUTSIDE MARGIN"
            )
        
        # Routes
        routes = comparison.get('routes')
        if routes:
            if routes.added:
                self.logger.info(f"  Routes added: {len(routes.added)}")
                for route in routes.added[:5]:  # Log first 5
                    self.logger.info(f"    + {route}")
            if routes.removed:
                self.logger.warning(f"  Routes removed: {len(routes.removed)}")
                for route in routes.removed[:5]:  # Log first 5
                    self.logger.warning(f"    - {route}")
        
        # ARP entries
        arp = comparison.get('arp_entries')
        if arp:
            if arp.added:
                self.logger.info(f"  ARP entries added: {len(arp.added)}")
            if arp.removed:
                self.logger.warning(f"  ARP entries removed: {len(arp.removed)}")
    
    def get_latest_pre_flight_metrics(self, serial: str) -> Optional[ValidationMetrics]:
        """
        Get the latest pre-flight metrics for a device.
        
        Args:
            serial: Device serial number
            
        Returns:
            ValidationMetrics or None if not found
        """
        pre_flight_dir = self.config.get_path(constants.DIR_VALIDATION_PRE)
        
        # Find latest file for this serial
        files = sorted(pre_flight_dir.glob(f"{serial}_*.json"), reverse=True)
        
        if not files:
            return None
        
        try:
            from panos_upgrade.utils.file_ops import read_json
            data = read_json(files[0])
            metrics_data = data.get('metrics', {})
            return ValidationMetrics(**metrics_data)
        except Exception as e:
            self.logger.error(f"Failed to load pre-flight metrics for {serial}: {e}")
            return None

