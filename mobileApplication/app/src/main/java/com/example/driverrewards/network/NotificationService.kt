package com.example.driverrewards.network

import android.util.Log
import com.google.gson.JsonObject
import com.google.gson.annotations.SerializedName
import com.example.driverrewards.network.NetworkClient.baseUrl
import com.example.driverrewards.network.NetworkClient.client
import com.example.driverrewards.network.NetworkClient.gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

data class NotificationItem(
    val id: String,
    val type: String,
    val title: String,
    val body: String,
    val metadata: JsonObject?,
    @SerializedName("deliveredVia") val deliveredVia: String?,
    @SerializedName("isRead") val isRead: Boolean,
    @SerializedName("createdAt") val createdAt: String?,
    @SerializedName("readAt") val readAt: String?,
    @SerializedName("sponsorContext") val sponsorContext: NotificationSponsorContext?
)

data class NotificationPagination(
    val page: Int,
    @SerializedName("pageSize") val pageSize: Int,
    val total: Int,
    @SerializedName("hasMore") val hasMore: Boolean
)

data class NotificationListEnvelope(
    val success: Boolean,
    val notifications: List<NotificationItem>?,
    val pagination: NotificationPagination?,
    val message: String?
)

data class MarkReadResponse(
    val success: Boolean,
    val message: String?,
    val updated: Int
)

data class BasicResponse(
    val success: Boolean,
    val message: String?
)

data class QuietHoursPreference(
    val enabled: Boolean,
    val start: String?,
    val end: String?
)

data class LowPointsPreference(
    val enabled: Boolean,
    val threshold: Int
)

data class NotificationPreferencesPayload(
    val pointChanges: Boolean,
    val orderConfirmations: Boolean,
    val applicationUpdates: Boolean,
    val ticketUpdates: Boolean,
    val refundWindowAlerts: Boolean,
    val accountStatusChanges: Boolean,
    val sensitiveInfoResets: Boolean,
    val emailEnabled: Boolean,
    val inAppEnabled: Boolean,
    val quietHours: QuietHoursPreference,
    val lowPoints: LowPointsPreference
)

data class NotificationPreferencesResponse(
    val success: Boolean,
    val message: String?,
    val preferences: NotificationPreferencesPayload?
)

data class NotificationSponsorContext(
    @SerializedName("sponsorId") val sponsorId: String?,
    @SerializedName("sponsorName") val sponsorName: String?,
    @SerializedName("sponsorCompanyName") val sponsorCompanyName: String?,
    @SerializedName("isSponsorSpecific") val isSponsorSpecific: Boolean = false
)

class NotificationService {

    companion object {
        private const val TAG = "NotificationService"
        private val JSON_MEDIA = "application/json".toMediaType()
    }

    suspend fun getNotifications(
        page: Int = 1,
        pageSize: Int = 20,
        unreadOnly: Boolean = false,
        since: String? = null
    ): NotificationListEnvelope = withContext(Dispatchers.IO) {
        val urlBuilder = "$baseUrl/api/mobile/notifications".toHttpUrlOrNull()?.newBuilder()
        urlBuilder?.addQueryParameter("page", page.toString())
        urlBuilder?.addQueryParameter("pageSize", pageSize.toString())
        if (unreadOnly) {
            urlBuilder?.addQueryParameter("unreadOnly", "true")
        }
        since?.let { urlBuilder?.addQueryParameter("since", it) }
        val url = urlBuilder?.build()?.toString() ?: "$baseUrl/api/mobile/notifications"

        val request = Request.Builder().url(url).get().build()
        try {
            val response = client.newCall(request).execute()
            Log.d(TAG, "Notifications response code=${response.code}")

            if (!response.isSuccessful) {
                return@withContext NotificationListEnvelope(
                    success = false,
                    notifications = emptyList(),
                    pagination = null,
                    message = "Failed to fetch notifications: HTTP ${response.code}"
                )
            }
            
            val body = NetworkClient.safeBodyString(response)
            if (body == null || body.isEmpty()) {
                return@withContext NotificationListEnvelope(
                    success = false,
                    notifications = emptyList(),
                    pagination = null,
                    message = "Empty response from server"
                )
            }
            
            try {
                gson.fromJson(body, NotificationListEnvelope::class.java)
            } catch (ex: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${ex.message}", ex)
                NotificationListEnvelope(
                    success = false,
                    notifications = emptyList(),
                    pagination = null,
                    message = "Invalid JSON response: ${ex.message}"
                )
            } catch (ex: Exception) {
                Log.e(TAG, "Failed to parse notifications response", ex)
                NotificationListEnvelope(
                    success = false,
                    notifications = emptyList(),
                    pagination = null,
                    message = "Failed to parse response: ${ex.message}"
                )
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            NotificationListEnvelope(
                success = false,
                notifications = emptyList(),
                pagination = null,
                message = "Request timed out. Please check your connection."
            )
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            NotificationListEnvelope(
                success = false,
                notifications = emptyList(),
                pagination = null,
                message = "Network error: ${e.message}"
            )
        } catch (e: Exception) {
            Log.e(TAG, "Get notifications error: ${e.message}", e)
            NotificationListEnvelope(
                success = false,
                notifications = emptyList(),
                pagination = null,
                message = "Network error: ${e.message}"
            )
        }
    }

    suspend fun markNotificationsRead(
        notificationIds: List<String>?,
        markAll: Boolean = false
    ): MarkReadResponse = withContext(Dispatchers.IO) {
        val payload = mutableMapOf<String, Any>("markAll" to markAll)
        if (!markAll && notificationIds != null) {
            payload["notificationIds"] = notificationIds
        }

        val requestBody = gson.toJson(payload).toRequestBody(JSON_MEDIA)
        val request = Request.Builder()
            .url("$baseUrl/api/mobile/notifications/mark-read")
            .post(requestBody)
            .build()

        try {
            val response = client.newCall(request).execute()
            Log.d(TAG, "Mark-read response code=${response.code}")

            if (!response.isSuccessful) {
                return@withContext MarkReadResponse(false, "Failed to update notifications: HTTP ${response.code}", 0)
            }
            
            val body = NetworkClient.safeBodyString(response)
            if (body == null || body.isEmpty()) {
                return@withContext MarkReadResponse(false, "Empty response from server", 0)
            }
            
            try {
                gson.fromJson(body, MarkReadResponse::class.java)
            } catch (ex: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${ex.message}", ex)
                MarkReadResponse(false, "Invalid JSON response: ${ex.message}", 0)
            } catch (ex: Exception) {
                Log.e(TAG, "Failed to parse mark-read response", ex)
                MarkReadResponse(false, "Failed to parse response: ${ex.message}", 0)
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            MarkReadResponse(false, "Request timed out. Please check your connection.", 0)
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            MarkReadResponse(false, "Network error: ${e.message}", 0)
        } catch (e: Exception) {
            Log.e(TAG, "Mark read error: ${e.message}", e)
            MarkReadResponse(false, "Network error: ${e.message}", 0)
        }
    }

    suspend fun getPreferences(): NotificationPreferencesResponse = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/api/mobile/notifications/preferences")
            .get()
            .build()
        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                return@withContext NotificationPreferencesResponse(
                    false,
                    "Failed to load notification preferences: HTTP ${response.code}",
                    null
                )
            }
            
            val body = NetworkClient.safeBodyString(response)
            if (body == null || body.isEmpty()) {
                return@withContext NotificationPreferencesResponse(false, "Empty response from server", null)
            }
            
            try {
                gson.fromJson(body, NotificationPreferencesResponse::class.java)
            } catch (ex: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${ex.message}", ex)
                NotificationPreferencesResponse(false, "Invalid JSON response: ${ex.message}", null)
            } catch (ex: Exception) {
                Log.e(TAG, "Failed to parse preferences response", ex)
                NotificationPreferencesResponse(false, "Failed to parse response: ${ex.message}", null)
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            NotificationPreferencesResponse(false, "Request timed out. Please check your connection.", null)
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            NotificationPreferencesResponse(false, "Network error: ${e.message}", null)
        } catch (e: Exception) {
            Log.e(TAG, "Get preferences error: ${e.message}", e)
            NotificationPreferencesResponse(false, "Network error: ${e.message}", null)
        }
    }

