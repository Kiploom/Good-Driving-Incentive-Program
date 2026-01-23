package com.example.driverrewards.ui.favorites

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.fragment.findNavController
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentFavoritesBinding
import com.example.driverrewards.ui.catalog.CatalogViewModel
import com.example.driverrewards.ui.catalog.ProductAdapter
import com.example.driverrewards.ui.catalog.FavoriteParticleAnimation
import com.example.driverrewards.ui.catalog.SkeletonCardAdapter

class FavoritesFragment : Fragment() {

    private var _binding: FragmentFavoritesBinding? = null
    private val binding get() = _binding!!
    private lateinit var favoritesViewModel: FavoritesViewModel
    private lateinit var catalogViewModel: CatalogViewModel
    private lateinit var productAdapter: ProductAdapter
    private lateinit var skeletonAdapter: SkeletonCardAdapter
    private var isLoading = false
    private var currentPage = 1
    private var hasMoreData = true

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        favoritesViewModel = ViewModelProvider(requireActivity()).get(FavoritesViewModel::class.java)
        catalogViewModel = ViewModelProvider(requireActivity()).get(CatalogViewModel::class.java)
        
        _binding = FragmentFavoritesBinding.inflate(inflater, container, false)
        val root: View = binding.root

        // Ensure paddingBottom is set correctly (100dp = ~400px at density 2.5)
        root.post {
            val paddingBottomPx = (100 * resources.displayMetrics.density).toInt()
            root.setPadding(
                root.paddingLeft,
                root.paddingTop,
                root.paddingRight,
                paddingBottomPx
            )
        }

        setupRecyclerView()
        setupSkeletonRecyclerView()
        
        // Restore scroll position after data is loaded
        binding.recyclerView.post {
            val scrollPos = favoritesViewModel.getScrollPosition()
            if (scrollPos > 0 && binding.recyclerView.layoutManager != null) {
                binding.recyclerView.scrollToPosition(scrollPos)
            }
        }
        
        loadFavoritesData()

