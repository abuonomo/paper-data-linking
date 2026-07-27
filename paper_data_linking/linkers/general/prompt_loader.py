"""
Simple prompt loader for XML templates with Jinja rendering
"""
from functools import lru_cache
from pathlib import Path
from jinja2 import Environment, BaseLoader
import xml.etree.ElementTree as ET
from typing import Tuple


@lru_cache(maxsize=None)
def _load_template_files(template_name: str) -> Tuple[str, str]:
    """Read + cache the raw template files (they are static; re-reading them from
    disk on every LLM call is measurable overhead in replay-heavy batch runs)."""
    prompts_dir = Path(__file__).parent / "prompts"
    template_dir = prompts_dir / template_name
    with open(template_dir / "system.xml", 'r', encoding='utf-8') as f:
        system_content = f.read()
    with open(template_dir / "user.xml", 'r', encoding='utf-8') as f:
        user_content = f.read()
    return system_content, user_content


def load_and_render_prompt(template_name: str, **kwargs) -> Tuple[str, str]:
    """Load system and user XML templates, render with Jinja, and preserve XML structure"""
    system_content, user_content = _load_template_files(template_name)
    
    # Use Jinja2 Environment with autoescape for XML safety
    env = Environment(autoescape=True)
    
    # Render templates with variables
    system_template = env.from_string(system_content)
    user_template = env.from_string(user_content)
    
    system_rendered = system_template.render(**kwargs)
    user_rendered = user_template.render(**kwargs)
    
    # Parse XML and extract content, preserving XML structure
    system_root = ET.fromstring(system_rendered)
    user_root = ET.fromstring(user_rendered)
    
    # Get XML content as string, preserving structure
    system_msg = ET.tostring(system_root, encoding='unicode', method='xml').strip()
    user_msg = ET.tostring(user_root, encoding='unicode', method='xml').strip()
    
    # Remove XML declaration if present
    if system_msg.startswith('<?xml'):
        system_msg = system_msg.split('?>', 1)[1].strip()
    if user_msg.startswith('<?xml'):
        user_msg = user_msg.split('?>', 1)[1].strip()
    
    return system_msg, user_msg

