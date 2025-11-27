"""Mock PanXapi class for testing without real API connections."""

import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from .command_matcher import CommandMatcher


@dataclass
class APICall:
    """Record of an API call made to the mock."""
    method: str  # 'op', 'config', etc.
    cmd: str
    kwargs: Dict[str, Any]
    matched_pattern: Optional[str] = None


@dataclass
class MockResponse:
    """A registered mock response."""
    pattern: str
    response_xml: str
    call_count: int = 0
    max_calls: Optional[int] = None  # None = unlimited
    side_effect: Optional[Callable] = None  # Called when matched


class MockPanXapi:
    """
    Mock implementation of pan.xapi.PanXapi for testing.
    
    Allows registering responses for command patterns and tracks all calls made.
    
    Example usage:
        mock = MockPanXapi()
        mock.add_response(
            "show.system.disk-space",
            '<response status="success"><result>...</result></response>'
        )
        
        # Use in client
        client = PanoramaClient(config, xapi=mock)
        result = client.check_disk_space("serial123")
        
        # Verify calls
        mock.assert_called_with("show.system.disk-space")
    """
    
    def __init__(self, hostname: str = "mock-panorama", api_key: str = "mock-key"):
        """
        Initialize mock PanXapi.
        
        Args:
            hostname: Mock hostname (for compatibility)
            api_key: Mock API key (for compatibility)
        """
        self.hostname = hostname
        self.api_key = api_key
        
        self._responses: List[MockResponse] = []
        self._call_history: List[APICall] = []
        self._default_response: Optional[str] = None
        
        # These attributes are set after op() calls, mimicking real PanXapi
        self.element_result: Optional[ET.Element] = None
        self.status: str = "success"
        self.status_detail: Optional[str] = None
    
    def add_response(
        self,
        pattern: str,
        response_xml: str,
        max_calls: Optional[int] = None,
        side_effect: Optional[Callable] = None
    ):
        """
        Register a response for a command pattern.
        
        Args:
            pattern: Command pattern (e.g., "show.system.info")
            response_xml: XML response to return
            max_calls: Maximum times this response can be used (None = unlimited)
            side_effect: Optional function to call when matched
        """
        self._responses.append(MockResponse(
            pattern=pattern,
            response_xml=response_xml,
            max_calls=max_calls,
            side_effect=side_effect
        ))
    
    def add_sequence(self, pattern: str, responses: List[str]):
        """
        Register a sequence of responses for repeated calls.
        
        Each call returns the next response in the sequence.
        After exhausting the sequence, the last response is repeated.
        
        Args:
            pattern: Command pattern
            responses: List of XML responses
        """
        for i, response in enumerate(responses[:-1]):
            self.add_response(pattern, response, max_calls=1)
        # Last response has unlimited calls
        self.add_response(pattern, responses[-1])
    
    def set_default_response(self, response_xml: str):
        """
        Set a default response for unmatched commands.
        
        Args:
            response_xml: Default XML response
        """
        self._default_response = response_xml
    
    def op(self, cmd: str, vsys: Optional[str] = None, extra_qs: Optional[Dict] = None):
        """
        Mock operational command execution.
        
        Args:
            cmd: XML command string
            vsys: Virtual system (ignored in mock)
            extra_qs: Extra query string parameters (e.g., target serial)
        """
        kwargs = {"vsys": vsys, "extra_qs": extra_qs}
        
        # Find matching response
        response_xml = None
        matched_pattern = None
        
        for mock_response in self._responses:
            matches, params = CommandMatcher.match(cmd, mock_response.pattern)
            
            if matches:
                # Check if this response has calls remaining
                if mock_response.max_calls is not None:
                    if mock_response.call_count >= mock_response.max_calls:
                        continue
                
                mock_response.call_count += 1
                response_xml = mock_response.response_xml
                matched_pattern = mock_response.pattern
                
                # Call side effect if registered
                if mock_response.side_effect:
                    mock_response.side_effect(cmd, params, kwargs)
                
                break
        
        # Record the call
        self._call_history.append(APICall(
            method="op",
            cmd=cmd,
            kwargs=kwargs,
            matched_pattern=matched_pattern
        ))
        
        # Use default if no match found
        if response_xml is None:
            if self._default_response:
                response_xml = self._default_response
            else:
                # Simulate error for unmatched command
                self.status = "error"
                self.status_detail = f"No mock response registered for command"
                self.element_result = None
                from pan.xapi import PanXapiError
                raise PanXapiError(f"No mock response for: {cmd[:100]}...")
        
        # Parse response and set attributes
        try:
            root = ET.fromstring(response_xml)
            self.status = root.get("status", "success")
            
            if self.status == "error":
                self.status_detail = root.findtext(".//msg") or root.findtext(".//line") or "Error"
                self.element_result = None
                from pan.xapi import PanXapiError
                raise PanXapiError(self.status_detail)
            
            self.element_result = root.find(".//result")
            self.status_detail = None
            
        except ET.ParseError as e:
            self.status = "error"
            self.status_detail = f"Invalid XML response: {e}"
            self.element_result = None
    
    # Assertion methods for tests
    
    def assert_called(self):
        """Assert that at least one call was made."""
        assert len(self._call_history) > 0, "Expected at least one API call"
    
    def assert_not_called(self):
        """Assert that no calls were made."""
        assert len(self._call_history) == 0, f"Expected no calls, got {len(self._call_history)}"
    
    def assert_called_with(self, pattern: str):
        """
        Assert that a command matching the pattern was called.
        
        Args:
            pattern: Command pattern to check
        """
        for call in self._call_history:
            matches, _ = CommandMatcher.match(call.cmd, pattern)
            if matches:
                return
        
        called_patterns = [c.matched_pattern or "unmatched" for c in self._call_history]
        raise AssertionError(
            f"Expected call matching '{pattern}', got calls: {called_patterns}"
        )
    
    def assert_called_once_with(self, pattern: str):
        """
        Assert that a command matching the pattern was called exactly once.
        
        Args:
            pattern: Command pattern to check
        """
        matching_calls = []
        for call in self._call_history:
            matches, _ = CommandMatcher.match(call.cmd, pattern)
            if matches:
                matching_calls.append(call)
        
        if len(matching_calls) == 0:
            raise AssertionError(f"Expected one call matching '{pattern}', got none")
        if len(matching_calls) > 1:
            raise AssertionError(
                f"Expected one call matching '{pattern}', got {len(matching_calls)}"
            )
    
    def assert_call_count(self, pattern: str, expected_count: int):
        """
        Assert the number of calls matching a pattern.
        
        Args:
            pattern: Command pattern to check
            expected_count: Expected number of calls
        """
        count = 0
        for call in self._call_history:
            matches, _ = CommandMatcher.match(call.cmd, pattern)
            if matches:
                count += 1
        
        assert count == expected_count, (
            f"Expected {expected_count} calls matching '{pattern}', got {count}"
        )
    
    def get_calls(self, pattern: Optional[str] = None) -> List[APICall]:
        """
        Get recorded calls, optionally filtered by pattern.
        
        Args:
            pattern: Optional pattern to filter by
            
        Returns:
            List of matching APICall objects
        """
        if pattern is None:
            return list(self._call_history)
        
        return [
            call for call in self._call_history
            if CommandMatcher.match(call.cmd, pattern)[0]
        ]
    
    def reset(self):
        """Reset call history and response counters."""
        self._call_history.clear()
        for response in self._responses:
            response.call_count = 0
    
    def clear_responses(self):
        """Clear all registered responses."""
        self._responses.clear()
        self._default_response = None

