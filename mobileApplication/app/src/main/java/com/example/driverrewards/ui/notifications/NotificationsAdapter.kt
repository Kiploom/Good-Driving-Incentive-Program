package com.example.driverrewards.ui.notifications

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.example.driverrewards.databinding.ItemNotificationBinding
import com.example.driverrewards.network.NotificationItem
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

class NotificationsAdapter(
    private val onNotificationClicked: (NotificationItem) -> Unit,
    private val onNotificationLongPressed: (NotificationItem) -> Unit
) : ListAdapter<NotificationItem, NotificationsAdapter.NotificationViewHolder>(DiffCallback) {

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): NotificationViewHolder {
        val binding = ItemNotificationBinding.inflate(
            LayoutInflater.from(parent.context),
            parent,
            false
        )
        return NotificationViewHolder(binding)
    }

    override fun onBindViewHolder(holder: NotificationViewHolder, position: Int) {
        holder.bind(getItem(position))
    }

    inner class NotificationViewHolder(
        private val binding: ItemNotificationBinding
    ) : RecyclerView.ViewHolder(binding.root) {

        init {
            binding.root.setOnClickListener {
                adapterPosition.takeIf { it != RecyclerView.NO_POSITION }?.let { pos ->
                    onNotificationClicked(getItem(pos))
                }
            }
            binding.root.setOnLongClickListener {
                adapterPosition.takeIf { it != RecyclerView.NO_POSITION }?.let { pos ->
                    onNotificationLongPressed(getItem(pos))
                }
                true
            }
        }

        fun bind(notification: NotificationItem) = with(binding) {
            textTitle.text = notification.title
            textBody.text = notification.body
            textTimestamp.text = formatTimestamp(notification.createdAt)
            chipType.text = when (notification.type.lowercase()) {
                "points_change", "points" -> itemView.context.getString(com.example.driverrewards.R.string.notification_type_points)
                "order_confirmation", "order" -> itemView.context.getString(com.example.driverrewards.R.string.notification_type_order)
                "account_status", "account" -> itemView.context.getString(com.example.driverrewards.R.string.notification_type_account)
                else -> itemView.context.getString(com.example.driverrewards.R.string.notification_type_generic)
            }

            val sponsorContext = notification.sponsorContext
            if (sponsorContext?.isSponsorSpecific == true) {
                val sponsorName = sponsorContext.sponsorName
                    ?: sponsorContext.sponsorCompanyName
                    ?: sponsorContext.sponsorId
                    ?: itemView.context.getString(com.example.driverrewards.R.string.notification_type_generic)
                textSponsorLabel.visibility = View.VISIBLE
                textSponsorLabel.text = itemView.context.getString(
                    com.example.driverrewards.R.string.notification_sponsor_label,
                    sponsorName
                )
            } else {
                textSponsorLabel.visibility = View.GONE
            }

            unreadIndicator.visibility = if (notification.isRead) View.GONE else View.VISIBLE
        }

        private fun formatTimestamp(value: String?): String {
            if (value.isNullOrBlank()) return ""
            return parseIsoDate(value)?.let { dateTime ->
                dateTime.format(DateTimeFormatter.ofPattern("MMM d, h:mm a"))
            } ?: value
        }

        private fun parseIsoDate(value: String): LocalDateTime? {
            return try {
                Instant.parse(value).atZone(ZoneId.systemDefault()).toLocalDateTime()
            } catch (_: DateTimeParseException) {
                try {
                    LocalDateTime.parse(value)
                } catch (_: Exception) {
                    null
                }
            }
        }
    }

    companion object {
        private val DiffCallback = object : DiffUtil.ItemCallback<NotificationItem>() {
            override fun areItemsTheSame(oldItem: NotificationItem, newItem: NotificationItem): Boolean =
                oldItem.id == newItem.id

            override fun areContentsTheSame(oldItem: NotificationItem, newItem: NotificationItem): Boolean =
                oldItem == newItem
        }
    }
}

