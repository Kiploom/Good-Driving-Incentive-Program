package com.example.driverrewards.ui.points

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.driverrewards.network.PointsService
import com.example.driverrewards.network.PointsDetailsResponse
import com.example.driverrewards.network.PointsTransaction
import com.example.driverrewards.network.PointsGraphDataPoint
import kotlinx.coroutines.launch
import kotlin.math.abs

class PointsViewModel : ViewModel() {

    private val pointsService = PointsService()
    
    private val _pointsDetails = MutableLiveData<PointsDetailsResponse?>()
    val pointsDetails: LiveData<PointsDetailsResponse?> = _pointsDetails
    
    private val _pointsHistory = MutableLiveData<List<PointsTransaction>>()
    val pointsHistory: LiveData<List<PointsTransaction>> = _pointsHistory
    
    private val _graphData = MutableLiveData<List<PointsGraphDataPoint>>()
    val graphData: LiveData<List<PointsGraphDataPoint>> = _graphData
    
    private val _isLoading = MutableLiveData<Boolean>(false)
    val isLoading: LiveData<Boolean> = _isLoading
    
    private val _errorMessage = MutableLiveData<String?>()
    val errorMessage: LiveData<String?> = _errorMessage
    
    private val _totalCount = MutableLiveData<Int>(0)
    val totalCount: LiveData<Int> = _totalCount
    
    // Filter state
    private var _showEarnedOnly = false
    private var _showSpentOnly = false
    private var _minDelta = 0

