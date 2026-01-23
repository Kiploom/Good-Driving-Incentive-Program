package com.example.driverrewards.ui.catalog

data class ProductItem(
    val id: String,
    val title: String,
    val points: Int,
    val imageUrl: String?,
    val availability: String,
    val isFavorite: Boolean,
    val isPinned: Boolean
)
