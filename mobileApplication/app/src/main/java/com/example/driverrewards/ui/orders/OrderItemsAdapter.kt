package com.example.driverrewards.ui.orders

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.driverrewards.R
import com.example.driverrewards.network.OrderItem

class OrderItemsAdapter(
    private var items: List<OrderItem>,
    private val onItemClick: ((OrderItem) -> Unit)? = null
) : RecyclerView.Adapter<OrderItemsAdapter.ViewHolder>() {

    class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val itemTitle: TextView = itemView.findViewById(R.id.item_title)
        val variationDetails: TextView = itemView.findViewById(R.id.variation_details)
        val itemPoints: TextView = itemView.findViewById(R.id.item_points)
        val itemQuantity: TextView = itemView.findViewById(R.id.item_quantity)
        val itemLineTotal: TextView = itemView.findViewById(R.id.item_line_total)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_order_detail, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val item = items[position]
        
        holder.itemTitle.text = item.title ?: "Unknown Item"
        
        // Display variation details if present
        if (!item.variationInfo.isNullOrEmpty()) {
            val variationMap = try {
                item.variationInfo.split("|").associate { part ->
                    val parts = part.split(":", limit = 2)
                    if (parts.size == 2) {
                        parts[0] to parts[1]
                    } else {
                        "" to ""
                    }
                }.filter { it.key.isNotEmpty() }
            } catch (e: Exception) {
                emptyMap()
            }
            
            if (variationMap.isNotEmpty()) {
                val variationText = variationMap.entries.joinToString(", ") { "${it.key}: ${it.value}" }
                holder.variationDetails.text = variationText
                holder.variationDetails.visibility = View.VISIBLE
            } else {
                holder.variationDetails.visibility = View.GONE
            }
        } else {
            holder.variationDetails.visibility = View.GONE
        }
        
        holder.itemPoints.text = "${item.unitPoints} pts each"
        holder.itemQuantity.text = item.quantity.toString()
        holder.itemLineTotal.text = "Total: ${item.lineTotalPoints} pts"
        
        // Make card clickable
        holder.itemView.setOnClickListener {
            onItemClick?.invoke(item)
        }
        holder.itemView.isClickable = true
        holder.itemView.isFocusable = true
    }

    override fun getItemCount() = items.size

    fun updateItems(newItems: List<OrderItem>) {
        items = newItems
        notifyDataSetChanged()
    }
    
    fun updateItems(newItems: List<OrderItem>, onItemClick: ((OrderItem) -> Unit)?) {
        items = newItems
        // Note: Can't change callback after creation, but if items change we can use the existing one
        notifyDataSetChanged()
    }
}

