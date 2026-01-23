package com.example.driverrewards.network

import com.example.driverrewards.network.NetworkClient.gson
import com.example.driverrewards.network.NetworkClient.client
import com.example.driverrewards.network.NetworkClient.baseUrl
import okhttp3.Request
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class PointsHistoryResponse(
    val success: Boolean,
    val message: String?,
    val transactions: List<PointsTransaction>,
    @com.google.gson.annotations.SerializedName("total_count") val totalCount: Int
)

data class PointsTransaction(
    @com.google.gson.annotations.SerializedName("point_change_id") val pointChangeId: String,
    @com.google.gson.annotations.SerializedName("delta_points") val deltaPoints: Int,
    @com.google.gson.annotations.SerializedName("balance_after") val balanceAfter: Int,
    val reason: String,
    @com.google.gson.annotations.SerializedName("created_at") val createdAt: String?,
    @com.google.gson.annotations.SerializedName("transaction_id") val transactionId: String?
)

data class PointsDetailsResponse(
    val success: Boolean,
    val message: String?,
    @com.google.gson.annotations.SerializedName("current_balance") val currentBalance: Int,
    @com.google.gson.annotations.SerializedName("conversion_rate") val conversionRate: Double,
    @com.google.gson.annotations.SerializedName("dollar_value") val dollarValue: Double,
    @com.google.gson.annotations.SerializedName("sponsor_company") val sponsorCompany: String?,
    @com.google.gson.annotations.SerializedName("member_since") val memberSince: String?,
    @com.google.gson.annotations.SerializedName("total_earned") val totalEarned: Int,
    @com.google.gson.annotations.SerializedName("total_spent") val totalSpent: Int
)

data class PointsGraphResponse(
    val success: Boolean,
    val message: String?,
    @com.google.gson.annotations.SerializedName("data_points") val dataPoints: List<PointsGraphDataPoint>
)

data class PointsGraphDataPoint(
    val date: String,
    val balance: Int,
    val delta: Int
)

class PointsService {

    suspend fun getPointsHistory(
        startDate: String? = null,
        endDate: String? = null,
        limit: Int? = null,
        sort: String? = null
    ): PointsHistoryResponse {
        return withContext(Dispatchers.IO) {
            val urlBuilder = StringBuilder("$baseUrl/api/mobile/points/history")
            val params = mutableListOf<String>()
            
            startDate?.let { params.add("start_date=$it") }
            endDate?.let { params.add("end_date=$it") }
            limit?.let { params.add("limit=$it") }
            sort?.let { params.add("sort=$it") }
            
            if (params.isNotEmpty()) {
                urlBuilder.append("?").append(params.joinToString("&"))
            }
            
            val url = urlBuilder.toString()
            val request = Request.Builder()
                .url(url)
                .get()
                .build()
            
            android.util.Log.d("PointsService", "Fetching points history from: $url")
            try {
                val response = client.newCall(request).execute()
                android.util.Log.d("PointsService", "Points history response code: ${response.code}")
                
                if (!response.isSuccessful) {
                    return@withContext PointsHistoryResponse(
                        success = false,
                        message = "Failed to fetch points history: HTTP ${response.code}",
                        transactions = emptyList(),
                        totalCount = 0
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext PointsHistoryResponse(
                        success = false,
                        message = "Empty response from server",
                        transactions = emptyList(),
                        totalCount = 0
                    )
                }
                
                try {
                    gson.fromJson(responseBody, PointsHistoryResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("PointsService", "JSON parsing error: ${e.message}", e)
                    PointsHistoryResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        transactions = emptyList(),
                        totalCount = 0
                    )
                } catch (e: Exception) {
                    android.util.Log.e("PointsService", "Failed to parse points history response: ${e.message}", e)
                    PointsHistoryResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        transactions = emptyList(),
                        totalCount = 0
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("PointsService", "Request timeout: ${e.message}", e)
                PointsHistoryResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    transactions = emptyList(),
                    totalCount = 0
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("PointsService", "Network error: ${e.message}", e)
                PointsHistoryResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    transactions = emptyList(),
                    totalCount = 0
                )
            } catch (e: Exception) {
                android.util.Log.e("PointsService", "Get points history error: ${e.message}", e)
                PointsHistoryResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    transactions = emptyList(),
                    totalCount = 0
                )
            }
        }
    }

    suspend fun getPointsDetails(): PointsDetailsResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/points/details"
            val request = Request.Builder()
                .url(url)
                .get()
                .build()
            
