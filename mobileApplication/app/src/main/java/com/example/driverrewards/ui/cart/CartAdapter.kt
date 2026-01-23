package com.example.driverrewards.ui.cart

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.example.driverrewards.R
import com.example.driverrewards.network.CartItem
import com.google.android.material.button.MaterialButton

class CartAdapter(
    private val items: List<CartItem>,
    private val onQuantityChanged: (String, Int) -> Unit,
    private val onRemove: (String) -> Unit,
    private val onItemClick: (String) -> Unit
) : RecyclerView.Adapter<CartAdapter.ViewHolder>() {

    class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val itemImage: ImageView = itemView.findViewById(R.id.item_image)
        val itemTitle: TextView = itemView.findViewById(R.id.item_title)
        val variationDetails: TextView = itemView.findViewById(R.id.variation_details)
        val pointsPerUnit: TextView = itemView.findViewById(R.id.points_per_unit)
        val quantity: TextView = itemView.findViewById(R.id.quantity)
        val lineTotal: TextView = itemView.findViewById(R.id.line_total)
        val quantityDecrease: ImageButton = itemView.findViewById(R.id.quantity_decrease)
        val quantityIncrease: ImageButton = itemView.findViewById(R.id.quantity_increase)
        val removeButton: ImageButton = itemView.findViewById(R.id.remove_button)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_cart, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val item = items[position]
        
        // Load image
        holder.itemImage.setImageResource(android.R.drawable.ic_menu_gallery) // Set placeholder first
        if (!item.itemImageUrl.isNullOrEmpty()) {
            try {
                Glide.with(holder.itemView.context)
                    .load(item.itemImageUrl)
                    .placeholder(android.R.drawable.ic_menu_gallery)
                    .error(android.R.drawable.ic_menu_gallery)
                    .into(holder.itemImage)
            } catch (e: Exception) {
                android.util.Log.e("CartAdapter", "Error loading image for ${item.itemTitle}: ${e.message}", e)
                holder.itemImage.setImageResource(android.R.drawable.ic_menu_gallery)
            }
        }
        
        holder.itemTitle.text = item.itemTitle ?: "Unknown Item"
        
        // Extract and display variation details from external_item_id
        val externalItemId = item.externalItemId ?: ""
        if (externalItemId.contains("::")) {
            val variationPart = externalItemId.substringAfter("::")
            val variationMap = variationPart.split("|").associate { part ->
                val (key, value) = part.split(":", limit = 2)
                key to value
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
        
        holder.pointsPerUnit.text = "${item.pointsPerUnit} pts each"
        holder.quantity.text = item.quantity.toString()
        holder.lineTotal.text = "${item.lineTotalPoints} pts"
        
        // Remove button - set clickable and prevent card click
        holder.removeButton.setOnClickListener { 
            android.util.Log.d("CartAdapter", "Remove button clicked for item: ${item.cartItemId}")
            onRemove(item.cartItemId ?: "")
        }
        holder.removeButton.isClickable = true
        
        // Quantity buttons
        holder.quantityDecrease.setOnClickListener {
            if (item.quantity > 1) {
                onQuantityChanged(item.cartItemId ?: "", item.quantity - 1)
            }
        }
        
        holder.quantityIncrease.setOnClickListener {
            onQuantityChanged(item.cartItemId ?: "", item.quantity + 1)
        }
        
        // Make card clickable to navigate to product detail (but not when clicking buttons)
        holder.itemView.setOnClickListener { view ->
            // Only trigger if the click wasn't on a button
            if (view == holder.itemView || !holder.removeButton.isPressed && !holder.quantityDecrease.isPressed && !holder.quantityIncrease.isPressed) {
                item.externalItemId?.let { itemId ->
                    android.util.Log.d("CartAdapter", "Card clicked with externalItemId: '$itemId'")
                    onItemClick(itemId)
                }
            }
        }
        
    }

    override fun getItemCount() = items.size
}

