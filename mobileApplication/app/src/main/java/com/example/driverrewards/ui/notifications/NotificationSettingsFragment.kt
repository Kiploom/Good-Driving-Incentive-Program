package com.example.driverrewards.ui.notifications

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentNotificationSettingsBinding
import com.example.driverrewards.network.LowPointsPreference
import com.example.driverrewards.network.NotificationPreferencesPayload
import com.example.driverrewards.network.QuietHoursPreference
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.timepicker.MaterialTimePicker
import com.google.android.material.timepicker.TimeFormat
import java.util.Locale

class NotificationSettingsFragment : Fragment() {

    private var _binding: FragmentNotificationSettingsBinding? = null
    private val binding get() = _binding!!

    private val viewModel: NotificationSettingsViewModel by viewModels()

    private var quietHoursStart: String? = null
    private var quietHoursEnd: String? = null

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentNotificationSettingsBinding.inflate(inflater, container, false)
        setupListeners()
        observeViewModel()
        return binding.root
    }

    private fun setupListeners() = with(binding) {
        buttonQuietStart.setOnClickListener {
            showTimePicker(quietHoursStart) { formatted ->
                quietHoursStart = formatted
                buttonQuietStart.text = formatDisplayTime(formatted)
            }
        }
        buttonQuietEnd.setOnClickListener {
            showTimePicker(quietHoursEnd) { formatted ->
                quietHoursEnd = formatted
                buttonQuietEnd.text = formatDisplayTime(formatted)
            }
        }
        sliderLowPoints.addOnChangeListener { _, value, _ ->
            updateLowPointsLabel(value.toInt())
        }
        buttonSavePreferences.setOnClickListener {
            viewModel.preferences.value?.let {
                viewModel.savePreferences(buildPayloadFromInputs(it))
            }
        }
        buttonTestLowPoints.setOnClickListener {
            val threshold = sliderLowPoints.value.toInt()
            viewModel.triggerLowPointsTest(balance = threshold - 10, threshold = threshold)
        }
        switchQuietHours.setOnCheckedChangeListener { _, isChecked ->
            buttonQuietStart.isEnabled = isChecked
            buttonQuietEnd.isEnabled = isChecked
        }
        switchLowPoints.setOnCheckedChangeListener { _, isChecked ->
            sliderLowPoints.isEnabled = isChecked
        }
    }

    private fun observeViewModel() = with(binding) {
        viewModel.preferences.observe(viewLifecycleOwner) { prefs ->
            if (prefs != null) {
                switchEmailEnabled.isChecked = prefs.emailEnabled
                switchInAppEnabled.isChecked = prefs.inAppEnabled
                switchPoints.isChecked = prefs.pointChanges
                switchOrders.isChecked = prefs.orderConfirmations
                switchApplications.isChecked = prefs.applicationUpdates
                switchTickets.isChecked = prefs.ticketUpdates
                switchRefunds.isChecked = prefs.refundWindowAlerts
                switchAccountStatus.isChecked = prefs.accountStatusChanges
                switchSensitive.isChecked = prefs.sensitiveInfoResets

                switchQuietHours.isChecked = prefs.quietHours.enabled
                quietHoursStart = prefs.quietHours.start
                quietHoursEnd = prefs.quietHours.end
                buttonQuietStart.text = formatDisplayTime(quietHoursStart)
                buttonQuietEnd.text = formatDisplayTime(quietHoursEnd)

                switchLowPoints.isChecked = prefs.lowPoints.enabled
                sliderLowPoints.value = prefs.lowPoints.threshold.toFloat()
                updateLowPointsLabel(prefs.lowPoints.threshold)
                buttonQuietStart.isEnabled = prefs.quietHours.enabled
                buttonQuietEnd.isEnabled = prefs.quietHours.enabled
                sliderLowPoints.isEnabled = prefs.lowPoints.enabled
            }
        }
        viewModel.isLoading.observe(viewLifecycleOwner) { isLoading ->
            settingsProgress.isVisible = isLoading
        }
        viewModel.isSaving.observe(viewLifecycleOwner) { saving ->
            buttonSavePreferences.isEnabled = !saving
        }
        viewModel.message.observe(viewLifecycleOwner) { msg ->
            msg?.let {
                Snackbar.make(binding.root, it, Snackbar.LENGTH_LONG).show()
            }
        }
        viewModel.testResult.observe(viewLifecycleOwner) { response ->
            response?.let {
                MaterialAlertDialogBuilder(requireContext())
                    .setTitle(R.string.notifications_test_low_points)
                    .setMessage(it.message ?: getString(R.string.notification_pref_updated))
                    .setPositiveButton(android.R.string.ok, null)
                    .show()
                viewModel.clearTestResult()
            }
        }
    }

    private fun buildPayloadFromInputs(existing: NotificationPreferencesPayload): NotificationPreferencesPayload {
        return NotificationPreferencesPayload(
            pointChanges = binding.switchPoints.isChecked,
            orderConfirmations = binding.switchOrders.isChecked,
            applicationUpdates = binding.switchApplications.isChecked,
            ticketUpdates = binding.switchTickets.isChecked,
            refundWindowAlerts = binding.switchRefunds.isChecked,
            accountStatusChanges = binding.switchAccountStatus.isChecked,
            sensitiveInfoResets = binding.switchSensitive.isChecked,
            emailEnabled = binding.switchEmailEnabled.isChecked,
            inAppEnabled = binding.switchInAppEnabled.isChecked,
            quietHours = QuietHoursPreference(
                enabled = binding.switchQuietHours.isChecked,
                start = quietHoursStart,
                end = quietHoursEnd
            ),
            lowPoints = LowPointsPreference(
                enabled = binding.switchLowPoints.isChecked,
                threshold = binding.sliderLowPoints.value.toInt()
            )
        )
    }

    private fun updateLowPointsLabel(value: Int) {
        binding.textLowPointsValue.text = getString(R.string.notifications_low_points_label, value)
    }

    private fun showTimePicker(currentValue: String?, onSelected: (String) -> Unit) {
        val (hour, minute) = parseTime(currentValue)
        val picker = MaterialTimePicker.Builder()
            .setTimeFormat(TimeFormat.CLOCK_24H)
            .setHour(hour)
            .setMinute(minute)
            .build()
        picker.addOnPositiveButtonClickListener {
            onSelected(String.format(Locale.getDefault(), "%02d:%02d", picker.hour, picker.minute))
        }
        picker.show(parentFragmentManager, "notification_time_picker")
    }

    private fun parseTime(value: String?): Pair<Int, Int> {
        return try {
            val parts = value?.split(":") ?: return 22 to 0
            val hour = parts.getOrNull(0)?.toInt() ?: 22
            val minute = parts.getOrNull(1)?.toInt() ?: 0
            hour to minute
        } catch (_: Exception) {
            22 to 0
        }
    }

    private fun formatDisplayTime(value: String?): String {
        if (value.isNullOrBlank()) {
            return getString(R.string.notifications_quiet_placeholder)
        }
        return try {
            val parts = value.split(":")
            val hour = parts.getOrNull(0)?.toInt() ?: return value
            val minute = parts.getOrNull(1)?.toInt() ?: 0
            String.format(Locale.getDefault(), "%02d:%02d", hour, minute)
        } catch (_: Exception) {
            value
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

