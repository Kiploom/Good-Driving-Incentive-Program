package com.example.driverrewards.ui.notifications

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.navigation.fragment.findNavController
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentNotificationsBinding
import com.example.driverrewards.network.NotificationItem
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.snackbar.Snackbar

class NotificationsFragment : Fragment() {

    private var _binding: FragmentNotificationsBinding? = null
    private val binding get() = _binding!!

    private val viewModel: NotificationsViewModel by viewModels()

    private lateinit var adapter: NotificationsAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentNotificationsBinding.inflate(inflater, container, false)
        setupRecycler()
        setupListeners()
        observeViewModel()
        return binding.root
    }

    private fun setupRecycler() {
        adapter = NotificationsAdapter(
            onNotificationClicked = { notification ->
                viewModel.markNotificationRead(notification.id)
                showNotificationDetails(notification)
            },
            onNotificationLongPressed = { notification ->
                viewModel.markNotificationRead(notification.id)
                Snackbar.make(
                    binding.root,
                    R.string.notification_mark_read,
                    Snackbar.LENGTH_SHORT
                ).show()
            }
        )
        binding.recyclerNotifications.layoutManager = LinearLayoutManager(requireContext())
        binding.recyclerNotifications.adapter = adapter
        binding.recyclerNotifications.addOnScrollListener(object : RecyclerView.OnScrollListener() {
            override fun onScrolled(recyclerView: RecyclerView, dx: Int, dy: Int) {
                super.onScrolled(recyclerView, dx, dy)
                if (dy <= 0) return
                val manager = recyclerView.layoutManager as? LinearLayoutManager ?: return
                val lastVisible = manager.findLastVisibleItemPosition()
                if (lastVisible >= adapter.itemCount - 4) {
                    viewModel.loadMore()
                }
            }
        })
    }

    private fun setupListeners() {
        binding.swipeRefresh.setOnRefreshListener {
            viewModel.refresh()
        }
        binding.buttonMarkAllRead.setOnClickListener {
            viewModel.markAllRead()
        }
        binding.buttonNotificationSettings.setOnClickListener {
            findNavController().navigate(R.id.action_navigation_notifications_to_notificationSettingsFragment)
        }
        binding.switchUnreadOnly.setOnCheckedChangeListener { _, isChecked ->
            viewModel.setUnreadOnly(isChecked)
        }
    }

    private fun observeViewModel() {
        viewModel.notifications.observe(viewLifecycleOwner) { notifications ->
            binding.emptyState.isVisible = notifications.isEmpty()
            adapter.submitList(notifications)
            binding.buttonMarkAllRead.isEnabled = notifications.any { !it.isRead }
        }
        viewModel.isLoading.observe(viewLifecycleOwner) { loading ->
            binding.progressIndicator.isVisible = loading
        }
        viewModel.isRefreshing.observe(viewLifecycleOwner) { refreshing ->
            binding.swipeRefresh.isRefreshing = refreshing
        }
        viewModel.showUnreadOnly.observe(viewLifecycleOwner) { onlyUnread ->
            if (binding.switchUnreadOnly.isChecked != onlyUnread) {
                binding.switchUnreadOnly.isChecked = onlyUnread
            }
        }
        viewModel.errorMessage.observe(viewLifecycleOwner) { message ->
            message?.let {
                Snackbar.make(binding.root, it, Snackbar.LENGTH_LONG).show()
            }
        }
    }

    private fun showNotificationDetails(notification: NotificationItem) {
        val metadataDetails = notification.metadata?.entrySet()
            ?.joinToString(separator = "\n") { entry ->
                val value = entry.value.takeUnless { it.isJsonNull }?.asString ?: entry.value.toString()
                "${entry.key}: $value"
            }.orEmpty()

        val message = buildString {
            append(notification.body)
            if (metadataDetails.isNotBlank()) {
                append("\n\n")
                append(metadataDetails)
            }
        }

        MaterialAlertDialogBuilder(requireContext())
            .setTitle(notification.title)
            .setMessage(message)
            .setPositiveButton(android.R.string.ok, null)
            .setNegativeButton(R.string.notification_mark_read) { _, _ ->
                viewModel.markNotificationRead(notification.id)
            }
            .show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}