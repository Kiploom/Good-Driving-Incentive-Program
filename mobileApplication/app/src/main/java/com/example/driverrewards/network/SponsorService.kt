package com.example.driverrewards.network

import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

data class DriverSponsorEnvironment(
    @com.google.gson.annotations.SerializedName("driverSponsorId") val driverSponsorId: String,
    @com.google.gson.annotations.SerializedName("driverId") val driverId: String?,
    @com.google.gson.annotations.SerializedName("sponsorId") val sponsorId: String?,
    @com.google.gson.annotations.SerializedName("sponsorCompanyId") val sponsorCompanyId: String?,
    @com.google.gson.annotations.SerializedName("sponsorName") val sponsorName: String?,
    @com.google.gson.annotations.SerializedName("sponsorCompanyName") val sponsorCompanyName: String?,
    @com.google.gson.annotations.SerializedName("status") val status: String?,
    @com.google.gson.annotations.SerializedName("pointsBalance") val pointsBalance: Int,
    @com.google.gson.annotations.SerializedName("joinedAt") val joinedAt: String?,
    @com.google.gson.annotations.SerializedName("updatedAt") val updatedAt: String?,
    @com.google.gson.annotations.SerializedName("isActive") val isActive: Boolean,
    @com.google.gson.annotations.SerializedName("isCurrent") val isCurrent: Boolean
)

data class DriverSponsorListResponse(
    @com.google.gson.annotations.SerializedName("success") val success: Boolean,
    @com.google.gson.annotations.SerializedName("message") val message: String?,
    @com.google.gson.annotations.SerializedName("currentDriverSponsorId") val currentDriverSponsorId: String?,
    @com.google.gson.annotations.SerializedName("hasMultiple") val hasMultiple: Boolean?,
    @com.google.gson.annotations.SerializedName("sponsors") val sponsors: List<DriverSponsorEnvironment>?
)

