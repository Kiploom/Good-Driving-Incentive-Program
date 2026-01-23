from typing import Dict, List, TypedDict, Optional

class ProviderItem(TypedDict, total=False):
    item_id: str
    title: str
    url: str
    image: str
    price: float
    currency: str
    condition: str
    category_id: str
    brand: Optional[str]
    seller: Dict
    shipping: Dict
    pinned: bool
    pin_rank: int

class ProviderResult(TypedDict):
    items: List[ProviderItem]
    total: int
    page: int
    page_size: int

class ProviderInterface:
    def search(self, filters: Dict, page: int, page_size: int, sort: str) -> ProviderResult:
        raise NotImplementedError
    def fetch_items_by_ids(self, ids: list[str]) -> List[ProviderItem]:
        """Used for inclusions/pins lookup"""
        raise NotImplementedError
