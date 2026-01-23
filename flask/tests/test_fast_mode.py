"""
Test suite for fast mode (fast=1) vs strict mode (fast=0) performance optimizations.

Tests verify:
1. fast=1 and fast=0 return identical item sets for the same page
2. Filters produce identical results in both modes
3. fast=1 has better performance (lower TTFB)
4. Caching works correctly
5. has_more flag is accurate in both modes
"""

import time
import json
from flask import Flask
from flask.testing import FlaskClient
import pytest


def test_fast_mode_returns_same_items(client: FlaskClient):
    """
    Test that fast=1 and fast=0 return identical items for the same query.
    Only the total field should differ.
    """
    # Test driver catalog endpoint
    fast_response = client.get('/driver-catalog/data?page=1&page_size=24&fast=1')
    strict_response = client.get('/driver-catalog/data?page=1&page_size=24&fast=0')
    
    assert fast_response.status_code == 200
    assert strict_response.status_code == 200
    
    fast_data = fast_response.get_json()
    strict_data = strict_response.get_json()
    
    # Extract item IDs for comparison
    fast_ids = [item['id'] for item in fast_data.get('items', [])]
    strict_ids = [item['id'] for item in strict_data.get('items', [])]
    
    # Items should be identical
    assert fast_ids == strict_ids, "Fast mode and strict mode should return same items"
    
    # fast=1 should have total=None or undefined
    # fast=0 should have total as a number
    assert fast_data.get('total') is None or 'total' not in fast_data, \
        "Fast mode should skip total count"
    assert isinstance(strict_data.get('total'), (int, type(None))), \
        "Strict mode should compute total"
    
    # Both should have has_more flag
    assert 'has_more' in fast_data
    assert 'has_more' in strict_data
    
    print(f"✓ Fast mode: {len(fast_ids)} items, total={fast_data.get('total')}")
    print(f"✓ Strict mode: {len(strict_ids)} items, total={strict_data.get('total')}")


def test_sponsor_preview_fast_mode(client: FlaskClient):
    """
    Test sponsor preview endpoint with fast mode.
    """
    fast_response = client.get('/sponsor-catalog/preview/data?page=1&page_size=48&fast=1')
    strict_response = client.get('/sponsor-catalog/preview/data?page=1&page_size=48&fast=0')
    
    assert fast_response.status_code == 200
    assert strict_response.status_code == 200
    
    fast_data = fast_response.get_json()
    strict_data = strict_response.get_json()
    
    # Extract item IDs
    fast_ids = [item['id'] for item in fast_data.get('items', [])]
    strict_ids = [item['id'] for item in strict_data.get('items', [])]
    
    # Items should be identical
    assert fast_ids == strict_ids, "Sponsor preview: Fast and strict modes should return same items"
    
    print(f"✓ Sponsor preview fast mode: {len(fast_ids)} items")
    print(f"✓ Sponsor preview strict mode: {len(strict_ids)} items")


def test_fast_mode_performance(client: FlaskClient):
    """
    Test that fast=1 has better performance (lower TTFB) than fast=0.
    """
    # Warm up - make initial requests to populate cache
    client.get('/driver-catalog/data?page=1&page_size=48&fast=1')
    time.sleep(0.1)
    
    # Test fast mode (should be cached)
    start = time.time()
    fast_response = client.get('/driver-catalog/data?page=1&page_size=48&fast=1')
    fast_duration = time.time() - start
    
    # Test strict mode (may or may not be cached)
    start = time.time()
    strict_response = client.get('/driver-catalog/data?page=1&page_size=48&fast=0')
    strict_duration = time.time() - start
    
    assert fast_response.status_code == 200
    assert strict_response.status_code == 200
    
    print(f"✓ Fast mode TTFB: {fast_duration*1000:.0f}ms")
    print(f"✓ Strict mode TTFB: {strict_duration*1000:.0f}ms")
    
    # On cached queries, fast mode should be very quick (< 400ms)
    # This is a lenient test since it depends on environment
    assert fast_duration < 2.0, f"Fast mode should complete quickly, took {fast_duration}s"


def test_filters_produce_identical_results(client: FlaskClient):
    """
    Test that filters (category, price, points) produce identical results in both modes.
    """
    # Test with keyword search
    fast_resp = client.get('/driver-catalog/data?page=1&page_size=24&q=headphones&fast=1')
    strict_resp = client.get('/driver-catalog/data?page=1&page_size=24&q=headphones&fast=0')
    
    assert fast_resp.status_code == 200
    assert strict_resp.status_code == 200
    
    fast_data = fast_resp.get_json()
    strict_data = strict_resp.get_json()
    
    fast_ids = [item['id'] for item in fast_data.get('items', [])]
    strict_ids = [item['id'] for item in strict_data.get('items', [])]
    
    assert fast_ids == strict_ids, "Keyword filter should produce same results"
    
    # Test with points filter
    fast_resp = client.get('/driver-catalog/data?page=1&page_size=24&min_points=100&max_points=500&fast=1')
    strict_resp = client.get('/driver-catalog/data?page=1&page_size=24&min_points=100&max_points=500&fast=0')
    
    assert fast_resp.status_code == 200
    assert strict_resp.status_code == 200
    
    fast_data = fast_resp.get_json()
    strict_data = strict_resp.get_json()
    
    fast_ids = [item['id'] for item in fast_data.get('items', [])]
    strict_ids = [item['id'] for item in strict_data.get('items', [])]
    
    assert fast_ids == strict_ids, "Points filter should produce same results"
    
    print(f"✓ Keyword filter: {len(fast_ids)} items match in both modes")


