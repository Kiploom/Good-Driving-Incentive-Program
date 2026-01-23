package com.example.driverrewards.ui.notifications

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.NotificationItem
import com.example.driverrewards.network.NotificationListEnvelope
import com.example.driverrewards.network.NotificationService
import kotlinx.coroutines.launch

class NotificationsViewModel : ViewModel() {

    private val notificationService = NotificationService()

    private val _notifications = MutableLiveData<List<NotificationItem>>(emptyList())
    val notifications: LiveData<List<NotificationItem>> = _notifications

    private val _isLoading = MutableLiveData(false)
    val isLoading: LiveData<Boolean> = _isLoading

    private val _isRefreshing = MutableLiveData(false)
    val isRefreshing: LiveData<Boolean> = _isRefreshing

    private val _hasMore = MutableLiveData(false)
    val hasMore: LiveData<Boolean> = _hasMore

    private val _errorMessage = MutableLiveData<String?>()
    val errorMessage: LiveData<String?> = _errorMessage

    private val _showUnreadOnly = MutableLiveData(false)
    val showUnreadOnly: LiveData<Boolean> = _showUnreadOnly

    private var currentPage = 1
    private val pageSize = 20
    private var loadingMore = false

    init {
        loadNotifications(refresh = true)
    }

    fun refresh() {
        loadNotifications(refresh = true)
    }

    fun setUnreadOnly(onlyUnread: Boolean) {
        if (_showUnreadOnly.value == onlyUnread) return
        _showUnreadOnly.value = onlyUnread
        currentPage = 1
        loadNotifications(refresh = true)
    }

    fun loadNotifications(refresh: Boolean = false) {
        android.util.Log.d("NotificationsViewModel", "===== LOAD NOTIFICATIONS =====")
        android.util.Log.d("NotificationsViewModel", "refresh: $refresh, page: $currentPage")
        android.util.Log.d("NotificationsViewModel", "IMPORTANT: Notifications should come from BOTH sponsors, not just the active one")
        if (loadingMore || (_isLoading.value == true && !refresh)) return

        viewModelScope.launch {
            try {
                if (refresh) {
                    currentPage = 1
                    _isRefreshing.value = true
                    android.util.Log.d("NotificationsViewModel", "Refreshing notifications - cleared existing notifications")
                } else {
                    _isLoading.value = true
                }
                _errorMessage.value = null

                val envelope: NotificationListEnvelope = notificationService.getNotifications(
                    page = currentPage,
                    pageSize = pageSize,
                    unreadOnly = _showUnreadOnly.value == true
                )

                if (envelope.success) {
                    android.util.Log.d("NotificationsViewModel", "===== NOTIFICATIONS LOADED SUCCESSFULLY =====")
                    val incoming = envelope.notifications ?: emptyList()
                    android.util.Log.d("NotificationsViewModel", "Received ${incoming.size} notifications")
                    android.util.Log.d("NotificationsViewModel", "These notifications should include notifications from BOTH sponsors")
                    
                    // Log notifications with sponsor context for debugging
                    incoming.take(5).forEachIndexed { index, notification ->
                        val sponsorContext = notification.sponsorContext
                        val sponsorInfo = if (sponsorContext != null) {
                            "Sponsor: ${sponsorContext.sponsorName ?: sponsorContext.sponsorId ?: "Unknown"} (specific: ${sponsorContext.isSponsorSpecific})"
                        } else {
                            "No sponsor context (general notification)"
                        }
                        android.util.Log.d("NotificationsViewModel", "  Notification $index: ${notification.title} - $sponsorInfo")
                    }
                    
                    val updated = if (currentPage == 1) {
                        incoming
                    } else {
                        (_notifications.value ?: emptyList()) + incoming
                    }
                    _notifications.value = updated
                    val hasMorePages = envelope.pagination?.hasMore ?: false
                    _hasMore.value = hasMorePages
                    if (hasMorePages) {
                        currentPage++
                    }
                } else {
                    android.util.Log.e("NotificationsViewModel", "Failed to load notifications: ${envelope.message}")
                    _errorMessage.value = envelope.message ?: "Failed to load notifications"
                }
            } catch (ex: Exception) {
                android.util.Log.e("NotificationsViewModel", "Error loading notifications: ${ex.message}", ex)
                _errorMessage.value = ex.message ?: "Error loading notifications"
            } finally {
                _isLoading.value = false
                _isRefreshing.value = false
                loadingMore = false
            }
        }
    }

    fun loadMore() {
        if (_hasMore.value != true || loadingMore) return
        loadingMore = true
        loadNotifications(refresh = false)
    }

    fun markNotificationRead(notificationId: String) {
        viewModelScope.launch {
            try {
                val response = notificationService.markNotificationsRead(
                    listOf(notificationId),
                    markAll = false
                )
                if (response.success) {
                    _notifications.value = _notifications.value?.map {
                        if (it.id == notificationId) it.copy(isRead = true) else it
                    }
                } else {
                    _errorMessage.value = response.message
                }
            } catch (ex: Exception) {
                _errorMessage.value = ex.message
            }
        }
    }

    fun markAllRead() {
        viewModelScope.launch {
            try {
                val response = notificationService.markNotificationsRead(null, markAll = true)
                if (response.success) {
                    _notifications.value = _notifications.value?.map { it.copy(isRead = true) }
                } else {
                    _errorMessage.value = response.message
                }
            } catch (ex: Exception) {
                _errorMessage.value = ex.message
            }
        }
    }
}