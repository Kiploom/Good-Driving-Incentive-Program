package com.example.driverrewards.network

import android.util.Log
import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.logging.HttpLoggingInterceptor
import java.io.IOException
import java.util.concurrent.TimeUnit

data class LoginRequest(
    val email: String,
    val password: String
)

data class LoginResponse(
    val success: Boolean,
    val message: String?,
    val accountId: String?,
    val driverId: String?,
    val username: String?,
    val email: String?,
    @SerializedName("mfa_required") val mfaRequired: Boolean? = false
)

data class ProfileData(
    @SerializedName("accountId") val accountId: String,
    @SerializedName("driverId") val driverId: String,
    @SerializedName("email") val email: String,
    @SerializedName("username") val username: String,
    @SerializedName("firstName") val firstName: String?,
    @SerializedName("lastName") val lastName: String?,
    @SerializedName("wholeName") val wholeName: String?,
    @SerializedName("pointsBalance") val pointsBalance: Int,
    @SerializedName("memberSince") val memberSince: String?,
    @SerializedName("shippingAddress") val shippingAddress: String?,
    @SerializedName("licenseNumber") val licenseNumber: String?,
    @SerializedName("licenseIssueDate") val licenseIssueDate: String?,
    @SerializedName("licenseExpirationDate") val licenseExpirationDate: String?,
    @SerializedName("sponsorCompany") val sponsorCompany: String?,
    @SerializedName("status") val status: String?,
    @SerializedName("age") val age: Int?,
    @SerializedName("gender") val gender: String?,
    @SerializedName("profileImageURL") val profileImageURL: String?
)

data class ProfileResponse(
    @SerializedName("success") val success: Boolean,
    @SerializedName("message") val message: String?,
    @SerializedName("profile") val profile: ProfileData?
)

data class UpdateProfileRequest(
    @SerializedName("firstName") val firstName: String?,
    @SerializedName("lastName") val lastName: String?,
    @SerializedName("wholeName") val wholeName: String?,
    @SerializedName("shippingAddress") val shippingAddress: String?,
    @SerializedName("licenseNumber") val licenseNumber: String?,
    @SerializedName("licenseIssueDate") val licenseIssueDate: String?,
    @SerializedName("licenseExpirationDate") val licenseExpirationDate: String?
)

data class ChangePasswordRequest(
    @SerializedName("currentPassword") val currentPassword: String,
    @SerializedName("newPassword") val newPassword: String
)

data class ApiResponse(
    @SerializedName("success") val success: Boolean,
    @SerializedName("message") val message: String?
)

data class UploadProfilePictureResponse(
    @SerializedName("success") val success: Boolean,
    @SerializedName("message") val message: String?,
    @SerializedName("profileImageURL") val profileImageURL: String?
)

// Singleton HTTP client that maintains cookies across requests
object NetworkClient {
    private const val TAG = "NetworkClient"
    
    // We'll initialize this with context when needed
    private var sessionManager: com.example.driverrewards.utils.SessionManager? = null
    
    fun initialize(context: android.content.Context) {
        sessionManager = com.example.driverrewards.utils.SessionManager(context)
    }
    
