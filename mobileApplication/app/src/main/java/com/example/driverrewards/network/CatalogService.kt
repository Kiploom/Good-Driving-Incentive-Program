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
import java.net.URLEncoder

data class CatalogResponse(
    val success: Boolean,
    val message: String?,
    val items: List<CatalogItem>,
    val page: Int,
    val page_size: Int,
    val total: Int,
    val has_more: Boolean
)

data class CatalogItem(
    val id: String?,
    val title: String?,
    val points: Double?,
    val image: String?,
    val availability: String?,
    @com.google.gson.annotations.SerializedName("is_favorite") val isFavorite: Boolean?,
    @com.google.gson.annotations.SerializedName("is_pinned") val isPinned: Boolean?
)

data class FavoriteResponse(
    val success: Boolean,
    val message: String?
)

data class ProductDetailResponse(
    val success: Boolean,
    val message: String?,
    val product: ProductDetail?,
    val related_items: List<RelatedProduct>?
)

data class ProductDetail(
    val id: String?,
    val title: String?,
    val subtitle: String?,
    val points: Double?,
    val display_points: String?,
    val price: Double?,
    val image: String?,
    val additional_images: List<String>?,
    val availability: String?,
    val availability_threshold: String?,
    val estimated_quantity: Int?,
    val stock_qty: Int?,
    val low_stock: Boolean?,
    val no_stock: Boolean?,
    val available: Boolean?,
    val condition: String?,
    val brand: String?,
    val description: String?,
    val item_specifics: Map<String, String>?,
    val variants: Map<String, List<String>>?,
    val variation_details: List<VariationDetail>?,
    val url: String?,
    val is_favorite: Boolean?,
    val seller: Map<String, Any>?
)

data class VariationDetail(
    val variants: Map<String, String>?,
    val price: Double?,
    val image: String?,
    val additional_images: List<String>?,
    val availability_threshold: String?,
    val estimated_quantity: Int?,
    val stock_qty: Int?,
    val low_stock: Boolean?,
    val no_stock: Boolean?,
    val available: Boolean?
)

data class RelatedProduct(
    val id: String?,
    val title: String?,
    val points: Double?,
    val image: String?,
    val availability: String?,
    val low_stock: Boolean?,
    val no_stock: Boolean?,
    val available: Boolean?,
    val stock_qty: Int?
)

data class CategoryResponse(
    val success: Boolean,
    val message: String?,
    val categories: List<CategoryItem>,
    val category_tree: Map<String, Any>? = null,
    val parent_categories: Map<String, String>? = null
)

data class CategoryItem(
    val id: String,
    val name: String,
    val is_parent: Boolean?
)

class CatalogService {

