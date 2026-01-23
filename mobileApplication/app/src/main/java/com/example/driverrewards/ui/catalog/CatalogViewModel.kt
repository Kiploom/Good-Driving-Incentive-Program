package com.example.driverrewards.ui.catalog

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.CatalogService
import kotlinx.coroutines.launch

class CatalogViewModel : ViewModel() {

    private val catalogService = CatalogService()
    
    private val _products = MutableLiveData<List<ProductItem>>()
    val products: LiveData<List<ProductItem>> = _products
    
    private val _loading = MutableLiveData<Boolean>()
    val loading: LiveData<Boolean> = _loading
    
    private val _error = MutableLiveData<String?>()
    val error: LiveData<String?> = _error
    
    // Caching state
    private var cachedProducts: List<ProductItem> = emptyList()
    private var cachedSearchQuery: String? = null
    private var cachedSort: String = "best_match"
    private var cachedMinPoints: Float? = null
    private var cachedMaxPoints: Float? = null
    private var cachedCategories: List<String> = emptyList()
    private var cachedPage: Int = 1
    private var cachedHasMoreData: Boolean = false
    private var isDataCached: Boolean = false
    private var scrollPosition: Int = 0
    
    // Navigation state
    private var currentProductItemId: String? = null

    fun testConnectivity(
        onSuccess: (String) -> Unit,
        onError: (String) -> Unit
    ) {
        viewModelScope.launch {
            try {
                _loading.value = true
                _error.value = null
                
                val response = catalogService.testConnectivity()
                
                if (response.success) {
                    val message = "Connectivity test successful: ${response.message}"
                    _error.value = null
                    onSuccess(message)
                } else {
                    val errorMessage = "Connectivity test failed: ${response.message}"
                    _error.value = errorMessage
                    onError(errorMessage)
                }
                
            } catch (e: Exception) {
                val errorMessage = "Connectivity test error: ${e.message ?: "Unknown error"}"
                _error.value = errorMessage
                onError(errorMessage)
            } finally {
                _loading.value = false
            }
        }
    }

    fun loadCatalogData(
        page: Int = 1,
        searchQuery: String? = null,
        sort: String = "best_match",
        categories: List<String>? = null,
        minPoints: Float? = null,
        maxPoints: Float? = null,
        recommendedOnly: Boolean = false,  // Used for recommended items view, not as a filter
        onSuccess: (List<ProductItem>, Boolean) -> Unit,
        onError: (String) -> Unit
    ) {
        android.util.Log.d("CatalogViewModel", "===== LOAD CATALOG DATA =====")
        android.util.Log.d("CatalogViewModel", "page: $page, minPoints: $minPoints, maxPoints: $maxPoints")
        android.util.Log.d("CatalogViewModel", "recommendedOnly: $recommendedOnly, searchQuery: $searchQuery, categories: $categories")
        android.util.Log.d("CatalogViewModel", "This should load products filtered by the ACTIVE sponsor environment")
        
        // Normalize categories for comparison
        val normalizedCategories = categories ?: emptyList()
        
        // Check if data is cached for the same parameters (only for page 1)
        if (page == 1 && isDataCached && 
            cachedSearchQuery == searchQuery && 
            cachedSort == sort && 
            cachedMinPoints == minPoints && 
            cachedMaxPoints == maxPoints && 
            cachedCategories.size == normalizedCategories.size &&
            cachedCategories.sorted() == normalizedCategories.sorted()) {
            android.util.Log.d("CatalogViewModel", "Using cached data")
            _products.value = cachedProducts
            onSuccess(cachedProducts, cachedHasMoreData)
            return
        }
        
        viewModelScope.launch {
            try {
                _loading.value = true
                _error.value = null
                
                val response = catalogService.getCatalogData(
                    page = page,
                    searchQuery = searchQuery,
                    sort = sort,
                    categories = categories,
                    minPoints = minPoints,
                    maxPoints = maxPoints,
                    recommendedOnly = recommendedOnly
                )
                
                if (response.success) {
                    android.util.Log.d("CatalogViewModel", "===== CATALOG DATA LOADED SUCCESSFULLY =====")
                    android.util.Log.d("CatalogViewModel", "Received ${response.items.size} items")
                    android.util.Log.d("CatalogViewModel", "These products should be filtered by the ACTIVE sponsor's catalog rules")
                    
                    val items = response.items.map { itemData ->
                        ProductItem(
                            id = itemData.id ?: "",
                            title = itemData.title ?: "Unknown Product",
                            points = itemData.points?.toInt() ?: 0,
                            imageUrl = itemData.image,
                            availability = itemData.availability ?: "IN_STOCK",
                            isFavorite = itemData.isFavorite ?: false,
                            isPinned = itemData.isPinned ?: false
                        )
                    }
                    
                    // Log first few items for debugging
                    items.take(3).forEachIndexed { index, item ->
                        android.util.Log.d("CatalogViewModel", "  Item $index: ${item.title} (${item.points} pts, pinned: ${item.isPinned})")
                    }
                    
                    // Cache data only for page 1
                    if (page == 1) {
                        cachedProducts = items
                        cachedSearchQuery = searchQuery
                        cachedSort = sort
                        cachedMinPoints = minPoints
                        cachedMaxPoints = maxPoints
                        cachedCategories = categories ?: emptyList()
                        cachedPage = page
                        cachedHasMoreData = response.has_more
                        isDataCached = true
                        android.util.Log.d("CatalogViewModel", "Cached catalog data for page 1")
                    }
                    
                    _products.value = items
                    onSuccess(items, response.has_more)
                } else {
                    val errorMessage = response.message ?: "Failed to load catalog"
                    _error.value = errorMessage
                    onError(errorMessage)
                }
                
            } catch (e: Exception) {
                val errorMessage = "Network error: ${e.message ?: "Unknown error"}"
                _error.value = errorMessage
                onError(errorMessage)
            } finally {
                _loading.value = false
            }
        }
    }
    
