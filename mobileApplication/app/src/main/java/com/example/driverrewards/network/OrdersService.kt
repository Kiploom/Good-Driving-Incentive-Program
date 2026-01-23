package com.example.driverrewards.network

import com.example.driverrewards.network.NetworkClient.gson
import com.example.driverrewards.network.NetworkClient.client
import com.example.driverrewards.network.NetworkClient.baseUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import com.example.driverrewards.network.CheckoutResponse

data class OrdersResponse(
    val success: Boolean,
    val message: String?,
    val orders: List<OrderData>,
    val page: Int,
    @com.google.gson.annotations.SerializedName("page_size") val pageSize: Int,
    val total: Int,
    @com.google.gson.annotations.SerializedName("has_more") val hasMore: Boolean
)

data class OrderData(
    @com.google.gson.annotations.SerializedName("order_id") val orderId: String?,
    @com.google.gson.annotations.SerializedName("order_number") val orderNumber: String?,
    @com.google.gson.annotations.SerializedName("total_points") val totalPoints: Int,
    val status: String?,
    @com.google.gson.annotations.SerializedName("created_at") val createdAt: String?,
    @com.google.gson.annotations.SerializedName("can_refund") val canRefund: Boolean,
    @com.google.gson.annotations.SerializedName("refund_time_remaining") val refundTimeRemaining: Int,
    @com.google.gson.annotations.SerializedName("order_items") val orderItems: List<OrderItem>
)

data class OrderItem(
    val title: String?,
    @com.google.gson.annotations.SerializedName("unit_points") val unitPoints: Int,
    val quantity: Int,
    @com.google.gson.annotations.SerializedName("line_total_points") val lineTotalPoints: Int,
    @com.google.gson.annotations.SerializedName("created_at") val createdAt: String?,
    @com.google.gson.annotations.SerializedName("external_item_id") val externalItemId: String?,
    @com.google.gson.annotations.SerializedName("variation_info") val variationInfo: String?
)

data class OrderDetailResponse(
    val success: Boolean,
    val message: String?,
    val order: OrderData?
)

data class RefundResponse(
    val success: Boolean,
    val message: String?,
    @com.google.gson.annotations.SerializedName("points_refunded") val pointsRefunded: Int?,
    @com.google.gson.annotations.SerializedName("balance_after") val balanceAfter: Int?
)

data class CancelResponse(
    val success: Boolean,
    val message: String?,
    @com.google.gson.annotations.SerializedName("points_refunded") val pointsRefunded: Int?,
    @com.google.gson.annotations.SerializedName("balance_after") val balanceAfter: Int?
)

class OrdersService {