    suspend fun testConnectivity(): CatalogResponse {
        return withContext(Dispatchers.IO) {
            try {
                val url = "$baseUrl/api/mobile/catalog/test"
                val request = Request.Builder()
                    .url(url)
                    .get()
                    .build()
                
                android.util.Log.d("CatalogService", "Testing connectivity to: $url")
                val response = client.newCall(request).execute()
                android.util.Log.d("CatalogService", "Test response code: ${response.code}")
                
                if (!response.isSuccessful) {
                    return@withContext CatalogResponse(
                        success = false,
                        message = "Test request failed: HTTP ${response.code} - ${response.message}",
                        items = emptyList(),
                        page = 1,
                        page_size = 1,
                        total = 0,
                        has_more = false
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CatalogResponse(
                        success = false,
                        message = "Empty response from server",
                        items = emptyList(),
                        page = 1,
                        page_size = 1,
                        total = 0,
                        has_more = false
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CatalogResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CatalogService", "JSON parsing error: ${e.message}", e)
                    CatalogResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        items = emptyList(),
                        page = 1,
                        page_size = 1,
                        total = 0,
                        has_more = false
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CatalogService", "Failed to parse test response: ${e.message}", e)
                    CatalogResponse(
                        success = false,
                        message = "Failed to parse test response: ${e.message}",
                        items = emptyList(),
                        page = 1,
                        page_size = 1,
                        total = 0,
                        has_more = false
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CatalogService", "Request timeout: ${e.message}", e)
                CatalogResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    items = emptyList(),
                    page = 1,
                    page_size = 1,
                    total = 0,
                    has_more = false
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CatalogService", "Network error: ${e.message}", e)
                CatalogResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    items = emptyList(),
                    page = 1,
                    page_size = 1,
                    total = 0,
                    has_more = false
                )
            } catch (e: Exception) {
                android.util.Log.e("CatalogService", "Unexpected error: ${e.message}", e)
                CatalogResponse(
                    success = false,
                    message = "Unexpected error: ${e.message}",
                    items = emptyList(),
                    page = 1,
                    page_size = 1,
                    total = 0,
                    has_more = false
                )
            }
        }
    }

    suspend fun getCatalogData(
        page: Int = 1,
        pageSize: Int = 48,
        searchQuery: String? = null,
        sort: String = "best_match",
        categories: List<String>? = null,
        minPoints: Float? = null,
        maxPoints: Float? = null,
        recommendedOnly: Boolean = false,
        favoritesOnly: Boolean = false
    ): CatalogResponse {
        return withContext(Dispatchers.IO) {
        
        android.util.Log.d("CatalogService", "===== getCatalogData() STARTING =====")
        android.util.Log.d("CatalogService", "Parameters received: minPoints=$minPoints, maxPoints=$maxPoints")
        
        val urlBuilder = "$baseUrl/api/mobile/catalog".toHttpUrlOrNull()?.newBuilder()
            ?: throw Exception("Invalid base URL: $baseUrl")
        
        urlBuilder.addQueryParameter("page", page.toString())
        urlBuilder.addQueryParameter("page_size", pageSize.toString())
        urlBuilder.addQueryParameter("sort", sort)
        
        searchQuery?.let { urlBuilder.addQueryParameter("q", it) }
        minPoints?.let { 
            val value = it.toString()
            android.util.Log.d("CatalogService", "Adding min_points parameter: $value")
            urlBuilder.addQueryParameter("min_points", value)
        }
        maxPoints?.let { 
            val value = it.toString()
            android.util.Log.d("CatalogService", "Adding max_points parameter: $value")
            urlBuilder.addQueryParameter("max_points", value)
        }
        if (recommendedOnly) urlBuilder.addQueryParameter("recommended_only", "true")
        if (favoritesOnly) urlBuilder.addQueryParameter("favorites_only", "true")
        
        categories?.forEach { category ->
            urlBuilder.addQueryParameter("cat[]", category)
        }
        
        val url = urlBuilder.build()
        val request = Request.Builder()
            .url(url)
            .get()
            .build()
        
            android.util.Log.d("CatalogService", "===== REQUEST URL =====")
            android.util.Log.d("CatalogService", "Full URL: ${url.toString()}")
            android.util.Log.d("CatalogService", "URL parameters manually logged:")
            for (name in url.queryParameterNames) {
                val values = url.queryParameterValues(name)
                android.util.Log.d("CatalogService", "  $name = ${values.joinToString(", ")}")
            }
            try {
                val response = client.newCall(request).execute()
                android.util.Log.d("CatalogService", "Response code: ${response.code}")
                
                if (!response.isSuccessful) {
                    return@withContext CatalogResponse(
                        success = false,
                        message = "Failed to fetch catalog data: HTTP ${response.code} - ${response.message}",
                        items = emptyList(),
                        page = page,
                        page_size = pageSize,
                        total = 0,
                        has_more = false
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CatalogResponse(
                        success = false,
                        message = "Empty response from server",
                        items = emptyList(),
                        page = page,
                        page_size = pageSize,
                        total = 0,
                        has_more = false
                    )
                }
                
                try {
                    gson.fromJson(responseBody, CatalogResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CatalogService", "JSON parsing error: ${e.message}", e)
                    CatalogResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        items = emptyList(),
                        page = page,
                        page_size = pageSize,
                        total = 0,
                        has_more = false
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CatalogService", "Failed to parse catalog response: ${e.message}", e)
                    CatalogResponse(
                        success = false,
                        message = "Failed to parse catalog response: ${e.message}",
                        items = emptyList(),
                        page = page,
                        page_size = pageSize,
                        total = 0,
                        has_more = false
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CatalogService", "Request timeout: ${e.message}", e)
                CatalogResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    items = emptyList(),
                    page = page,
                    page_size = pageSize,
                    total = 0,
                    has_more = false
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CatalogService", "Network error: ${e.message}", e)
                CatalogResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    items = emptyList(),
                    page = page,
                    page_size = pageSize,
                    total = 0,
                    has_more = false
                )
            } catch (e: Exception) {
                android.util.Log.e("CatalogService", "Unexpected error: ${e.message}", e)
                CatalogResponse(
                    success = false,
                    message = "Unexpected error: ${e.message}",
                    items = emptyList(),
                    page = page,
                    page_size = pageSize,
                    total = 0,
                    has_more = false
                )
            }
        }
    }
    
    suspend fun addFavorite(itemId: String): FavoriteResponse {
        return withContext(Dispatchers.IO) {
            try {
                val url = "$baseUrl/api/mobile/favorites"
                val json = gson.toJson(mapOf("item_id" to itemId))
                val requestBody = json.toRequestBody("application/json".toMediaType())
                
                val request = Request.Builder()
                    .url(url)
                    .post(requestBody)
                    .build()
                
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext FavoriteResponse(
                        success = false,
                        message = "Failed to add favorite: HTTP ${response.code}"
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext FavoriteResponse(
                        success = false,
                        message = "Empty response from server"
                    )
                }
                
                try {
                    gson.fromJson(responseBody, FavoriteResponse::class.java)
                } catch (e: Exception) {
                    android.util.Log.e("CatalogService", "Failed to parse favorite response: ${e.message}", e)
                    FavoriteResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}"
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CatalogService", "Request timeout: ${e.message}", e)
                FavoriteResponse(
                    success = false,
                    message = "Request timed out. Please check your connection."
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CatalogService", "Network error: ${e.message}", e)
                FavoriteResponse(
                    success = false,
                    message = "Network error: ${e.message}"
                )
            } catch (e: Exception) {
                android.util.Log.e("CatalogService", "Unexpected error: ${e.message}", e)
                FavoriteResponse(
                    success = false,
                    message = "Unexpected error: ${e.message}"
                )
            }
        }
    }
    
    suspend fun removeFavorite(itemId: String): FavoriteResponse {
        return withContext(Dispatchers.IO) {
            try {
                val url = "$baseUrl/api/mobile/favorites/$itemId"
                
                val request = Request.Builder()
                    .url(url)
                    .delete()
                    .build()
                
                val response = client.newCall(request).execute()
                
                if (!response.isSuccessful) {
                    return@withContext FavoriteResponse(
                        success = false,
                        message = "Failed to remove favorite: HTTP ${response.code}"
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext FavoriteResponse(
                        success = false,
                        message = "Empty response from server"
                    )
                }
                
                try {
                    gson.fromJson(responseBody, FavoriteResponse::class.java)
                } catch (e: Exception) {
                    android.util.Log.e("CatalogService", "Failed to parse favorite response: ${e.message}", e)
                    FavoriteResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}"
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CatalogService", "Request timeout: ${e.message}", e)
                FavoriteResponse(
                    success = false,
                    message = "Request timed out. Please check your connection."
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CatalogService", "Network error: ${e.message}", e)
                FavoriteResponse(
                    success = false,
                    message = "Network error: ${e.message}"
                )
            } catch (e: Exception) {
                android.util.Log.e("CatalogService", "Unexpected error: ${e.message}", e)
                FavoriteResponse(
                    success = false,
                    message = "Unexpected error: ${e.message}"
                )
            }
        }
    }
    
    suspend fun getProductDetail(itemId: String): ProductDetailResponse {
        return withContext(Dispatchers.IO) {
            try {
                // URL encode the item ID to handle special characters like pipes
                val encodedItemId = URLEncoder.encode(itemId, "UTF-8")
                    .replace("+", "%20")  // Replace + with %20 for spaces
                
                val url = "$baseUrl/api/mobile/product/$encodedItemId"
                
                android.util.Log.d("CatalogService", "Fetching product detail for itemId: $itemId")
                android.util.Log.d("CatalogService", "Encoded URL: $url")
                
                val request = Request.Builder()
                    .url(url)
                    .get()
                    .build()
                
                val response = client.newCall(request).execute()
                
                android.util.Log.d("CatalogService", "Product detail response code: ${response.code}")
                
                if (!response.isSuccessful) {
                    android.util.Log.e("CatalogService", "Failed to fetch product detail: HTTP ${response.code} - ${response.message}")
                    return@withContext ProductDetailResponse(
                        success = false,
                        message = "Failed to fetch product detail: HTTP ${response.code}",
                        product = null,
                        related_items = null
                    )
                }
                
                // Use safe response body reading to prevent "unexpected end of stream" errors
                val responseBody = NetworkClient.safeBodyString(response)
                
                if (responseBody == null || responseBody.isEmpty()) {
                    android.util.Log.e("CatalogService", "Product detail response body is null or empty")
                    return@withContext ProductDetailResponse(
                        success = false,
                        message = "Empty response from server",
                        product = null,
                        related_items = null
                    )
                }
                
                android.util.Log.d("CatalogService", "Product detail response body length: ${responseBody.length}")
                android.util.Log.d("CatalogService", "Product detail response body preview: ${responseBody.take(500)}")
                
                try {
                    gson.fromJson(responseBody, ProductDetailResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CatalogService", "JSON parsing error: ${e.message}", e)
                    android.util.Log.e("CatalogService", "Response body that failed to parse: ${responseBody.take(500)}")
                    ProductDetailResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        product = null,
                        related_items = null
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CatalogService", "Failed to parse product detail response: ${e.message}", e)
                    android.util.Log.e("CatalogService", "Response body that failed to parse: ${responseBody.take(500)}")
                    ProductDetailResponse(
                        success = false,
                        message = "Failed to parse product detail response: ${e.message}",
                        product = null,
                        related_items = null
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CatalogService", "Request timeout: ${e.message}", e)
                ProductDetailResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    product = null,
                    related_items = null
                )
            } catch (e: java.net.UnknownHostException) {
                android.util.Log.e("CatalogService", "Unknown host: ${e.message}", e)
                ProductDetailResponse(
                    success = false,
                    message = "Cannot reach server. Please check your connection.",
                    product = null,
                    related_items = null
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CatalogService", "Network error: ${e.message}", e)
                ProductDetailResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    product = null,
                    related_items = null
                )
            } catch (e: Exception) {
                android.util.Log.e("CatalogService", "Unexpected error: ${e.message}", e)
                ProductDetailResponse(
                    success = false,
                    message = "Unexpected error: ${e.message}",
                    product = null,
                    related_items = null
                )
            }
        }
    }
    
    suspend fun getCategories(): CategoryResponse {
        return withContext(Dispatchers.IO) {
            try {
                val url = "$baseUrl/api/mobile/catalog/categories"
                
                val request = Request.Builder()
                    .url(url)
                    .get()
                    .build()
                
                android.util.Log.d("CatalogService", "Fetching categories from: $url")
                val response = client.newCall(request).execute()
                android.util.Log.d("CatalogService", "Categories response code: ${response.code}")
                
                if (!response.isSuccessful) {
                    return@withContext CategoryResponse(
                        success = false,
                        message = "Failed to fetch categories: HTTP ${response.code}",
                        categories = emptyList()
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext CategoryResponse(
                        success = false,
                        message = "Empty response from server",
                        categories = emptyList()
                    )
                }
                
                try {
                    // Parse the response - Flask returns {"categories": [...], "category_tree": {...}, "parent_categories": {...}}
                    val jsonObject = com.google.gson.JsonParser.parseString(responseBody).asJsonObject
                    val categoriesArray = jsonObject.getAsJsonArray("categories")
                    val categories = categoriesArray?.mapNotNull { element ->
                        val catObj = element.asJsonObject
                        try {
                            CategoryItem(
                                id = catObj.get("id").asString,
                                name = catObj.get("name").asString,
                                is_parent = catObj.get("is_parent")?.asBoolean
                            )
                        } catch (e: Exception) {
                            android.util.Log.e("CatalogService", "Error parsing category: ${e.message}")
                            null
                        }
                    } ?: emptyList()
                    
                    // Parse category tree if available
                    val categoryTree = jsonObject.get("category_tree")?.asJsonObject?.let { treeObj ->
                        try {
                            // Convert JsonObject to Map<String, Any>
                            val gson = com.google.gson.Gson()
                            val treeString = treeObj.toString()
                            val type = object : com.google.gson.reflect.TypeToken<Map<String, Any>>() {}.type
                            gson.fromJson<Map<String, Any>>(treeString, type)
                        } catch (e: Exception) {
                            android.util.Log.e("CatalogService", "Error parsing category tree: ${e.message}")
                            null
                        }
                    }
                    
                    // Parse parent categories
                    val parentCategories = jsonObject.get("parent_categories")?.asJsonObject?.let { parentObj ->
                        try {
                            val gson = com.google.gson.Gson()
                            val parentString = parentObj.toString()
                            val type = object : com.google.gson.reflect.TypeToken<Map<String, String>>() {}.type
                            gson.fromJson<Map<String, String>>(parentString, type)
                        } catch (e: Exception) {
                            android.util.Log.e("CatalogService", "Error parsing parent categories: ${e.message}")
                            null
                        }
                    }
                    
                    CategoryResponse(
                        success = true,
                        message = null,
                        categories = categories,
                        category_tree = categoryTree,
                        parent_categories = parentCategories
                    )
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("CatalogService", "JSON parsing error: ${e.message}", e)
                    CategoryResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        categories = emptyList()
                    )
                } catch (e: Exception) {
                    android.util.Log.e("CatalogService", "Failed to parse categories response: ${e.message}", e)
                    CategoryResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        categories = emptyList()
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("CatalogService", "Request timeout: ${e.message}", e)
                CategoryResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    categories = emptyList()
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("CatalogService", "Network error: ${e.message}", e)
                CategoryResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    categories = emptyList()
                )
            } catch (e: Exception) {
                android.util.Log.e("CatalogService", "Unexpected error: ${e.message}", e)
                CategoryResponse(
                    success = false,
                    message = "Unexpected error: ${e.message}",
                    categories = emptyList()
                )
            }
        }
    }
}