    fun loadPointsDetails() {
        android.util.Log.d("PointsViewModel", "===== LOAD POINTS DETAILS =====")
        android.util.Log.d("PointsViewModel", "This should load points information from the ACTIVE sponsor")
        viewModelScope.launch {
            try {
                _isLoading.value = true
                _errorMessage.value = null
                
                val response = pointsService.getPointsDetails()
                
                if (response.success) {
                    android.util.Log.d("PointsViewModel", "===== POINTS DETAILS LOADED SUCCESSFULLY =====")
                    android.util.Log.d("PointsViewModel", "Current balance: ${response.currentBalance}")
                    android.util.Log.d("PointsViewModel", "Total earned: ${response.totalEarned}")
                    android.util.Log.d("PointsViewModel", "Total spent: ${response.totalSpent}")
                    android.util.Log.d("PointsViewModel", "Sponsor company: ${response.sponsorCompany}")
                    android.util.Log.d("PointsViewModel", "These points should be from the ACTIVE sponsor")
                    _pointsDetails.value = response
                } else {
                    android.util.Log.e("PointsViewModel", "Failed to load points details: ${response.message}")
                    _errorMessage.value = response.message ?: "Failed to load points details"
                }
            } catch (e: Exception) {
                android.util.Log.e("PointsViewModel", "Error loading points details: ${e.message}", e)
                _errorMessage.value = "Error loading points details: ${e.message}"
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun loadPointsHistory(startDate: String? = null, endDate: String? = null) {
        android.util.Log.d("PointsViewModel", "===== LOAD POINTS HISTORY =====")
        android.util.Log.d("PointsViewModel", "startDate: $startDate, endDate: $endDate")
        android.util.Log.d("PointsViewModel", "This should load points history from the ACTIVE sponsor")
        viewModelScope.launch {
            try {
                _isLoading.value = true
                _errorMessage.value = null
                
                val response = pointsService.getPointsHistory(
                    startDate = startDate,
                    endDate = endDate,
                    limit = 100,
                    sort = "desc"
                )
                
                if (response.success) {
                    android.util.Log.d("PointsViewModel", "===== POINTS HISTORY LOADED SUCCESSFULLY =====")
                    android.util.Log.d("PointsViewModel", "Received ${response.transactions.size} transactions")
                    android.util.Log.d("PointsViewModel", "Total count: ${response.totalCount}")
                    android.util.Log.d("PointsViewModel", "These transactions should be from the ACTIVE sponsor")
                    
                    // Log first few transactions for debugging
                    response.transactions.take(3).forEachIndexed { index, transaction ->
                        android.util.Log.d("PointsViewModel", "  Transaction $index: ${transaction.reason} (${transaction.deltaPoints} pts)")
                    }
                    
                    _pointsHistory.value = response.transactions
                    _totalCount.value = response.totalCount
                } else {
                    android.util.Log.e("PointsViewModel", "Failed to load points history: ${response.message}")
                    _errorMessage.value = response.message ?: "Failed to load points history"
                    _pointsHistory.value = emptyList()
                }
            } catch (e: Exception) {
                android.util.Log.e("PointsViewModel", "Error loading points history: ${e.message}", e)
                _errorMessage.value = "Error loading points history: ${e.message}"
                _pointsHistory.value = emptyList()
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun loadPointsGraph(period: String = "30d", granularity: String = "day") {
        viewModelScope.launch {
            try {
                _isLoading.value = true
                _errorMessage.value = null
                
                val response = pointsService.getPointsGraph(period, granularity)
                
                if (response.success) {
                    _graphData.value = response.dataPoints
                } else {
                    _errorMessage.value = response.message ?: "Failed to load graph data"
                    _graphData.value = emptyList()
                }
            } catch (e: Exception) {
                _errorMessage.value = "Error loading graph data: ${e.message}"
                _graphData.value = emptyList()
            } finally {
                _isLoading.value = false
            }
        }
    }

    fun refreshAll() {
        loadPointsDetails()
        loadPointsHistory()
        loadPointsGraph()
    }

    fun clearError() {
        _errorMessage.value = null
    }
    
    // Data aggregation methods for different graph types
    
    data class EarnedSpentData(
        val date: String,
        val earned: Int,
        val spent: Int
    )
    
    data class ReasonBreakdown(
        val reason: String,
        val points: Int,
        val count: Int
    )
    
    data class FrequencyData(
        val date: String,
        val count: Int
    )
    
    data class CumulativeData(
        val date: String,
        val cumulativeEarned: Int,
        val cumulativeSpent: Int
    )
    
    /**
     * Set filter preferences
     */
    fun setFilters(showEarnedOnly: Boolean = false, showSpentOnly: Boolean = false, minDelta: Int = 0) {
        _showEarnedOnly = showEarnedOnly
        _showSpentOnly = showSpentOnly
        _minDelta = minDelta
    }
    
    /**
     * Get filtered history
     */
    private fun getFilteredHistory(): List<PointsTransaction> {
        val history = _pointsHistory.value ?: return emptyList()
        return history.filter { transaction ->
            // Min delta filter
            if (abs(transaction.deltaPoints) < _minDelta) return@filter false
            
            // Earned/Spent filter
            when {
                _showEarnedOnly && transaction.deltaPoints <= 0 -> return@filter false
                _showSpentOnly && transaction.deltaPoints >= 0 -> return@filter false
                else -> true
            }
        }
    }
    
    /**
     * Aggregate earned vs spent points by period
     */
    fun getEarnedSpentData(granularity: String = "day"): List<EarnedSpentData> {
        val history = getFilteredHistory()
        if (history.isEmpty()) return emptyList()
        
        // Group transactions by date period
        val grouped = mutableMapOf<String, Pair<Int, Int>>() // date -> (earned, spent)
        
        history.forEach { transaction ->
            val dateStr = transaction.createdAt ?: return@forEach
            val periodKey = getPeriodKey(dateStr, granularity)
            
            val current = grouped.getOrDefault(periodKey, Pair(0, 0))
            if (transaction.deltaPoints > 0) {
                grouped[periodKey] = Pair(current.first + transaction.deltaPoints, current.second)
            } else if (transaction.deltaPoints < 0) {
                grouped[periodKey] = Pair(current.first, current.second + abs(transaction.deltaPoints))
            }
        }
        
        return grouped.entries.sortedBy { it.key }.map {
            EarnedSpentData(it.key, it.value.first, it.value.second)
        }
    }
    
    /**
     * Group reason into category based on actual reason strings from the app
     * Order matters - more specific matches first to avoid false positives
     */
    private fun groupReason(reason: String?): String {
        val reasonLower = reason?.lowercase() ?: return "Unknown"
        
        // First, check for refunds and cancellations BEFORE orders (to avoid grouping them together)
        if (reasonLower.contains("refund") || reasonLower.contains("return")) {
            return "Refunds"
        }
        if (reasonLower.contains("cancel") || reasonLower.contains("cancelled")) {
            return "Cancellations"
        }
        
        // Check for Points Payment (orders) - this is the actual reason name used in the app
        if (reasonLower.contains("points payment") || reasonLower.contains("point payment") || 
            reasonLower.contains("payment") && (reasonLower.contains("point") || reasonLower.contains("points"))) {
            return "Order Purchases"
        }
        
        // Exact matches for adding points (positive reasons) - from screenshot
        when {
            reasonLower.contains("safety bonus") || (reasonLower.contains("safety") && reasonLower.contains("no incidents")) -> return "Safety Bonus (No Incidents)"
            reasonLower.contains("on-time delivery streak") -> return "On-Time Delivery Streak"
            reasonLower.contains("positive customer feedback") -> return "Positive Customer Feedback"
            reasonLower.contains("monthly performance bonus") -> return "Monthly Performance Bonus"
            reasonLower.contains("training completed") -> return "Training Completed"
            reasonLower.contains("referral bonus") || (reasonLower.contains("referral") && reasonLower.contains("driver hired")) -> return "Referral Bonus (Driver Hired)"
            reasonLower.contains("holiday bonus") -> return "Holiday Bonus"
            reasonLower.contains("extra shift") || reasonLower.contains("route coverage") -> return "Extra Shift/Route Coverage"
            reasonLower.contains("fuel efficiency target met") -> return "Fuel Efficiency Target Met"
            reasonLower.contains("special project completion") -> return "Special Project Completion"
            reasonLower.contains("attendance milestone") -> return "Attendance Milestone"
        }
        
        // Exact matches for deducting points (negative reasons) - from screenshot
        when {
            reasonLower.contains("order purchases") && reasonLower.contains("catalog") -> return "Order Purchases"
            reasonLower.contains("shipping cost") || reasonLower.contains("shipping costs") -> return "Shipping Costs"
            reasonLower.contains("late delivery") -> return "Late Delivery"
            reasonLower.contains("missed pickup") -> return "Missed Pickup"
            reasonLower.contains("customer complaint") -> return "Customer Complaint"
            reasonLower.contains("safety violation") && reasonLower.contains("minor") -> return "Safety Violation (Minor)"
            reasonLower.contains("safety violation") && reasonLower.contains("major") -> return "Safety Violation (Major)"
            reasonLower.contains("equipment misuse") || (reasonLower.contains("equipment") && reasonLower.contains("damage")) -> return "Equipment Misuse/Damage"
            reasonLower.contains("policy non-compliance") -> return "Policy Non-Compliance"
            reasonLower.contains("no-show") || (reasonLower.contains("unapproved") && reasonLower.contains("absence")) -> return "No-Show/Unapproved Absence"
            reasonLower.contains("excessive idling") || reasonLower.contains("fuel waste") -> return "Excessive Idling/Fuel Waste"
            reasonLower.contains("paperwork error") || (reasonLower.contains("paperwork") && reasonLower.contains("missing")) -> return "Paperwork Error/Missing Docs"
            reasonLower.contains("uniform") || reasonLower.contains("branding issue") -> return "Uniform/Branding Issue"
        }
        
        // Fallback categories for variations (only if not already matched above)
        when {
            reasonLower.contains("points payment") || reasonLower.contains("point payment") -> return "Order Purchases"
            reasonLower.contains("order") && reasonLower.contains("purchase") -> return "Order Purchases"
            reasonLower.contains("order") && reasonLower.contains("catalog") -> return "Order Purchases"
            reasonLower.contains("safety") && reasonLower.contains("bonus") -> return "Safety Bonus (No Incidents)"
            reasonLower.contains("safety") && reasonLower.contains("violation") -> return "Safety Violation"
            reasonLower.contains("delivery") && reasonLower.contains("on-time") -> return "On-Time Delivery Streak"
            reasonLower.contains("delivery") && !reasonLower.contains("late") -> return "Delivery"
            reasonLower.contains("customer") && reasonLower.contains("feedback") -> return "Positive Customer Feedback"
            reasonLower.contains("customer") && reasonLower.contains("complaint") -> return "Customer Complaint"
            reasonLower.contains("performance") && reasonLower.contains("bonus") -> return "Monthly Performance Bonus"
            reasonLower.contains("training") -> return "Training Completed"
            reasonLower.contains("referral") -> return "Referral Bonus (Driver Hired)"
            reasonLower.contains("shipping") -> return "Shipping Costs"
            reasonLower.contains("attendance") && reasonLower.contains("milestone") -> return "Attendance Milestone"
            reasonLower.contains("attendance") -> return "Attendance"
            reasonLower.contains("equipment") -> return "Equipment Misuse/Damage"
            reasonLower.contains("policy") -> return "Policy Non-Compliance"
            reasonLower.contains("fuel") && reasonLower.contains("efficiency") -> return "Fuel Efficiency Target Met"
            reasonLower.contains("fuel") || reasonLower.contains("idling") -> return "Excessive Idling/Fuel Waste"
            reasonLower.contains("paperwork") || reasonLower.contains("document") -> return "Paperwork Error/Missing Docs"
            reasonLower.contains("uniform") || reasonLower.contains("branding") -> return "Uniform/Branding Issue"
            reasonLower.contains("holiday") -> return "Holiday Bonus"
            reasonLower.contains("extra") || reasonLower.contains("shift") || reasonLower.contains("route") -> return "Extra Shift/Route Coverage"
            reasonLower.contains("project") -> return "Special Project Completion"
        }
        
        return reason // Return original if no match
    }
    
    /**
     * Get breakdown of points by transaction reason (grouped), excluding orders/refunds/cancellations
     */
    fun getReasonBreakdown(): List<ReasonBreakdown> {
        val history = getFilteredHistory()
        if (history.isEmpty()) return emptyList()
        
        val grouped = mutableMapOf<String, Pair<Int, Int>>() // category -> (points, count)
        
        history.forEach { transaction ->
            val category = groupReason(transaction.reason)
            // Exclude order-related categories
            if (!isOrderRelated(category)) {
                val current = grouped.getOrDefault(category, Pair(0, 0))
                grouped[category] = Pair(current.first + abs(transaction.deltaPoints), current.second + 1)
            }
        }
        
        // Sort by points descending, take top 10, group rest as "Others"
        val sorted = grouped.entries.sortedByDescending { it.value.first }
        val topReasons = sorted.take(10)
        val others = sorted.drop(10)
        
        val result = mutableListOf<ReasonBreakdown>()
        result.addAll(topReasons.map { 
            ReasonBreakdown(it.key, it.value.first, it.value.second) 
        })
        
        if (others.isNotEmpty()) {
            val othersPoints = others.sumOf { it.value.first }
            val othersCount = others.sumOf { it.value.second }
            result.add(ReasonBreakdown("Others", othersPoints, othersCount))
        }
        
        return result
    }
    
    /**
     * Check if reason is order-related (orders, refunds, cancellations)
     */
    private fun isOrderRelated(category: String): Boolean {
        return category == "Order Purchases" || category == "Refunds" || category == "Cancellations"
    }
    
    /**
     * Get breakdown of positive reasons (earned points), excluding orders/refunds/cancellations
     */
    fun getPositiveReasonBreakdown(): List<ReasonBreakdown> {
        val history = getFilteredHistory()
        if (history.isEmpty()) return emptyList()
        
        val grouped = mutableMapOf<String, Pair<Int, Int>>()
        
        history.filter { it.deltaPoints > 0 }.forEach { transaction ->
            val category = groupReason(transaction.reason)
            // Exclude order-related categories
            if (!isOrderRelated(category)) {
                val current = grouped.getOrDefault(category, Pair(0, 0))
                grouped[category] = Pair(current.first + transaction.deltaPoints, current.second + 1)
            }
        }
        
        val sorted = grouped.entries.sortedByDescending { it.value.first }
        return sorted.map { 
            ReasonBreakdown(it.key, it.value.first, it.value.second) 
        }
    }
    
    /**
     * Get breakdown of negative reasons (spent points), excluding orders/refunds/cancellations
     */
    fun getNegativeReasonBreakdown(): List<ReasonBreakdown> {
        val history = getFilteredHistory()
        if (history.isEmpty()) return emptyList()
        
        val grouped = mutableMapOf<String, Pair<Int, Int>>()
        
        history.filter { it.deltaPoints < 0 }.forEach { transaction ->
            val category = groupReason(transaction.reason)
            // Exclude order-related categories
            if (!isOrderRelated(category)) {
                val current = grouped.getOrDefault(category, Pair(0, 0))
                grouped[category] = Pair(current.first + abs(transaction.deltaPoints), current.second + 1)
            }
        }
        
        val sorted = grouped.entries.sortedByDescending { it.value.first }
        return sorted.map { 
            ReasonBreakdown(it.key, it.value.first, it.value.second) 
        }
    }
    
    /**
     * Get breakdown of order-related transactions (orders spent, refunds earned, cancellations earned)
     */
    fun getOrderBreakdown(): List<ReasonBreakdown> {
        val history = getFilteredHistory()
        if (history.isEmpty()) return emptyList()
        
        var ordersSpent = 0
        var refundsEarned = 0
        var cancellationsEarned = 0
        var ordersCount = 0
        var refundsCount = 0
        var cancellationsCount = 0
        
        history.forEach { transaction ->
            val category = groupReason(transaction.reason)
            when (category) {
                "Order Purchases" -> {
                    // Orders are negative (spent)
                    if (transaction.deltaPoints < 0) {
                        ordersSpent += abs(transaction.deltaPoints)
                        ordersCount++
                    }
                }
                "Refunds" -> {
                    // Refunds are positive (earned back)
                    if (transaction.deltaPoints > 0) {
                        refundsEarned += transaction.deltaPoints
                        refundsCount++
                    }
                }
                "Cancellations" -> {
                    // Cancellations are positive (earned back)
                    if (transaction.deltaPoints > 0) {
                        cancellationsEarned += transaction.deltaPoints
                        cancellationsCount++
                    }
                }
            }
        }
        
        val result = mutableListOf<ReasonBreakdown>()
        if (ordersSpent > 0) {
            result.add(ReasonBreakdown("Order Purchases", ordersSpent, ordersCount))
        }
        if (refundsEarned > 0) {
            result.add(ReasonBreakdown("Refunds", refundsEarned, refundsCount))
        }
        if (cancellationsEarned > 0) {
            result.add(ReasonBreakdown("Cancellations", cancellationsEarned, cancellationsCount))
        }
        
        return result.sortedByDescending { it.points }
    }
    
    /**
     * Get transaction frequency per period
     */
    fun getTransactionFrequency(granularity: String = "day"): List<FrequencyData> {
        val history = getFilteredHistory()
        if (history.isEmpty()) return emptyList()
        
        val grouped = mutableMapOf<String, Int>() // date -> count
        
        history.forEach { transaction ->
            val dateStr = transaction.createdAt ?: return@forEach
            val periodKey = getPeriodKey(dateStr, granularity)
            grouped[periodKey] = grouped.getOrDefault(periodKey, 0) + 1
        }
        
        return grouped.entries.sortedBy { it.key }.map {
            FrequencyData(it.key, it.value)
        }
    }
    
    /**
     * Get cumulative earned and spent over time
     */
    fun getCumulativeData(): List<CumulativeData> {
        val history = getFilteredHistory()
        if (history.isEmpty()) return emptyList()
        
        // Sort by date
        val sorted = history.sortedBy { it.createdAt ?: "" }
        
        var cumulativeEarned = 0
        var cumulativeSpent = 0
        val result = mutableListOf<CumulativeData>()
        
        sorted.forEach { transaction ->
            val dateStr = transaction.createdAt ?: return@forEach
            if (transaction.deltaPoints > 0) {
                cumulativeEarned += transaction.deltaPoints
            } else if (transaction.deltaPoints < 0) {
                cumulativeSpent += abs(transaction.deltaPoints)
            }
            result.add(CumulativeData(dateStr, cumulativeEarned, cumulativeSpent))
        }
        
        return result
    }
    
    /**
     * Helper to get period key from date string based on granularity
     */
    private fun getPeriodKey(dateStr: String, granularity: String): String {
        try {
            val inputFormat = java.text.SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", java.util.Locale.getDefault())
            val date = inputFormat.parse(dateStr) ?: return dateStr
            
            return when (granularity) {
                "week" -> {
                    val calendar = java.util.Calendar.getInstance()
                    calendar.time = date
                    val weekOfYear = calendar.get(java.util.Calendar.WEEK_OF_YEAR)
                    val year = calendar.get(java.util.Calendar.YEAR)
                    "$year-W$weekOfYear"
                }
                "month" -> {
                    val outputFormat = java.text.SimpleDateFormat("yyyy-MM", java.util.Locale.getDefault())
                    outputFormat.format(date)
                }
                else -> { // "day"
                    val outputFormat = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.getDefault())
                    outputFormat.format(date)
                }
            }
        } catch (e: Exception) {
            return dateStr.substring(0, 10) // Fallback to first 10 chars (date part)
        }
    }
}


