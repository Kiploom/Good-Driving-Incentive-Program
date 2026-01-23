package com.example.driverrewards.ui.catalog

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.recyclerview.widget.RecyclerView
import com.example.driverrewards.R

class SkeletonCardAdapter(private val itemCount: Int = 6) : RecyclerView.Adapter<SkeletonCardAdapter.SkeletonViewHolder>() {
    
    class SkeletonViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val cardView: View = itemView
    }
    
    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): SkeletonViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_skeleton_product_card, parent, false)
        return SkeletonViewHolder(view)
    }
    
    override fun onBindViewHolder(holder: SkeletonViewHolder, position: Int) {
        // ShimmerView handles its own animation, no need to do anything here
    }
    
    override fun getItemCount(): Int = itemCount
    
    fun stopAllAnimations() {
        // ShimmerView handles its own lifecycle, no manual cleanup needed
    }
}

