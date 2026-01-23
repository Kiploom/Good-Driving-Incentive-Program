package com.example.driverrewards.network

import com.example.driverrewards.network.NetworkClient.gson
import com.example.driverrewards.network.NetworkClient.client
import com.example.driverrewards.network.NetworkClient.baseUrl
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class CartResponse(
    val success: Boolean,
    val message: String?,
    val cart: CartData?
)

data class CartData(
    @com.google.gson.annotations.SerializedName("cart_id") val cartId: String?,
    @com.google.gson.annotations.SerializedName("total_points") val totalPoints: Int,
    @com.google.gson.annotations.SerializedName("item_count") val itemCount: Int,
    @com.google.gson.annotations.SerializedName("driver_points") val driverPoints: Int,
    val items: List<CartItem>
)

data class CartItem(
    @com.google.gson.annotations.SerializedName("cart_item_id") val cartItemId: String?,
    @com.google.gson.annotations.SerializedName("external_item_id") val externalItemId: String?,
    @com.google.gson.annotations.SerializedName("item_title") val itemTitle: String?,
    @com.google.gson.annotations.SerializedName("item_image_url") val itemImageUrl: String?,
    @com.google.gson.annotations.SerializedName("item_url") val itemUrl: String?,
    @com.google.gson.annotations.SerializedName("points_per_unit") val pointsPerUnit: Int,
    val quantity: Int,
    @com.google.gson.annotations.SerializedName("line_total_points") val lineTotalPoints: Int
)

data class CartSummaryResponse(
    val success: Boolean,
    @com.google.gson.annotations.SerializedName("cart_total") val cartTotal: Int,
    @com.google.gson.annotations.SerializedName("item_count") val itemCount: Int,
    @com.google.gson.annotations.SerializedName("driver_points") val driverPoints: Int
)

data class CartApiResponse(
    val success: Boolean,
    val message: String?,
    @com.google.gson.annotations.SerializedName("cart_total") val cartTotal: Int?,
    @com.google.gson.annotations.SerializedName("item_count") val itemCount: Int?
)

class CartService {

    suspend fun getCart(): CartResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/cart"
            val request = Request.Builder()
                .url(url)
                .get()
                .build()
            
