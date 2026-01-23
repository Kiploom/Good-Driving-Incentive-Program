package com.example.driverrewards.ui.catalog

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
import com.example.driverrewards.databinding.FragmentCatalogBinding
import com.example.driverrewards.network.CatalogService

class CatalogFragment : Fragment() {

    private var _binding: FragmentCatalogBinding? = null
    private val binding get() = _binding!!
    private lateinit var catalogViewModel: CatalogViewModel
    private lateinit var catalogService: CatalogService
    private lateinit var productAdapter: ProductAdapter
    private lateinit var skeletonAdapter: SkeletonCardAdapter
    private var isLoading = false
    private var currentPage = 1
    private var hasMoreData = true
    private var currentSearchQuery: String? = null
    
    // Store current filter state
    private var currentMinPoints: Float? = null
    private var currentMaxPoints: Float? = null
    private var currentSort: String = "best_match"
    private var currentCategories: List<String> = emptyList()
    private var showingRecommended: Boolean = false

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        catalogViewModel = ViewModelProvider(requireActivity()).get(CatalogViewModel::class.java)
        catalogService = CatalogService()
        
        _binding = FragmentCatalogBinding.inflate(inflater, container, false)
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

        // Restore filter state from ViewModel
        val filterState = catalogViewModel.getCachedFilterState()
        if (filterState.searchQuery != null || filterState.minPoints != null || filterState.maxPoints != null || 
            filterState.sort != "best_match" || filterState.categories.isNotEmpty()) {
            currentSearchQuery = filterState.searchQuery
            currentSort = filterState.sort
            currentMinPoints = filterState.minPoints
            currentMaxPoints = filterState.maxPoints
            currentCategories = filterState.categories
            currentPage = filterState.currentPage
            hasMoreData = filterState.hasMoreData
        }

        setupRecyclerView()
        setupSkeletonRecyclerView()
        
        // Restore scroll position after data is loaded
        binding.recyclerView.post {
            val scrollPos = catalogViewModel.getScrollPosition()
            if (scrollPos > 0 && binding.recyclerView.layoutManager != null) {
                binding.recyclerView.scrollToPosition(scrollPos)
            }
        }
        
        loadCatalogData()

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
                catalogViewModel.setScrollPosition(layoutManager.findLastVisibleItemPosition())
                // Navigate to product detail page
                val bundle = Bundle().apply {
                    putString("itemId", item.id)
                }
                findNavController().navigate(R.id.action_catalog_to_product_detail, bundle)
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
                    val totalItemCount = layoutManager.itemCount
                    val lastVisibleItem = layoutManager.findLastVisibleItemPosition()
                    
                    // Save scroll position to ViewModel
                    if (lastVisibleItem >= 0) {
                        catalogViewModel.setScrollPosition(lastVisibleItem)
                    }
                    
