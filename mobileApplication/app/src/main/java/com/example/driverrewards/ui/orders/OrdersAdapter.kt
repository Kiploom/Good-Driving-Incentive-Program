package com.example.driverrewards.ui.orders

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.example.driverrewards.R
import com.example.driverrewards.network.OrderData
import java.text.SimpleDateFormat
import java.util.*

class OrdersAdapter(
    private val orders: List<OrderData>,
    private val onRefundClick: (String) -> Unit,
    private val onViewDetailsClick: (String) -> Unit
) : RecyclerView.Adapter<OrdersAdapter.ViewHolder>() {

    private val dateFormat = SimpleDateFormat("MMM dd, yyyy", Locale.getDefault())

    class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val orderNumber: TextView = itemView.findViewById(R.id.order_number)
        val orderDate: TextView = itemView.findViewById(R.id.order_date)
        val orderStatus: TextView = itemView.findViewById(R.id.order_status)
        val totalPoints: TextView = itemView.findViewById(R.id.total_points)
        val itemCount: TextView = itemView.findViewById(R.id.item_count)
        val refundButton: com.google.android.material.button.MaterialButton = itemView.findViewById(R.id.refund_button)
        val viewDetailsButton: com.google.android.material.button.MaterialButton = itemView.findViewById(R.id.view_details_button)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val order = orders[position]
        
        holder.orderNumber.text = order.orderNumber ?: "Unknown Order"
        
        // Format date
        try {
            if (order.createdAt != null) {
                val date = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault()).parse(order.createdAt)
                holder.orderDate.text = date?.let { dateFormat.format(it) } ?: order.createdAt
            } else {
                holder.orderDate.text = "Unknown date"
            }
        } catch (e: Exception) {
            holder.orderDate.text = order.createdAt ?: "Unknown date"
        }
        
        // Status badge
        val status = order.status ?: "unknown"
        holder.orderStatus.text = status.replaceFirstChar { it.uppercase() }
        val context = holder.itemView.context
        when (status.lowercase()) {
            "completed" -> {
                holder.orderStatus.setBackgroundColor(ContextCompat.getColor(context, R.color.status_completed_bg))
                holder.orderStatus.setTextColor(ContextCompat.getColor(context, R.color.status_completed_text))
            }
            "pending" -> {
                holder.orderStatus.setBackgroundColor(ContextCompat.getColor(context, R.color.status_pending_bg))
                holder.orderStatus.setTextColor(ContextCompat.getColor(context, R.color.status_pending_text))
            }
            "refunded", "cancelled" -> {
                holder.orderStatus.setBackgroundColor(ContextCompat.getColor(context, R.color.status_refunded_bg))
                holder.orderStatus.setTextColor(ContextCompat.getColor(context, R.color.status_refunded_text))
            }
            else -> {
                holder.orderStatus.setBackgroundColor(ContextCompat.getColor(context, R.color.status_default_bg))
                holder.orderStatus.setTextColor(ContextCompat.getColor(context, R.color.status_default_text))
            }
        }
        
        holder.totalPoints.text = "${order.totalPoints} pts"
        holder.itemCount.text = "${order.orderItems.size} item(s)"
        
        // Refund/Cancel button visibility
        when (status.lowercase()) {
            "pending" -> {
                holder.refundButton.visibility = View.VISIBLE
                holder.refundButton.text = "Cancel"
                holder.refundButton.setOnClickListener {
                    onRefundClick(order.orderId ?: "") // Reuse for cancel
                }
            }
            "completed" -> {
                if (order.canRefund) {
                    holder.refundButton.visibility = View.VISIBLE
                    holder.refundButton.text = "Refund"
                    holder.refundButton.setOnClickListener {
                        onRefundClick(order.orderId ?: "")
                    }
                } else {
                    holder.refundButton.visibility = View.GONE
                }
            }
            else -> {
                holder.refundButton.visibility = View.GONE
            }
        }
        
        holder.viewDetailsButton.setOnClickListener {
            onViewDetailsClick(order.orderId ?: "")
        }
    }

    override fun getItemCount() = orders.size
}

