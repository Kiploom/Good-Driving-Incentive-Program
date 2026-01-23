"""
Avatar helper utility for template usage.
Provides a simple interface for getting avatar display URLs.
"""

from flask import url_for
from app.services.s3_service import get_avatar_url


def get_avatar_display_url(profile_image_url):
    """
    Get display URL for profile avatar.
    Handles both old local paths and new S3 keys.
    Returns default avatar URL if profile_image_url is None/empty.
    
    Args:
        profile_image_url: ProfileImageURL from database (could be S3 key, local path, or None)
    
    Returns:
        URL string for <img src="">, or default avatar URL
    """
    if not profile_image_url:
        # Return default avatar URL
        try:
            return url_for('static', filename='img/default_avatar.svg')
        except Exception:
            return '/static/img/default_avatar.svg'
    
    # Use S3 service to get URL (handles both S3 keys and local paths)
    url = get_avatar_url(profile_image_url)
    
    if not url:
        # Fallback to default avatar
        try:
            return url_for('static', filename='img/default_avatar.svg')
        except Exception:
            return '/static/img/default_avatar.svg'
    
    return url

