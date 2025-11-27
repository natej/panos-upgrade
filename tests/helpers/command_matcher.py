"""Command matcher for structured XML command matching."""

import xml.etree.ElementTree as ET
from typing import Optional, List, Tuple
import re


class CommandMatcher:
    """
    Matches PAN-OS XML commands based on structure rather than exact string match.
    
    This allows tests to match commands regardless of whitespace or attribute ordering.
    """
    
    @staticmethod
    def parse_command(cmd: str) -> Optional[ET.Element]:
        """
        Parse XML command string into ElementTree.
        
        Args:
            cmd: XML command string
            
        Returns:
            Parsed Element or None if parsing fails
        """
        try:
            return ET.fromstring(cmd)
        except ET.ParseError:
            return None
    
    @staticmethod
    def get_command_path(element: ET.Element) -> List[str]:
        """
        Extract the command path from an XML element.
        
        For example, <show><system><info/></system></show> returns:
        ['show', 'system', 'info']
        
        Args:
            element: XML element
            
        Returns:
            List of tag names forming the command path
        """
        path = [element.tag]
        
        # Traverse down to leaf nodes
        current = element
        while len(current) > 0:
            # Take the first child (commands are typically linear)
            child = current[0]
            path.append(child.tag)
            current = child
        
        return path
    
    @staticmethod
    def extract_parameters(element: ET.Element) -> dict:
        """
        Extract parameters from command XML.
        
        Parameters can be:
        - Text content of leaf elements (e.g., <version>10.1.0</version>)
        - Attributes on elements
        
        Args:
            element: XML element
            
        Returns:
            Dictionary of parameter names to values
        """
        params = {}
        
        def traverse(el: ET.Element, prefix: str = ""):
            # Add attributes
            for attr, value in el.attrib.items():
                key = f"{prefix}{el.tag}.{attr}" if prefix else f"{el.tag}.{attr}"
                params[key] = value
            
            # If leaf node with text, add the text
            if len(el) == 0 and el.text and el.text.strip():
                key = f"{prefix}{el.tag}" if prefix else el.tag
                params[key] = el.text.strip()
            
            # Recurse into children
            for child in el:
                new_prefix = f"{prefix}{el.tag}." if prefix else f"{el.tag}."
                traverse(child, new_prefix)
        
        traverse(element)
        return params
    
    @classmethod
    def match(cls, cmd: str, pattern: str) -> Tuple[bool, dict]:
        """
        Check if a command matches a pattern.
        
        Pattern format examples:
        - "show.system.info" - matches <show><system><info/></system></show>
        - "request.system.software.download" - matches download command
        - "show.system.disk-space" - matches disk space command
        
        Args:
            cmd: XML command string
            pattern: Dot-separated command path pattern
            
        Returns:
            Tuple of (matches: bool, parameters: dict)
        """
        element = cls.parse_command(cmd)
        if element is None:
            return False, {}
        
        path = cls.get_command_path(element)
        path_str = ".".join(path)
        
        # Check if pattern matches (pattern can be prefix)
        if path_str.startswith(pattern) or path_str == pattern:
            params = cls.extract_parameters(element)
            return True, params
        
        return False, {}
    
    @classmethod
    def matches_any(cls, cmd: str, patterns: List[str]) -> Tuple[bool, str, dict]:
        """
        Check if command matches any of the given patterns.
        
        Args:
            cmd: XML command string
            patterns: List of patterns to check
            
        Returns:
            Tuple of (matches: bool, matched_pattern: str, parameters: dict)
        """
        for pattern in patterns:
            matches, params = cls.match(cmd, pattern)
            if matches:
                return True, pattern, params
        
        return False, "", {}