    val client: OkHttpClient by lazy {
        // Custom logging interceptor that sanitizes passwords
        val loggingInterceptor = object : HttpLoggingInterceptor.Logger {
            override fun log(message: String) {
                // Sanitize password fields in JSON logs
                val sanitizedMessage = if (message.contains("\"password\"") || message.contains("\"currentPassword\"") || message.contains("\"newPassword\"")) {
                    message.replace(Regex("\"(password|currentPassword|newPassword)\":\\s*\"[^\"]*\"")) {
                        "${it.groupValues[1]}=\"••••••••\""
                    }
                } else {
                    message
                }
                Log.d(TAG, sanitizedMessage)
            }
        }
        
        val interceptor = HttpLoggingInterceptor(loggingInterceptor)
        interceptor.level = HttpLoggingInterceptor.Level.BODY
        
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            // Limit redirects to prevent infinite loops (default is 20, we'll set to 5 for API endpoints)
            .followRedirects(true)
            .followSslRedirects(true)
            .addInterceptor(interceptor)
            .addInterceptor { chain ->
                val request = chain.request()
                Log.d(TAG, "Making request to: ${request.url}")
                Log.d(TAG, "Request headers: ${request.headers}")
                
                try {
                    val response = chain.proceed(request)
                    Log.d(TAG, "Response code: ${response.code}")
                    Log.d(TAG, "Response headers: ${response.headers}")
                    
                    // Extract and merge cookies from response for all API endpoints
                    // This ensures we always have the latest csrf_token and session cookies
                    if (request.url.toString().contains("/api/mobile/")) {
                        updateCookiesFromResponse(response)
                    }
                    
                    // If we get a redirect (3xx) for an API endpoint, don't follow it
                    // This prevents redirect loops when sessions expire
                    if (response.code in 300..399 && request.url.toString().contains("/api/mobile/")) {
                        val location = response.header("Location")
                        Log.w(TAG, "Redirect detected for API endpoint: $location - stopping redirect loop")
                        // Convert redirect to 401 Unauthorized for API endpoints
                        return@addInterceptor response.newBuilder()
                            .code(401)
                            .message("Unauthorized - Session expired")
                            .body("""{"success":false,"message":"Not authenticated"}""".toResponseBody("application/json".toMediaType()))
                            .removeHeader("Location")
                            .build()
                    }
                    
                    response
                } catch (e: java.net.ProtocolException) {
                    // Catch redirect loop exceptions
                    if (e.message?.contains("Too many follow-up requests") == true) {
                        Log.e(TAG, "Redirect loop detected: ${e.message}")
                        // Return a 401 response instead of throwing
                        return@addInterceptor Response.Builder()
                            .request(request)
                            .protocol(Protocol.HTTP_1_1)
                            .code(401)
                            .message("Unauthorized - Session expired")
                            .body("""{"success":false,"message":"Not authenticated - Session expired"}""".toResponseBody("application/json".toMediaType()))
                            .build()
                    }
                    throw e
                }
            }
            .addInterceptor { chain ->
                val originalRequest = chain.request()
                val sessionCookies = getSessionCookies()
                
                val newRequest = if (sessionCookies != null && sessionCookies.isNotEmpty()) {
                    originalRequest.newBuilder()
                        .addHeader("Cookie", sessionCookies)
                        .build()
                } else {
                    originalRequest
                }
                
                chain.proceed(newRequest)
            }
            .build()
    }
    
    val gson: Gson by lazy { Gson() }
    
    // Update this URL to match your Flask server
    // EC2 instance server address
    const val baseUrl = "https://gooddriver-app.site"
    
    fun setSessionCookies(cookies: String?) {
        sessionManager?.saveSessionCookies(cookies)
        Log.d(TAG, "Session cookies set: $cookies")
    }
    
    fun getSessionCookies(): String? {
        val cookies = sessionManager?.getSessionCookies()
        Log.d(TAG, "Getting session cookies: $cookies")
        return cookies
    }
    
    fun clearSessionCookies() {
        sessionManager?.clearSessionCookies()
        Log.d(TAG, "Clearing session cookies")
    }
    
    /**
     * Safely reads response body string, handling IOException and stream errors
     * This prevents "unexpected end of stream" errors by properly handling stream reading
     */
    fun safeBodyString(response: okhttp3.Response): String? {
        return try {
            response.body?.string()
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Error reading response body: ${e.message}", e)
            null
        } catch (e: Exception) {
            Log.e(TAG, "Unexpected error reading response body: ${e.message}", e)
            null
        }
    }
    
    /**
     * Updates stored cookies by merging new cookies from response Set-Cookie headers
     * with existing cookies. This ensures we always have the latest csrf_token and session.
     */
    private fun updateCookiesFromResponse(response: Response) {
        val setCookieHeaders = response.headers.values("Set-Cookie")
        if (setCookieHeaders.isEmpty()) {
            return
        }
        
        // Parse Set-Cookie headers to extract only name=value pairs
        val newCookies = setCookieHeaders.mapNotNull { cookieHeader ->
            cookieHeader.split(";").firstOrNull()?.trim()
        }.filter { it.isNotEmpty() }
        
        if (newCookies.isEmpty()) {
            return
        }
        
        // Get existing cookies
        val existingCookiesStr = getSessionCookies()
        val cookieMap = mutableMapOf<String, String>()
        
        // Parse existing cookies into a map
        existingCookiesStr?.split(";")?.forEach { cookie ->
            val parts = cookie.trim().split("=", limit = 2)
            if (parts.size == 2) {
                cookieMap[parts[0].trim()] = parts[1].trim()
            }
        }
        
        // Merge new cookies (new values override existing ones)
        newCookies.forEach { cookie ->
            val parts = cookie.split("=", limit = 2)
            if (parts.size == 2) {
                cookieMap[parts[0].trim()] = parts[1].trim()
            }
        }
        
        // Rebuild cookie string
        val mergedCookies = cookieMap.map { "${it.key}=${it.value}" }.joinToString("; ")
        
        if (mergedCookies.isNotEmpty()) {
            setSessionCookies(mergedCookies)
            Log.d(TAG, "Updated cookies from response: ${cookieMap.keys.joinToString(", ")}")
        }
    }
}

