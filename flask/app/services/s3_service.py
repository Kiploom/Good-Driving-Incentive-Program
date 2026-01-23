"""
S3 service for uploading and managing profile pictures in AWS S3.
Uses private bucket with presigned URLs for secure access.
Uses IAM roles for authentication via boto3's default credential chain.
"""

import boto3
from botocore.exceptions import ClientError, BotoCoreError
from flask import current_app, url_for
from werkzeug.utils import secure_filename
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Allowed file extensions for avatars
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def get_s3_client():
    """
    Initialize and return boto3 S3 client.
    Uses default credential chain (IAM roles, environment variables, credentials file).
    """
    from config import s3_config
    
    try:
        client = boto3.client(
            's3',
            region_name=s3_config['region']
        )
        return client
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {e}")
        raise


def generate_s3_key(account_id: str, extension: str) -> str:
    """
    Generate S3 object key for avatar.
    
    Args:
        account_id: The account ID
        extension: File extension (e.g., '.jpg')
    
    Returns:
        S3 key string (e.g., 'avatars/{account_id}.jpg')
    """
    from config import s3_config
    prefix_avatars = s3_config['bucket_prefix_avatars']
    return f"{prefix_avatars}/{account_id}{extension}"


def _upload_avatar_local(file, account_id: str, extension: str) -> str:
    """
    Upload avatar to local file system (fallback when S3 is not configured).
    
    Args:
        file: Werkzeug FileStorage object
        account_id: The account ID
        extension: File extension (e.g., '.jpg')
    
    Returns:
        Local path string (e.g., 'uploads/avatars/{account_id}.jpg')
    
    Raises:
        Exception: For file system errors
    """
    from flask import current_app
    
    try:
        # Create uploads directory structure
        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'avatars')
        os.makedirs(upload_dir, exist_ok=True)
        
        # Generate filename
        filename = f"{account_id}{extension}"
        filepath = os.path.join(upload_dir, filename)
        
        # Save file
        file.save(filepath)
        
        # Return path relative to static directory
        relative_path = f"uploads/avatars/{filename}"
        logger.info(f"Successfully uploaded avatar to local storage: {relative_path}")
        return relative_path
    
    except Exception as e:
        logger.error(f"Failed to upload avatar to local storage: {e}")
        raise Exception(f"Failed to upload avatar: {str(e)}")


def upload_avatar(file, account_id: str) -> Optional[str]:
    """
    Upload avatar file to S3 or local storage (fallback).
    
    Args:
        file: Werkzeug FileStorage object or file-like object
        account_id: The account ID
    
    Returns:
        S3 key string or local path string if successful, None otherwise
    
    Raises:
        ValueError: If file type or size is invalid
        Exception: For upload failures
    """
    from config import s3_config
    from flask import current_app
    
    # Validate file first
    if not file or not hasattr(file, 'filename') or not file.filename:
        raise ValueError("No file provided")
    
    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    
    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)  # Reset file pointer
    
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"File size exceeds maximum allowed size of {MAX_FILE_SIZE / (1024*1024)}MB")
    
    # If S3 is not configured, fall back to local storage
    if not s3_config.get('bucket_name'):
        logger.warning("AWS_S3_BUCKET_NAME is not configured, falling back to local storage")
        return _upload_avatar_local(file, account_id, ext)
    
    # Validate file
    if not file or not hasattr(file, 'filename') or not file.filename:
        raise ValueError("No file provided")
    
    # Generate S3 key
    s3_key = generate_s3_key(account_id, ext)
    
    # Determine content type
    content_type_map = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.ico': 'image/x-icon'
    }
    content_type = content_type_map.get(ext, 'application/octet-stream')
    
    try:
        s3_client = get_s3_client()
        
        # Ensure file pointer is at the beginning
        file.seek(0)
        
        # Upload to S3 with private ACL (private bucket)
        s3_client.upload_fileobj(
            file,
            s3_config['bucket_name'],
            s3_key,
            ExtraArgs={
                'ContentType': content_type,
                'ACL': 'private'  # Private bucket
            }
        )
        
        logger.info(f"Successfully uploaded avatar to S3: {s3_key}")
        return s3_key
    
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"S3 upload error ({error_code}): {e}")
        raise Exception(f"Failed to upload avatar to S3: {error_code}")
    except BotoCoreError as e:
        logger.error(f"Boto3 error during upload: {e}")
        raise Exception(f"Failed to upload avatar: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during S3 upload: {e}")
        raise