    suspend fun getOrders(page: Int = 1, pageSize: Int = 20): OrdersResponse {
        return withContext(Dispatchers.IO) {
            val urlBuilder = "$baseUrl/api/mobile/orders".toHttpUrlOrNull()?.newBuilder()
                ?: throw Exception("Invalid base URL: $baseUrl")
            
            urlBuilder.addQueryParameter("page", page.toString())
            urlBuilder.addQueryParameter("page_size", pageSize.toString())
            
            val url = urlBuilder.build()
            val request = Request.Builder()
                .url(url)
                .get()
                .build()
            
            android.util.Log.d("OrdersService", "Fetching orders: page=$page, pageSize=$pageSize")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext OrdersResponse(
                        success = false,
                        message = "Failed to fetch orders: HTTP ${response.code}",
                        orders = emptyList(),
                        page = page,
                        pageSize = pageSize,
                        total = 0,
                        hasMore = false
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext OrdersResponse(
                        success = false,
                        message = "Empty response from server",
                        orders = emptyList(),
                        page = page,
                        pageSize = pageSize,
                        total = 0,
                        hasMore = false
                    )
                }
                
                try {
                    gson.fromJson(responseBody, OrdersResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("OrdersService", "JSON parsing error: ${e.message}", e)
                    OrdersResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        orders = emptyList(),
                        page = page,
                        pageSize = pageSize,
                        total = 0,
                        hasMore = false
                    )
                } catch (e: Exception) {
                    android.util.Log.e("OrdersService", "Failed to parse orders response: ${e.message}", e)
                    OrdersResponse(
                        success = false,
                        message = "Failed to parse orders response: ${e.message}",
                        orders = emptyList(),
                        page = page,
                        pageSize = pageSize,
                        total = 0,
                        hasMore = false
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("OrdersService", "Request timeout: ${e.message}", e)
                OrdersResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    orders = emptyList(),
                    page = page,
                    pageSize = pageSize,
                    total = 0,
                    hasMore = false
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("OrdersService", "Network error: ${e.message}", e)
                OrdersResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    orders = emptyList(),
                    page = page,
                    pageSize = pageSize,
                    total = 0,
                    hasMore = false
                )
            } catch (e: Exception) {
                android.util.Log.e("OrdersService", "Get orders error: ${e.message}", e)
                OrdersResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    orders = emptyList(),
                    page = page,
                    pageSize = pageSize,
                    total = 0,
                    hasMore = false
                )
            }
        }
    }

    suspend fun getOrderDetail(orderId: String): OrderDetailResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/orders/$orderId"
            
            val request = Request.Builder()
                .url(url)
                .get()
                .build()
            
            android.util.Log.d("OrdersService", "Fetching order detail: $orderId")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext OrderDetailResponse(
                        success = false,
                        message = "Failed to fetch order detail: HTTP ${response.code}",
                        order = null
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext OrderDetailResponse(
                        success = false,
                        message = "Empty response from server",
                        order = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, OrderDetailResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("OrdersService", "JSON parsing error: ${e.message}", e)
                    OrderDetailResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        order = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("OrdersService", "Failed to parse order detail response: ${e.message}", e)
                    OrderDetailResponse(
                        success = false,
                        message = "Failed to parse order detail response: ${e.message}",
                        order = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("OrdersService", "Request timeout: ${e.message}", e)
                OrderDetailResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    order = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("OrdersService", "Network error: ${e.message}", e)
                OrderDetailResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    order = null
                )
            } catch (e: Exception) {
                android.util.Log.e("OrdersService", "Get order detail error: ${e.message}", e)
                OrderDetailResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    order = null
                )
            }
        }
    }

    suspend fun refundOrder(orderId: String): RefundResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/orders/$orderId/refund"
            
            val request = Request.Builder()
                .url(url)
                .post("".toRequestBody("application/json".toMediaType()))
                .build()
            
            android.util.Log.d("OrdersService", "Refunding order: $orderId")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext RefundResponse(
                        success = false,
                        message = "Failed to refund order: HTTP ${response.code}",
                        pointsRefunded = null,
                        balanceAfter = null
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext RefundResponse(
                        success = false,
                        message = "Empty response from server",
                        pointsRefunded = null,
                        balanceAfter = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, RefundResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("OrdersService", "JSON parsing error: ${e.message}", e)
                    RefundResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        pointsRefunded = null,
                        balanceAfter = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("OrdersService", "Failed to parse refund response: ${e.message}", e)
                    RefundResponse(
                        success = false,
                        message = "Failed to parse refund response: ${e.message}",
                        pointsRefunded = null,
                        balanceAfter = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("OrdersService", "Request timeout: ${e.message}", e)
                RefundResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    pointsRefunded = null,
                    balanceAfter = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("OrdersService", "Network error: ${e.message}", e)
                RefundResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    pointsRefunded = null,
                    balanceAfter = null
                )
            } catch (e: Exception) {
                android.util.Log.e("OrdersService", "Refund order error: ${e.message}", e)
                RefundResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    pointsRefunded = null,
                    balanceAfter = null
                )
            }
        }
    }

    suspend fun cancelOrder(orderId: String): CancelResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/orders/$orderId/cancel"
            
            val request = Request.Builder()
                .url(url)
                .post("".toRequestBody("application/json".toMediaType()))
                .build()
            
            android.util.Log.d("OrdersService", "Cancelling order: $orderId")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext CancelResponse(
                        success = false,
                        message = "Failed to cancel order: HTTP ${response.code}",
                        pointsRefunded = null,
                        balanceAfter = null
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CancelResponse(
                        success = false,
                        message = "Empty response from server",
                        pointsRefunded = null,
                        balanceAfter = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CancelResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("OrdersService", "JSON parsing error: ${e.message}", e)
                    CancelResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        pointsRefunded = null,
                        balanceAfter = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("OrdersService", "Failed to parse cancel response: ${e.message}", e)
                    CancelResponse(
                        success = false,
                        message = "Failed to parse cancel response: ${e.message}",
                        pointsRefunded = null,
                        balanceAfter = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("OrdersService", "Request timeout: ${e.message}", e)
                CancelResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    pointsRefunded = null,
                    balanceAfter = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("OrdersService", "Network error: ${e.message}", e)
                CancelResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    pointsRefunded = null,
                    balanceAfter = null
                )
            } catch (e: Exception) {
                android.util.Log.e("OrdersService", "Cancel order error: ${e.message}", e)
                CancelResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    pointsRefunded = null,
                    balanceAfter = null
                )
            }
        }
    }

    suspend fun reorderCheckout(orderId: String, request: ReorderCheckoutRequest): CheckoutResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/orders/$orderId/reorder"
            
            val json = gson.toJson(request)
            val requestBody = json.toRequestBody("application/json".toMediaType())
            
            val httpRequest = Request.Builder()
                .url(url)
                .post(requestBody)
                .build()
            
            android.util.Log.d("OrdersService", "Re-ordering checkout for order: $orderId")
            try {
                val response = client.newCall(httpRequest).execute()
                
                if (!response.isSuccessful) {
                    return@withContext CheckoutResponse(
                        success = false,
                        message = "Failed to process reorder checkout: HTTP ${response.code}",
                        orderId = null,
                        orderNumber = null
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CheckoutResponse(
                        success = false,
                        message = "Empty response from server",
                        orderId = null,
                        orderNumber = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CheckoutResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("OrdersService", "JSON parsing error: ${e.message}", e)
                    CheckoutResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        orderId = null,
                        orderNumber = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("OrdersService", "Failed to parse reorder checkout response: ${e.message}", e)
                    CheckoutResponse(
                        success = false,
                        message = "Failed to parse reorder checkout response: ${e.message}",
                        orderId = null,
                        orderNumber = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("OrdersService", "Request timeout: ${e.message}", e)
                CheckoutResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    orderId = null,
                    orderNumber = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("OrdersService", "Network error: ${e.message}", e)
                CheckoutResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    orderId = null,
                    orderNumber = null
                )
            } catch (e: Exception) {
                android.util.Log.e("OrdersService", "Reorder checkout error: ${e.message}", e)
                CheckoutResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    orderId = null,
                    orderNumber = null
                )
            }
        }
    }
}

data class ReorderCheckoutRequest(
    @com.google.gson.annotations.SerializedName("first_name") val firstName: String,
    @com.google.gson.annotations.SerializedName("last_name") val lastName: String,
    val email: String,
    @com.google.gson.annotations.SerializedName("shipping_street") val shippingStreet: String,
    @com.google.gson.annotations.SerializedName("shipping_city") val shippingCity: String,
    @com.google.gson.annotations.SerializedName("shipping_state") val shippingState: String,
    @com.google.gson.annotations.SerializedName("shipping_postal") val shippingPostal: String,
    @com.google.gson.annotations.SerializedName("shipping_country") val shippingCountry: String,
    @com.google.gson.annotations.SerializedName("shipping_cost_points") val shippingCostPoints: Int = 0
)

