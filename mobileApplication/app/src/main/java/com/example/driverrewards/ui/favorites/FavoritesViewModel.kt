package com.example.driverrewards.ui.favorites

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.CatalogService
import com.example.driverrewards.ui.catalog.ProductItem
import kotlinx.coroutines.launch

class FavoritesViewModel : ViewModel() {

    private val catalogService = CatalogService()
    
    private val _products = MutableLiveData<List<ProductItem>>()
    val products: LiveData<List<ProductItem>> = _products
    
    private val _loading = MutableLiveData<Boolean>()
    val loading: LiveData<Boolean> = _loading
    
    private val _error = MutableLiveData<String?>()
    val error: LiveData<String?> = _error
    
    // Caching state
    private var cachedProducts: List<ProductItem> = emptyList()
    private var cachedPage: Int = 1
    private var cachedHasMoreData: Boolean = false
    private var isDataCached: Boolean = false
    private var scrollPosition: Int = 0

    fun loadFavorites(
        page: Int = 1,
        sort: String = "best_match",
        onSuccess: (List<ProductItem>, Boolean) -> Unit,
        onError: (String) -> Unit
    ) {
        android.util.Log.d("FavoritesViewModel", "===== LOAD FAVORITES =====")
        android.util.Log.d("FavoritesViewModel", "page: $page, sort: $sort")
        android.util.Log.d("FavoritesViewModel", "This should load favorites filtered by the ACTIVE sponsor environment")
        
        // Check if data is cached (only for page 1)
        if (page == 1 && isDataCached) {
            android.util.Log.d("FavoritesViewModel", "Using cached favorites data")
            _products.value = cachedProducts
            onSuccess(cachedProducts, cachedHasMoreData)
            return
        }
        
        viewModelScope.launch {
            try {
                _loading.value = true
                _error.value = null
                
                // Load favorites with favoritesOnly=true and no search query
                val response = catalogService.getCatalogData(
                    page = page,
                    pageSize = 48,
                    searchQuery = null,
                    sort = sort,
                    categories = null,
                    minPoints = null,
                    maxPoints = null,
                    favoritesOnly = true
                )
                
                if (response.success) {
                    android.util.Log.d("FavoritesViewModel", "===== FAVORITES LOADED SUCCESSFULLY =====")
                    android.util.Log.d("FavoritesViewModel", "Received ${response.items.size} favorite items")
                    android.util.Log.d("FavoritesViewModel", "These favorites should be filtered by the ACTIVE sponsor environment")
                    
                    val items = response.items.map { itemData ->
                        ProductItem(
                            id = itemData.id ?: "",
                            title = itemData.title ?: "Unknown Product",
                            points = itemData.points?.toInt() ?: 0,
                            imageUrl = itemData.image,
                            availability = itemData.availability ?: "IN_STOCK",
                            isFavorite = true, // All items in favorites are favorited
                            isPinned = itemData.isPinned ?: false
                        )
                    }
                    
                    // Log first few items for debugging
                    items.take(3).forEachIndexed { index, item ->
                        android.util.Log.d("FavoritesViewModel", "  Favorite $index: ${item.title} (${item.points} pts)")
                    }
                    
                    // Cache data only for page 1
                    if (page == 1) {
                        cachedProducts = items
                        cachedPage = page
                        cachedHasMoreData = response.has_more
                        isDataCached = true
                        android.util.Log.d("FavoritesViewModel", "Cached favorites data for page 1")
                    }
                    
                    _products.value = items
                    onSuccess(items, response.has_more)
                } else {
                    val errorMessage = response.message ?: "Failed to load favorites"
                    _error.value = errorMessage
                    onError(errorMessage)
                }
            } catch (e: Exception) {
                val errorMessage = "Error loading favorites: ${e.message ?: "Unknown error"}"
                _error.value = errorMessage
                onError(errorMessage)
            } finally {
                _loading.value = false
            }
        }
    }

    fun refreshFavorites() {
        android.util.Log.d("FavoritesViewModel", "===== REFRESH FAVORITES =====")
        android.util.Log.d("FavoritesViewModel", "Clearing cache to force fresh fetch")
        android.util.Log.d("FavoritesViewModel", "This should reload favorites for the CURRENT active sponsor")
        // Clear cache to force fresh fetch
        isDataCached = false
        cachedProducts = emptyList()
        cachedPage = 1
        cachedHasMoreData = false
    }

    fun getCachedProducts(): List<ProductItem> = cachedProducts

    fun getScrollPosition(): Int = scrollPosition

    fun setScrollPosition(position: Int) {
        scrollPosition = position
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
                    // If item was removed from favorites, refresh to remove from list
                    if (isCurrentlyFavorite) {
                        refreshFavorites()
                        loadFavorites(1, "best_match", { _: List<com.example.driverrewards.ui.catalog.ProductItem>, _: Boolean -> }, { _: String -> })
                    }
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
}