            android.util.Log.d("CartService", "Fetching cart from: $url")
            try {
                val response = client.newCall(request).execute()
                android.util.Log.d("CartService", "Cart response code: ${response.code}")
                
                if (!response.isSuccessful) {
                    return@withContext CartResponse(
                        success = false,
                        message = "Failed to fetch cart: HTTP ${response.code}",
                        cart = null
                    )
                }
                
                // Use safe response body reading to prevent "unexpected end of stream" errors
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CartResponse(
                        success = false,
                        message = "Empty response from server",
                        cart = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CartResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CartService", "JSON parsing error: ${e.message}", e)
                    CartResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        cart = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CartService", "Failed to parse cart response: ${e.message}", e)
                    CartResponse(
                        success = false,
                        message = "Failed to parse cart response: ${e.message}",
                        cart = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CartService", "Request timeout: ${e.message}", e)
                CartResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    cart = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CartService", "Network error: ${e.message}", e)
                CartResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cart = null
                )
            } catch (e: Exception) {
                android.util.Log.e("CartService", "Unexpected error: ${e.message}", e)
                CartResponse(
                    success = false,
                    message = "Unexpected error: ${e.message}",
                    cart = null
                )
            }
        }
    }

    suspend fun addToCart(
        itemId: String,
        title: String,
        imageUrl: String,
        itemUrl: String,
        points: Int,
        quantity: Int = 1
    ): CartApiResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/cart/add"
            val requestBody = mapOf(
                "external_item_id" to itemId,
                "item_title" to title,
                "item_image_url" to imageUrl,
                "item_url" to itemUrl,
                "points_per_unit" to points,
                "quantity" to quantity
            )
            val json = gson.toJson(requestBody)
            val body = json.toRequestBody("application/json".toMediaType())
            
            val request = Request.Builder()
                .url(url)
                .post(body)
                .build()
            
            android.util.Log.d("CartService", "Adding item to cart: $itemId")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext CartApiResponse(
                        success = false,
                        message = "Failed to add to cart: HTTP ${response.code}",
                        cartTotal = null,
                        itemCount = null
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CartApiResponse(
                        success = false,
                        message = "Empty response from server",
                        cartTotal = null,
                        itemCount = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CartApiResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CartService", "JSON parsing error: ${e.message}", e)
                    CartApiResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        cartTotal = null,
                        itemCount = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CartService", "Failed to parse add to cart response: ${e.message}", e)
                    CartApiResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        cartTotal = null,
                        itemCount = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CartService", "Request timeout: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    cartTotal = null,
                    itemCount = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CartService", "Network error: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cartTotal = null,
                    itemCount = null
                )
            } catch (e: Exception) {
                android.util.Log.e("CartService", "Add to cart error: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cartTotal = null,
                    itemCount = null
                )
            }
        }
    }

    suspend fun updateCartItem(cartItemId: String, quantity: Int): CartApiResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/cart/update"
            val requestBody = mapOf(
                "cart_item_id" to cartItemId,
                "quantity" to quantity
            )
            val json = gson.toJson(requestBody)
            val body = json.toRequestBody("application/json".toMediaType())
            
            val request = Request.Builder()
                .url(url)
                .post(body)
                .build()
            
            android.util.Log.d("CartService", "Updating cart item: $cartItemId, quantity: $quantity")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext CartApiResponse(
                        success = false,
                        message = "Failed to update cart: HTTP ${response.code}",
                        cartTotal = null,
                        itemCount = null
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CartApiResponse(
                        success = false,
                        message = "Empty response from server",
                        cartTotal = null,
                        itemCount = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CartApiResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CartService", "JSON parsing error: ${e.message}", e)
                    CartApiResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        cartTotal = null,
                        itemCount = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CartService", "Failed to parse update cart response: ${e.message}", e)
                    CartApiResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        cartTotal = null,
                        itemCount = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CartService", "Request timeout: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    cartTotal = null,
                    itemCount = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CartService", "Network error: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cartTotal = null,
                    itemCount = null
                )
            } catch (e: Exception) {
                android.util.Log.e("CartService", "Update cart item error: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cartTotal = null,
                    itemCount = null
                )
            }
        }
    }

    suspend fun removeCartItem(cartItemId: String): CartApiResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/cart/remove"
            val requestBody = mapOf("cart_item_id" to cartItemId)
            val json = gson.toJson(requestBody)
            val body = json.toRequestBody("application/json".toMediaType())
            
            val request = Request.Builder()
                .url(url)
                .post(body)
                .build()
            
            android.util.Log.d("CartService", "Removing cart item: $cartItemId")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext CartApiResponse(
                        success = false,
                        message = "Failed to remove from cart: HTTP ${response.code}",
                        cartTotal = null,
                        itemCount = null
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CartApiResponse(
                        success = false,
                        message = "Empty response from server",
                        cartTotal = null,
                        itemCount = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CartApiResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CartService", "JSON parsing error: ${e.message}", e)
                    CartApiResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        cartTotal = null,
                        itemCount = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CartService", "Failed to parse remove cart response: ${e.message}", e)
                    CartApiResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        cartTotal = null,
                        itemCount = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CartService", "Request timeout: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    cartTotal = null,
                    itemCount = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CartService", "Network error: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cartTotal = null,
                    itemCount = null
                )
            } catch (e: Exception) {
                android.util.Log.e("CartService", "Remove from cart error: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cartTotal = null,
                    itemCount = null
                )
            }
        }
    }

    suspend fun clearCart(): CartApiResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/cart/clear"
            val request = Request.Builder()
                .url(url)
                .post("".toRequestBody("application/json".toMediaType()))
                .build()
            
            android.util.Log.d("CartService", "Clearing cart")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext CartApiResponse(
                        success = false,
                        message = "Failed to clear cart: HTTP ${response.code}",
                        cartTotal = null,
                        itemCount = null
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CartApiResponse(
                        success = false,
                        message = "Empty response from server",
                        cartTotal = null,
                        itemCount = null
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CartApiResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CartService", "JSON parsing error: ${e.message}", e)
                    CartApiResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        cartTotal = null,
                        itemCount = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CartService", "Failed to parse clear cart response: ${e.message}", e)
                    CartApiResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        cartTotal = null,
                        itemCount = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CartService", "Request timeout: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    cartTotal = null,
                    itemCount = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CartService", "Network error: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cartTotal = null,
                    itemCount = null
                )
            } catch (e: Exception) {
                android.util.Log.e("CartService", "Clear cart error: ${e.message}", e)
                CartApiResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    cartTotal = null,
                    itemCount = null
                )
            }
        }
    }

    suspend fun getCartSummary(): CartSummaryResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/cart/summary"
            val request = Request.Builder()
                .url(url)
                .get()
                .build()
            
            android.util.Log.d("CartService", "Fetching cart summary")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext CartSummaryResponse(
                        success = false,
                        cartTotal = 0,
                        itemCount = 0,
                        driverPoints = 0
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CartSummaryResponse(
                        success = false,
                        cartTotal = 0,
                        itemCount = 0,
                        driverPoints = 0
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CartSummaryResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CartService", "JSON parsing error: ${e.message}", e)
                    CartSummaryResponse(
                        success = false,
                        cartTotal = 0,
                        itemCount = 0,
                        driverPoints = 0
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CartService", "Failed to parse cart summary response: ${e.message}", e)
                    CartSummaryResponse(
                        success = false,
                        cartTotal = 0,
                        itemCount = 0,
                        driverPoints = 0
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CartService", "Request timeout: ${e.message}", e)
                CartSummaryResponse(
                    success = false,
                    cartTotal = 0,
                    itemCount = 0,
                    driverPoints = 0
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CartService", "Network error: ${e.message}", e)
                CartSummaryResponse(
                    success = false,
                    cartTotal = 0,
                    itemCount = 0,
                    driverPoints = 0
                )
            } catch (e: Exception) {
                android.util.Log.e("CartService", "Get cart summary error: ${e.message}", e)
                CartSummaryResponse(
                    success = false,
                    cartTotal = 0,
                    itemCount = 0,
                    driverPoints = 0
                )
            }
        }
    }

    suspend fun processCheckout(checkoutData: CheckoutRequest): CheckoutResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/checkout/process"
            val json = gson.toJson(checkoutData)
            val body = json.toRequestBody("application/json".toMediaType())
            
            val request = Request.Builder()
                .url(url)
                .post(body)
                .build()
            
            android.util.Log.d("CartService", "Processing checkout")
            try {
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext CheckoutResponse(
                        success = false,
                        message = "Failed to process checkout: HTTP ${response.code}",
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
                    android.util.Log.e("CartService", "JSON parsing error: ${e.message}", e)
                    CheckoutResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        orderId = null,
                        orderNumber = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CartService", "Failed to parse checkout response: ${e.message}", e)
                    CheckoutResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        orderId = null,
                        orderNumber = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CartService", "Request timeout: ${e.message}", e)
                CheckoutResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    orderId = null,
                    orderNumber = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CartService", "Network error: ${e.message}", e)
                CheckoutResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    orderId = null,
                    orderNumber = null
                )
            } catch (e: Exception) {
                android.util.Log.e("CartService", "Process checkout error: ${e.message}", e)
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

data class CheckoutRequest(
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

data class CheckoutResponse(
    val success: Boolean,
    val message: String?,
    @com.google.gson.annotations.SerializedName("order_id") val orderId: String?,
    @com.google.gson.annotations.SerializedName("order_number") val orderNumber: String?
)

