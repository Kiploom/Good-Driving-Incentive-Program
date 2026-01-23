package com.example.driverrewards.ui.orders

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.OrdersService
import com.example.driverrewards.network.OrderData
import kotlinx.coroutines.launch

class OrdersViewModel : ViewModel() {

    private val ordersService = OrdersService()
    
    private val _orders = MutableLiveData<List<OrderData>>()
    val orders: LiveData<List<OrderData>> = _orders
    
    private val _isLoading = MutableLiveData<Boolean>(false)
    val isLoading: LiveData<Boolean> = _isLoading
    
    private val _isLoadingMore = MutableLiveData<Boolean>(false)
    val isLoadingMore: LiveData<Boolean> = _isLoadingMore
    
    private val _hasMore = MutableLiveData<Boolean>(false)
    val hasMore: LiveData<Boolean> = _hasMore
    
    private val _errorMessage = MutableLiveData<String?>()
    val errorMessage: LiveData<String?> = _errorMessage
    
    private val _refundSuccess = MutableLiveData<Boolean>()
    val refundSuccess: LiveData<Boolean> = _refundSuccess
    
    private val _cancelSuccess = MutableLiveData<Boolean>()
    val cancelSuccess: LiveData<Boolean> = _cancelSuccess
    
    private var currentPage = 1
    private val pageSize = 20
    
    fun loadOrders(refresh: Boolean = false) {
        android.util.Log.d("OrdersViewModel", "===== LOAD ORDERS =====")
        android.util.Log.d("OrdersViewModel", "refresh: $refresh, page: $currentPage")
        android.util.Log.d("OrdersViewModel", "This should load orders ONLY from the ACTIVE sponsor environment")
        viewModelScope.launch {
            try {
                if (refresh) {
                    currentPage = 1
                    _orders.value = emptyList()
                    android.util.Log.d("OrdersViewModel", "Refreshing orders - cleared existing orders")
                }
                
                _isLoading.value = true
                _errorMessage.value = null
                
                val response = ordersService.getOrders(currentPage, pageSize)
                
                if (response.success) {
                    android.util.Log.d("OrdersViewModel", "===== ORDERS LOADED SUCCESSFULLY =====")
                    android.util.Log.d("OrdersViewModel", "Received ${response.orders.size} orders")
                    android.util.Log.d("OrdersViewModel", "These orders should ONLY be from the ACTIVE sponsor")
                    
                    // Log first few orders for debugging
                    response.orders.take(3).forEachIndexed { index, order ->
                        android.util.Log.d("OrdersViewModel", "  Order $index: ${order.orderNumber} (${order.status}, ${order.totalPoints} pts)")
                    }
                    
                    val currentOrders = _orders.value?.toMutableList() ?: mutableListOf()
                    if (refresh) {
                        currentOrders.clear()
                    }
                    currentOrders.addAll(response.orders)
                    _orders.value = currentOrders
                    _hasMore.value = response.hasMore
                    currentPage++
                } else {
                    android.util.Log.e("OrdersViewModel", "Failed to load orders: ${response.message}")
                    _errorMessage.value = response.message ?: "Failed to load orders"
                }
            } catch (e: Exception) {
                android.util.Log.e("OrdersViewModel", "Error loading orders: ${e.message}", e)
                _errorMessage.value = "Error loading orders: ${e.message}"
            } finally {
                _isLoading.value = false
            }
        }
    }
    
    fun loadMoreOrders() {
        if (_isLoadingMore.value == true || _hasMore.value == false) {
            return
        }
        
        viewModelScope.launch {
            try {
                _isLoadingMore.value = true
                
                val response = ordersService.getOrders(currentPage, pageSize)
                
                if (response.success) {
                    val currentOrders = _orders.value?.toMutableList() ?: mutableListOf()
                    currentOrders.addAll(response.orders)
                    _orders.value = currentOrders
                    _hasMore.value = response.hasMore
                    currentPage++
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error loading more orders: ${e.message}"
            } finally {
                _isLoadingMore.value = false
            }
        }
    }
    
    fun getOrderDetail(orderId: String, onSuccess: (OrderData) -> Unit, onError: (String) -> Unit) {
        viewModelScope.launch {
            try {
                val response = ordersService.getOrderDetail(orderId)
                
                if (response.success && response.order != null) {
                    onSuccess(response.order)
                } else {
                    onError(response.message ?: "Failed to load order details")
                }
            } catch (e: Exception) {
                onError("Error loading order details: ${e.message}")
            }
        }
    }
    
    fun refundOrder(orderId: String) {
        viewModelScope.launch {
            try {
                _errorMessage.value = null
                
                val response = ordersService.refundOrder(orderId)
                
                if (response.success) {
                    _refundSuccess.value = true
                    // Reload orders to get updated status
                    loadOrders(refresh = true)
                } else {
                    _errorMessage.value = response.message ?: "Failed to refund order"
                    _refundSuccess.value = false
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error refunding order: ${e.message}"
                _refundSuccess.value = false
            }
        }
    }
    
    fun cancelOrder(orderId: String) {
        viewModelScope.launch {
            try {
                _errorMessage.value = null
                
                val response = ordersService.cancelOrder(orderId)
                
                if (response.success) {
                    _cancelSuccess.value = true
                    // Reload orders to get updated status
                    loadOrders(refresh = true)
                } else {
                    _errorMessage.value = response.message ?: "Failed to cancel order"
                    _cancelSuccess.value = false
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error cancelling order: ${e.message}"
                _cancelSuccess.value = false
            }
        }
    }
    
    fun refreshOrders() {
        android.util.Log.d("OrdersViewModel", "===== REFRESH ORDERS =====")
        android.util.Log.d("OrdersViewModel", "This should reload orders for the CURRENT active sponsor")
        loadOrders(refresh = true)
    }
}
