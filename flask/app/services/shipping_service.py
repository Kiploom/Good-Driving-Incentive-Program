"""
Shipping cost calculation service for driver orders.
Provides simulated shipping costs based on location and order details.
"""

from typing import Any, Dict, List, Tuple


class ShippingService:
    """Service for calculating shipping costs based on location and order details."""
    
    # Base shipping costs by region (in USD)
    REGION_BASE_COSTS = {
        'US': {
            'domestic': 8.99,  # Within US
            'alaska': 15.99,   # Alaska
            'hawaii': 18.99,   # Hawaii
            'puerto_rico': 12.99,  # Puerto Rico
        },
        'CA': {
            'domestic': 12.99,  # Within Canada
            'remote': 25.99,    # Remote areas
        },
        'MX': {
            'domestic': 15.99,  # Within Mexico
        },
        'EU': {
            'domestic': 14.99,  # Within EU
            'uk': 16.99,        # UK
        },
        'ASIA': {
            'domestic': 19.99,  # Within Asia
        },
        'OTHER': {
            'international': 29.99,  # International
        }
    }
    
    # Weight multipliers for different item types
    WEIGHT_MULTIPLIERS = {
        'light': 1.0,      # Hats, small items
        'medium': 1.5,     # Clothing, shoes
        'heavy': 2.0,      # Electronics, books
        'oversized': 3.0   # Large items
    }
    
    # Default points conversion rate (points per dollar) used when no sponsor override is available
    POINTS_PER_DOLLAR = 100
    
    @classmethod
    def calculate_shipping_cost(
        cls,
        shipping_country: str,
        shipping_state: str | None = None,
        shipping_postal: str | None = None,
        item_count: int = 1,
        estimated_weight: str = 'medium',
        sponsor_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Calculate shipping cost based on location and order details.
        
        Args:
            shipping_country: Country code (US, CA, MX, etc.)
            shipping_state: State/province code
            shipping_postal: Postal/ZIP code
            item_count: Number of items in order
            estimated_weight: Weight category ('light', 'medium', 'heavy', 'oversized')
            
        Returns:
            Dict containing shipping cost details
        """
        # Determine region and base cost
        region, base_cost = cls._get_region_cost(shipping_country, shipping_state)
        
        # Apply weight multiplier
        weight_multiplier = cls.WEIGHT_MULTIPLIERS.get(estimated_weight, 1.5)
        
        # Apply item count multiplier (bulk discount)
        item_multiplier = cls._get_item_multiplier(item_count)
        
        # Calculate final cost
        shipping_cost_usd = base_cost * weight_multiplier * item_multiplier
        
        # Round to 2 decimal places
        shipping_cost_usd = round(shipping_cost_usd, 2)
        
        # Convert to points
        shipping_cost_points = cls._usd_to_points(shipping_cost_usd, sponsor_id)
        
        return {
            'region': region,
            'base_cost_usd': base_cost,
            'weight_multiplier': weight_multiplier,
            'item_multiplier': item_multiplier,
            'shipping_cost_usd': shipping_cost_usd,
            'shipping_cost_points': shipping_cost_points,
            'estimated_days': cls._get_estimated_delivery_days(region),
            'shipping_method': cls._get_shipping_method(region)
        }
    
    @classmethod
    def _get_region_cost(cls, country: str, state: str | None = None) -> Tuple[str, float]:
        """Get base shipping cost for region."""
        country = country.upper() if country else 'OTHER'
        state = state.upper() if state else ''
        
        if country == 'US':
            if state in ['AK']:
                return 'US-Alaska', cls.REGION_BASE_COSTS['US']['alaska']
            elif state in ['HI']:
                return 'US-Hawaii', cls.REGION_BASE_COSTS['US']['hawaii']
            elif state in ['PR']:
                return 'US-Puerto Rico', cls.REGION_BASE_COSTS['US']['puerto_rico']
            else:
                return 'US-Domestic', cls.REGION_BASE_COSTS['US']['domestic']
        elif country == 'CA':
            # Check for remote areas (simplified)
            if state in ['YT', 'NT', 'NU']:
                return 'CA-Remote', cls.REGION_BASE_COSTS['CA']['remote']
            else:
                return 'CA-Domestic', cls.REGION_BASE_COSTS['CA']['domestic']
        elif country == 'MX':
            return 'MX-Domestic', cls.REGION_BASE_COSTS['MX']['domestic']
        elif country in ['DE', 'FR', 'IT', 'ES', 'NL', 'BE', 'AT', 'CH', 'SE', 'NO', 'DK', 'FI']:
            return 'EU-Domestic', cls.REGION_BASE_COSTS['EU']['domestic']
        elif country == 'GB':
            return 'UK', cls.REGION_BASE_COSTS['EU']['uk']
        elif country in ['JP', 'KR', 'CN', 'SG', 'HK', 'TW', 'TH', 'MY', 'ID', 'PH', 'VN']:
            return 'Asia-Domestic', cls.REGION_BASE_COSTS['ASIA']['domestic']
        else:
            return 'International', cls.REGION_BASE_COSTS['OTHER']['international']
    
    @classmethod
    def _get_item_multiplier(cls, item_count: int) -> float:
        """Get multiplier based on item count (bulk discount)."""
        if item_count <= 1:
            return 1.0
        elif item_count <= 3:
            return 0.9  # 10% discount
        elif item_count <= 5:
            return 0.8  # 20% discount
        elif item_count <= 10:
            return 0.7  # 30% discount
        else:
            return 0.6  # 40% discount for 10+ items
    
    @classmethod
    def _get_estimated_delivery_days(cls, region: str) -> int:
        """Get estimated delivery days for region."""
        delivery_days = {
            'US-Domestic': 3,
            'US-Alaska': 7,
            'US-Hawaii': 5,
            'US-Puerto Rico': 6,
            'CA-Domestic': 5,
            'CA-Remote': 10,
            'MX-Domestic': 7,
            'EU-Domestic': 5,
            'UK': 4,
            'Asia-Domestic': 7,
            'International': 14
        }
        return delivery_days.get(region, 10)
    
    @classmethod
    def _get_shipping_method(cls, region: str) -> str:
        """Get shipping method description for region."""
        methods = {
            'US-Domestic': 'Standard Ground',
            'US-Alaska': 'Expedited Air',
            'US-Hawaii': 'Expedited Air',
            'US-Puerto Rico': 'Expedited Air',
            'CA-Domestic': 'Standard International',
            'CA-Remote': 'Expedited International',
            'MX-Domestic': 'Standard International',
            'EU-Domestic': 'Standard International',
            'UK': 'Standard International',
            'Asia-Domestic': 'Standard International',
            'International': 'Express International'
        }
        return methods.get(region, 'Standard International')
    
    @classmethod
    def get_shipping_options(
        cls,
        shipping_country: str,
        shipping_state: str | None = None,
        item_count: int = 1,
        estimated_weight: str = 'medium',
        sponsor_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Get available shipping options for location."""
        options = []
        
        # Standard shipping
        standard = cls.calculate_shipping_cost(
            shipping_country,
            shipping_state,
            item_count=item_count,
            estimated_weight=estimated_weight,
            sponsor_id=sponsor_id,
        )
        options.append({
            'name': 'Standard Shipping',
            'method': standard['shipping_method'],
            'cost_usd': standard['shipping_cost_usd'],
            'cost_points': standard['shipping_cost_points'],
            'days': standard['estimated_days'],
            'description': f"{standard['estimated_days']} business days",
            'region': standard['region'],
        })
        
        # Express shipping (if domestic)
        if standard['region'] in ['US-Domestic', 'CA-Domestic', 'EU-Domestic', 'UK']:
            express = cls.calculate_shipping_cost(
                shipping_country,
                shipping_state,
                item_count=item_count,
                estimated_weight=estimated_weight,
                sponsor_id=sponsor_id,
            )
            express['shipping_cost_usd'] = round(express['shipping_cost_usd'] * 1.8, 2)
            express['shipping_cost_points'] = cls._usd_to_points(express['shipping_cost_usd'], sponsor_id)
            express['estimated_days'] = max(1, express['estimated_days'] - 2)
            
            options.append({
                'name': 'Express Shipping',
                'method': 'Express',
                'cost_usd': express['shipping_cost_usd'],
                'cost_points': express['shipping_cost_points'],
                'days': express['estimated_days'],
                'description': f"{express['estimated_days']} business days",
                'region': express['region'],
            })
        
        return options

    @classmethod
    def _usd_to_points(cls, amount_usd: float, sponsor_id: str | None) -> int:
        """Convert USD to points, respecting sponsor-specific conversion rules when available."""
        if amount_usd is None:
            return 0

        if sponsor_id:
            try:
                from app.driver_points_catalog.services.points_service import price_to_points

                return price_to_points(sponsor_id, amount_usd)
            except Exception:
                # Fall back to default conversion if policy lookup fails
                pass

        return int(round(amount_usd * cls.POINTS_PER_DOLLAR))
