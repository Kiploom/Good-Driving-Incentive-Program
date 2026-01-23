package com.example.driverrewards.ui.notifications

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.BasicResponse
import com.example.driverrewards.network.NotificationPreferencesPayload
import com.example.driverrewards.network.NotificationPreferencesResponse
import com.example.driverrewards.network.NotificationService
import kotlinx.coroutines.launch

class NotificationSettingsViewModel : ViewModel() {

    private val notificationService = NotificationService()

    private val _preferences = MutableLiveData<NotificationPreferencesPayload?>()
    val preferences: LiveData<NotificationPreferencesPayload?> = _preferences

    private val _isLoading = MutableLiveData(false)
    val isLoading: LiveData<Boolean> = _isLoading

    private val _isSaving = MutableLiveData(false)
    val isSaving: LiveData<Boolean> = _isSaving

    private val _message = MutableLiveData<String?>()
    val message: LiveData<String?> = _message

    private val _testResult = MutableLiveData<BasicResponse?>()
    val testResult: LiveData<BasicResponse?> = _testResult

    init {
        loadPreferences()
    }

    fun loadPreferences() {
        viewModelScope.launch {
            _isLoading.value = true
            try {
                val response: NotificationPreferencesResponse = notificationService.getPreferences()
                if (response.success && response.preferences != null) {
                    _preferences.value = response.preferences
                } else {
                    _message.value = response.message ?: "Failed to load preferences"
                }
            } catch (ex: Exception) {
                _message.value = ex.message ?: "Error loading preferences"
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun savePreferences(payload: NotificationPreferencesPayload) {
        viewModelScope.launch {
            _isSaving.value = true
            try {
                val response = notificationService.updatePreferences(payload)
                if (response.success && response.preferences != null) {
                    _preferences.value = response.preferences
                    _message.value = response.message
                } else {
                    _message.value = response.message ?: "Failed to update preferences"
                }
            } catch (ex: Exception) {
                _message.value = ex.message ?: "Error updating preferences"
            } finally {
                _isSaving.value = false
            }
        }
    }

    fun triggerLowPointsTest(balance: Int, threshold: Int) {
        viewModelScope.launch {
            try {
                val response = notificationService.triggerLowPointsTest(balance, threshold)
                _testResult.value = response
                if (!response.success) {
                    _message.value = response.message
                }
            } catch (ex: Exception) {
                _message.value = ex.message ?: "Unable to send test notification"
            }
        }
    }

    fun clearTestResult() {
        _testResult.value = null
    }
}