def delete_avatar(s3_key: str) -> bool:
    """
    Delete avatar from S3 or local storage.
    
    Args:
        s3_key: The S3 object key or local path to delete
    
    Returns:
        True if deleted successfully, False otherwise
    """
    from config import s3_config
    from flask import current_app
    
    if not s3_key:
        return False
    
    # Don't delete if it's a URL
    if s3_key.startswith('http://') or s3_key.startswith('https://'):
        # This is a URL, not a key - skip
        return False
    
    # Handle local file deletion
    if s3_key.startswith('uploads/'):
        try:
            filepath = os.path.join(current_app.root_path, 'static', s3_key)
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Successfully deleted local avatar: {s3_key}")
                return True
            else:
                logger.warning(f"Local avatar file not found: {s3_key}")
                return False
        except Exception as e:
            logger.error(f"Failed to delete local avatar: {e}")
            return False
    
    # Handle S3 deletion
    if not s3_config.get('bucket_name'):
        logger.warning("AWS_S3_BUCKET_NAME is not configured, cannot delete from S3")
        return False
    
    try:
        s3_client = get_s3_client()
        
        # Check if object exists
        try:
            s3_client.head_object(
                Bucket=s3_config['bucket_name'],
                Key=s3_key
            )
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                logger.info(f"Avatar not found in S3: {s3_key}")
                return False
            raise
        
        # Delete object
        s3_client.delete_object(
            Bucket=s3_config['bucket_name'],
            Key=s3_key
        )
        
        logger.info(f"Successfully deleted avatar from S3: {s3_key}")
        return True
    
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"S3 delete error ({error_code}): {e}")
        return False
    except BotoCoreError as e:
        logger.error(f"Boto3 error during delete: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during S3 delete: {e}")
        return False


def generate_presigned_url(s3_key: str, expiration: Optional[int] = None) -> Optional[str]:
    """
    Generate presigned URL for accessing avatar from private S3 bucket.
    
    Args:
        s3_key: The S3 object key
        expiration: URL expiration time in seconds (defaults to config value)
    
    Returns:
        Presigned URL string, or None on error
    """
    from config import s3_config
    
    if not s3_key or not s3_config.get('bucket_name'):
        return None
    
    # Don't generate presigned URL for old local paths or URLs
    if s3_key.startswith('http://') or s3_key.startswith('https://'):
        return s3_key  # Already a URL
    
    if s3_key.startswith('uploads/'):
        # This is a local path - return None to use Flask static serving
        return None
    
    try:
        s3_client = get_s3_client()
        
        expiration_time = expiration or s3_config['presigned_url_expiration']
        
        
        presigned_url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': s3_config['bucket_name'],
                'Key': s3_key
            },
            ExpiresIn=expiration_time
        )
        
        return presigned_url
    
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f"S3 presigned URL error ({error_code}): {e}")
        return None
    except BotoCoreError as e:
        logger.error(f"Boto3 error generating presigned URL: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating presigned URL: {e}")
        return None


def get_avatar_url(profile_image_url: Optional[str]) -> Optional[str]:
    """
    Smart URL resolver for profile images.
    Handles both old local paths and new S3 keys.
    
    Args:
        profile_image_url: ProfileImageURL from database (could be S3 key, local path, or None)
    
    Returns:
        URL string for <img src="">, or None for default avatar
    """
    if not profile_image_url:
        return None
    
    # If it's already a full URL (presigned URL), return as-is
    if profile_image_url.startswith('http://') or profile_image_url.startswith('https://'):
        return profile_image_url
    
    # If it's a local path (old format), return Flask static URL
    if profile_image_url.startswith('uploads/'):
        try:
            return url_for('static', filename=profile_image_url)
        except Exception:
            return None
    
    # If it's an S3 key (new format), generate presigned URL
    return generate_presigned_url(profile_image_url)

