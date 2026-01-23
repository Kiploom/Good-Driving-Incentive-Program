package com.example.driverrewards.ui.points

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.Observer
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentPointsDetailBinding
import com.github.mikephil.charting.charts.LineChart
import com.github.mikephil.charting.charts.BarChart
import com.github.mikephil.charting.charts.PieChart
import com.github.mikephil.charting.charts.CombinedChart
import com.github.mikephil.charting.components.XAxis
import com.github.mikephil.charting.components.YAxis
import com.github.mikephil.charting.data.Entry
import com.github.mikephil.charting.data.LineData
import com.github.mikephil.charting.data.LineDataSet
import com.github.mikephil.charting.data.BarData
import com.github.mikephil.charting.data.BarDataSet
import com.github.mikephil.charting.data.BarEntry
import com.github.mikephil.charting.data.PieData
import com.github.mikephil.charting.data.PieDataSet
import com.github.mikephil.charting.data.PieEntry
import com.github.mikephil.charting.data.CombinedData
import com.github.mikephil.charting.formatter.ValueFormatter
import com.github.mikephil.charting.formatter.IndexAxisValueFormatter
import android.graphics.Color
import androidx.core.content.ContextCompat
import com.google.android.material.tabs.TabLayout
import java.text.SimpleDateFormat
import java.util.*

class PointsDetailFragment : Fragment() {

    private var _binding: FragmentPointsDetailBinding? = null
    private val binding get() = _binding!!
    private lateinit var viewModel: PointsViewModel
    private lateinit var historyAdapter: PointsTransactionAdapter
    private var currentPeriod = "30d"
    private var currentGranularity = "day"
    private var currentGraphType = "balance" // balance, earned_spent, reason, frequency, cumulative, combined
    private var currentReasonType = "all" // all, positive, negative
    private var customStartDate: String? = null
    private var customEndDate: String? = null

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        viewModel = ViewModelProvider(requireActivity())[PointsViewModel::class.java]
        _binding = FragmentPointsDetailBinding.inflate(inflater, container, false)

        // Restore state if available
        savedInstanceState?.let {
            currentPeriod = it.getString("currentPeriod", "30d")
            currentGranularity = it.getString("currentGranularity", "day")
            currentGraphType = it.getString("currentGraphType", "balance")
            customStartDate = it.getString("customStartDate")
            customEndDate = it.getString("customEndDate")
            isSettingsExpanded = it.getBoolean("isSettingsExpanded", false)
        }

        setupRecyclerView()
        setupTabLayout()
        setupObservers()
        setupClickListeners()
        loadData()
        
        // Restore UI state
        restoreUIState()