    suspend fun updatePreferences(
        payload: NotificationPreferencesPayload
    ): NotificationPreferencesResponse = withContext(Dispatchers.IO) {
        val requestBody = gson.toJson(payload).toRequestBody(JSON_MEDIA)
        val request = Request.Builder()
            .url("$baseUrl/api/mobile/notifications/preferences")
            .put(requestBody)
            .build()

        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                return@withContext NotificationPreferencesResponse(
                    false,
                    "Failed to update notification preferences: HTTP ${response.code}",
                    null
                )
            }
            
            val body = NetworkClient.safeBodyString(response)
            if (body == null || body.isEmpty()) {
                return@withContext NotificationPreferencesResponse(false, "Empty response from server", null)
            }
            
            try {
                gson.fromJson(body, NotificationPreferencesResponse::class.java)
            } catch (ex: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${ex.message}", ex)
                NotificationPreferencesResponse(false, "Invalid JSON response: ${ex.message}", null)
            } catch (ex: Exception) {
                Log.e(TAG, "Failed to parse update preferences response", ex)
                NotificationPreferencesResponse(false, "Failed to parse response: ${ex.message}", null)
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            NotificationPreferencesResponse(false, "Request timed out. Please check your connection.", null)
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            NotificationPreferencesResponse(false, "Network error: ${e.message}", null)
        } catch (e: Exception) {
            Log.e(TAG, "Update preferences error: ${e.message}", e)
            NotificationPreferencesResponse(false, "Network error: ${e.message}", null)
        }
    }

    suspend fun triggerLowPointsTest(
        balance: Int,
        threshold: Int
    ): BasicResponse = withContext(Dispatchers.IO) {
        val payload = mapOf("balance" to balance, "threshold" to threshold)
        val requestBody = gson.toJson(payload).toRequestBody(JSON_MEDIA)
        val request = Request.Builder()
            .url("$baseUrl/api/mobile/notifications/test-low-points")
            .post(requestBody)
            .build()

        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                return@withContext BasicResponse(false, "Failed to trigger low points notification: HTTP ${response.code}")
            }
            
            val body = NetworkClient.safeBodyString(response)
            if (body == null || body.isEmpty()) {
                return@withContext BasicResponse(false, "Empty response from server")
            }
            
            try {
                gson.fromJson(body, BasicResponse::class.java)
            } catch (ex: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${ex.message}", ex)
                BasicResponse(false, "Invalid JSON response: ${ex.message}")
            } catch (ex: Exception) {
                Log.e(TAG, "Failed to parse test low points response", ex)
                BasicResponse(false, "Failed to parse response: ${ex.message}")
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            BasicResponse(false, "Request timed out. Please check your connection.")
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            BasicResponse(false, "Network error: ${e.message}")
        } catch (e: Exception) {
            Log.e(TAG, "Trigger low points test error: ${e.message}", e)
            BasicResponse(false, "Network error: ${e.message}")
        }
    }
}