            android.util.Log.d("PointsService", "Fetching points details from: $url")
            try {
                val response = client.newCall(request).execute()
                android.util.Log.d("PointsService", "Points details response code: ${response.code}")
                
                if (!response.isSuccessful) {
                    return@withContext PointsDetailsResponse(
                        success = false,
                        message = "Failed to fetch points details: HTTP ${response.code}",
                        currentBalance = 0,
                        conversionRate = 0.01,
                        dollarValue = 0.0,
                        sponsorCompany = null,
                        memberSince = null,
                        totalEarned = 0,
                        totalSpent = 0
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext PointsDetailsResponse(
                        success = false,
                        message = "Empty response from server",
                        currentBalance = 0,
                        conversionRate = 0.01,
                        dollarValue = 0.0,
                        sponsorCompany = null,
                        memberSince = null,
                        totalEarned = 0,
                        totalSpent = 0
                    )
                }
                
                try {
                    gson.fromJson(responseBody, PointsDetailsResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("PointsService", "JSON parsing error: ${e.message}", e)
                    PointsDetailsResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        currentBalance = 0,
                        conversionRate = 0.01,
                        dollarValue = 0.0,
                        sponsorCompany = null,
                        memberSince = null,
                        totalEarned = 0,
                        totalSpent = 0
                    )
                } catch (e: Exception) {
                    android.util.Log.e("PointsService", "Failed to parse points details response: ${e.message}", e)
                    PointsDetailsResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        currentBalance = 0,
                        conversionRate = 0.01,
                        dollarValue = 0.0,
                        sponsorCompany = null,
                        memberSince = null,
                        totalEarned = 0,
                        totalSpent = 0
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("PointsService", "Request timeout: ${e.message}", e)
                PointsDetailsResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    currentBalance = 0,
                    conversionRate = 0.01,
                    dollarValue = 0.0,
                    sponsorCompany = null,
                    memberSince = null,
                    totalEarned = 0,
                    totalSpent = 0
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("PointsService", "Network error: ${e.message}", e)
                PointsDetailsResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    currentBalance = 0,
                    conversionRate = 0.01,
                    dollarValue = 0.0,
                    sponsorCompany = null,
                    memberSince = null,
                    totalEarned = 0,
                    totalSpent = 0
                )
            } catch (e: Exception) {
                android.util.Log.e("PointsService", "Get points details error: ${e.message}", e)
                PointsDetailsResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    currentBalance = 0,
                    conversionRate = 0.01,
                    dollarValue = 0.0,
                    sponsorCompany = null,
                    memberSince = null,
                    totalEarned = 0,
                    totalSpent = 0
                )
            }
        }
    }

    suspend fun getPointsGraph(
        period: String = "30d",
        granularity: String = "day"
    ): PointsGraphResponse {
        return withContext(Dispatchers.IO) {
            val url = "$baseUrl/api/mobile/points/graph?period=$period&granularity=$granularity"
            val request = Request.Builder()
                .url(url)
                .get()
                .build()
            
            android.util.Log.d("PointsService", "Fetching points graph from: $url")
            try {
                val response = client.newCall(request).execute()
                android.util.Log.d("PointsService", "Points graph response code: ${response.code}")
                
                if (!response.isSuccessful) {
                    return@withContext PointsGraphResponse(
                        success = false,
                        message = "Failed to fetch points graph: HTTP ${response.code}",
                        dataPoints = emptyList()
                    )
                }
                
                val responseBody = NetworkClient.safeBodyString(response)
                if (responseBody == null || responseBody.isEmpty()) {
                    return@withContext PointsGraphResponse(
                        success = false,
                        message = "Empty response from server",
                        dataPoints = emptyList()
                    )
                }
                
                try {
                    gson.fromJson(responseBody, PointsGraphResponse::class.java)
                } catch (e: com.google.gson.JsonSyntaxException) {
                    android.util.Log.e("PointsService", "JSON parsing error: ${e.message}", e)
                    PointsGraphResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        dataPoints = emptyList()
                    )
                } catch (e: Exception) {
                    android.util.Log.e("PointsService", "Failed to parse points graph response: ${e.message}", e)
                    PointsGraphResponse(
                        success = false,
                        message = "Failed to parse response: ${e.message}",
                        dataPoints = emptyList()
                    )
                }
            } catch (e: java.net.SocketTimeoutException) {
                android.util.Log.e("PointsService", "Request timeout: ${e.message}", e)
                PointsGraphResponse(
                    success = false,
                    message = "Request timed out. Please check your connection.",
                    dataPoints = emptyList()
                )
            } catch (e: java.io.IOException) {
                android.util.Log.e("PointsService", "Network error: ${e.message}", e)
                PointsGraphResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    dataPoints = emptyList()
                )
            } catch (e: Exception) {
                android.util.Log.e("PointsService", "Get points graph error: ${e.message}", e)
                PointsGraphResponse(
                    success = false,
                    message = "Network error: ${e.message}",
                    dataPoints = emptyList()
                )
            }
        }
    }
}


