"""Tests for the command matcher helper."""

import pytest
from tests.helpers.command_matcher import CommandMatcher


class TestCommandMatching:
    """Test XML command pattern matching."""
    
    def test_matches_simple_command(self):
        """Should match simple show command."""
        cmd = "<show><system><info/></system></show>"
        
        matches, params = CommandMatcher.match(cmd, "show.system.info")
        
        assert matches == True
    
    def test_matches_with_prefix(self):
        """Should match when pattern is prefix of command path."""
        cmd = "<show><system><disk-space/></system></show>"
        
        matches, params = CommandMatcher.match(cmd, "show.system")
        
        assert matches == True
    
    def test_no_match_different_command(self):
        """Should not match different command."""
        cmd = "<show><system><info/></system></show>"
        
        matches, params = CommandMatcher.match(cmd, "show.routing.route")
        
        assert matches == False
    
    def test_extracts_parameters(self):
        """Should extract parameters from command."""
        cmd = "<request><system><software><download><version>11.0.0</version></download></software></system></request>"
        
        matches, params = CommandMatcher.match(cmd, "request.system.software.download")
        
        assert matches == True
        assert "request.system.software.download.version" in params
        assert params["request.system.software.download.version"] == "11.0.0"
    
    def test_matches_request_command(self):
        """Should match request commands."""
        cmd = "<request><system><software><info/></software></system></request>"
        
        matches, params = CommandMatcher.match(cmd, "request.system.software.info")
        
        assert matches == True
    
    def test_handles_invalid_xml(self):
        """Should return no match for invalid XML."""
        cmd = "not valid xml"
        
        matches, params = CommandMatcher.match(cmd, "show.system.info")
        
        assert matches == False
        assert params == {}


class TestCommandPath:
    """Test command path extraction."""
    
    def test_extracts_simple_path(self):
        """Should extract simple command path."""
        import xml.etree.ElementTree as ET
        
        element = ET.fromstring("<show><system><info/></system></show>")
        path = CommandMatcher.get_command_path(element)
        
        assert path == ["show", "system", "info"]
    
    def test_extracts_deep_path(self):
        """Should extract deep command path."""
        import xml.etree.ElementTree as ET
        
        element = ET.fromstring(
            "<request><system><software><download><version>11.0.0</version></download></software></system></request>"
        )
        path = CommandMatcher.get_command_path(element)
        
        assert path == ["request", "system", "software", "download", "version"]


class TestMatchesAny:
    """Test matching against multiple patterns."""
    
    def test_matches_first_pattern(self):
        """Should match first matching pattern."""
        cmd = "<show><system><info/></system></show>"
        patterns = ["show.system.info", "show.routing.route"]
        
        matches, pattern, params = CommandMatcher.matches_any(cmd, patterns)
        
        assert matches == True
        assert pattern == "show.system.info"
    
    def test_matches_second_pattern(self):
        """Should match second pattern if first doesn't match."""
        cmd = "<show><routing><route/></routing></show>"
        patterns = ["show.system.info", "show.routing.route"]
        
        matches, pattern, params = CommandMatcher.matches_any(cmd, patterns)
        
        assert matches == True
        assert pattern == "show.routing.route"
    
    def test_no_match_any(self):
        """Should return no match if no patterns match."""
        cmd = "<show><arp><entry/></arp></show>"
        patterns = ["show.system.info", "show.routing.route"]
        
        matches, pattern, params = CommandMatcher.matches_any(cmd, patterns)
        
        assert matches == False
        assert pattern == ""

