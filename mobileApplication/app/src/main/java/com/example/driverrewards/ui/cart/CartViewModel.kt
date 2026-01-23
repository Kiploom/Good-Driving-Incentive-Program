package com.example.driverrewards.ui.cart

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.CartService
import com.example.driverrewards.network.CartItem as NetworkCartItem
import kotlinx.coroutines.launch

class CartViewModel : ViewModel() {

    private val cartService = CartService()
    
    // Cart caching
    private var cachedCartItems: List<NetworkCartItem>? = null
    private var isCartCached: Boolean = false
    
    // Scroll position saving
    private var savedScrollPosition: Int = 0
    
    private val _cartItems = MutableLiveData<List<NetworkCartItem>>()
    val cartItems: LiveData<List<NetworkCartItem>> = _cartItems
    
    private val _totalPoints = MutableLiveData<Int>(0)
    val totalPoints: LiveData<Int> = _totalPoints
    
    private val _itemCount = MutableLiveData<Int>(0)
    val itemCount: LiveData<Int> = _itemCount
    
    private val _driverPoints = MutableLiveData<Int>(0)
    val driverPoints: LiveData<Int> = _driverPoints
    
    private val _isLoading = MutableLiveData<Boolean>(false)
    val isLoading: LiveData<Boolean> = _isLoading
    
    private val _errorMessage = MutableLiveData<String?>()
    val errorMessage: LiveData<String?> = _errorMessage
    
    private val _addToCartSuccess = MutableLiveData<Boolean?>()
    val addToCartSuccess: LiveData<Boolean?> = _addToCartSuccess
    
    fun loadCart() {
        android.util.Log.d("CartViewModel", "===== LOAD CART =====")
        android.util.Log.d("CartViewModel", "This should load cart items for the ACTIVE sponsor environment")
        // Return cached data immediately if available
        if (isCartCached && cachedCartItems != null) {
            android.util.Log.d("CartViewModel", "Using cached cart data (${cachedCartItems!!.size} items)")
            _cartItems.value = cachedCartItems!!
            return
        }
        
        android.util.Log.d("CartViewModel", "Fetching cart from server (cache miss or refresh)")
        viewModelScope.launch {
            try {
                _isLoading.value = true
                _errorMessage.value = null
                
                val response = cartService.getCart()
                
                if (response.success && response.cart != null) {
                    android.util.Log.d("CartViewModel", "===== CART LOADED SUCCESSFULLY =====")
                    android.util.Log.d("CartViewModel", "Cart data:")
                    android.util.Log.d("CartViewModel", "  - itemCount: ${response.cart.itemCount}")
                    android.util.Log.d("CartViewModel", "  - totalPoints: ${response.cart.totalPoints}")
                    android.util.Log.d("CartViewModel", "  - driverPoints: ${response.cart.driverPoints}")
                    android.util.Log.d("CartViewModel", "  - items: ${response.cart.items.size}")
                    android.util.Log.d("CartViewModel", "This cart should belong to the ACTIVE sponsor")
                    
                    // Log first few items for debugging
                    response.cart.items.take(3).forEachIndexed { index, item ->
                        android.util.Log.d("CartViewModel", "  Cart item $index: ${item.itemTitle} (${item.pointsPerUnit} pts, qty: ${item.quantity})")
                    }
                    
                    // Cache the cart items
                    cachedCartItems = response.cart.items
                    isCartCached = true
                    
                    _cartItems.value = response.cart.items
                    _totalPoints.value = response.cart.totalPoints
                    _itemCount.value = response.cart.itemCount
                    _driverPoints.value = response.cart.driverPoints
                } else {
                    android.util.Log.e("CartViewModel", "Failed to load cart: ${response.message}")
                    _errorMessage.value = response.message ?: "Failed to load cart"
                }
            } catch (e: Exception) {
                android.util.Log.e("CartViewModel", "Error loading cart: ${e.message}", e)
                _errorMessage.value = "Error loading cart: ${e.message}"
            } finally {
                _isLoading.value = false
            }
        }
    }
    
