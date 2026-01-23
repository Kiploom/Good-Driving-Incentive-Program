package com.example.driverrewards.ui.points

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.RecyclerView
import com.example.driverrewards.R
import com.example.driverrewards.network.PointsTransaction
import java.text.SimpleDateFormat
import java.util.*

class PointsTransactionAdapter(
    private var transactions: List<PointsTransaction>,
    private val onItemClick: ((PointsTransaction) -> Unit)? = null
) : RecyclerView.Adapter<PointsTransactionAdapter.ViewHolder>() {

    inner class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val transactionDate: TextView = itemView.findViewById(R.id.transaction_date)
        val transactionReason: TextView = itemView.findViewById(R.id.transaction_reason)
        val deltaPoints: TextView = itemView.findViewById(R.id.delta_points)
        val balanceAfter: TextView = itemView.findViewById(R.id.balance_after)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_points_transaction, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val transaction = transactions[position]

        // Format date
        transaction.createdAt?.let { dateStr ->
            try {
                val inputFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
                val outputFormat = SimpleDateFormat("MMM d, yyyy h:mm a", Locale.getDefault())
                val date = inputFormat.parse(dateStr)
                holder.transactionDate.text = date?.let { outputFormat.format(it) } ?: dateStr
            } catch (e: Exception) {
                // Try alternative format
                try {
                    val inputFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.getDefault())
                    val outputFormat = SimpleDateFormat("MMM d, yyyy h:mm a", Locale.getDefault())
                    val date = inputFormat.parse(dateStr)
                    holder.transactionDate.text = date?.let { outputFormat.format(it) } ?: dateStr
                } catch (e2: Exception) {
                    holder.transactionDate.text = dateStr
                }
            }
        } ?: run {
            holder.transactionDate.text = "Unknown date"
        }

        // Set reason
        holder.transactionReason.text = transaction.reason.ifEmpty { "Transaction" }

        // Set delta points with color
        val delta = transaction.deltaPoints
        val context = holder.itemView.context
        if (delta >= 0) {
            holder.deltaPoints.text = "+${delta}"
            holder.deltaPoints.setTextColor(ContextCompat.getColor(context, R.color.success))
        } else {
            holder.deltaPoints.text = delta.toString()
            holder.deltaPoints.setTextColor(ContextCompat.getColor(context, R.color.error))
        }

        // Set balance after
        holder.balanceAfter.text = "Balance: ${transaction.balanceAfter} pts"

        // Set click listener
        onItemClick?.let { click ->
            holder.itemView.setOnClickListener {
                click(transaction)
            }
        }
    }

    override fun getItemCount(): Int = transactions.size

    fun updateTransactions(newTransactions: List<PointsTransaction>) {
        transactions = newTransactions
        notifyDataSetChanged()
    }
}

