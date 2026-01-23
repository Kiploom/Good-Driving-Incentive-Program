package com.example.driverrewards.ui.catalog

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.example.driverrewards.R
import com.example.driverrewards.network.RelatedProduct

class RelatedProductAdapter(
    private val onItemClick: (RelatedProduct) -> Unit
) : RecyclerView.Adapter<RelatedProductAdapter.RelatedProductViewHolder>() {

    private var items = mutableListOf<RelatedProduct>()

    fun updateItems(newItems: List<RelatedProduct>) {
        items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RelatedProductViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_related_product_card, parent, false)
        return RelatedProductViewHolder(view)
    }

    override fun onBindViewHolder(holder: RelatedProductViewHolder, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount(): Int = items.size

    inner class RelatedProductViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val imageView: ImageView = itemView.findViewById(R.id.product_image)
        private val titleView: TextView = itemView.findViewById(R.id.product_title)
        private val pointsView: TextView = itemView.findViewById(R.id.product_points)
        private val availabilityBadge: TextView = itemView.findViewById(R.id.availability_badge)

        fun bind(item: RelatedProduct) {
            titleView.text = item.title ?: "Unknown Product"
            pointsView.text = "${item.points?.toInt() ?: 0} pts"

            // Load image with Glide
            if (!item.image.isNullOrEmpty()) {
                Glide.with(itemView.context)
                    .load(item.image)
                    .placeholder(R.drawable.ic_catalog)
                    .error(R.drawable.ic_catalog)
                    .into(imageView)
            } else {
                imageView.setImageResource(R.drawable.ic_catalog)
            }

            // Set availability badge
            when {
                item.no_stock == true -> {
                    availabilityBadge.text = "OUT OF STOCK"
                    availabilityBadge.setTextColor(0xFFFF4444.toInt())
                    availabilityBadge.visibility = View.VISIBLE
                }
                item.low_stock == true -> {
                    val stockQty = item.stock_qty
                    availabilityBadge.text = if (stockQty != null) "LOW STOCK ($stockQty)" else "LOW STOCK"
                    availabilityBadge.setTextColor(0xFFFF8800.toInt())
                    availabilityBadge.visibility = View.VISIBLE
                }
                else -> {
                    availabilityBadge.visibility = View.GONE
                }
            }

            // Set click listener
            itemView.setOnClickListener { onItemClick(item) }
        }
    }
}