        return binding.root
    }
    
    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString("currentPeriod", currentPeriod)
        outState.putString("currentGranularity", currentGranularity)
        outState.putString("currentGraphType", currentGraphType)
        outState.putString("customStartDate", customStartDate)
        outState.putString("customEndDate", customEndDate)
        outState.putBoolean("isSettingsExpanded", isSettingsExpanded)
        
        // Save settings preferences - only if binding is available
        _binding?.let { binding ->
            val prefs = requireContext().getSharedPreferences("points_graph_prefs", android.content.Context.MODE_PRIVATE)
            prefs.edit().apply {
                putString("graphType", currentGraphType)
                putString("reasonType", currentReasonType)
                putBoolean("smoothLines", binding.smoothLines.isChecked)
                putBoolean("showGridLines", binding.showGridLines.isChecked)
                putBoolean("showDataPoints", binding.showDataPoints.isChecked)
                putBoolean("showLegend", binding.showLegend.isChecked)
                putBoolean("enableAnimation", binding.enableAnimation.isChecked)
                putBoolean("autoYAxis", binding.autoYAxis.isChecked)
                putBoolean("filterEarnedOnly", binding.filterEarnedOnly.isChecked)
                putBoolean("filterSpentOnly", binding.filterSpentOnly.isChecked)
                putFloat("minDelta", binding.minDeltaSlider.value)
                apply()
            }
        }
    }
    
    private fun restoreUIState() {
        val prefs = requireContext().getSharedPreferences("points_graph_prefs", android.content.Context.MODE_PRIVATE)
        
        // Restore graph type
        val savedGraphType = prefs.getString("graphType", "balance")
        if (savedGraphType != null && savedGraphType != currentGraphType) {
            currentGraphType = savedGraphType
            switchGraphType(savedGraphType)
        }
        
        // Restore reason type
        currentReasonType = prefs.getString("reasonType", "all") ?: "all"
        
        // Restore settings
        binding.smoothLines.isChecked = prefs.getBoolean("smoothLines", true)
        binding.showGridLines.isChecked = prefs.getBoolean("showGridLines", true)
        binding.showDataPoints.isChecked = prefs.getBoolean("showDataPoints", false)
        binding.showLegend.isChecked = prefs.getBoolean("showLegend", false)
        binding.enableAnimation.isChecked = prefs.getBoolean("enableAnimation", true)
        binding.autoYAxis.isChecked = prefs.getBoolean("autoYAxis", true)
        binding.filterEarnedOnly.isChecked = prefs.getBoolean("filterEarnedOnly", false)
        binding.filterSpentOnly.isChecked = prefs.getBoolean("filterSpentOnly", false)
        binding.minDeltaSlider.value = prefs.getFloat("minDelta", 0f)
        
        // Restore settings panel state
        if (isSettingsExpanded) {
            binding.settingsContent.visibility = View.VISIBLE
            binding.settingsExpandIcon.rotation = 180f
        }
        
        // Restore date range display
        if (customStartDate != null && customEndDate != null) {
            try {
                val startFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
                val endFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
                val startDate = startFormat.parse(customStartDate)
                val endDate = endFormat.parse(customEndDate)
                val displayFormat = SimpleDateFormat("MMM d, yyyy", Locale.getDefault())
                binding.dateRangeDisplay.text = "${displayFormat.format(startDate)} - ${displayFormat.format(endDate)}"
                binding.dateRangeContainer.visibility = View.VISIBLE
            } catch (e: Exception) {
                // Ignore parsing errors
            }
        } else {
            binding.dateRangeDisplay.text = when (currentPeriod) {
                "7d" -> "Last 7 days"
                "30d" -> "Last 30 days"
                "90d" -> "Last 90 days"
                "1y" -> "Last year"
                "all" -> "All time"
                else -> "Auto"
            }
        }
        
        // Apply filters to ViewModel
        viewModel.setFilters(
            showEarnedOnly = binding.filterEarnedOnly.isChecked,
            showSpentOnly = binding.filterSpentOnly.isChecked,
            minDelta = binding.minDeltaSlider.value.toInt()
        )
    }

    private fun setupRecyclerView() {
        historyAdapter = PointsTransactionAdapter(emptyList()) { transaction ->
            // Handle transaction click - could navigate to order detail if transaction_id is present
            transaction.transactionId?.let { transactionId ->
                // Navigate to order detail if needed
                android.util.Log.d("PointsDetailFragment", "Transaction clicked: $transactionId")
            }
        }
        binding.historyRecycler.layoutManager = LinearLayoutManager(requireContext())
        binding.historyRecycler.adapter = historyAdapter
    }

    private fun setupTabLayout() {
        binding.tabLayout.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab?) {
                when (tab?.position) {
                    0 -> showHistoryTab()
                    1 -> showGraphTab()
                    2 -> showInfoTab()
                }
            }

            override fun onTabUnselected(tab: TabLayout.Tab?) {}
            override fun onTabReselected(tab: TabLayout.Tab?) {}
        })
        // Default to history tab
        showHistoryTab()
    }

    private fun showHistoryTab() {
        binding.historyTab.visibility = View.VISIBLE
        binding.graphTab.visibility = View.GONE
        binding.infoTab.visibility = View.GONE
    }

    private fun showGraphTab() {
        binding.historyTab.visibility = View.GONE
        binding.graphTab.visibility = View.VISIBLE
        binding.infoTab.visibility = View.GONE
        // Load graph data if not already loaded
        if (viewModel.graphData.value.isNullOrEmpty()) {
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
        } else {
            updateChart()
        }
    }

    private fun showInfoTab() {
        binding.historyTab.visibility = View.GONE
        binding.graphTab.visibility = View.GONE
        binding.infoTab.visibility = View.VISIBLE
    }

    private fun setupObservers() {
        viewModel.pointsDetails.observe(viewLifecycleOwner) { details ->
            details?.let {
                if (it.success) {
                    binding.currentBalance.text = it.currentBalance.toString()
                    binding.dollarValue.text = "≈ $${String.format("%.2f", it.dollarValue)}"
                    binding.conversionRate.text = "1 point = $${String.format("%.2f", it.conversionRate)}"
                    
                    // Update info tab with conversion info
                    val conversionInfo = "Your current conversion rate is $${String.format("%.2f", it.conversionRate)} per point. " +
                            "This rate may vary by sponsor. Your current balance of ${it.currentBalance} points " +
                            "is worth approximately $${String.format("%.2f", it.dollarValue)}."
                    binding.conversionInfo.text = conversionInfo
                }
            }
        }

        viewModel.pointsHistory.observe(viewLifecycleOwner) { history ->
            if (history.isNotEmpty()) {
                historyAdapter.updateTransactions(history)
                binding.emptyHistory.visibility = View.GONE
                binding.historyRecycler.visibility = View.VISIBLE
            } else {
                binding.emptyHistory.visibility = View.VISIBLE
                binding.historyRecycler.visibility = View.GONE
            }
            // Update charts that depend on history data
            if (currentGraphType in listOf("earned_spent", "reason", "frequency", "cumulative", "combined")) {
                updateChart()
            }
        }

        viewModel.graphData.observe(viewLifecycleOwner) { data ->
            if (data.isNotEmpty()) {
                updateChart()
            } else {
                // Handle empty state for charts that depend on graphData
                if (currentGraphType == "balance" || currentGraphType == "cumulative" || currentGraphType == "combined") {
                    binding.emptyGraph.visibility = View.VISIBLE
                    binding.emptyGraph.text = "No graph data available"
                    binding.chartContainer.visibility = View.VISIBLE
                }
            }
        }

        viewModel.isLoading.observe(viewLifecycleOwner) { isLoading ->
            binding.progressBar.visibility = if (isLoading) View.VISIBLE else View.GONE
        }

        viewModel.errorMessage.observe(viewLifecycleOwner) { errorMessage ->
            errorMessage?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_LONG).show()
                viewModel.clearError()
            }
        }
    }

    private fun setupClickListeners() {
        binding.refreshButton.setOnClickListener {
            loadData()
        }

        // Period buttons - ButtonGroup handles selection automatically
        binding.period7d.setOnClickListener {
            currentPeriod = "7d"
            customStartDate = null
            customEndDate = null
            binding.dateRangeContainer.visibility = View.GONE
            binding.dateRangeDisplay.text = "Last 7 days"
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
            viewModel.loadPointsHistory() // Reload history for filtered charts
            updateChart() // Update chart to refresh title
        }
        binding.period30d.setOnClickListener {
            currentPeriod = "30d"
            customStartDate = null
            customEndDate = null
            binding.dateRangeContainer.visibility = View.GONE
            binding.dateRangeDisplay.text = "Last 30 days"
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
            viewModel.loadPointsHistory()
            updateChart() // Update chart to refresh title
        }
        binding.period90d.setOnClickListener {
            currentPeriod = "90d"
            customStartDate = null
            customEndDate = null
            binding.dateRangeContainer.visibility = View.GONE
            binding.dateRangeDisplay.text = "Last 90 days"
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
            viewModel.loadPointsHistory()
            updateChart() // Update chart to refresh title
        }
        binding.period1y.setOnClickListener {
            currentPeriod = "1y"
            customStartDate = null
            customEndDate = null
            binding.dateRangeContainer.visibility = View.GONE
            binding.dateRangeDisplay.text = "Last year"
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
            viewModel.loadPointsHistory()
            updateChart() // Update chart to refresh title
        }
        binding.periodAll.setOnClickListener {
            currentPeriod = "all"
            customStartDate = null
            customEndDate = null
            binding.dateRangeContainer.visibility = View.GONE
            binding.dateRangeDisplay.text = "All time"
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
            viewModel.loadPointsHistory()
            updateChart() // Update chart to refresh title
        }
        
        // Custom date range button
        binding.customDateRangeButton.setOnClickListener {
            showDateRangePicker()
        }
        
        // Set initial checked button programmatically
        binding.period30d.isChecked = true
        binding.dateRangeDisplay.text = "Last 30 days"
        
        // Granularity buttons
        binding.granularityDay.setOnClickListener {
            currentGranularity = "day"
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
        }
        binding.granularityWeek.setOnClickListener {
            currentGranularity = "week"
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
        }
        binding.granularityMonth.setOnClickListener {
            currentGranularity = "month"
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
        }
        
        // Set initial granularity button
        binding.granularityDay.isChecked = true
        
        // Graph type buttons
        binding.graphTypeBalance.setOnClickListener {
            switchGraphType("balance")
        }
        binding.graphTypeEarnedSpent.setOnClickListener {
            switchGraphType("earned_spent")
        }
        binding.graphTypeReason.setOnClickListener {
            switchGraphType("reason")
        }
        binding.graphTypeFrequency.setOnClickListener {
            switchGraphType("frequency")
        }
        binding.graphTypeCumulative.setOnClickListener {
            switchGraphType("cumulative")
        }
        binding.graphTypeCombined.setOnClickListener {
            switchGraphType("combined")
        }
        
        // Set initial graph type
        binding.graphTypeBalance.isChecked = true
        
        // Reason type buttons
        binding.reasonTypeAll.setOnClickListener {
            currentReasonType = "all"
            if (currentGraphType == "reason") {
                updateReasonChart() // Will update title
            }
        }
        binding.reasonTypePositive.setOnClickListener {
            currentReasonType = "positive"
            if (currentGraphType == "reason") {
                updateReasonChart() // Will update title
            }
        }
        binding.reasonTypeNegative.setOnClickListener {
            currentReasonType = "negative"
            if (currentGraphType == "reason") {
                updateReasonChart() // Will update title
            }
        }
        binding.reasonTypeOrders.setOnClickListener {
            currentReasonType = "orders"
            if (currentGraphType == "reason") {
                updateReasonChart() // Will update title
            }
        }
        binding.reasonTypeAll.isChecked = true
        
        // Settings panel toggle
        binding.settingsHeader.setOnClickListener {
            toggleSettingsPanel()
        }
        
        // Setup settings controls
        setupSettingsControls()
    }
    
    private var isSettingsExpanded = false
    
    private fun toggleSettingsPanel() {
        isSettingsExpanded = !isSettingsExpanded
        binding.settingsContent.visibility = if (isSettingsExpanded) View.VISIBLE else View.GONE
        
        // Rotate icon
        val rotation = if (isSettingsExpanded) 180f else 0f
        binding.settingsExpandIcon.animate()
            .rotation(rotation)
            .setDuration(200)
            .start()
    }
    
    private fun setupSettingsControls() {
        val handler = android.os.Handler(android.os.Looper.getMainLooper())
        
        // Smoothing toggle
        binding.smoothLines.setOnCheckedChangeListener { _, _ ->
            updateChart()
        }
        
        // Y-axis auto toggle
        binding.autoYAxis.setOnCheckedChangeListener { _, isChecked ->
            binding.yAxisMinSlider.isEnabled = !isChecked
            binding.yAxisMaxSlider.isEnabled = !isChecked
            if (isChecked) {
                updateChart() // Reset to auto
            }
        }
        
        // Y-axis sliders
        binding.yAxisMinSlider.addOnChangeListener { _, _, _ ->
            if (!binding.autoYAxis.isChecked) {
                handler.postDelayed({
                    updateChart()
                }, 200)
            }
        }
        
        binding.yAxisMaxSlider.addOnChangeListener { _, _, _ ->
            if (!binding.autoYAxis.isChecked) {
                handler.postDelayed({
                    updateChart()
                }, 200)
            }
        }
        
        // Display settings
        binding.showGridLines.setOnCheckedChangeListener { _, _ ->
            updateChart()
        }
        
        binding.showDataPoints.setOnCheckedChangeListener { _, _ ->
            updateChart()
        }
        
        binding.showLegend.setOnCheckedChangeListener { _, _ ->
            updateChart()
        }
        
        binding.enableAnimation.setOnCheckedChangeListener { _, _ ->
            updateChart()
        }
        
        // Data filters
        binding.filterEarnedOnly.setOnCheckedChangeListener { _, isChecked ->
            if (isChecked) {
                binding.filterSpentOnly.isChecked = false
            }
            viewModel.setFilters(
                showEarnedOnly = isChecked,
                showSpentOnly = binding.filterSpentOnly.isChecked,
                minDelta = binding.minDeltaSlider.value.toInt()
            )
            updateChart()
        }
        
        binding.filterSpentOnly.setOnCheckedChangeListener { _, isChecked ->
            if (isChecked) {
                binding.filterEarnedOnly.isChecked = false
            }
            viewModel.setFilters(
                showEarnedOnly = binding.filterEarnedOnly.isChecked,
                showSpentOnly = isChecked,
                minDelta = binding.minDeltaSlider.value.toInt()
            )
            updateChart()
        }
        
        // Min delta slider
        binding.minDeltaSlider.addOnChangeListener { _, value, _ ->
            binding.minDeltaValue.text = "${value.toInt()} pts"
            viewModel.setFilters(
                showEarnedOnly = binding.filterEarnedOnly.isChecked,
                showSpentOnly = binding.filterSpentOnly.isChecked,
                minDelta = value.toInt()
            )
            handler.postDelayed({
                updateChart()
            }, 200)
        }
    }
    
    private fun showDateRangePicker() {
        // Use Material DatePicker for date range selection
        val today = java.util.Calendar.getInstance()
        val startCalendar = java.util.Calendar.getInstance()
        startCalendar.add(java.util.Calendar.DAY_OF_MONTH, -30)
        
        val datePicker = com.google.android.material.datepicker.MaterialDatePicker.Builder.dateRangePicker()
            .setTitleText("Select Date Range")
            .setSelection(
                androidx.core.util.Pair(
                    startCalendar.timeInMillis,
                    today.timeInMillis
                )
            )
            .build()
        
        datePicker.addOnPositiveButtonClickListener { selection ->
            val startDate = selection.first
            val endDate = selection.second
            
            val startFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
            val endFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
            
            customStartDate = startFormat.format(Date(startDate))
            customEndDate = endFormat.format(Date(endDate))
            
            val displayFormat = SimpleDateFormat("MMM d, yyyy", Locale.getDefault())
            binding.dateRangeDisplay.text = "${displayFormat.format(Date(startDate))} - ${displayFormat.format(Date(endDate))}"
            binding.dateRangeContainer.visibility = View.VISIBLE
            currentPeriod = "custom"
            
            // Update graph and history with custom dates
            viewModel.loadPointsHistory(customStartDate, customEndDate)
            viewModel.loadPointsGraph(currentPeriod, currentGranularity)
        }
        
        datePicker.show(parentFragmentManager, "DATE_RANGE_PICKER")
    }
    
    private fun switchGraphType(graphType: String) {
        currentGraphType = graphType
        
        // Hide all charts
        binding.pointsChartLine.visibility = View.GONE
        binding.pointsChartBar.visibility = View.GONE
        binding.pointsChartPie.visibility = View.GONE
        binding.pointsChartArea.visibility = View.GONE
        binding.pointsChartCombined.visibility = View.GONE
        
        // Show/hide granularity selector based on graph type
        // Pie chart (reason) doesn't need granularity
        binding.granularityGroup.visibility = if (graphType == "reason") View.GONE else View.VISIBLE
        binding.reasonTypeGroup.visibility = if (graphType == "reason") View.VISIBLE else View.GONE
        binding.legendLabel.visibility = if (graphType == "reason") View.VISIBLE else View.GONE
        
        // Show appropriate chart and update
        when (graphType) {
            "balance" -> {
                binding.pointsChartLine.visibility = View.VISIBLE
                updateBalanceChart()
            }
            "earned_spent" -> {
                binding.pointsChartBar.visibility = View.VISIBLE
                updateEarnedSpentChart()
            }
            "reason" -> {
                binding.pointsChartPie.visibility = View.VISIBLE
                binding.reasonTypeGroup.visibility = View.VISIBLE
                updateReasonChart()
            }
            "frequency" -> {
                binding.pointsChartBar.visibility = View.VISIBLE
                updateFrequencyChart()
            }
            "cumulative" -> {
                binding.pointsChartArea.visibility = View.VISIBLE
                updateCumulativeChart()
            }
            "combined" -> {
                binding.pointsChartCombined.visibility = View.VISIBLE
                updateCombinedChart()
            }
        }
    }


    private fun loadData() {
        viewModel.loadPointsDetails()
        viewModel.loadPointsHistory()
        viewModel.loadPointsGraph(currentPeriod, currentGranularity)
    }

    private fun updateChart() {
        when (currentGraphType) {
            "balance" -> updateBalanceChart()
            "earned_spent" -> updateEarnedSpentChart()
            "reason" -> updateReasonChart()
            "frequency" -> updateFrequencyChart()
            "cumulative" -> updateCumulativeChart()
            "combined" -> updateCombinedChart()
        }
    }
    
    private fun updateBalanceChart() {
        // Update title first, regardless of data availability
        val periodText = when (currentPeriod) {
            "7d" -> "Last 7 Days"
            "30d" -> "Last 30 Days"
            "90d" -> "Last 90 Days"
            "1y" -> "Last Year"
            else -> "All Time"
        }
        binding.chartTitle.text = "Points Balance Over Time ($periodText)"
        
        val dataPoints = viewModel.graphData.value ?: run {
            binding.pointsChartLine.visibility = View.GONE
            binding.emptyGraph.visibility = View.VISIBLE
            binding.emptyGraph.text = "No graph data available"
            return
        }
        
        val chart = binding.pointsChartLine
        
        if (dataPoints.isEmpty()) {
            chart.visibility = View.GONE
            binding.emptyGraph.visibility = View.VISIBLE
            binding.emptyGraph.text = "No graph data available"
            return
        }
        
        chart.visibility = View.VISIBLE
        binding.emptyGraph.visibility = View.GONE
        val balanceEntries = mutableListOf<Entry>()
        val deltaEntries = mutableListOf<BarEntry>()

        // Parse dates and create entries
        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        dataPoints.forEachIndexed { index, point ->
            try {
                val date = dateFormat.parse(point.date)
                val xValue = date?.time?.toFloat() ?: index.toFloat()
                balanceEntries.add(Entry(xValue, point.balance.toFloat()))
                // Delta bars for dual-axis (optional overlay)
                deltaEntries.add(BarEntry(index.toFloat(), point.delta.toFloat()))
            } catch (e: Exception) {
                balanceEntries.add(Entry(index.toFloat(), point.balance.toFloat()))
                deltaEntries.add(BarEntry(index.toFloat(), point.delta.toFloat()))
            }
        }

        if (balanceEntries.isEmpty()) return

        val balanceDataSet = LineDataSet(balanceEntries, "Points Balance")
        // Get primary color from theme
        val typedValue = android.util.TypedValue()
        requireContext().theme.resolveAttribute(android.R.attr.colorPrimary, typedValue, true)
        val primaryColor = typedValue.data
        balanceDataSet.color = primaryColor
        balanceDataSet.valueTextColor = ContextCompat.getColor(requireContext(), R.color.chart_text_black)
        balanceDataSet.lineWidth = 2f
        balanceDataSet.setCircleColor(primaryColor)
        balanceDataSet.circleRadius = if (binding.showDataPoints.isChecked) 4f else 0f
        balanceDataSet.setDrawValues(false)
        balanceDataSet.axisDependency = YAxis.AxisDependency.LEFT
        
        // Apply smoothing based on toggle
        if (binding.smoothLines.isChecked) {
            balanceDataSet.mode = LineDataSet.Mode.CUBIC_BEZIER
        } else {
            balanceDataSet.mode = LineDataSet.Mode.LINEAR
        }

        val lineData = LineData(balanceDataSet)
        chart.data = lineData

        // Configure X-axis
        val xAxis = chart.xAxis
        xAxis.position = XAxis.XAxisPosition.BOTTOM
        xAxis.setDrawGridLines(false)
        xAxis.labelRotationAngle = -45f
        xAxis.valueFormatter = object : ValueFormatter() {
            override fun getFormattedValue(value: Float): String {
                try {
                    val date = Date(value.toLong())
                    val format = when (currentPeriod) {
                        "7d" -> SimpleDateFormat("MMM d", Locale.getDefault())
                        "30d" -> SimpleDateFormat("MMM d", Locale.getDefault())
                        "90d" -> SimpleDateFormat("MMM d", Locale.getDefault())
                        "1y" -> SimpleDateFormat("MMM", Locale.getDefault())
                        else -> SimpleDateFormat("MMM yyyy", Locale.getDefault())
                    }
                    return format.format(date)
                } catch (e: Exception) {
                    return ""
                }
            }
        }

        // Configure Y-axis (left - balance)
        val leftYAxis = chart.axisLeft
        leftYAxis.setDrawGridLines(binding.showGridLines.isChecked)
        if (binding.autoYAxis.isChecked) {
            leftYAxis.axisMinimum = 0f
            leftYAxis.resetAxisMinimum()
            leftYAxis.resetAxisMaximum()
        } else {
            leftYAxis.axisMinimum = binding.yAxisMinSlider.value
            leftYAxis.axisMaximum = binding.yAxisMaxSlider.value
        }
        
        // Format Y-axis with thousands separator
        leftYAxis.valueFormatter = object : ValueFormatter() {
            override fun getFormattedValue(value: Float): String {
                return String.format(Locale.getDefault(), "%,.0f", value)
            }
        }
        leftYAxis.textColor = primaryColor

        // Right Y-axis for delta (optional - can be enabled if needed)
        val rightYAxis = chart.axisRight
        rightYAxis.isEnabled = false

        chart.description.isEnabled = false
        chart.legend.isEnabled = binding.showLegend.isChecked
        
        // Apply animation setting
        if (binding.enableAnimation.isChecked) {
            chart.animateX(500)
        } else {
            chart.invalidate()
        }
        chart.setTouchEnabled(true)
        chart.setDragEnabled(true)
        chart.setScaleEnabled(true)
        chart.setPinchZoom(true)
        
        // Enable marker for tooltips - using default implementation
        chart.setMarker(null) // Will use default marker
        chart.invalidate()
    }
    
    private fun updateEarnedSpentChart() {
        val earnedSpentData = viewModel.getEarnedSpentData(currentGranularity)
        
        val chart = binding.pointsChartBar
        
        // Update title regardless of data availability
        val periodText = when (currentPeriod) {
            "7d" -> "Last 7 Days"
            "30d" -> "Last 30 Days"
            "90d" -> "Last 90 Days"
            "1y" -> "Last Year"
            else -> "All Time"
        }
        val granularityText = when (currentGranularity) {
            "week" -> "Weekly"
            "month" -> "Monthly"
            else -> "Daily"
        }
        binding.chartTitle.text = "Earned vs Spent Points ($periodText - $granularityText)"
        
        if (earnedSpentData.isEmpty()) {
            chart.visibility = View.GONE
            binding.emptyGraph.visibility = View.VISIBLE
            binding.emptyGraph.text = "No earned/spent data available"
            return
        }
        
        chart.visibility = View.VISIBLE
        binding.emptyGraph.visibility = View.GONE
        val earnedEntries = mutableListOf<BarEntry>()
        val spentEntries = mutableListOf<BarEntry>()
        val labels = mutableListOf<String>()

        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        earnedSpentData.forEachIndexed { index, data ->
            earnedEntries.add(BarEntry(index.toFloat(), data.earned.toFloat()))
            spentEntries.add(BarEntry(index.toFloat(), data.spent.toFloat()))
            
            try {
                val date = dateFormat.parse(data.date)
                val labelFormat = when (currentGranularity) {
                    "week" -> SimpleDateFormat("MMM d", Locale.getDefault())
                    "month" -> SimpleDateFormat("MMM", Locale.getDefault())
                    else -> SimpleDateFormat("MMM d", Locale.getDefault())
                }
                labels.add(date?.let { labelFormat.format(it) } ?: data.date)
            } catch (e: Exception) {
                labels.add(data.date)
            }
        }

        val context = requireContext()
        val earnedDataSet = BarDataSet(earnedEntries, "Earned")
        earnedDataSet.color = ContextCompat.getColor(context, R.color.chart_earned)
        earnedDataSet.valueTextColor = ContextCompat.getColor(context, R.color.chart_text_black)
        earnedDataSet.setDrawValues(false)

        val spentDataSet = BarDataSet(spentEntries, "Spent")
        spentDataSet.color = ContextCompat.getColor(context, R.color.chart_spent)
        spentDataSet.valueTextColor = ContextCompat.getColor(context, R.color.chart_text_black)
        spentDataSet.setDrawValues(false)

        val barData = BarData(earnedDataSet, spentDataSet)
        barData.barWidth = 0.4f
        chart.data = barData

        // Configure X-axis
        val xAxis = chart.xAxis
        xAxis.position = XAxis.XAxisPosition.BOTTOM
        xAxis.setDrawGridLines(false)
        xAxis.valueFormatter = IndexAxisValueFormatter(labels)
        xAxis.labelRotationAngle = -45f
        xAxis.granularity = 1f

        // Configure Y-axis
        val leftYAxis = chart.axisLeft
        leftYAxis.setDrawGridLines(binding.showGridLines.isChecked)
        leftYAxis.axisMinimum = 0f
        leftYAxis.valueFormatter = object : ValueFormatter() {
            override fun getFormattedValue(value: Float): String {
                return String.format(Locale.getDefault(), "%,.0f", value)
            }
        }

        chart.axisRight.isEnabled = false
        chart.description.isEnabled = false
        chart.legend.isEnabled = binding.showLegend.isChecked
        
        if (binding.enableAnimation.isChecked) {
            chart.animateY(500)
        } else {
            chart.invalidate()
        }
        chart.setTouchEnabled(true)
        chart.setDragEnabled(true)
        chart.setScaleEnabled(true)
        chart.setPinchZoom(true)
        chart.invalidate()
    }
    
    private fun updateReasonChart() {
        val reasonData = when (currentReasonType) {
            "positive" -> viewModel.getPositiveReasonBreakdown()
            "negative" -> viewModel.getNegativeReasonBreakdown()
            "orders" -> viewModel.getOrderBreakdown()
            else -> viewModel.getReasonBreakdown()
        }
        
        val chart = binding.pointsChartPie
        
        // Update title regardless of data availability
        binding.chartTitle.text = when (currentReasonType) {
            "positive" -> "Positive Point Reasons"
            "negative" -> "Negative Point Reasons"
            "orders" -> "Order Transactions"
            else -> "Point Transaction Reasons"
        }
        
        if (reasonData.isEmpty()) {
            // Show empty state in chart container
            chart.visibility = View.GONE
            binding.emptyGraph.visibility = View.VISIBLE
            binding.emptyGraph.text = when (currentReasonType) {
                "positive" -> "No positive point transactions available"
                "negative" -> "No negative point transactions available"
                "orders" -> "No order-related transactions available"
                else -> "No transaction data available"
            }
            binding.chartContainer.visibility = View.VISIBLE
            return
        }

        // Show chart and hide empty state
        chart.visibility = View.VISIBLE
        binding.emptyGraph.visibility = View.GONE
        binding.chartContainer.visibility = View.VISIBLE
        
        val entries = mutableListOf<PieEntry>()
        
        // Create color array for pie segments
        val colors = mutableListOf<Int>()
        
        // Special colors for orders chart
        val ctx = requireContext()
        val orderColorPalette = if (currentReasonType == "orders") {
            listOf(
                ContextCompat.getColor(ctx, R.color.chart_spent), // Red for Order Purchases (spent)
                ContextCompat.getColor(ctx, R.color.chart_earned), // Green for Refunds (earned back)
                ContextCompat.getColor(ctx, R.color.chart_blue)  // Blue for Cancellations (earned back)
            )
        } else {
            listOf(
                ContextCompat.getColor(ctx, R.color.chart_earned), // Green
                ContextCompat.getColor(ctx, R.color.chart_blue), // Blue
                ContextCompat.getColor(ctx, R.color.chart_warning), // Orange/Warning
                ContextCompat.getColor(ctx, R.color.chart_purple), // Purple
                ContextCompat.getColor(ctx, R.color.chart_spent), // Red
                ContextCompat.getColor(ctx, R.color.chart_cyan), // Cyan
                ContextCompat.getColor(ctx, R.color.chart_amber), // Amber
                ContextCompat.getColor(ctx, R.color.chart_brown), // Brown
                ContextCompat.getColor(ctx, R.color.chart_grey), // Grey
                ContextCompat.getColor(ctx, R.color.chart_pink), // Pink
                ContextCompat.getColor(ctx, R.color.chart_grey)  // Grey for Others
            )
        }
        
        reasonData.forEachIndexed { index, reason ->
            entries.add(PieEntry(reason.points.toFloat(), reason.reason))
            colors.add(orderColorPalette[index % orderColorPalette.size])
        }

        val dataSet = PieDataSet(entries, "")
        dataSet.colors = colors
        dataSet.valueTextColor = ContextCompat.getColor(requireContext(), R.color.chart_text_black)
        dataSet.valueTextSize = 12f
        dataSet.setDrawValues(true)
        
        // Format values to show points and percentage
        dataSet.valueFormatter = object : ValueFormatter() {
            override fun getFormattedValue(value: Float): String {
                val total = reasonData.sumOf { it.points }.toFloat()
                if (total == 0f) return "0 pts\n(0%)"
                val percentage = (value / total * 100).toInt()
                return "${value.toInt()} pts\n($percentage%)"
            }
        }

        val pieData = PieData(dataSet)
        chart.data = pieData

        chart.description.isEnabled = false
        chart.legend.isEnabled = true
        // Configure legend to display vertically
        chart.legend.verticalAlignment = com.github.mikephil.charting.components.Legend.LegendVerticalAlignment.BOTTOM
        chart.legend.horizontalAlignment = com.github.mikephil.charting.components.Legend.LegendHorizontalAlignment.CENTER
        chart.legend.orientation = com.github.mikephil.charting.components.Legend.LegendOrientation.VERTICAL
        chart.legend.setDrawInside(false)
        chart.legend.xEntrySpace = 10f
        chart.legend.yEntrySpace = 5f
        chart.legend.formSize = 12f
        chart.legend.textSize = 12f
        chart.setEntryLabelColor(ContextCompat.getColor(requireContext(), R.color.chart_text_black))
        chart.setEntryLabelTextSize(10f)
        chart.setUsePercentValues(false)
        chart.setTouchEnabled(true)
        chart.setRotationEnabled(true)
        chart.setHoleColor(Color.TRANSPARENT)
        chart.setTransparentCircleAlpha(0)
        chart.animateY(500)
        chart.invalidate()
    }
    
    private fun updateFrequencyChart() {
        val frequencyData = viewModel.getTransactionFrequency(currentGranularity)
        
        val chart = binding.pointsChartBar
        
        // Update title regardless of data availability
        val periodText = when (currentPeriod) {
            "7d" -> "Last 7 Days"
            "30d" -> "Last 30 Days"
            "90d" -> "Last 90 Days"
            "1y" -> "Last Year"
            else -> "All Time"
        }
        val granularityText = when (currentGranularity) {
            "week" -> "Weekly"
            "month" -> "Monthly"
            else -> "Daily"
        }
        binding.chartTitle.text = "Transaction Frequency ($periodText - $granularityText)"
        
        if (frequencyData.isEmpty()) {
            chart.visibility = View.GONE
            binding.emptyGraph.visibility = View.VISIBLE
            binding.emptyGraph.text = "No transaction frequency data available"
            return
        }
        
        chart.visibility = View.VISIBLE
        binding.emptyGraph.visibility = View.GONE
        val entries = mutableListOf<BarEntry>()
        val labels = mutableListOf<String>()

        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        frequencyData.forEachIndexed { index, data ->
            entries.add(BarEntry(index.toFloat(), data.count.toFloat()))
            
            try {
                val date = dateFormat.parse(data.date)
                val labelFormat = when (currentGranularity) {
                    "week" -> SimpleDateFormat("MMM d", Locale.getDefault())
                    "month" -> SimpleDateFormat("MMM", Locale.getDefault())
                    else -> SimpleDateFormat("MMM d", Locale.getDefault())
                }
                labels.add(date?.let { labelFormat.format(it) } ?: data.date)
            } catch (e: Exception) {
                labels.add(data.date)
            }
        }

        val dataSet = BarDataSet(entries, "Transactions")
        val typedValue = android.util.TypedValue()
        requireContext().theme.resolveAttribute(android.R.attr.colorPrimary, typedValue, true)
        val primaryColor = typedValue.data
        dataSet.color = primaryColor
        dataSet.valueTextColor = ContextCompat.getColor(requireContext(), R.color.chart_text_black)
        dataSet.setDrawValues(true)
        dataSet.valueTextSize = 10f

        val barData = BarData(dataSet)
        barData.barWidth = 0.6f
        chart.data = barData

        // Configure X-axis
        val xAxis = chart.xAxis
        xAxis.position = XAxis.XAxisPosition.BOTTOM
        xAxis.setDrawGridLines(false)
        xAxis.valueFormatter = IndexAxisValueFormatter(labels)
        xAxis.labelRotationAngle = -45f
        xAxis.granularity = 1f

        // Configure Y-axis
        val leftYAxis = chart.axisLeft
        leftYAxis.setDrawGridLines(true)
        leftYAxis.axisMinimum = 0f
        leftYAxis.granularity = 1f

        chart.axisRight.isEnabled = false
        chart.description.isEnabled = false
        chart.legend.isEnabled = false
        chart.setTouchEnabled(true)
        chart.setDragEnabled(true)
        chart.setScaleEnabled(true)
        chart.setPinchZoom(true)
        chart.animateY(500)
        chart.invalidate()
    }
    
    private fun updateCumulativeChart() {
        val cumulativeData = viewModel.getCumulativeData()
        
        val chart = binding.pointsChartArea
        
        // Update title regardless of data availability
        val periodText = when (currentPeriod) {
            "7d" -> "Last 7 Days"
            "30d" -> "Last 30 Days"
            "90d" -> "Last 90 Days"
            "1y" -> "Last Year"
            else -> "All Time"
        }
        binding.chartTitle.text = "Cumulative Earned and Spent ($periodText)"
        
        if (cumulativeData.isEmpty()) {
            chart.visibility = View.GONE
            binding.emptyGraph.visibility = View.VISIBLE
            binding.emptyGraph.text = "No cumulative data available"
            return
        }
        
        chart.visibility = View.VISIBLE
        binding.emptyGraph.visibility = View.GONE
        val earnedEntries = mutableListOf<Entry>()
        val spentEntries = mutableListOf<Entry>()

        val dateFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
        cumulativeData.forEachIndexed { index, data ->
            try {
                val date = dateFormat.parse(data.date)
                val xValue = date?.time?.toFloat() ?: index.toFloat()
                earnedEntries.add(Entry(xValue, data.cumulativeEarned.toFloat()))
                spentEntries.add(Entry(xValue, data.cumulativeSpent.toFloat()))
            } catch (e: Exception) {
                earnedEntries.add(Entry(index.toFloat(), data.cumulativeEarned.toFloat()))
                spentEntries.add(Entry(index.toFloat(), data.cumulativeSpent.toFloat()))
            }
        }

        val ctx2 = requireContext()
        val earnedDataSet = LineDataSet(earnedEntries, "Cumulative Earned")
        earnedDataSet.color = ContextCompat.getColor(ctx2, R.color.chart_earned)
        earnedDataSet.valueTextColor = ContextCompat.getColor(ctx2, R.color.chart_text_black)
        earnedDataSet.lineWidth = 2f
        earnedDataSet.setDrawValues(false)
        earnedDataSet.setDrawCircles(false)
        earnedDataSet.setDrawFilled(true)
        earnedDataSet.fillColor = ContextCompat.getColor(ctx2, R.color.chart_earned)
        earnedDataSet.fillAlpha = 100

        val spentDataSet = LineDataSet(spentEntries, "Cumulative Spent")
        spentDataSet.color = ContextCompat.getColor(ctx2, R.color.chart_spent)
        spentDataSet.valueTextColor = ContextCompat.getColor(ctx2, R.color.chart_text_black)
        spentDataSet.lineWidth = 2f
        spentDataSet.setDrawValues(false)
        spentDataSet.setDrawCircles(false)
        spentDataSet.setDrawFilled(true)
        spentDataSet.fillColor = ContextCompat.getColor(ctx2, R.color.chart_spent)
        spentDataSet.fillAlpha = 100

        val lineData = LineData(earnedDataSet, spentDataSet)
        chart.data = lineData

        // Configure X-axis
        val xAxis = chart.xAxis
        xAxis.position = XAxis.XAxisPosition.BOTTOM
        xAxis.setDrawGridLines(false)
        xAxis.valueFormatter = object : ValueFormatter() {
            override fun getFormattedValue(value: Float): String {
                try {
                    val date = Date(value.toLong())
                    val format = SimpleDateFormat("MMM d", Locale.getDefault())
                    return format.format(date)
                } catch (e: Exception) {
                    return ""
                }
            }
        }

        // Configure Y-axis
        val yAxis = chart.axisLeft
        yAxis.setDrawGridLines(binding.showGridLines.isChecked)
        yAxis.axisMinimum = 0f
        yAxis.valueFormatter = object : ValueFormatter() {
            override fun getFormattedValue(value: Float): String {
                return String.format(Locale.getDefault(), "%,.0f", value)
            }
        }

        chart.axisRight.isEnabled = false
        chart.description.isEnabled = false
        chart.legend.isEnabled = binding.showLegend.isChecked
        
        chart.setTouchEnabled(true)
        chart.setDragEnabled(true)
        chart.setScaleEnabled(true)
        chart.setPinchZoom(true)
        
        if (binding.enableAnimation.isChecked) {
            chart.animateY(500)
        } else {
            chart.invalidate()
        }
    }
    
    private fun updateCombinedChart() {
        // Update title first, regardless of data availability
        val periodText = when (currentPeriod) {
            "7d" -> "Last 7 Days"
            "30d" -> "Last 30 Days"
            "90d" -> "Last 90 Days"
            "1y" -> "Last Year"
            else -> "All Time"
        }
        val granularityText = when (currentGranularity) {
            "week" -> "Weekly"
            "month" -> "Monthly"
            else -> "Daily"
        }
        binding.chartTitle.text = "Balance with Earned/Spent ($periodText - $granularityText)"
        
        val graphData = viewModel.graphData.value ?: run {
            binding.pointsChartCombined.visibility = View.GONE
            binding.emptyGraph.visibility = View.VISIBLE
            binding.emptyGraph.text = "No combined chart data available"
            return
        }
        val earnedSpentData = viewModel.getEarnedSpentData(currentGranularity)
        
        val chart = binding.pointsChartCombined
        
        if (graphData.isEmpty() || earnedSpentData.isEmpty()) {
            chart.visibility = View.GONE
            binding.emptyGraph.visibility = View.VISIBLE
            binding.emptyGraph.text = "No combined chart data available"
            return
        }
        
        chart.visibility = View.VISIBLE
        binding.emptyGraph.visibility = View.GONE
        
        // Balance line data
        val balanceEntries = mutableListOf<Entry>()
        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        graphData.forEachIndexed { index, point ->
            try {
                val date = dateFormat.parse(point.date)
                val xValue = date?.time?.toFloat() ?: index.toFloat()
                balanceEntries.add(Entry(xValue, point.balance.toFloat()))
            } catch (e: Exception) {
                balanceEntries.add(Entry(index.toFloat(), point.balance.toFloat()))
            }
        }

        // Earned/Spent bar data
        val earnedEntries = mutableListOf<BarEntry>()
        val spentEntries = mutableListOf<BarEntry>()
        val labels = mutableListOf<String>()
        
        earnedSpentData.forEachIndexed { index, data ->
            earnedEntries.add(BarEntry(index.toFloat(), data.earned.toFloat()))
            spentEntries.add(BarEntry(index.toFloat(), data.spent.toFloat()))
            
            try {
                val date = dateFormat.parse(data.date)
                val labelFormat = when (currentGranularity) {
                    "week" -> SimpleDateFormat("MMM d", Locale.getDefault())
                    "month" -> SimpleDateFormat("MMM", Locale.getDefault())
                    else -> SimpleDateFormat("MMM d", Locale.getDefault())
                }
                labels.add(date?.let { labelFormat.format(it) } ?: data.date)
            } catch (e: Exception) {
                labels.add(data.date)
            }
        }

        // Create line data set for balance
        val balanceDataSet = LineDataSet(balanceEntries, "Balance")
        val typedValue = android.util.TypedValue()
        requireContext().theme.resolveAttribute(android.R.attr.colorPrimary, typedValue, true)
        val primaryColor = typedValue.data
        balanceDataSet.color = primaryColor
        balanceDataSet.valueTextColor = ContextCompat.getColor(requireContext(), R.color.chart_text_black)
        balanceDataSet.lineWidth = 3f
        balanceDataSet.setCircleColor(primaryColor)
        balanceDataSet.circleRadius = 4f
        balanceDataSet.setDrawValues(false)
        balanceDataSet.mode = LineDataSet.Mode.CUBIC_BEZIER
        balanceDataSet.axisDependency = YAxis.AxisDependency.LEFT

        // Create bar data sets for earned/spent
        val ctx3 = requireContext()
        val earnedBarDataSet = BarDataSet(earnedEntries, "Earned")
        earnedBarDataSet.color = ContextCompat.getColor(ctx3, R.color.chart_earned)
        earnedBarDataSet.valueTextColor = ContextCompat.getColor(ctx3, R.color.chart_text_black)
        earnedBarDataSet.setDrawValues(false)
        earnedBarDataSet.axisDependency = YAxis.AxisDependency.RIGHT

        val spentBarDataSet = BarDataSet(spentEntries, "Spent")
        spentBarDataSet.color = ContextCompat.getColor(ctx3, R.color.chart_spent)
        spentBarDataSet.valueTextColor = ContextCompat.getColor(ctx3, R.color.chart_text_black)
        spentBarDataSet.setDrawValues(false)
        spentBarDataSet.axisDependency = YAxis.AxisDependency.RIGHT

        val barData = BarData(earnedBarDataSet, spentBarDataSet)
        barData.barWidth = 0.4f

        val lineData = LineData(balanceDataSet)

        val combinedData = CombinedData()
        combinedData.setData(barData)
        combinedData.setData(lineData)
        
        chart.data = combinedData

        // Configure axes
        val xAxis = chart.xAxis
        xAxis.position = XAxis.XAxisPosition.BOTTOM
        xAxis.setDrawGridLines(false)
        xAxis.valueFormatter = IndexAxisValueFormatter(labels)
        xAxis.labelRotationAngle = -45f
        xAxis.granularity = 1f

        val leftYAxis = chart.axisLeft
        leftYAxis.setDrawGridLines(true)
        leftYAxis.axisMinimum = 0f
        leftYAxis.textColor = primaryColor

        val rightYAxis = chart.axisRight
        rightYAxis.isEnabled = true
        rightYAxis.setDrawGridLines(false)
        rightYAxis.axisMinimum = 0f
        rightYAxis.textColor = ContextCompat.getColor(requireContext(), R.color.chart_earned)

        chart.description.isEnabled = false
        chart.legend.isEnabled = binding.showLegend.isChecked
        chart.setTouchEnabled(true)
        chart.setDragEnabled(true)
        chart.setScaleEnabled(true)
        chart.setPinchZoom(true)
        
        if (binding.enableAnimation.isChecked) {
            chart.animateY(500)
        } else {
            chart.invalidate()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

