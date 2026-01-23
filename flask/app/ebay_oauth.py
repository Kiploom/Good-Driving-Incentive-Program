# app/ebay_oauth.py
import os
import threading
import time
import logging
from typing import Optional, Dict, Any
import requests
from flask import current_app
from dotenv import load_dotenv, find_dotenv

# Load .env regardless of current working directory
load_dotenv(find_dotenv())

logger = logging.getLogger(__name__)


class EbayOAuthManager:
    """
    Manages eBay OAuth token refresh automatically.
    - Memoizes token for 55 minutes to reduce requests
    - Auto-refreshes on 401 responses
    - Background thread refreshes every hour
    - Thread-safe with locking
    """
    
    def __init__(self):
        self.client_id = os.getenv("EBAY_CLIENT_ID")
        self.client_secret = os.getenv("EBAY_CLIENT_SECRET")
        self.env = os.getenv("EBAY_ENV", "PRODUCTION").upper()
        self.token = None
        self.token_expires_at = None
        self.refresh_thread = None
        self.running = False
        self._lock = threading.Lock()  # Thread-safe token refresh
        
        # Memoize bearer header (valid for 55 minutes)
        self._cached_header = None
        self._header_cached_at = None
        self._header_cache_duration = 3300  # 55 minutes in seconds
        
        # Set up endpoints based on environment
        if self.env == "SANDBOX":
            self.token_url = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        else:
            self.token_url = "https://api.ebay.com/identity/v1/oauth2/token"
    
    def get_token(self) -> Optional[str]:
        """Get the current OAuth token, refreshing if necessary."""
        if not self.token or self._is_token_expired():
            with self._lock:  # Thread-safe refresh
                # Double-check after acquiring lock
                if not self.token or self._is_token_expired():
                    self._refresh_token()
        return self.token
    
    def get_bearer_header(self) -> Optional[str]:
        """
        Get memoized bearer authorization header.
        Cached for 55 minutes to reduce per-request overhead.
        """
        now = time.time()
        
        # Check if cached header is still valid
        if (self._cached_header and 
            self._header_cached_at and 
            (now - self._header_cached_at) < self._header_cache_duration):
            return self._cached_header
        
        # Refresh token and rebuild header
        token = self.get_token()
        if token:
            self._cached_header = f"Bearer {token}"
            self._header_cached_at = now
            return self._cached_header
        
        return None
    
    def handle_401_refresh(self) -> bool:
        """
        Handle 401 Unauthorized response by forcing token refresh.
        Returns True if refresh was successful, False otherwise.
        """
        logger.warning("Received 401 Unauthorized - forcing token refresh")
        
        with self._lock:
            # Invalidate cached header
            self._cached_header = None
            self._header_cached_at = None
            
            # Force token refresh
            if self._refresh_token():
                logger.info("Token refresh successful after 401")
                return True
            else:
                logger.error("Token refresh failed after 401")
                return False
    
    def _is_token_expired(self) -> bool:
        """Check if the current token is expired or about to expire (within 5 minutes)."""
        if not self.token_expires_at:
            return True
        return time.time() >= (self.token_expires_at - 300)  # 5 minutes buffer
    
    def _refresh_token(self) -> bool:
        """
        Refresh the OAuth token using client credentials flow.
        Returns True if successful, False otherwise.
        """
        if not self.client_id or not self.client_secret:
            logger.error("EBAY_CLIENT_ID or EBAY_CLIENT_SECRET not configured")
            return False
        
        try:
            # Prepare the request
            auth_header = f"{self.client_id}:{self.client_secret}"
            import base64
            encoded_auth = base64.b64encode(auth_header.encode()).decode()
            
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {encoded_auth}"
            }
            
            data = {
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope"
            }
            
            logger.info(f"Refreshing eBay OAuth token from {self.token_url}")
            response = requests.post(self.token_url, headers=headers, data=data, timeout=30)
            
            if response.status_code == 200:
                token_data = response.json()
                self.token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 7200)  # Default 2 hours
                self.token_expires_at = time.time() + expires_in
                
                logger.info(f"Successfully refreshed eBay OAuth token. Expires in {expires_in} seconds.")
                
                # Update environment variable for other parts of the app
                os.environ["EBAY_OAUTH_TOKEN"] = self.token
                
                return True
            else:
                logger.error(f"Failed to refresh eBay OAuth token. Status: {response.status_code}, Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Exception while refreshing eBay OAuth token: {e}")
            return False
    
    def start_auto_refresh(self):
        """Start the automatic token refresh thread."""
        if self.running:
            return
        
        self.running = True
        self.refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self.refresh_thread.start()
        logger.info("Started eBay OAuth auto-refresh thread")
    
    def stop_auto_refresh(self):
        """Stop the automatic token refresh thread."""
        self.running = False
        if self.refresh_thread:
            self.refresh_thread.join(timeout=5)
        logger.info("Stopped eBay OAuth auto-refresh thread")
    
    def _refresh_loop(self):
        """Background thread that refreshes the token every hour."""
        # Initial refresh
        if not self._refresh_token():
            logger.warning("Initial token refresh failed")
        
        # Refresh every hour (3600 seconds)
        while self.running:
            time.sleep(3600)  # Wait 1 hour
            if self.running:
                self._refresh_token()


# Global instance
oauth_manager = EbayOAuthManager()


def init_ebay_oauth(app):
    """Initialize eBay OAuth manager with Flask app context."""
    with app.app_context():
        # Set up logging
        app.logger.info("Initializing eBay OAuth manager")
        
        # Start auto-refresh
        oauth_manager.start_auto_refresh()
        
        # Set up cleanup on app shutdown
        import atexit
        atexit.register(oauth_manager.stop_auto_refresh)


def get_ebay_token() -> Optional[str]:
    """Get the current eBay OAuth token."""
    return oauth_manager.get_token()