class AuthService {
    private val TAG = "AuthService"
    
    suspend fun login(email: String, password: String): LoginResponse {
        Log.d(TAG, "Starting login process for email: $email")
        return try {
            val requestBody = LoginRequest(email, password)
            val json = NetworkClient.gson.toJson(requestBody)
            
            Log.d(TAG, "Login request URL: ${NetworkClient.baseUrl}/api/mobile/login")
            // Don't log the actual password - just log that a request body was created
            Log.d(TAG, "Login request body created (password hidden)")
            
            val request = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/login")
                .post(json.toRequestBody("application/json".toMediaType()))
                .addHeader("Content-Type", "application/json")
                .build()
            
            Log.d(TAG, "Executing login request...")
            val response = NetworkClient.client.newCall(request).execute()
            
            Log.d(TAG, "Login response code: ${response.code}")
            Log.d(TAG, "Login response headers: ${response.headers}")
            
            // Extract session cookies from response headers
            val setCookieHeaders = response.headers.values("Set-Cookie")
            Log.d(TAG, "Set-Cookie headers: $setCookieHeaders")
            if (setCookieHeaders.isNotEmpty()) {
                // Parse Set-Cookie headers to extract only name=value pairs (ignore attributes like Path, SameSite, etc.)
                val cookiePairs = setCookieHeaders.mapNotNull { cookieHeader ->
                    // Extract the name=value part (before first semicolon)
                    cookieHeader.split(";").firstOrNull()?.trim()
                }.filter { it.isNotEmpty() }
                
                val cookies = cookiePairs.joinToString("; ")
                NetworkClient.setSessionCookies(cookies)
                Log.d(TAG, "Stored session cookies: $cookies")
            } else {
                Log.w(TAG, "No Set-Cookie headers found in login response")
            }
            
            if (!response.isSuccessful) {
                val errorMessage = when (response.code) {
                    400 -> "Bad request - check your credentials format"
                    401 -> "Invalid credentials"
                    403 -> "Access denied - driver account required"
                    404 -> "Server endpoint not found"
                    500 -> "Server error"
                    else -> "HTTP ${response.code}: ${response.message}"
                }
                Log.e(TAG, "Login failed with HTTP error: $errorMessage")
                return LoginResponse(
                    success = false,
                    message = errorMessage,
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            }
            
            // Use safe response body reading to prevent "unexpected end of stream" errors
            val responseBody = NetworkClient.safeBodyString(response)
            Log.d(TAG, "Login response body: $responseBody")
            
            if (responseBody == null || responseBody.isEmpty()) {
                Log.e(TAG, "Empty response body from login")
                return LoginResponse(
                    success = false,
                    message = "Empty response from server",
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            }
            
            try {
                // Parse the actual response from the Flask API
                val loginResponse = NetworkClient.gson.fromJson(responseBody, LoginResponse::class.java)
                Log.d(TAG, "Parsed login response: $loginResponse")
                loginResponse
            } catch (e: Exception) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                LoginResponse(
                    success = false,
                    message = "Failed to parse server response: ${e.message}",
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            }
        } catch (e: java.net.UnknownHostException) {
            Log.e(TAG, "Unknown host error: ${e.message}", e)
            LoginResponse(
                success = false,
                message = "Cannot connect to server. Check your network connection.",
                accountId = null,
                driverId = null,
                username = null,
                email = null,
                mfaRequired = false
            )
        } catch (e: java.net.ConnectException) {
            Log.e(TAG, "Connection error: ${e.message}", e)
            LoginResponse(
                success = false,
                message = "Connection refused. Is the server running?",
                accountId = null,
                driverId = null,
                username = null,
                email = null,
                mfaRequired = false
            )
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Timeout error: ${e.message}", e)
            LoginResponse(
                success = false,
                message = "Request timed out. Server may be slow.",
                accountId = null,
                driverId = null,
                username = null,
                email = null,
                mfaRequired = false
            )
        } catch (e: Exception) {
            Log.e(TAG, "General error: ${e.javaClass.simpleName} - ${e.message}", e)
            LoginResponse(
                success = false,
                message = "Network error: ${e.javaClass.simpleName} - ${e.message}",
                accountId = null,
                driverId = null,
                username = null,
                email = null,
                mfaRequired = false
            )
        }
    }
    
data class MfaVerifyRequest(
    val code: String
)

data class MfaStatusResponse(
    val success: Boolean,
    @SerializedName("mfa_enabled") val mfaEnabled: Boolean?
)

data class MfaEnableResponse(
    val success: Boolean,
    val message: String?,
    @SerializedName("qr_uri") val qrUri: String?,
    val secret: String?
)

data class MfaConfirmResponse(
    val success: Boolean,
    val message: String?,
    @SerializedName("recovery_codes") val recoveryCodes: List<String>?
)

data class MfaPasswordRequest(
    val password: String
)

data class MfaConfirmRequest(
    val code: String
)
    
    suspend fun verifyMfa(code: String): LoginResponse {
        Log.d(TAG, "Verifying MFA code")
        return try {
            val requestBody = MfaVerifyRequest(code)
            val json = NetworkClient.gson.toJson(requestBody)
            
            val request = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/mfa/verify")
                .post(json.toRequestBody("application/json".toMediaType()))
                .build()
            
            val response = NetworkClient.client.newCall(request).execute()
            
            Log.d(TAG, "MFA verify response code: ${response.code}")
            Log.d(TAG, "MFA verify response headers: ${response.headers}")
            
            // Extract session cookies from response headers (same as login)
            val setCookieHeaders = response.headers.values("Set-Cookie")
            Log.d(TAG, "Set-Cookie headers: $setCookieHeaders")
            if (setCookieHeaders.isNotEmpty()) {
                // Parse Set-Cookie headers to extract only name=value pairs (ignore attributes like Path, SameSite, etc.)
                val cookiePairs = setCookieHeaders.mapNotNull { cookieHeader ->
                    // Extract the name=value part (before first semicolon)
                    cookieHeader.split(";").firstOrNull()?.trim()
                }.filter { it.isNotEmpty() }
                
                val cookies = cookiePairs.joinToString("; ")
                NetworkClient.setSessionCookies(cookies)
                Log.d(TAG, "Stored session cookies from MFA verify: $cookies")
            } else {
                Log.w(TAG, "No Set-Cookie headers found in MFA verify response")
            }
            
            if (!response.isSuccessful) {
                val errorMessage = when (response.code) {
                    400 -> "Invalid MFA code format"
                    401 -> "Invalid MFA or recovery code"
                    404 -> "MFA verification session expired. Please log in again."
                    else -> "MFA verification failed: HTTP ${response.code}"
                }
                return LoginResponse(
                    success = false,
                    message = errorMessage,
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            }
            
            // Use safe response body reading to prevent "unexpected end of stream" errors
            val responseBody = NetworkClient.safeBodyString(response)
            Log.d(TAG, "MFA verify response body: $responseBody")
            
            if (responseBody == null || responseBody.isEmpty()) {
                Log.e(TAG, "Empty response body from MFA verify")
                return LoginResponse(
                    success = false,
                    message = "Empty response from server",
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            }
            
            try {
                NetworkClient.gson.fromJson(responseBody, LoginResponse::class.java)
            } catch (e: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                LoginResponse(
                    success = false,
                    message = "Invalid JSON response: ${e.message}",
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse server response: ${e.message}", e)
                LoginResponse(
                    success = false,
                    message = "Failed to parse server response: ${e.message}",
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            }
        } catch (e: java.net.ProtocolException) {
            if (e.message?.contains("Too many follow-up requests") == true) {
                NetworkClient.clearSessionCookies()
                LoginResponse(
                    success = false,
                    message = "Session expired. Please log in again.",
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            } else {
                LoginResponse(
                    success = false,
                    message = "Network protocol error: ${e.message}",
                    accountId = null,
                    driverId = null,
                    username = null,
                    email = null,
                    mfaRequired = false
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "MFA verify error: ${e.javaClass.simpleName} - ${e.message}", e)
            LoginResponse(
                success = false,
                message = "Network error: ${e.javaClass.simpleName} - ${e.message}",
                accountId = null,
                driverId = null,
                username = null,
                email = null,
                mfaRequired = false
            )
        }
    }
    
    suspend fun getMfaStatus(): MfaStatusResponse {
        Log.d(TAG, "Getting MFA status")
        return try {
            val request = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/mfa/status")
                .get()
                .build()
            
            val response = NetworkClient.client.newCall(request).execute()
            
            Log.d(TAG, "MFA status response code: ${response.code}")
            
            if (!response.isSuccessful) {
                return MfaStatusResponse(success = false, mfaEnabled = null)
            }
            
            val responseBody = NetworkClient.safeBodyString(response)
            if (responseBody == null || responseBody.isEmpty()) {
                return MfaStatusResponse(success = false, mfaEnabled = null)
            }
            
            try {
                NetworkClient.gson.fromJson(responseBody, MfaStatusResponse::class.java)
            } catch (e: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                MfaStatusResponse(success = false, mfaEnabled = null)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse response: ${e.message}", e)
                MfaStatusResponse(success = false, mfaEnabled = null)
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            MfaStatusResponse(success = false, mfaEnabled = null)
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            MfaStatusResponse(success = false, mfaEnabled = null)
        } catch (e: Exception) {
            Log.e(TAG, "MFA status error: ${e.message}", e)
            MfaStatusResponse(success = false, mfaEnabled = null)
        }
    }
    
    suspend fun enableMfa(password: String): MfaEnableResponse {
        Log.d(TAG, "Enabling MFA")
        return try {
            val requestBody = MfaPasswordRequest(password)
            val json = NetworkClient.gson.toJson(requestBody)
            
            val request = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/mfa/enable")
                .post(json.toRequestBody("application/json".toMediaType()))
                .build()
            
            val response = NetworkClient.client.newCall(request).execute()
            
            Log.d(TAG, "MFA enable response code: ${response.code}")
            
            if (!response.isSuccessful) {
                val errorMessage = when (response.code) {
                    401 -> "Incorrect password"
                    400 -> "Bad request"
                    else -> "MFA enable failed: HTTP ${response.code}"
                }
                return MfaEnableResponse(
                    success = false,
                    message = errorMessage,
                    qrUri = null,
                    secret = null
                )
            }
            
            val responseBody = NetworkClient.safeBodyString(response)
            if (responseBody == null || responseBody.isEmpty()) {
                return MfaEnableResponse(
                    success = false,
                    message = "Empty response from server",
                    qrUri = null,
                    secret = null
                )
            }
            
            try {
                NetworkClient.gson.fromJson(responseBody, MfaEnableResponse::class.java)
            } catch (e: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                MfaEnableResponse(
                    success = false,
                    message = "Invalid JSON response: ${e.message}",
                    qrUri = null,
                    secret = null
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse server response: ${e.message}", e)
                MfaEnableResponse(
                    success = false,
                    message = "Failed to parse server response: ${e.message}",
                    qrUri = null,
                    secret = null
                )
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            MfaEnableResponse(
                success = false,
                message = "Request timed out. Please check your connection.",
                qrUri = null,
                secret = null
            )
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            MfaEnableResponse(
                success = false,
                message = "Network error: ${e.message}",
                qrUri = null,
                secret = null
            )
        }
    }
    
    suspend fun confirmMfa(code: String): MfaConfirmResponse {
        Log.d(TAG, "Confirming MFA")
        return try {
            val requestBody = MfaConfirmRequest(code)
            val json = NetworkClient.gson.toJson(requestBody)
            
            val request = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/mfa/confirm")
                .post(json.toRequestBody("application/json".toMediaType()))
                .build()
            
            val response = NetworkClient.client.newCall(request).execute()
            
            Log.d(TAG, "MFA confirm response code: ${response.code}")
            
            if (!response.isSuccessful) {
                val errorMessage = when (response.code) {
                    401 -> "Invalid code. Try again."
                    400 -> "Bad request"
                    else -> "MFA confirm failed: HTTP ${response.code}"
                }
                return MfaConfirmResponse(
                    success = false,
                    message = errorMessage,
                    recoveryCodes = null
                )
            }
            
            val responseBody = NetworkClient.safeBodyString(response)
            if (responseBody == null || responseBody.isEmpty()) {
                return MfaConfirmResponse(
                    success = false,
                    message = "Empty response from server",
                    recoveryCodes = null
                )
            }
            
            try {
                NetworkClient.gson.fromJson(responseBody, MfaConfirmResponse::class.java)
            } catch (e: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                MfaConfirmResponse(
                    success = false,
                    message = "Invalid JSON response: ${e.message}",
                    recoveryCodes = null
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse server response: ${e.message}", e)
                MfaConfirmResponse(
                    success = false,
                    message = "Failed to parse server response: ${e.message}",
                    recoveryCodes = null
                )
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            MfaConfirmResponse(
                success = false,
                message = "Request timed out. Please check your connection.",
                recoveryCodes = null
            )
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            MfaConfirmResponse(
                success = false,
                message = "Network error: ${e.message}",
                recoveryCodes = null
            )
        } catch (e: Exception) {
            Log.e(TAG, "MFA confirm error: ${e.message}", e)
            MfaConfirmResponse(
                success = false,
                message = "Network error: ${e.message}",
                recoveryCodes = null
            )
        }
    }
    
    suspend fun disableMfa(password: String): ApiResponse {
        Log.d(TAG, "Disabling MFA")
        return try {
            val requestBody = MfaPasswordRequest(password)
            val json = NetworkClient.gson.toJson(requestBody)
            
            val request = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/mfa/disable")
                .post(json.toRequestBody("application/json".toMediaType()))
                .build()
            
            val response = NetworkClient.client.newCall(request).execute()
            
            Log.d(TAG, "MFA disable response code: ${response.code}")
            
            if (!response.isSuccessful) {
                val errorMessage = when (response.code) {
                    401 -> "Incorrect password"
                    400 -> "Bad request"
                    else -> "MFA disable failed: HTTP ${response.code}"
                }
                return ApiResponse(
                    success = false,
                    message = errorMessage
                )
            }
            
            val responseBody = NetworkClient.safeBodyString(response)
            if (responseBody == null || responseBody.isEmpty()) {
                return ApiResponse(
                    success = false,
                    message = "Empty response from server"
                )
            }
            
            try {
                NetworkClient.gson.fromJson(responseBody, ApiResponse::class.java)
            } catch (e: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                ApiResponse(
                    success = false,
                    message = "Invalid JSON response: ${e.message}"
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse server response: ${e.message}", e)
                ApiResponse(
                    success = false,
                    message = "Failed to parse server response: ${e.message}"
                )
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            ApiResponse(
                success = false,
                message = "Request timed out. Please check your connection."
            )
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            ApiResponse(
                success = false,
                message = "Network error: ${e.message}"
            )
        } catch (e: Exception) {
            Log.e(TAG, "MFA disable error: ${e.message}", e)
            ApiResponse(
                success = false,
                message = "Network error: ${e.message}"
            )
        }
    }
    
    suspend fun testConnection(): String {
        Log.d(TAG, "Testing connection to: ${NetworkClient.baseUrl}/api/mobile/login")
        return try {
            val requestBody = LoginRequest("test@example.com", "testpass")
            val json = NetworkClient.gson.toJson(requestBody)
            
            val request = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/login")
                .post(json.toRequestBody("application/json".toMediaType()))
                .addHeader("Content-Type", "application/json")
                .build()
            
            val response = NetworkClient.client.newCall(request).execute()
            val responseBody = response.body?.string()
            
            Log.d(TAG, "Test response code: ${response.code}")
            Log.d(TAG, "Test response body: $responseBody")
            
            if (response.isSuccessful && responseBody != null) {
                "Connection successful: Server is responding"
            } else if (response.code == 401) {
                "Connection successful: Server is responding (401 expected with test credentials)"
            } else {
                "Connection failed: HTTP ${response.code} - ${response.message}"
            }
        } catch (e: Exception) {
            Log.e(TAG, "Test connection error: ${e.javaClass.simpleName} - ${e.message}", e)
            "Connection error: ${e.javaClass.simpleName} - ${e.message}"
        }
    }
    
    suspend fun logout(): Boolean {
        Log.d(TAG, "Starting logout process")
        return try {
            val requestBuilder = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/logout")
                .post("".toRequestBody(null))
            
            // Include session cookies in logout request
            NetworkClient.getSessionCookies()?.let { cookies ->
                requestBuilder.addHeader("Cookie", cookies)
                Log.d(TAG, "Including cookies in logout request: $cookies")
            } ?: run {
                Log.w(TAG, "No session cookies available for logout request")
            }
            
            val request = requestBuilder.build()
            val response = NetworkClient.client.newCall(request).execute()
            
            Log.d(TAG, "Logout response code: ${response.code}")
            
            // Clear session cookies after logout
            NetworkClient.clearSessionCookies()
            
            response.isSuccessful
        } catch (e: Exception) {
            Log.e(TAG, "Logout error: ${e.message}", e)
            false
        }
    }
}

class ProfileService {
    private val TAG = "ProfileService"
    
    suspend fun getProfile(): ProfileResponse {
        Log.d(TAG, "Starting getProfile request")
        return try {
            val requestBuilder = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/profile")
                .get()
                .addHeader("Content-Type", "application/json")
            
            // Include session cookies in profile request
            NetworkClient.getSessionCookies()?.let { cookies ->
                requestBuilder.addHeader("Cookie", cookies)
                Log.d(TAG, "Sending profile request with cookies: $cookies")
            } ?: run {
                Log.w(TAG, "No session cookies available for profile request")
            }
            
            val request = requestBuilder.build()
            Log.d(TAG, "Profile request URL: ${request.url}")
            Log.d(TAG, "Profile request headers: ${request.headers}")
            
            val response = NetworkClient.client.newCall(request).execute()
            
            Log.d(TAG, "Profile response code: ${response.code}")
            Log.d(TAG, "Profile response headers: ${response.headers}")
            
            if (!response.isSuccessful) {
                return ProfileResponse(
                    success = false,
                    message = "Failed to fetch profile: HTTP ${response.code}",
                    profile = null
                )
            }
            
            val responseBody = NetworkClient.safeBodyString(response)
            Log.d(TAG, "Profile response body: $responseBody")
            
            if (responseBody == null || responseBody.isEmpty()) {
                return ProfileResponse(
                    success = false,
                    message = "Empty response from server",
                    profile = null
                )
            }
            
            try {
                val profileResponse = NetworkClient.gson.fromJson(responseBody, ProfileResponse::class.java)
                    Log.d(TAG, "Parsed profile response: $profileResponse")
                    Log.d(TAG, "Profile age: ${profileResponse.profile?.age} (type: ${profileResponse.profile?.age?.javaClass?.simpleName})")
                    Log.d(TAG, "Profile gender: \"${profileResponse.profile?.gender}\" (type: ${profileResponse.profile?.gender?.javaClass?.simpleName})")
                    profileResponse
                } catch (e: com.google.gson.JsonSyntaxException) {
                    Log.e(TAG, "JSON parsing error: ${e.message}", e)
                    ProfileResponse(
                        success = false,
                        message = "Invalid JSON response: ${e.message}",
                        profile = null
                    )
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to parse profile response: ${e.message}", e)
                    ProfileResponse(
                        success = false,
                        message = "Failed to parse server response: ${e.message}",
                        profile = null
                    )
                }
        } catch (e: java.net.ProtocolException) {
            // Handle redirect loops - typically happens when session expires
            if (e.message?.contains("Too many follow-up requests") == true) {
                Log.e(TAG, "Redirect loop detected - session likely expired: ${e.message}")
                // Clear invalid session cookies
                NetworkClient.clearSessionCookies()
                ProfileResponse(
                    success = false,
                    message = "Session expired. Please log in again.",
                    profile = null
                )
            } else {
                Log.e(TAG, "Protocol error: ${e.message}", e)
                ProfileResponse(
                    success = false,
                    message = "Network protocol error: ${e.message}",
                    profile = null
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "Profile request exception: ${e.javaClass.simpleName} - ${e.message}", e)
            ProfileResponse(
                success = false,
                message = "Network error: ${e.javaClass.simpleName} - ${e.message}",
                profile = null
            )
        }
    }
    
    suspend fun updateProfile(updateRequest: UpdateProfileRequest): ApiResponse {
        Log.d(TAG, "Starting updateProfile request")
        return try {
            val json = NetworkClient.gson.toJson(updateRequest)
            
            val requestBuilder = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/profile")
                .put(json.toRequestBody("application/json".toMediaType()))
                .addHeader("Content-Type", "application/json")
            
            // Include session cookies
            NetworkClient.getSessionCookies()?.let { cookies ->
                requestBuilder.addHeader("Cookie", cookies)
            }
            
            val request = requestBuilder.build()
            val response = NetworkClient.client.newCall(request).execute()
            
            if (!response.isSuccessful) {
                val errorMessage = when (response.code) {
                    400 -> "Bad request"
                    401 -> "Not authenticated"
                    404 -> "Profile not found"
                    500 -> "Server error"
                    else -> "HTTP ${response.code}: ${response.message}"
                }
                return ApiResponse(
                    success = false,
                    message = errorMessage
                )
            }
            
            val responseBody = NetworkClient.safeBodyString(response)
            if (responseBody == null || responseBody.isEmpty()) {
                return ApiResponse(
                    success = false,
                    message = "Empty response from server"
                )
            }
            
            try {
                NetworkClient.gson.fromJson(responseBody, ApiResponse::class.java)
            } catch (e: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                ApiResponse(
                    success = false,
                    message = "Invalid JSON response: ${e.message}"
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse server response: ${e.message}", e)
                ApiResponse(
                    success = false,
                    message = "Failed to parse server response: ${e.message}"
                )
            }
        } catch (e: java.net.ProtocolException) {
            if (e.message?.contains("Too many follow-up requests") == true) {
                NetworkClient.clearSessionCookies()
                ApiResponse(
                    success = false,
                    message = "Session expired. Please log in again."
                )
            } else {
                ApiResponse(
                    success = false,
                    message = "Network protocol error: ${e.message}"
                )
            }
        } catch (e: Exception) {
            ApiResponse(
                success = false,
                message = "Network error: ${e.message}"
            )
        }
    }
    
    suspend fun changePassword(changePasswordRequest: ChangePasswordRequest): ApiResponse {
        Log.d(TAG, "Starting changePassword request")
        return try {
            val json = NetworkClient.gson.toJson(changePasswordRequest)
            
            val requestBuilder = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/change-password")
                .put(json.toRequestBody("application/json".toMediaType()))
                .addHeader("Content-Type", "application/json")
            
            // Include session cookies
            NetworkClient.getSessionCookies()?.let { cookies ->
                requestBuilder.addHeader("Cookie", cookies)
            }
            
            val request = requestBuilder.build()
            val response = NetworkClient.client.newCall(request).execute()
            
            if (!response.isSuccessful) {
                return ApiResponse(
                    success = false,
                    message = "Failed to change password: HTTP ${response.code}"
                )
            }
            
            val responseBody = NetworkClient.safeBodyString(response)
            if (responseBody == null || responseBody.isEmpty()) {
                return ApiResponse(
                    success = false,
                    message = "Empty response from server"
                )
            }
            
            try {
                NetworkClient.gson.fromJson(responseBody, ApiResponse::class.java)
            } catch (e: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                ApiResponse(
                    success = false,
                    message = "Invalid JSON response: ${e.message}"
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse server response: ${e.message}", e)
                ApiResponse(
                    success = false,
                    message = "Failed to parse server response: ${e.message}"
                )
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            ApiResponse(
                success = false,
                message = "Request timed out. Please check your connection."
            )
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            ApiResponse(
                success = false,
                message = "Network error: ${e.message}"
            )
        } catch (e: Exception) {
            Log.e(TAG, "Change password error: ${e.message}", e)
            ApiResponse(
                success = false,
                message = "Network error: ${e.message}"
            )
        }
    }
    
    suspend fun uploadProfilePicture(imageFile: java.io.File): UploadProfilePictureResponse {
        Log.d(TAG, "Starting uploadProfilePicture request")
        return try {
            val requestBody = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart(
                    "file",
                    imageFile.name,
                    imageFile.asRequestBody("image/*".toMediaType())
                )
                .build()
            
            val requestBuilder = Request.Builder()
                .url("${NetworkClient.baseUrl}/api/mobile/profile/picture")
                .post(requestBody)
            
            // Include session cookies
            NetworkClient.getSessionCookies()?.let { cookies ->
                requestBuilder.addHeader("Cookie", cookies)
            }
            
            val request = requestBuilder.build()
            val response = NetworkClient.client.newCall(request).execute()
            
            if (!response.isSuccessful) {
                return UploadProfilePictureResponse(
                    success = false,
                    message = "Failed to upload picture: HTTP ${response.code}",
                    profileImageURL = null
                )
            }
            
            val responseBody = NetworkClient.safeBodyString(response)
            if (responseBody == null || responseBody.isEmpty()) {
                return UploadProfilePictureResponse(
                    success = false,
                    message = "Empty response from server",
                    profileImageURL = null
                )
            }
            
            try {
                NetworkClient.gson.fromJson(responseBody, UploadProfilePictureResponse::class.java)
            } catch (e: com.google.gson.JsonSyntaxException) {
                Log.e(TAG, "JSON parsing error: ${e.message}", e)
                UploadProfilePictureResponse(
                    success = false,
                    message = "Invalid JSON response: ${e.message}",
                    profileImageURL = null
                )
            } catch (e: Exception) {
                Log.e(TAG, "Failed to parse server response: ${e.message}", e)
                UploadProfilePictureResponse(
                    success = false,
                    message = "Failed to parse server response: ${e.message}",
                    profileImageURL = null
                )
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.e(TAG, "Request timeout: ${e.message}", e)
            UploadProfilePictureResponse(
                success = false,
                message = "Request timed out. Please check your connection.",
                profileImageURL = null
            )
        } catch (e: java.io.IOException) {
            Log.e(TAG, "Network error: ${e.message}", e)
            UploadProfilePictureResponse(
                success = false,
                message = "Network error: ${e.message}",
                profileImageURL = null
            )
        } catch (e: Exception) {
            Log.e(TAG, "Upload picture error: ${e.message}", e)
            UploadProfilePictureResponse(
                success = false,
                message = "Network error: ${e.message}",
                profileImageURL = null
            )
        }
    }
}
