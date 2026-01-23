package com.example.driverrewards.ui.catalog

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.example.driverrewards.R

class ProductAdapter(
    private val onItemClick: (ProductItem) -> Unit,
    private val onFavoriteClick: (ProductItem) -> Unit
) : RecyclerView.Adapter<ProductAdapter.ProductViewHolder>() {

    private var items = mutableListOf<ProductItem>()

    fun updateItems(newItems: List<ProductItem>) {
        items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    fun addItems(newItems: List<ProductItem>) {
        val startPosition = items.size
        items.addAll(newItems)
        notifyItemRangeInserted(startPosition, newItems.size)
    }

    fun updateFavoriteStatus(itemId: String, isFavorite: Boolean) {
        val index = items.indexOfFirst { it.id == itemId }
        if (index != -1) {
            items[index] = items[index].copy(isFavorite = isFavorite)
            notifyItemChanged(index)
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ProductViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_product_card, parent, false)
        return ProductViewHolder(view)
    }

    override fun onBindViewHolder(holder: ProductViewHolder, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount(): Int = items.size

    inner class ProductViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val imageView: ImageView = itemView.findViewById(R.id.product_image)
        private val titleView: TextView = itemView.findViewById(R.id.product_title)
        private val pointsView: TextView = itemView.findViewById(R.id.product_points)
        private val favoriteButton: ImageView = itemView.findViewById(R.id.favorite_button)
        private val pinnedBadge: View = itemView.findViewById(R.id.pinned_badge)
        private val availabilityStatus: TextView = itemView.findViewById(R.id.availability_status)

        fun bind(item: ProductItem) {
            titleView.text = item.title
            pointsView.text = "${item.points} pts"

            // Load image with Glide
            if (!item.imageUrl.isNullOrEmpty()) {
                Glide.with(itemView.context)
                    .load(item.imageUrl)
                    .placeholder(R.drawable.ic_catalog) // Default placeholder
                    .error(R.drawable.ic_catalog) // Error placeholder
                    .into(imageView)
            } else {
                imageView.setImageResource(R.drawable.ic_catalog)
            }

            // Update favorite button - red when favorited, white with black outline when not
            if (item.isFavorite) {
                favoriteButton.setImageResource(R.drawable.ic_favorite_filled)
                // No tinting needed - drawable already has red fill and black outline
                favoriteButton.clearColorFilter()
                favoriteButton.imageTintList = null
            } else {
                favoriteButton.setImageResource(R.drawable.ic_favorite_border)
                // White fill with black outline - drawable already has this
                favoriteButton.clearColorFilter()
                favoriteButton.imageTintList = null
            }

            // Show/hide pinned badge
            pinnedBadge.visibility = if (item.isPinned) View.VISIBLE else View.GONE

            // Set availability status
            when (item.availability) {
                "OUT_OF_STOCK" -> {
                    availabilityStatus.text = "OUT OF STOCK"
                    availabilityStatus.setTextColor(0xFFFF4444.toInt()) // Red
                }
                "LIMITED" -> {
                    availabilityStatus.text = "LIMITED"
                    availabilityStatus.setTextColor(0xFFFF8800.toInt()) // Orange
                }
                else -> {
                    availabilityStatus.text = "IN STOCK"
                    availabilityStatus.setTextColor(0xFF00AA00.toInt()) // Green
                }
            }

            // Set click listeners
            itemView.setOnClickListener { onItemClick(item) }
            favoriteButton.setOnClickListener { 
                // Add particle animation
                FavoriteParticleAnimation.animateFavorite(favoriteButton, !item.isFavorite)
                // Add scale animation
                favoriteButton.animate()
                    .scaleX(1.3f)
                    .scaleY(1.3f)
                    .setDuration(150)
                    .withEndAction {
                        favoriteButton.animate()
                            .scaleX(1f)
                            .scaleY(1f)
                            .setDuration(150)
                            .start()
                    }
                    .start()
                onFavoriteClick(item) 
            }
        }
    }
}
