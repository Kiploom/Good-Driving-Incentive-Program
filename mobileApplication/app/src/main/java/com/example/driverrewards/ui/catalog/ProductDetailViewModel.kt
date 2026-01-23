package com.example.driverrewards.ui.catalog

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.CatalogService
import com.example.driverrewards.network.ProductDetail
import com.example.driverrewards.network.RelatedProduct
import com.example.driverrewards.network.VariationDetail
import kotlinx.coroutines.launch

class ProductDetailViewModel : ViewModel() {
    
    private val catalogService = CatalogService()
    
    private val _product = MutableLiveData<ProductDetail?>()
    val product: LiveData<ProductDetail?> = _product
    
    private val _relatedProducts = MutableLiveData<List<RelatedProduct>>()
    val relatedProducts: LiveData<List<RelatedProduct>> = _relatedProducts
    
    private val _loading = MutableLiveData<Boolean>()
    val loading: LiveData<Boolean> = _loading
    
    private val _error = MutableLiveData<String?>()
    val error: LiveData<String?> = _error
    
    private val _selectedVariation = MutableLiveData<VariationDetail?>()
    val selectedVariation: LiveData<VariationDetail?> = _selectedVariation
    
    private val _variantSelections = MutableLiveData<Map<String, String>>()
    val variantSelections: LiveData<Map<String, String>> = _variantSelections
    
    // Caching for product details
    private val productCache = mutableMapOf<String, ProductDetail>()
    private val relatedProductsCache = mutableMapOf<String, List<RelatedProduct>>()
    private val variantSelectionsCache = mutableMapOf<String, Map<String, String>>()
    private var currentItemId: String? = null
    
    init {
        _variantSelections.value = emptyMap()
        _selectedVariation.value = null
    }
    
    fun loadProductDetail(itemId: String, skipCachedSelections: Boolean = false) {
        android.util.Log.d("ProductDetailViewModel", "=== loadProductDetail START ===")
        android.util.Log.d("ProductDetailViewModel", "itemId: '$itemId', skipCachedSelections: $skipCachedSelections")
        
        // Check if we're switching to a different product
        val isSwitchingProduct = currentItemId != null && currentItemId != itemId
        android.util.Log.d("ProductDetailViewModel", "isSwitchingProduct: $isSwitchingProduct, currentItemId: '$currentItemId'")
        
        // If switching to a different product, clear old data immediately
        if (isSwitchingProduct) {
            android.util.Log.d("ProductDetailViewModel", "Switching product - clearing old data")
            _product.value = null
            _relatedProducts.value = emptyList()
            _selectedVariation.value = null
            _variantSelections.value = emptyMap()
        }
        
        currentItemId = itemId
        
        // Check if product is cached
        val cachedProduct = productCache[itemId]
        val cachedRelated = relatedProductsCache[itemId]
        val cachedSelections = variantSelectionsCache[itemId]
        
        android.util.Log.d("ProductDetailViewModel", "Cache check - cachedProduct: ${cachedProduct != null}, cachedSelections: $cachedSelections")
        
        if (cachedProduct != null) {
            android.util.Log.d("ProductDetailViewModel", "Product is cached, loading from cache")
            // Use cached data - load immediately after clearing old data
            _product.value = cachedProduct
            _relatedProducts.value = cachedRelated ?: emptyList()
            // Only restore variant selections if not explicitly skipping (i.e., when we have navigation args)
            if (!skipCachedSelections) {
                android.util.Log.d("ProductDetailViewModel", "Not skipping cached selections, restoring: $cachedSelections")
                cachedSelections?.let {
                    android.util.Log.d("ProductDetailViewModel", "Restoring cached selections: $it")
                    _variantSelections.value = it
                    findMatchingVariation(it)
                } ?: run {
                    android.util.Log.d("ProductDetailViewModel", "No cached selections to restore")
                }
            } else {
                android.util.Log.d("ProductDetailViewModel", "Skipping cached selections - clearing state")
                // Clear any existing selections when skipping cached selections
                _variantSelections.value = emptyMap()
                _selectedVariation.value = null
                android.util.Log.d("ProductDetailViewModel", "State cleared - _variantSelections is now empty, _selectedVariation is null")
            }
            _loading.value = false
            android.util.Log.d("ProductDetailViewModel", "Returning early (cached product loaded)")
            return
        }
        
        android.util.Log.d("ProductDetailViewModel", "Product not cached, loading from network")
        
        viewModelScope.launch {
            try {
                _loading.value = true
                _error.value = null
                
                val response = catalogService.getProductDetail(itemId)
                
                if (response.success && response.product != null) {
                    // Cache the product data
                    productCache[itemId] = response.product
                    relatedProductsCache[itemId] = response.related_items ?: emptyList()
                    
                    _product.value = response.product
                    _relatedProducts.value = response.related_items ?: emptyList()
                } else {
                    _error.value = response.message ?: "Failed to load product details"
                }
            } catch (e: Exception) {
                _error.value = "Error loading product: ${e.message ?: "Unknown error"}"
            } finally {
                _loading.value = false
            }
        }
    }
    
