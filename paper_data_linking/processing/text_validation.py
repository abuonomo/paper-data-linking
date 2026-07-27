"""Text validation utilities for paper processing"""

from typing import Tuple, Optional
from ..config.settings import settings


class TextValidationError(Exception):
    """Raised when text fails validation checks"""
    pass


class TextValidationWarning(UserWarning):
    """Warning for text that passes validation but may be problematic"""
    pass


def validate_text_length(text: str, paper_id: Optional[str] = None) -> Tuple[bool, str]:
    """
    Validate text length against configured limits.
    
    Args:
        text: The text to validate
        paper_id: Optional paper identifier for error messages
        
    Returns:
        Tuple of (is_valid, message)
        
    Raises:
        TextValidationError: If text exceeds hard limit
    """
    if not text:
        return True, "Text is empty"
        
    text_length = len(text)
    paper_ref = f" (paper {paper_id})" if paper_id else ""
    
    # Check hard limit
    if text_length > settings.MAX_TEXT_LENGTH:
        message = (
            f"Text length {text_length:,} characters exceeds maximum limit "
            f"of {settings.MAX_TEXT_LENGTH:,} characters{paper_ref}. "
            f"This may indicate a PDF extraction error."
        )
        raise TextValidationError(message)
    
    # Check warning threshold
    if text_length > settings.TEXT_LENGTH_WARNING_THRESHOLD:
        message = (
            f"Warning: Text length {text_length:,} characters exceeds warning threshold "
            f"of {settings.TEXT_LENGTH_WARNING_THRESHOLD:,} characters{paper_ref}. "
            f"Processing may be slow and expensive."
        )
        return False, message
        
    return True, f"Text length {text_length:,} characters is within normal limits"



def estimate_token_count(text: str, chars_per_token: float = 3.5) -> int:
    """
    Estimate token count for text.
    
    Args:
        text: Text to estimate tokens for
        chars_per_token: Average characters per token (GPT models ~3-4)
        
    Returns:
        Estimated token count
    """
    if not text:
        return 0
    return int(len(text) / chars_per_token)


def get_text_stats(text: str) -> dict:
    """
    Get comprehensive statistics about text.
    
    Args:
        text: Text to analyze
        
    Returns:
        Dictionary with text statistics
    """
    if not text:
        return {
            "length": 0,
            "estimated_tokens": 0,
            "unique_chars": 0,
            "is_valid": True,
            "validation_message": "Text is empty"
        }
    
    try:
        is_valid, message = validate_text_length(text)
        
        return {
            "length": len(text),
            "estimated_tokens": estimate_token_count(text),
            "unique_chars": len(set(text)),
            "is_valid": is_valid,
            "validation_message": message,
            "exceeds_warning_threshold": len(text) > settings.TEXT_LENGTH_WARNING_THRESHOLD,
            "exceeds_hard_limit": len(text) > settings.MAX_TEXT_LENGTH
        }
    except TextValidationError as e:
        return {
            "length": len(text),
            "estimated_tokens": estimate_token_count(text),
            "unique_chars": len(set(text)),
            "is_valid": False,
            "validation_message": str(e),
            "exceeds_warning_threshold": True,
            "exceeds_hard_limit": True
        }