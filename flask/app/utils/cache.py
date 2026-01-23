"""
Caching utilities with Redis fallback to in-process TTLCache.
Automatically selects Redis if REDIS_URL is configured, otherwise uses local cache.
"""
import os
import json
import hashlib
from typing import Optional, Any
from functools import wraps

# Try Redis first
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Fallback to cachetools
try:
    from cachetools import TTLCache
    CACHETOOLS_AVAILABLE = True
except ImportError:
    CACHETOOLS_AVAILABLE = False


class CacheBackend:
    """Abstract cache interface."""
    
    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError
    
    def set(self, key: str, value: Any, ttl: int):
        raise NotImplementedError
    
    def delete(self, key: str):
        raise NotImplementedError
    
    def clear(self):
        raise NotImplementedError


class RedisCache(CacheBackend):
    """Redis-backed cache."""
    
    def __init__(self, redis_url: str):
        self.client = redis.from_url(redis_url, decode_responses=False)
    
    def get(self, key: str) -> Optional[Any]:
        try:
            data = self.client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception:
            return None
    
    def set(self, key: str, value: Any, ttl: int):
        try:
            self.client.setex(key, ttl, json.dumps(value))
        except Exception:
            pass
    
    def delete(self, key: str):
        try:
            self.client.delete(key)
        except Exception:
            pass
    
    def clear(self):
        try:
            self.client.flushdb()
        except Exception:
            pass


class LocalCache(CacheBackend):
    """In-process TTL cache fallback."""
    
    def __init__(self, maxsize: int = 1000, ttl: int = 120):
        if not CACHETOOLS_AVAILABLE:
            # Minimal dict-based cache if cachetools not available
            self._cache = {}
            self._timestamps = {}
            self.default_ttl = ttl
            self.maxsize = maxsize
        else:
            self._cache = TTLCache(maxsize=maxsize, ttl=ttl)
    
    def get(self, key: str) -> Optional[Any]:
        try:
            if not CACHETOOLS_AVAILABLE:
                import time
                if key in self._cache:
                    if time.time() - self._timestamps.get(key, 0) < self.default_ttl:
                        return self._cache[key]
                    else:
                        del self._cache[key]
                        del self._timestamps[key]
                return None
            return self._cache.get(key)
        except Exception:
            return None
    
    def set(self, key: str, value: Any, ttl: int):
        try:
            if not CACHETOOLS_AVAILABLE:
                import time
                if len(self._cache) >= self.maxsize:
                    # Simple eviction: remove oldest
                    oldest_key = min(self._timestamps, key=self._timestamps.get)
                    del self._cache[oldest_key]
                    del self._timestamps[oldest_key]
                self._cache[key] = value
                self._timestamps[key] = time.time()
            else:
                self._cache[key] = value
        except Exception:
            pass
    
    def delete(self, key: str):
        try:
            if not CACHETOOLS_AVAILABLE:
                self._cache.pop(key, None)
                self._timestamps.pop(key, None)
            else:
                self._cache.pop(key, None)
        except Exception:
            pass
    
    def clear(self):
        try:
            if not CACHETOOLS_AVAILABLE:
                self._cache.clear()
                self._timestamps.clear()
            else:
                self._cache.clear()
        except Exception:
            pass


# Global cache instance
_cache_instance: Optional[CacheBackend] = None


def get_cache() -> CacheBackend:
    """
    Get the configured cache backend.
    Returns Redis if REDIS_URL is set, otherwise LocalCache.
    """
    global _cache_instance
    
    if _cache_instance is None:
        redis_url = os.environ.get('REDIS_URL')
        
        if redis_url and REDIS_AVAILABLE:
            try:
                _cache_instance = RedisCache(redis_url)
            except Exception:
                # Fallback to local cache if Redis fails
                _cache_instance = LocalCache()
        else:
            _cache_instance = LocalCache()
    
    return _cache_instance


def make_cache_key(*args, **kwargs) -> str:
    """
    Generate a deterministic cache key from arguments.
    Handles nested dicts/lists by sorting JSON.
    """
    def normalize(obj):
        if isinstance(obj, dict):
            return json.dumps(obj, sort_keys=True)
        elif isinstance(obj, (list, tuple)):
            return json.dumps(obj, sort_keys=True)
        return str(obj)
    
    key_parts = [normalize(arg) for arg in args]
    key_parts.extend(f"{k}={normalize(v)}" for k, v in sorted(kwargs.items()))
    
    key_string = "|".join(key_parts)
    
    # Hash to keep keys reasonable length
    return f"cache:{hashlib.sha256(key_string.encode()).hexdigest()[:16]}"


def cached(ttl: int = 120, key_prefix: str = ""):
    """
    Decorator for caching function results.
    
    Args:
        ttl: Time-to-live in seconds
        key_prefix: Optional prefix for cache keys
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = get_cache()
            
            # Generate cache key
            cache_key = f"{key_prefix}:{func.__name__}:" + make_cache_key(*args, **kwargs)
            
            # Try to get from cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Call function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            
            return result
        
        return wrapper
    return decorator

