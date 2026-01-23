package com.example.driverrewards.utils

import android.content.Context
import android.content.SharedPreferences
import java.time.Instant

class SessionManager(context: Context) {
    // Use MODE_PRIVATE but add additional persistence mechanisms
    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    
    companion object {
        private const val PREFS_NAME = "DriverRewardsSession"
        private const val KEY_IS_LOGGED_IN = "is_logged_in"
        private const val KEY_ACCOUNT_ID = "account_id"
        private const val KEY_DRIVER_ID = "driver_id"
        private const val KEY_EMAIL = "email"
        private const val KEY_USERNAME = "username"
        private const val KEY_DARK_MODE = "dark_mode"
        private const val KEY_SESSION_COOKIES = "session_cookies"
        private const val KEY_LOGIN_TIMESTAMP = "login_timestamp"
        private const val SESSION_TIMEOUT_HOURS = 24 * 7 // 7 days
        private const val KEY_LAST_NOTIFICATION_SYNC = "last_notification_sync"
    }
    
    fun saveSession(accountId: String, driverId: String, email: String, username: String) {
        prefs.edit().apply {
            putBoolean(KEY_IS_LOGGED_IN, true)
            putString(KEY_ACCOUNT_ID, accountId)
            putString(KEY_DRIVER_ID, driverId)
            putString(KEY_EMAIL, email)
            putString(KEY_USERNAME, username)
            putLong(KEY_LOGIN_TIMESTAMP, System.currentTimeMillis())
            apply()
        }
    }
    
    fun saveSessionCookies(cookies: String?) {
        if (cookies != null) {
            prefs.edit().putString(KEY_SESSION_COOKIES, cookies).commit()
        }
    }
    
    fun getSessionCookies(): String? {
        return prefs.getString(KEY_SESSION_COOKIES, null)
    }
    
    fun isLoggedIn(): Boolean {
        val isLoggedIn = prefs.getBoolean(KEY_IS_LOGGED_IN, false)
        if (!isLoggedIn) return false
        
        // Check if session has expired
        val loginTimestamp = prefs.getLong(KEY_LOGIN_TIMESTAMP, 0)
        val currentTime = System.currentTimeMillis()
        val sessionTimeoutMs = SESSION_TIMEOUT_HOURS * 60 * 60 * 1000L
        
        if (currentTime - loginTimestamp > sessionTimeoutMs) {
            // Session expired, clear it
            logout()
            return false
        }
        
        return true
    }
    
    fun getAccountId(): String? {
        return prefs.getString(KEY_ACCOUNT_ID, null)
    }
    
    fun getDriverId(): String? {
        return prefs.getString(KEY_DRIVER_ID, null)
    }
    
    fun getEmail(): String? {
        return prefs.getString(KEY_EMAIL, null)
    }
    
    fun getUsername(): String? {
        return prefs.getString(KEY_USERNAME, null)
    }
    
    fun setDarkMode(enabled: Boolean) {
        prefs.edit().putBoolean(KEY_DARK_MODE, enabled).apply()
    }
    
    fun isDarkModeEnabled(): Boolean {
        return prefs.getBoolean(KEY_DARK_MODE, false)
    }
    
    fun logout() {
        // Preserve dark mode setting during logout
        val darkModeEnabled = isDarkModeEnabled()
        prefs.edit().clear().apply()
        if (darkModeEnabled) {
            setDarkMode(true)
        }
    }

    fun updateLastNotificationSync(timestampIso: String = Instant.now().toString()) {
        prefs.edit().putString(KEY_LAST_NOTIFICATION_SYNC, timestampIso).apply()
    }

    fun getLastNotificationSync(): String? {
        return prefs.getString(KEY_LAST_NOTIFICATION_SYNC, null)
    }

    fun clearNotificationSync() {
        prefs.edit().remove(KEY_LAST_NOTIFICATION_SYNC).apply()
    }
    
    fun clearSessionCookies() {
        prefs.edit().remove(KEY_SESSION_COOKIES).apply()
    }
    
    fun validateSession(): Boolean {
        // Check if session exists and hasn't expired
        if (!isLoggedIn()) {
            return false
        }
        
        // Check if we have essential session data
        val accountId = getAccountId()
        val driverId = getDriverId()
        val email = getEmail()
        val username = getUsername()
        
        if (accountId.isNullOrEmpty() || driverId.isNullOrEmpty() || 
            email.isNullOrEmpty() || username.isNullOrEmpty()) {
            logout()
            return false
        }
        
        return true
    }
    
    fun hasValidSessionData(): Boolean {
        // Check if we have the minimum required session data without expiration check
        val accountId = getAccountId()
        val driverId = getDriverId()
        val email = getEmail()
        val username = getUsername()
        
        return !accountId.isNullOrEmpty() && !driverId.isNullOrEmpty() && 
               !email.isNullOrEmpty() && !username.isNullOrEmpty()
    }
}