    fun toggleFavorite(itemId: String, isCurrentlyFavorite: Boolean, onFavoriteToggled: ((Boolean) -> Unit)? = null) {
        // Optimistically update UI immediately
        _product.value?.let { product ->
            val updatedProduct = product.copy(is_favorite = !isCurrentlyFavorite)
            _product.value = updatedProduct
            // Update cache immediately
            productCache[itemId] = updatedProduct
        }
        
        viewModelScope.launch {
            try {
                val response = if (isCurrentlyFavorite) {
                    catalogService.removeFavorite(itemId)
                } else {
                    catalogService.addFavorite(itemId)
                }
                
                if (response.success) {
                    // Notify callback
                    onFavoriteToggled?.invoke(!isCurrentlyFavorite)
                } else {
                    // Revert on error
                    _product.value?.let { product ->
                        val revertedProduct = product.copy(is_favorite = isCurrentlyFavorite)
                        _product.value = revertedProduct
                        productCache[itemId] = revertedProduct
                    }
                    _error.value = response.message ?: "Failed to update favorite"
                    onFavoriteToggled?.invoke(isCurrentlyFavorite)
                }
            } catch (e: Exception) {
                // Revert on error
                _product.value?.let { product ->
                    val revertedProduct = product.copy(is_favorite = isCurrentlyFavorite)
                    _product.value = revertedProduct
                    productCache[itemId] = revertedProduct
                }
                _error.value = "Error updating favorite: ${e.message ?: "Unknown error"}"
                onFavoriteToggled?.invoke(isCurrentlyFavorite)
            }
        }
    }
    
    fun selectVariant(variantType: String, value: String) {
        val currentSelections = _variantSelections.value?.toMutableMap() ?: mutableMapOf()
        if (value.isNotEmpty()) {
            currentSelections[variantType] = value
        } else {
            currentSelections.remove(variantType)
        }
        _variantSelections.value = currentSelections
        
        // Cache variant selections
        currentItemId?.let { itemId ->
            variantSelectionsCache[itemId] = currentSelections.toMap()
        }
        
        // Find matching variation
        findMatchingVariation(currentSelections)
    }
    
    private fun findMatchingVariation(selections: Map<String, String>) {
        val product = _product.value ?: return
        val variationDetails = product.variation_details ?: return
        
        if (selections.isEmpty()) {
            _selectedVariation.value = null
            return
        }
        
        // Find variation that matches all selected attributes
        for (variation in variationDetails) {
            val variantMap = variation.variants ?: continue
            var matches = true
            
            for ((key, value) in selections) {
                if (variantMap[key] != value) {
                    matches = false
                    break
                }
            }
            
            if (matches) {
                _selectedVariation.value = variation
                return
            }
        }
        
        // No exact match found
        _selectedVariation.value = null
    }
    
    fun clearVariantSelection() {
        _variantSelections.value = emptyMap()
        _selectedVariation.value = null
    }
    
    fun clearCachedVariantSelections(itemId: String) {
        variantSelectionsCache.remove(itemId)
    }
    
    fun updateProductFavorite(product: ProductDetail) {
        _product.value = product
        // Update cache
        product.id?.let { itemId ->
            productCache[itemId] = product
        }
    }
}