    fun refreshCatalogData() {
        android.util.Log.d("CatalogViewModel", "===== REFRESH CATALOG DATA =====")
        android.util.Log.d("CatalogViewModel", "Clearing cache to force fresh fetch")
        android.util.Log.d("CatalogViewModel", "This should reload products for the CURRENT active sponsor")
        // Clear cache to force fresh fetch
        isDataCached = false
        cachedProducts = emptyList()
        cachedSearchQuery = null
        cachedSort = "best_match"
        cachedMinPoints = null
        cachedMaxPoints = null
        cachedCategories = emptyList()
        cachedPage = 1
        cachedHasMoreData = false
    }
    
    fun getCachedProducts(): List<ProductItem> = cachedProducts
    
    fun getScrollPosition(): Int = scrollPosition
    
    fun setScrollPosition(position: Int) {
        scrollPosition = position
    }
    
    fun getCurrentProductItemId(): String? = currentProductItemId
    
    fun setCurrentProductItemId(itemId: String?) {
        currentProductItemId = itemId
    }
    
    fun getCachedFilterState(): FilterState {
        return FilterState(
            searchQuery = cachedSearchQuery,
            sort = cachedSort,
            minPoints = cachedMinPoints,
            maxPoints = cachedMaxPoints,
            categories = cachedCategories,
            currentPage = cachedPage,
            hasMoreData = cachedHasMoreData
        )
    }
    
    data class FilterState(
        val searchQuery: String?,
        val sort: String,
        val minPoints: Float?,
        val maxPoints: Float?,
        val categories: List<String>,
        val currentPage: Int,
        val hasMoreData: Boolean
    )
    
    fun toggleFavorite(
        itemId: String,
        isCurrentlyFavorite: Boolean,
        onSuccess: (Boolean) -> Unit,
        onError: (String) -> Unit
    ) {
        // Optimistically update cached products immediately
        val newFavoriteState = !isCurrentlyFavorite
        _products.value?.let { products ->
            val updatedProducts = products.map { item ->
                if (item.id == itemId) {
                    item.copy(isFavorite = newFavoriteState)
                } else {
                    item
                }
            }
            _products.value = updatedProducts
            // Update cached products if cache matches
            if (isDataCached) {
                cachedProducts = updatedProducts
            }
        }
        
        viewModelScope.launch {
            try {
                val response = if (isCurrentlyFavorite) {
                    catalogService.removeFavorite(itemId)
                } else {
                    catalogService.addFavorite(itemId)
                }
                
                if (response.success) {
                    onSuccess(newFavoriteState)
                } else {
                    // Revert optimistic update on error
                    _products.value?.let { products ->
                        val revertedProducts = products.map { item ->
                            if (item.id == itemId) {
                                item.copy(isFavorite = isCurrentlyFavorite)
                            } else {
                                item
                            }
                        }
                        _products.value = revertedProducts
                        if (isDataCached) {
                            cachedProducts = revertedProducts
                        }
                    }
                    onError(response.message ?: "Failed to update favorite")
                }
                
            } catch (e: Exception) {
                // Revert optimistic update on error
                _products.value?.let { products ->
                    val revertedProducts = products.map { item ->
                        if (item.id == itemId) {
                            item.copy(isFavorite = isCurrentlyFavorite)
                        } else {
                            item
                        }
                    }
                    _products.value = revertedProducts
                    if (isDataCached) {
                        cachedProducts = revertedProducts
                    }
                }
                onError("Network error: ${e.message}")
            }
        }
    }
    
    fun updateFavoriteInCache(itemId: String, isFavorite: Boolean) {
        // Update favorite status in cached products
        _products.value?.let { products ->
            val updatedProducts = products.map { item ->
                if (item.id == itemId) {
                    item.copy(isFavorite = isFavorite)
                } else {
                    item
                }
            }
            _products.value = updatedProducts
            if (isDataCached) {
                cachedProducts = updatedProducts
            }
        }
    }
}