    fun addToCart(
        itemId: String,
        title: String,
        imageUrl: String,
        itemUrl: String,
        points: Int,
        quantity: Int = 1
    ) {
        viewModelScope.launch {
            try {
                _errorMessage.value = null
                
                val response = cartService.addToCart(itemId, title, imageUrl, itemUrl, points, quantity)
                
                if (response.success) {
                    _addToCartSuccess.value = true
                    _totalPoints.value = response.cartTotal ?: 0
                    _itemCount.value = response.itemCount ?: 0
                    // Invalidate cache and reload cart
                    isCartCached = false
                    cachedCartItems = null
                    loadCart()
                } else {
                    _errorMessage.value = response.message ?: "Failed to add to cart"
                    _addToCartSuccess.value = false
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error adding to cart: ${e.message}"
                _addToCartSuccess.value = false
            }
        }
    }
    
    fun updateQuantity(cartItemId: String, quantity: Int) {
        viewModelScope.launch {
            try {
                _errorMessage.value = null
                
                val response = cartService.updateCartItem(cartItemId, quantity)
                
                if (response.success) {
                    _totalPoints.value = response.cartTotal ?: 0
                    _itemCount.value = response.itemCount ?: 0
                    // Invalidate cache and reload
                    isCartCached = false
                    cachedCartItems = null
                    loadCart()
                } else {
                    _errorMessage.value = response.message ?: "Failed to update cart"
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error updating cart: ${e.message}"
            }
        }
    }
    
    fun removeItem(cartItemId: String) {
        viewModelScope.launch {
            try {
                _errorMessage.value = null
                
                val response = cartService.removeCartItem(cartItemId)
                
                if (response.success) {
                    _totalPoints.value = response.cartTotal ?: 0
                    _itemCount.value = response.itemCount ?: 0
                    // Invalidate cache and reload
                    isCartCached = false
                    cachedCartItems = null
                    loadCart()
                } else {
                    _errorMessage.value = response.message ?: "Failed to remove item"
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error removing item: ${e.message}"
            }
        }
    }
    
    fun clearCart() {
        viewModelScope.launch {
            try {
                _errorMessage.value = null
                
                val response = cartService.clearCart()
                
                if (response.success) {
                    // Clear cache
                    cachedCartItems = emptyList()
                    isCartCached = true
                    _cartItems.value = emptyList()
                    _totalPoints.value = 0
                    _itemCount.value = 0
                } else {
                    _errorMessage.value = response.message ?: "Failed to clear cart"
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error clearing cart: ${e.message}"
            }
        }
    }
    
    fun refreshCart() {
        android.util.Log.d("CartViewModel", "===== REFRESH CART =====")
        android.util.Log.d("CartViewModel", "Clearing cache to force fresh fetch")
        android.util.Log.d("CartViewModel", "This should reload cart for the CURRENT active sponsor")
        // Invalidate cache on refresh
        isCartCached = false
        cachedCartItems = null
        loadCart()
    }
    
    fun setScrollPosition(position: Int) {
        savedScrollPosition = position
    }
    
    fun getScrollPosition(): Int = savedScrollPosition
    
    fun clearError() {
        _errorMessage.value = null
    }
    
    fun clearAddToCartSuccess() {
        _addToCartSuccess.value = null
    }
    
    private val _checkoutSuccess = MutableLiveData<CheckoutResult?>()
    val checkoutSuccess: LiveData<CheckoutResult?> = _checkoutSuccess
    
    data class CheckoutResult(
        val orderId: String,
        val orderNumber: String
    )
    
    fun processCheckout(
        firstName: String,
        lastName: String,
        email: String,
        shippingStreet: String,
        shippingCity: String,
        shippingState: String,
        shippingPostal: String,
        shippingCountry: String,
        shippingCostPoints: Int = 0
    ) {
        // Check balance before processing
        val totalCost = _totalPoints.value ?: 0
        val balance = _driverPoints.value ?: 0
        if (totalCost > balance) {
            _errorMessage.value = "Insufficient points. You have $balance pts but need $totalCost pts."
            return
        }
        
        viewModelScope.launch {
            try {
                _isLoading.value = true
                _errorMessage.value = null
                
                val response = cartService.processCheckout(
                    com.example.driverrewards.network.CheckoutRequest(
                        firstName = firstName,
                        lastName = lastName,
                        email = email,
                        shippingStreet = shippingStreet,
                        shippingCity = shippingCity,
                        shippingState = shippingState,
                        shippingPostal = shippingPostal,
                        shippingCountry = shippingCountry,
                        shippingCostPoints = shippingCostPoints
                    )
                )
                
                if (response.success) {
                    val orderId = response.orderId ?: ""
                    val orderNumber = response.orderNumber ?: ""
                    _checkoutSuccess.value = CheckoutResult(orderId, orderNumber)
                    // Clear cart after successful checkout
                    cachedCartItems = emptyList()
                    isCartCached = true
                    _cartItems.value = emptyList()
                    _totalPoints.value = 0
                    _itemCount.value = 0
                    // Refresh to get updated driver points
                    isCartCached = false
                    cachedCartItems = null
                    loadCart()
                } else {
                    _errorMessage.value = response.message ?: "Failed to process checkout"
                    _checkoutSuccess.value = null
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error processing checkout: ${e.message}"
                _checkoutSuccess.value = null
            } finally {
                _isLoading.value = false
            }
        }
    }
}