        return root
    }
    
    private fun setupSkeletonRecyclerView() {
        skeletonAdapter = SkeletonCardAdapter(itemCount = 6)
        binding.skeletonRecyclerView.apply {
            layoutManager = GridLayoutManager(context, 2)
            adapter = skeletonAdapter
        }
    }
    
    private fun setupRecyclerView() {
        productAdapter = ProductAdapter(
            onItemClick = { item ->
                // Save current product itemId to ViewModel
                catalogViewModel.setCurrentProductItemId(item.id)
                // Save scroll position before navigating
                val layoutManager = binding.recyclerView.layoutManager as GridLayoutManager
                favoritesViewModel.setScrollPosition(layoutManager.findLastVisibleItemPosition())
                // Navigate to product detail page
                val bundle = Bundle().apply {
                    putString("itemId", item.id)
                }
                findNavController().navigate(R.id.action_favorites_to_product_detail, bundle)
            },
            onFavoriteClick = { item ->
                // Handle favorite toggle
                toggleFavorite(item)
            }
        )

        binding.recyclerView.apply {
            layoutManager = GridLayoutManager(context, 2)
            adapter = productAdapter
            
            // Add spacing decoration that removes top/bottom padding but keeps item spacing
            val density = context.resources.displayMetrics.density
            addItemDecoration(object : RecyclerView.ItemDecoration() {
                override fun getItemOffsets(
                    outRect: android.graphics.Rect,
                    view: View,
                    parent: RecyclerView,
                    state: RecyclerView.State
                ) {
                    val position = parent.getChildAdapterPosition(view)
                    if (position == RecyclerView.NO_POSITION) return
                    
                    val layoutManager = parent.layoutManager as GridLayoutManager
                    val spanCount = layoutManager.spanCount
                    val itemCount = parent.adapter?.itemCount ?: 0
                    
                    // Calculate row and column
                    val row = position / spanCount
                    val column = position % spanCount
                    val totalRows = (itemCount + spanCount - 1) / spanCount
                    
                    // Convert dp to px
                    val spacingPx = (4 * density).toInt()
                    
                    // Horizontal spacing (between columns)
                    if (column < spanCount - 1) {
                        outRect.right = spacingPx
                    }
                    
                    // Vertical spacing (between rows) but NOT at top or bottom
                    if (row < totalRows - 1) {
                        outRect.bottom = spacingPx
                    }
                    
                    // Add top padding for first row to create space from action bar
                    if (row == 0) {
                        val topPaddingPx = (8 * density).toInt()
                        outRect.top = topPaddingPx
                    }
                    
                    // Remove bottom padding from last row
                    if (row == totalRows - 1) {
                        outRect.bottom = 0
                    }
                }
            })
            
            // Add scroll listener for infinite scroll and position tracking
            addOnScrollListener(object : RecyclerView.OnScrollListener() {
                override fun onScrolled(recyclerView: RecyclerView, dx: Int, dy: Int) {
                    super.onScrolled(recyclerView, dx, dy)
                    
                    val layoutManager = recyclerView.layoutManager as GridLayoutManager
                    val visibleItemCount = layoutManager.childCount
                    val totalItemCount = layoutManager.itemCount
                    val firstVisibleItemPosition = layoutManager.findFirstVisibleItemPosition()
                    
                    // Save scroll position
                    favoritesViewModel.setScrollPosition(firstVisibleItemPosition)
                    
                    // Load more if we're near the end
                    if (!isLoading && hasMoreData) {
                        if ((visibleItemCount + firstVisibleItemPosition) >= totalItemCount - 5) {
                            loadMoreData()
                        }
                    }
                }
            })
        }
    }
    
    private fun loadFavoritesData() {
        if (isLoading) return
        
        isLoading = true
        binding.emptyState.visibility = View.GONE
        
        // Show skeleton loading, hide actual content
        if (currentPage == 1) {
            _binding?.skeletonRecyclerView?.visibility = View.VISIBLE
            _binding?.recyclerView?.visibility = View.GONE
        }
        
        favoritesViewModel.loadFavorites(
            page = currentPage,
            sort = "best_match",
            onSuccess = { items, hasMore ->
                // Hide skeleton, show actual content
                _binding?.skeletonRecyclerView?.visibility = View.GONE
                _binding?.recyclerView?.visibility = View.VISIBLE
                
                if (items.isEmpty() && currentPage == 1) {
                    _binding?.emptyState?.visibility = View.VISIBLE
                } else {
                    _binding?.emptyState?.visibility = View.GONE
                }
                
                if (currentPage == 1) {
                    productAdapter.updateItems(items)
                } else {
                    productAdapter.addItems(items)
                }
                hasMoreData = hasMore
                isLoading = false
            },
            onError = { error ->
                // Hide skeleton on error
                _binding?.skeletonRecyclerView?.visibility = View.GONE
                _binding?.recyclerView?.visibility = View.VISIBLE
                context?.let { ctx ->
                    Toast.makeText(ctx, "Error loading favorites: $error", Toast.LENGTH_LONG).show()
                }
                isLoading = false
            }
        )
    }

    private fun loadMoreData() {
        if (isLoading || !hasMoreData) return
        
        currentPage++
        loadFavoritesData()
    }

    private fun toggleFavorite(item: com.example.driverrewards.ui.catalog.ProductItem) {
        // Optimistically update UI
        productAdapter.updateFavoriteStatus(item.id, !item.isFavorite)
        
        favoritesViewModel.toggleFavorite(
            itemId = item.id,
            isCurrentlyFavorite = item.isFavorite,
            onSuccess = { isFavorite ->
                // Already updated optimistically
                // If item was removed from favorites, it should disappear from list
                if (!isFavorite) {
                    // Remove item from adapter
                    val currentItems = productAdapter.itemCount
                    // Refresh the list
                    currentPage = 1
                    hasMoreData = true
                    loadFavoritesData()
                }
                
                // Update catalog view model when toggling favorite
                catalogViewModel.updateFavoriteInCache(item.id, isFavorite)
            },
            onError = { error ->
                // Revert optimistic update on error
                productAdapter.updateFavoriteStatus(item.id, item.isFavorite)
                Toast.makeText(context, "Error updating favorite: $error", Toast.LENGTH_SHORT).show()
            }
        )
    }

    override fun onPause() {
        super.onPause()
        // Save scroll position
        val layoutManager = binding.recyclerView.layoutManager as? GridLayoutManager
        layoutManager?.let {
            favoritesViewModel.setScrollPosition(it.findFirstVisibleItemPosition())
        }
    }

    override fun onDestroyView() {
        // Stop all skeleton animations
        if (::skeletonAdapter.isInitialized) {
            skeletonAdapter.stopAllAnimations()
        }
        super.onDestroyView()
        // Save scroll position
        val layoutManager = binding.recyclerView.layoutManager as? GridLayoutManager
        layoutManager?.let {
            favoritesViewModel.setScrollPosition(it.findFirstVisibleItemPosition())
        }
        _binding = null
    }
    
    override fun onResume() {
        super.onResume()
        // Refresh favorites when returning to this page to pick up changes from other pages
        favoritesViewModel.refreshFavorites()
        currentPage = 1
        hasMoreData = true
        loadFavoritesData()
    }
}