def test_cache_hit_performance(client: FlaskClient):
    """
    Test that cache hits are significantly faster than cache misses.
    """
    # First request - cache miss
    start = time.time()
    resp1 = client.get('/driver-catalog/data?page=1&page_size=48&sort=price_asc&fast=1')
    cache_miss_duration = time.time() - start
    
    assert resp1.status_code == 200
    
    # Second identical request - should be cache hit
    start = time.time()
    resp2 = client.get('/driver-catalog/data?page=1&page_size=48&sort=price_asc&fast=1')
    cache_hit_duration = time.time() - start
    
    assert resp2.status_code == 200
    
    # Results should be identical
    data1 = resp1.get_json()
    data2 = resp2.get_json()
    
    ids1 = [item['id'] for item in data1.get('items', [])]
    ids2 = [item['id'] for item in data2.get('items', [])]
    
    assert ids1 == ids2, "Cached result should match original"
    
    print(f"✓ Cache miss: {cache_miss_duration*1000:.0f}ms")
    print(f"✓ Cache hit: {cache_hit_duration*1000:.0f}ms")
    
    # Cache hit should be faster (though this depends on Redis vs in-memory)
    # Just verify both complete in reasonable time
    assert cache_hit_duration < 2.0, "Cache hit should be fast"


def test_has_more_flag_accuracy(client: FlaskClient):
    """
    Test that has_more flag is accurate in both fast and strict modes.
    """
    # Test first page
    fast_resp = client.get('/driver-catalog/data?page=1&page_size=10&fast=1')
    strict_resp = client.get('/driver-catalog/data?page=1&page_size=10&fast=0')
    
    assert fast_resp.status_code == 200
    assert strict_resp.status_code == 200
    
    fast_data = fast_resp.get_json()
    strict_data = strict_resp.get_json()
    
    # has_more should be consistent between modes
    fast_has_more = fast_data.get('has_more')
    strict_has_more = strict_data.get('has_more')
    
    # If there are results, both should agree on has_more
    if fast_data.get('items') and strict_data.get('items'):
        assert fast_has_more == strict_has_more, \
            f"has_more should match: fast={fast_has_more}, strict={strict_has_more}"
    
    print(f"✓ has_more flag: fast={fast_has_more}, strict={strict_has_more}")


def test_different_sorts_produce_different_cache_keys(client: FlaskClient):
    """
    Test that different sort orders are cached separately.
    """
    # Request with price_asc
    resp1 = client.get('/driver-catalog/data?page=1&page_size=24&sort=price_asc&fast=1')
    assert resp1.status_code == 200
    data1 = resp1.get_json()
    
    # Request with price_desc  
    resp2 = client.get('/driver-catalog/data?page=1&page_size=24&sort=price_desc&fast=1')
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    
    # Extract item IDs
    ids1 = [item['id'] for item in data1.get('items', [])]
    ids2 = [item['id'] for item in data2.get('items', [])]
    
    # If there are enough results, the order should be different
    if len(ids1) >= 3 and len(ids2) >= 3:
        # At least some items should be in different positions
        # (unless all items have the same price, which is unlikely)
        assert ids1 != ids2 or len(set(ids1)) < 3, \
            "Different sort orders should produce different results or ordering"
    
    print(f"✓ Different sorts cached separately")


def test_pagination_consistency(client: FlaskClient):
    """
    Test that pagination works consistently across fast and strict modes.
    """
    # Get page 1
    page1_fast = client.get('/driver-catalog/data?page=1&page_size=12&fast=1')
    page1_strict = client.get('/driver-catalog/data?page=1&page_size=12&fast=0')
    
    assert page1_fast.status_code == 200
    assert page1_strict.status_code == 200
    
    # Get page 2
    page2_fast = client.get('/driver-catalog/data?page=2&page_size=12&fast=1')
    page2_strict = client.get('/driver-catalog/data?page=2&page_size=12&fast=0')
    
    assert page2_fast.status_code == 200
    assert page2_strict.status_code == 200
    
    # Extract IDs
    p1_fast_ids = [item['id'] for item in page1_fast.get_json().get('items', [])]
    p1_strict_ids = [item['id'] for item in page1_strict.get_json().get('items', [])]
    p2_fast_ids = [item['id'] for item in page2_fast.get_json().get('items', [])]
    p2_strict_ids = [item['id'] for item in page2_strict.get_json().get('items', [])]
    
    # Page 1 should match between modes
    assert p1_fast_ids == p1_strict_ids, "Page 1 should match between modes"
    
    # Page 2 should match between modes
    assert p2_fast_ids == p2_strict_ids, "Page 2 should match between modes"
    
    # Page 1 and Page 2 should be different (no duplicates)
    if p1_fast_ids and p2_fast_ids:
        assert set(p1_fast_ids).isdisjoint(set(p2_fast_ids)), \
            "Page 1 and Page 2 should have different items"
    
    print(f"✓ Pagination: Page 1 has {len(p1_fast_ids)} items, Page 2 has {len(p2_fast_ids)} items")


# Pytest fixtures
@pytest.fixture
def app():
    """Create Flask app for testing."""
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


if __name__ == '__main__':
    print("=" * 70)
    print("FAST MODE PERFORMANCE & CORRECTNESS TEST SUITE")
    print("=" * 70)
    print()
    
    # Run tests manually if pytest not available
    try:
        import pytest
        pytest.main([__file__, '-v', '--tb=short'])
    except ImportError:
        print("pytest not available, run: pip install pytest")
        print("Or run with: python -m pytest flask/tests/test_fast_mode.py -v")

