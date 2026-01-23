package com.example.driverrewards.ui.profile

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.ProfileData
import com.example.driverrewards.network.ProfileService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class ProfileViewModel : ViewModel() {
    private val profileService = ProfileService()
    
    private val _profileData = MutableLiveData<ProfileData?>()
    val profileData: LiveData<ProfileData?> = _profileData
    
    private val _isLoading = MutableLiveData<Boolean>()
    val isLoading: LiveData<Boolean> = _isLoading
    
    private val _errorMessage = MutableLiveData<String?>()
    val errorMessage: LiveData<String?> = _errorMessage
    
    private var isDataCached: Boolean = false
    
    fun loadProfile() {
        android.util.Log.d("ProfileViewModel", "===== LOAD PROFILE =====")
        // If data is already cached, skip network call
        if (isDataCached && _profileData.value != null) {
            android.util.Log.d("ProfileViewModel", "Using cached profile data (skipping network call)")
            android.util.Log.d("ProfileViewModel", "Cached sponsorCompany: ${_profileData.value?.sponsorCompany}")
            android.util.Log.d("ProfileViewModel", "Cached pointsBalance: ${_profileData.value?.pointsBalance}")
            return
        }
        
        android.util.Log.d("ProfileViewModel", "Fetching profile from server (cache miss or refresh)")
        viewModelScope.launch {
            _isLoading.value = true
            _errorMessage.value = null
            
            try {
                // Run network call on IO dispatcher (background thread)
                val response = withContext(Dispatchers.IO) {
                    profileService.getProfile()
                }
                
                if (response.success) {
                    response.profile?.let { profile ->
                        android.util.Log.d("ProfileViewModel", "===== PROFILE LOADED SUCCESSFULLY =====")
                        android.util.Log.d("ProfileViewModel", "Profile data:")
                        android.util.Log.d("ProfileViewModel", "  - driverId: ${profile.driverId}")
                        android.util.Log.d("ProfileViewModel", "  - pointsBalance: ${profile.pointsBalance}")
                        android.util.Log.d("ProfileViewModel", "  - sponsorCompany: ${profile.sponsorCompany}")
                        android.util.Log.d("ProfileViewModel", "  - email: ${profile.email}")
                        android.util.Log.d("ProfileViewModel", "This profile data should reflect the ACTIVE sponsor environment")
                        
                        // Verify this matches the active sponsor by checking the sponsor list
                        // (This will be done in ProfileFragment after sponsor switch)
                    }
                    _profileData.value = response.profile
                    isDataCached = true
                } else {
                    val message = response.message ?: "Failed to load profile"
                    android.util.Log.e("ProfileViewModel", "Failed to load profile: $message")
                    _errorMessage.value = message
                    
                    // If session expired, set a special flag that the UI can handle
                    if (message.contains("Session expired", ignoreCase = true) || 
                        message.contains("Not authenticated", ignoreCase = true)) {
                        _errorMessage.value = "Session expired. Please log in again."
                    }
                }
            } catch (e: Exception) {
                android.util.Log.e("ProfileViewModel", "Error loading profile: ${e.message}", e)
                _errorMessage.value = "Network error: ${e.message}"
            } finally {
                _isLoading.value = false
            }
        }
    }
    
    fun refreshProfile() {
        android.util.Log.d("ProfileViewModel", "===== REFRESH PROFILE =====")
        android.util.Log.d("ProfileViewModel", "Clearing cache and forcing fresh fetch")
        android.util.Log.d("ProfileViewModel", "This should fetch profile data for the CURRENT active sponsor")
        // Force a fresh fetch by clearing cache flag
        isDataCached = false
        loadProfile()
    }
    
    /**
     * Workaround: Manually update profile data with sponsor-specific information.
     * This is needed because the backend profile endpoint sometimes returns stale data
     * after a sponsor switch. We update the UI immediately with the correct data from
     * the switch response.
     */
    fun updateSponsorInfo(sponsorCompany: String?, pointsBalance: Int) {
        android.util.Log.d("ProfileViewModel", "===== MANUALLY UPDATING SPONSOR INFO =====")
        android.util.Log.d("ProfileViewModel", "Updating sponsorCompany to: $sponsorCompany")
        android.util.Log.d("ProfileViewModel", "Updating pointsBalance to: $pointsBalance")
        
        _profileData.value?.let { currentProfile ->
            val updatedProfile = ProfileData(
                accountId = currentProfile.accountId,
                driverId = currentProfile.driverId,
                email = currentProfile.email,
                username = currentProfile.username,
                firstName = currentProfile.firstName,
                lastName = currentProfile.lastName,
                wholeName = currentProfile.wholeName,
                pointsBalance = pointsBalance,
                memberSince = currentProfile.memberSince,
                shippingAddress = currentProfile.shippingAddress,
                licenseNumber = currentProfile.licenseNumber,
                licenseIssueDate = currentProfile.licenseIssueDate,
                licenseExpirationDate = currentProfile.licenseExpirationDate,
                sponsorCompany = sponsorCompany,
                status = currentProfile.status,
                age = currentProfile.age,
                gender = currentProfile.gender,
                profileImageURL = currentProfile.profileImageURL
            )
            _profileData.value = updatedProfile
            android.util.Log.d("ProfileViewModel", "Profile data manually updated with new sponsor info")
        } ?: run {
            android.util.Log.w("ProfileViewModel", "Cannot update sponsor info - no existing profile data")
        }
    }
}