                    if (!isLoading && hasMoreData && lastVisibleItem >= totalItemCount - 4) {
                        loadMoreData()
                    }
                }
            })
        }
    }


    private fun setupFilters() {
        // TODO: Implement filter functionality
        // Category filters, sort options, point range filters
    }
    
    // Public method to perform search from action bar
    fun performSearch(query: String?) {
        updateDebugInfo("Search submitted: '${query ?: "empty"}'")
        currentSearchQuery = query
        currentPage = 1
        hasMoreData = true
        
        android.util.Log.d("CatalogFragment", "===== performSearch() CALLED =====")
        android.util.Log.d("CatalogFragment", "query: '$query', currentMinPoints: $currentMinPoints, currentMaxPoints: $currentMaxPoints")
        
        // Use loadCatalogDataWithFilters to maintain filter state
        showingRecommended = false
        loadCatalogDataWithFilters(query, currentSort, currentMinPoints, currentMaxPoints, currentCategories, recommendedOnly = false)
    }
    
    // Public method to view recommended items
    fun viewRecommendedItems() {
        showingRecommended = true
        currentPage = 1
        hasMoreData = true
        currentSearchQuery = null
        currentCategories = emptyList()
        // Hide browsing indicator when viewing recommended
        _binding?.root?.findViewById<ViewGroup>(R.id.browsing_indicator)?.visibility = View.GONE
        loadCatalogDataWithFilters(null, "best_match", null, null, emptyList(), recommendedOnly = true)
    }
    
    // Public method to apply filters from action bar
    fun applyFilters(sort: String, minPoints: String?, maxPoints: String?, categories: List<String>) {
        android.util.Log.d("CatalogFragment", "===== applyFilters() CALLED =====")
        android.util.Log.d("CatalogFragment", "Input - minPoints (string): '$minPoints'")
        android.util.Log.d("CatalogFragment", "Input - maxPoints (string): '$maxPoints'")
        android.util.Log.d("CatalogFragment", "Input - sort: $sort")
        android.util.Log.d("CatalogFragment", "Input - categories: $categories")
        
        updateDebugInfo("Applying filters - Sort: $sort, Min: $minPoints, Max: $maxPoints, Categories: $categories")
        currentPage = 1
        hasMoreData = true
        showingRecommended = false
        
        // Convert string values to appropriate types
        val minPointsFloat = minPoints?.toFloatOrNull()
        val maxPointsFloat = maxPoints?.toFloatOrNull()
        
        android.util.Log.d("CatalogFragment", "Converted - minPoints (float): $minPointsFloat")
        android.util.Log.d("CatalogFragment", "Converted - maxPoints (float): $maxPointsFloat")
        
        // Store current filter state
        currentMinPoints = minPointsFloat
        currentMaxPoints = maxPointsFloat
        currentSort = sort
        currentCategories = categories
        
        // Update browsing indicator if a single category is selected
        updateBrowsingIndicator(categories)
        
        loadCatalogDataWithFilters(currentSearchQuery, sort, minPointsFloat, maxPointsFloat, categories, recommendedOnly = false)
    }
    
    fun updateBrowsingIndicator(categories: List<String>, categoryName: String? = null) {
        val indicator = _binding?.root?.findViewById<ViewGroup>(R.id.browsing_indicator)
        val categoryNameView = _binding?.root?.findViewById<android.widget.TextView>(R.id.browsing_category_name)
        val clearButton = _binding?.root?.findViewById<android.widget.Button>(R.id.clear_category_button)
        
        if (categories.isNotEmpty() && categories.size == 1) {
            // Show indicator for single category selection
            indicator?.visibility = View.VISIBLE
            categoryNameView?.text = categoryName ?: "Category"
            
            clearButton?.setOnClickListener {
                // Clear category selection
                (activity as? com.example.driverrewards.MainActivity)?.clearCategorySelection()
                // Apply filters without category
                applyFilters(currentSort, currentMinPoints?.toString(), currentMaxPoints?.toString(), emptyList())
            }
        } else {
            // Hide indicator if no category or multiple categories
            indicator?.visibility = View.GONE
        }
    }
    
    private fun loadCatalogDataWithFilters(searchQuery: String?, sort: String, minPoints: Float?, maxPoints: Float?, categories: List<String>, recommendedOnly: Boolean = false) {
        if (isLoading) return
        
        isLoading = true
        
        // Show skeleton loading, hide actual content
        if (currentPage == 1) {
            _binding?.skeletonRecyclerView?.visibility = View.VISIBLE
            _binding?.recyclerView?.visibility = View.GONE
        }
        
        // Update debug info
        updateDebugInfo("Loading catalog with filters... Page: $currentPage, Query: ${searchQuery ?: "none"}, Sort: $sort")
        
        catalogViewModel.loadCatalogData(
            page = currentPage,
            searchQuery = searchQuery,
            sort = sort,
            categories = categories,
            minPoints = minPoints,
            maxPoints = maxPoints,
            recommendedOnly = recommendedOnly,
            onSuccess = { items, hasMore ->
                // Hide skeleton, show actual content
                _binding?.skeletonRecyclerView?.visibility = View.GONE
                _binding?.recyclerView?.visibility = View.VISIBLE
                
                if (currentPage == 1) {
                    productAdapter.updateItems(items)
                    _binding?.debugInfo?.text = "Debug: Loaded ${items.size} items with filters. Page: $currentPage"
                } else {
                    productAdapter.addItems(items)
                    _binding?.debugInfo?.text = "Debug: Added ${items.size} more items. Total: ${productAdapter.itemCount}"
                }
                hasMoreData = hasMore
                isLoading = false
            },
            onError = { error ->
                // Hide skeleton on error
                _binding?.skeletonRecyclerView?.visibility = View.GONE
                _binding?.recyclerView?.visibility = View.VISIBLE
                _binding?.debugInfo?.text = "Debug: Error: $error"
                context?.let { ctx ->
                    Toast.makeText(ctx, "Error loading catalog: $error", Toast.LENGTH_LONG).show()
                }
                isLoading = false
            }
        )
    }

    private fun loadCatalogData(searchQuery: String? = null) {
        // Store the current search query for pagination
        if (searchQuery != null) {
            currentSearchQuery = searchQuery
        }
        
        // Use loadCatalogDataWithFilters to maintain filter state
        loadCatalogDataWithFilters(currentSearchQuery, currentSort, currentMinPoints, currentMaxPoints, currentCategories, recommendedOnly = showingRecommended)
    }

    private fun loadMoreData() {
        if (isLoading || !hasMoreData) return
        
        currentPage++
        loadCatalogDataWithFilters(currentSearchQuery, currentSort, currentMinPoints, currentMaxPoints, currentCategories, recommendedOnly = showingRecommended)
    }

    private fun toggleFavorite(item: ProductItem) {
        updateDebugInfo("Toggling favorite for item: ${item.title}")
        
        // Optimistically update UI
        productAdapter.updateFavoriteStatus(item.id, !item.isFavorite)
        
        catalogViewModel.toggleFavorite(
            itemId = item.id,
            isCurrentlyFavorite = item.isFavorite,
            onSuccess = { isFavorite ->
                // Already updated optimistically, just update debug
                updateDebugInfo("Favorite ${if (isFavorite) "added" else "removed"} for ${item.title}")
                
                // Update product detail view model if that product is currently viewed
                val productDetailViewModel = androidx.lifecycle.ViewModelProvider(requireActivity()).get(ProductDetailViewModel::class.java)
                productDetailViewModel.product.value?.let { product ->
                    if (product.id == item.id) {
                        val updatedProduct = product.copy(is_favorite = isFavorite)
                        productDetailViewModel.updateProductFavorite(updatedProduct)
                    }
                }
            },
            onError = { error ->
                // Revert optimistic update on error
                productAdapter.updateFavoriteStatus(item.id, item.isFavorite)
                updateDebugInfo("Favorite error: $error")
                Toast.makeText(context, "Error updating favorite: $error", Toast.LENGTH_SHORT).show()
            }
        )
    }
    
    private fun updateDebugInfo(message: String) {
        _binding?.debugInfo?.text = "Debug: $message"
    }

    override fun onPause() {
        super.onPause()
        // Save scroll position when fragment is paused
        _binding?.recyclerView?.layoutManager?.let { layoutManager ->
            if (layoutManager is GridLayoutManager) {
                catalogViewModel.setScrollPosition(layoutManager.findLastVisibleItemPosition())
            }
        }
    }

    override fun onDestroyView() {
        // Stop all skeleton animations
        if (::skeletonAdapter.isInitialized) {
            skeletonAdapter.stopAllAnimations()
        }
        super.onDestroyView()
        // Save scroll position before destroying view
        _binding?.recyclerView?.layoutManager?.let { layoutManager ->
            if (layoutManager is GridLayoutManager) {
                catalogViewModel.setScrollPosition(layoutManager.findLastVisibleItemPosition())
            }
        }
        _binding = null
    }
}
