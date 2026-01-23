package com.example.driverrewards.ui.catalog

import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ArrayAdapter
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.fragment.findNavController
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentProductDetailBinding
import com.example.driverrewards.network.ProductDetail
import com.example.driverrewards.network.RelatedProduct
import com.example.driverrewards.network.VariationDetail

class ProductDetailFragment : Fragment() {

    private var _binding: FragmentProductDetailBinding? = null
    private val binding get() = _binding!!
    private lateinit var viewModel: ProductDetailViewModel
    private lateinit var thumbnailAdapter: ThumbnailAdapter
    private lateinit var itemSpecsAdapter: ItemSpecsAdapter
    private lateinit var relatedProductsAdapter: RelatedProductAdapter

    private var lastProcessedItemId: String? = null
    private var lastProcessedVariationInfo: String? = null
    
    override fun onResume() {
        super.onResume()
        // Handle fragment reuse - check if arguments changed
        val currentItemId = arguments?.getString("itemId") ?: ""
        val currentVariationInfo = arguments?.getString("variationInfo")
        
        if (currentItemId != lastProcessedItemId || currentVariationInfo != lastProcessedVariationInfo) {
            android.util.Log.d("ProductDetailFragment", "onResume - Arguments changed, re-processing")
            android.util.Log.d("ProductDetailFragment", "Current itemId: '$currentItemId', variationInfo: '$currentVariationInfo'")
            android.util.Log.d("ProductDetailFragment", "Previous itemId: '$lastProcessedItemId', variationInfo: '$lastProcessedVariationInfo'")
            
            // Re-process variation info
            if (!currentVariationInfo.isNullOrEmpty()) {
                val variationMap = try {
                    currentVariationInfo.split("|").associate { part ->
                        val parts = part.split(":", limit = 2)
                        if (parts.size == 2) {
                            parts[0] to parts[1]
                        } else {
                            "" to ""
                        }
                    }.filter { it.key.isNotEmpty() }
                } catch (e: Exception) {
                    android.util.Log.e("ProductDetailFragment", "Error parsing variation info in onResume: ${e.message}", e)
                    emptyMap()
                }
                
                if (variationMap.isNotEmpty()) {
                    android.util.Log.d("ProductDetailFragment", "Re-storing variationMap in onResume: $variationMap")
                    pendingVariationRestore = variationMap
                    
                    // Try to restore immediately if spinners are ready
                    if (variantSpinners.isNotEmpty()) {
                        binding.root.postDelayed({
                            if (variantSpinners.isNotEmpty() && pendingVariationRestore != null) {
                                android.util.Log.d("ProductDetailFragment", "Restoring variations in onResume - spinners ready")
                                restoreVariationSelections(pendingVariationRestore!!)
                                pendingVariationRestore = null
                            }
                        }, 100)
                    }
                }
            }
            
            lastProcessedItemId = currentItemId
            lastProcessedVariationInfo = currentVariationInfo
        }
    }
    
    override fun onPause() {
        super.onPause()
        // Clear pending variation restore when navigating away to prevent stale state
        // This ensures each navigation starts fresh
        pendingVariationRestore = null
    }
    
    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentProductDetailBinding.inflate(inflater, container, false)
        val root: View = binding.root

        viewModel = ViewModelProvider(requireActivity())[ProductDetailViewModel::class.java]

        setupRecyclerViews()
        
        // Parse variation info FIRST before setting up observers (to avoid race conditions)
        val rawItemId = arguments?.getString("itemId") ?: ""
        val rawVariationInfo = arguments?.getString("variationInfo")
        
        android.util.Log.d("ProductDetailFragment", "=== onCreateView START ===")
        android.util.Log.d("ProductDetailFragment", "Raw arguments - itemId: '$rawItemId', variationInfo: '$rawVariationInfo'")
        android.util.Log.d("ProductDetailFragment", "All argument keys: ${arguments?.keySet()?.joinToString()}")
        android.util.Log.d("ProductDetailFragment", "All argument values: ${arguments?.keySet()?.associateWith { arguments?.get(it) }}")
        
        // Check if itemId contains variation info (shouldn't happen, but handle it defensively)
        val itemId: String
        val variationInfo: String?
        
        if (rawItemId.contains("::") && rawVariationInfo.isNullOrEmpty()) {
            // itemId contains variation info but variationInfo is null - extract it
            android.util.Log.w("ProductDetailFragment", "WARNING: itemId contains '::' but variationInfo is null! Extracting from itemId")
            itemId = rawItemId.substringBefore("::")
            variationInfo = rawItemId.substringAfter("::")
            android.util.Log.d("ProductDetailFragment", "Extracted - itemId: '$itemId', variationInfo: '$variationInfo'")
        } else {
            itemId = rawItemId
            variationInfo = rawVariationInfo
            android.util.Log.d("ProductDetailFragment", "Using raw arguments - itemId: '$itemId', variationInfo: '$variationInfo'")
        }
        
        android.util.Log.d("ProductDetailFragment", "Final values - itemId: '$itemId', variationInfo: '$variationInfo'")
        android.util.Log.d("ProductDetailFragment", "Previous itemId: '$lastProcessedItemId', previous variationInfo: '$lastProcessedVariationInfo'")
        
        // Check if this is a new navigation (different arguments)
        val isNewNavigation = itemId != lastProcessedItemId || variationInfo != lastProcessedVariationInfo
        if (isNewNavigation) {
            android.util.Log.d("ProductDetailFragment", "New navigation detected - clearing previous state and processing new arguments")
            // Clear previous state
            pendingVariationRestore = null
            lastProcessedItemId = itemId
            lastProcessedVariationInfo = variationInfo
        }
        
        // Parse variation info if provided (needed for both restoration and cache clearing)
        val variationMap = if (!variationInfo.isNullOrEmpty()) {
            android.util.Log.d("ProductDetailFragment", "Parsing variationInfo: '$variationInfo'")
            try {
                val parsed = variationInfo.split("|").associate { part ->
                    val parts = part.split(":", limit = 2)
                    if (parts.size == 2) {
                        parts[0] to parts[1]
                    } else {
                        "" to ""
                    }
                }.filter { it.key.isNotEmpty() }
                android.util.Log.d("ProductDetailFragment", "Parsed variationMap: $parsed")
                parsed
            } catch (e: Exception) {
                android.util.Log.e("ProductDetailFragment", "Error parsing variation info: ${e.message}", e)
                emptyMap()
            }
        } else {
            android.util.Log.d("ProductDetailFragment", "No variationInfo provided, variationMap is empty")
            emptyMap()
        }
        
        // If variation info is provided, store for restoration BEFORE observers are set up
        if (variationMap.isNotEmpty()) {
            android.util.Log.d("ProductDetailFragment", "Storing variationMap for restoration BEFORE observers: $variationMap")
            android.util.Log.d("ProductDetailFragment", "variationMap keys: ${variationMap.keys}, values: ${variationMap.values}")
            pendingVariationRestore = variationMap
        } else {
            // Clear any pending restoration if no variation info provided
            if (isNewNavigation) {
                android.util.Log.d("ProductDetailFragment", "No variation info in new navigation, clearing pendingVariationRestore")
                pendingVariationRestore = null
            }
        }
        
        // Now set up observers (variation info is already parsed)
        setupObservers()
        setupClickListeners()
        
        // Load product details
        if (itemId.isNotEmpty()) {
            // Ensure we only use the base item ID (remove any variation suffix if somehow present)
            val baseItemId = if (itemId.contains("::")) {
                val extracted = itemId.substringBefore("::")
                android.util.Log.w("ProductDetailFragment", "Warning: itemId contained '::', extracted base: '$extracted'")
                extracted
            } else {
                itemId
            }
            
            android.util.Log.d("ProductDetailFragment", "Loading product detail for baseItemId: '$baseItemId'")
            
            // If we have variation info from navigation arguments, clear any cached variant selections
            // so our navigation arguments take precedence over cached selections
            if (variationMap.isNotEmpty()) {
                android.util.Log.d("ProductDetailFragment", "=== CLEARING CACHE AND STATE ===")
                android.util.Log.d("ProductDetailFragment", "Clearing cached variant selections for baseItemId: '$baseItemId' to allow navigation arguments to take precedence")
                android.util.Log.d("ProductDetailFragment", "variationMap before clearing: $variationMap")
                viewModel.clearCachedVariantSelections(baseItemId)
                android.util.Log.d("ProductDetailFragment", "Cached selections cleared")
                // Also clear current ViewModel state to ensure clean slate
                viewModel.clearVariantSelection()
                android.util.Log.d("ProductDetailFragment", "ViewModel state cleared")
                android.util.Log.d("ProductDetailFragment", "Calling loadProductDetail with skipCachedSelections = true")
                // Load product detail but skip restoring cached selections
                viewModel.loadProductDetail(baseItemId, skipCachedSelections = true)
            } else {
                android.util.Log.d("ProductDetailFragment", "No variationMap, calling loadProductDetail normally (will restore cached selections if available)")
                // Normal load without skipping cached selections
                viewModel.loadProductDetail(baseItemId)
            }
        } else {
            Toast.makeText(requireContext(), "Invalid product ID", Toast.LENGTH_SHORT).show()
            findNavController().navigateUp()
        }

        return root
    }

    private fun setupRecyclerViews() {
        // Thumbnail adapter
        thumbnailAdapter = ThumbnailAdapter { imageUrl ->
            loadMainImage(imageUrl)
        }
        binding.thumbnailRecyclerView.layoutManager = LinearLayoutManager(requireContext(), LinearLayoutManager.HORIZONTAL, false)
        binding.thumbnailRecyclerView.adapter = thumbnailAdapter

        // Item specs adapter
        itemSpecsAdapter = ItemSpecsAdapter()
        binding.itemSpecificsRecyclerView.layoutManager = LinearLayoutManager(requireContext())
        binding.itemSpecificsRecyclerView.adapter = itemSpecsAdapter

        // Related products adapter
        relatedProductsAdapter = RelatedProductAdapter { relatedProduct ->
            navigateToProductDetail(relatedProduct.id ?: "")
        }
        binding.relatedProductsRecyclerView.layoutManager = LinearLayoutManager(requireContext(), LinearLayoutManager.HORIZONTAL, false)
        binding.relatedProductsRecyclerView.adapter = relatedProductsAdapter
    }

    private fun setupObservers() {
        viewModel.product.observe(viewLifecycleOwner) { product ->
            product?.let {
                android.util.Log.d("ProductDetailFragment", "=== PRODUCT OBSERVER FIRED ===")
                android.util.Log.d("ProductDetailFragment", "Product loaded - id: '${it.id}', title: '${it.title}'")
                android.util.Log.d("ProductDetailFragment", "pendingVariationRestore: $pendingVariationRestore")
                android.util.Log.d("ProductDetailFragment", "variantSpinners size: ${variantSpinners.size}, keys: ${variantSpinners.keys}")
                android.util.Log.d("ProductDetailFragment", "ViewModel variantSelections: ${viewModel.variantSelections.value}")
                android.util.Log.d("ProductDetailFragment", "ViewModel selectedVariation: ${viewModel.selectedVariation.value?.variants}")
                displayProduct(it)
                
                // Try to restore variations after displayProduct sets up the spinners
                // This handles cases where pendingVariationRestore was set before product loaded
                // setupVariants is called from displayProduct, which will also try to restore
                // But if setupVariants hasn't run yet, wait a bit and try again
                if (pendingVariationRestore != null) {
                    android.util.Log.d("ProductDetailFragment", "Pending variation restore detected in observer, attempting restoration")
                    // Try immediate restoration if spinners are ready
                    if (variantSpinners.isNotEmpty()) {
                        android.util.Log.d("ProductDetailFragment", "Spinners already ready, restoring immediately")
                        binding.root.post {
                            if (variantSpinners.isNotEmpty() && pendingVariationRestore != null) {
                                restoreVariationSelections(pendingVariationRestore!!)
                                pendingVariationRestore = null
                            }
                        }
                    } else {
                        // Spinners not ready yet, wait for setupVariants
                        binding.root.postDelayed({
                            if (variantSpinners.isNotEmpty() && pendingVariationRestore != null) {
                                android.util.Log.d("ProductDetailFragment", "Restoring variations after displayProduct from setupObservers (delayed): $pendingVariationRestore")
                                restoreVariationSelections(pendingVariationRestore!!)
                                pendingVariationRestore = null
                            } else if (pendingVariationRestore != null) {
                                android.util.Log.w("ProductDetailFragment", "Variation restoration failed - spinners still not ready after delay")
                            }
                        }, 300) // Increased delay to ensure setupVariants has completed
                    }
                } else {
                    android.util.Log.d("ProductDetailFragment", "No pending variation restore in observer")
                }
                // Update favorite button state
                val isFavorite = it.is_favorite ?: false
                binding.favoriteButton.text = if (isFavorite) "Remove from Favorites" else "Add to Favorites"
                if (isFavorite) {
                    binding.favoriteButton.setIconResource(R.drawable.ic_favorite_filled)
                    binding.favoriteButton.iconTint = android.content.res.ColorStateList.valueOf(0xFFFF4444.toInt())
                } else {
                    binding.favoriteButton.setIconResource(R.drawable.ic_favorite_border)
                    binding.favoriteButton.iconTint = android.content.res.ColorStateList.valueOf(0xFF808080.toInt())
                }
            }
        }

        viewModel.relatedProducts.observe(viewLifecycleOwner) { products ->
            if (products.isNotEmpty()) {
                binding.relatedProductsLabel.visibility = View.VISIBLE
                binding.relatedProductsRecyclerView.visibility = View.VISIBLE
                relatedProductsAdapter.updateItems(products)
            }
        }

        viewModel.loading.observe(viewLifecycleOwner) { isLoading ->
            updateLoadingState(isLoading)
        }

        viewModel.error.observe(viewLifecycleOwner) { error ->
            error?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_LONG).show()
            }
        }

        viewModel.selectedVariation.observe(viewLifecycleOwner) { variation ->
            variation?.let {
                updateDisplayForVariation(it)
            } ?: run {
                // Reset to base product
                viewModel.product.value?.let { product ->
                    updateDisplayForBaseProduct(product)
                }
            }
        }
    }

    private fun setupClickListeners() {
        binding.favoriteButton.setOnClickListener {
            viewModel.product.value?.let { product ->
                val itemId = product.id ?: return@let
                val isFavorite = product.is_favorite ?: false
                
                // Add particle animation
                FavoriteParticleAnimation.animateFavorite(binding.favoriteButton, !isFavorite)
                
                // Add scale animation
                binding.favoriteButton.animate()
                    .scaleX(1.2f)
                    .scaleY(1.2f)
                    .setDuration(150)
                    .withEndAction {
                        binding.favoriteButton.animate()
                            .scaleX(1f)
                            .scaleY(1f)
                            .setDuration(150)
                            .start()
                    }
                    .start()
                
                // Add haptic feedback
                binding.favoriteButton.performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS)
                
                // Update catalog view model when toggling favorite
                val catalogViewModel = androidx.lifecycle.ViewModelProvider(requireActivity()).get(CatalogViewModel::class.java)
                viewModel.toggleFavorite(itemId, isFavorite) { newFavoriteState ->
                    // Sync with catalog view model
                    catalogViewModel.updateFavoriteInCache(itemId, newFavoriteState)
                }
            }
        }

        binding.addToCartButton.setOnClickListener {
            viewModel.product.value?.let { product ->
                val itemId = product.id ?: return@let
                val title = product.title ?: "Unknown Product"
                val imageUrl = product.image ?: ""
                val itemUrl = product.url ?: ""
                val points = product.points?.toInt() ?: 0
                
                // Check if product has variations that require selection
                val hasVariations = !product.variation_details.isNullOrEmpty()
                val cartViewModel = androidx.lifecycle.ViewModelProvider(requireActivity()).get(com.example.driverrewards.ui.cart.CartViewModel::class.java)
                
                if (hasVariations) {
                    val selectedVariation = viewModel.selectedVariation.value
                    if (selectedVariation == null) {
                        Toast.makeText(requireContext(), "Please select a variation before adding to cart", Toast.LENGTH_SHORT).show()
                        return@let
                    }
                    
                    // Build variation ID string for unique cart item
                    // Sort entries by key to ensure consistent ordering for duplicate detection
                    val variantSelections = viewModel.variantSelections.value ?: emptyMap()
                    val variationId = variantSelections.entries
                        .sortedBy { it.key }  // Sort by key to ensure consistent order
                        .joinToString("|") { "${it.key}:${it.value}" }
                    val uniqueItemId = "${itemId}::${variationId}"
                    android.util.Log.d("ProductDetailFragment", "Adding to cart - uniqueItemId: '$uniqueItemId'")
                    
                    val finalPoints = selectedVariation.price?.let { 
                        // Variation price is in dollars, convert to points (multiply by 100, default rate)
                        // Then round to nearest 10 points (matching backend price_to_points behavior)
                        val rawPoints = it * 100.0
                        (kotlin.math.round(rawPoints / 10.0) * 10.0).toInt()
                    } ?: points
                    val variationImage = selectedVariation.image ?: imageUrl
                    
                    // Get CartViewModel and add to cart with variation
                    cartViewModel.addToCart(uniqueItemId, title, variationImage, itemUrl, finalPoints, 1)
                } else {
                    // No variations, add as normal
                    if (points <= 0) {
                        Toast.makeText(requireContext(), "Invalid product points", Toast.LENGTH_SHORT).show()
                        return@let
                    }
                    
                    // Get CartViewModel and add to cart
                    cartViewModel.addToCart(itemId, title, imageUrl, itemUrl, points, 1)
                }
                
                // Observe success (shared for both paths)
                cartViewModel.addToCartSuccess.observe(viewLifecycleOwner) { success ->
                    if (success == true) {
                        Toast.makeText(requireContext(), "Added to cart!", Toast.LENGTH_SHORT).show()
                        cartViewModel.clearAddToCartSuccess()
                    }
                }
                
                // Observe errors (shared for both paths)
                cartViewModel.errorMessage.observe(viewLifecycleOwner) { error ->
                    error?.let {
                        if (it.contains("cart", ignoreCase = true)) {
                            Toast.makeText(requireContext(), it, Toast.LENGTH_SHORT).show()
                            cartViewModel.clearError()
                        }
                    }
                }
            }
        }

        binding.shareButton.setOnClickListener {
            val product = viewModel.product.value
            if (product == null) {
                Toast.makeText(requireContext(), R.string.share_product_missing_data, Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            shareProduct(product)
        }
    }

    private fun displayProduct(product: ProductDetail) {
        // Ensure skeleton is hidden when product is displayed
        binding.skeletonImage.visibility = View.GONE
        binding.skeletonDetailsRow1.visibility = View.GONE
        binding.skeletonDetailsRow2.visibility = View.GONE
        binding.skeletonDetailsRow3.visibility = View.GONE
        
        // Show content elements
        binding.productTitle.visibility = View.VISIBLE
        binding.productPoints.visibility = View.VISIBLE
        
        // Title
        binding.productTitle.text = product.title ?: "Unknown Product"

        // Subtitle
        product.subtitle?.let {
            binding.productSubtitle.text = it
            binding.productSubtitle.visibility = View.VISIBLE
        } ?: run {
            binding.productSubtitle.visibility = View.GONE
        }

        // Points
        binding.productPoints.text = product.display_points ?: "${product.points?.toInt() ?: 0} pts"

        // Brand
        product.brand?.let {
            binding.productBrand.text = "Brand: $it"
            binding.productBrand.visibility = View.VISIBLE
        } ?: run {
            binding.productBrand.visibility = View.GONE
        }

        // Condition
        product.condition?.let {
            binding.productCondition.text = "Condition: $it"
            binding.productCondition.visibility = View.VISIBLE
        } ?: run {
            binding.productCondition.visibility = View.GONE
        }

        // Description
        product.subtitle?.let {
            binding.descriptionLabel.visibility = View.VISIBLE
            binding.productDescription.text = it
            binding.productDescription.visibility = View.VISIBLE
        } ?: run {
            binding.descriptionLabel.visibility = View.GONE
            binding.productDescription.visibility = View.GONE
        }

        // Main image
        loadMainImage(product.image)

        // Thumbnail gallery
        val allImages = mutableListOf<String>()
        product.image?.let { allImages.add(it) }
        product.additional_images?.let { allImages.addAll(it) }
        if (allImages.size > 1) {
            binding.thumbnailRecyclerView.visibility = View.VISIBLE
            thumbnailAdapter.updateItems(allImages.take(6)) // Limit to 6 thumbnails
        } else {
            binding.thumbnailRecyclerView.visibility = View.GONE
        }

        // Availability badges
        updateAvailabilityBadges(product)

        // Item specifics
        product.item_specifics?.let { specs ->
            if (specs.isNotEmpty()) {
                binding.itemSpecificsLabel.visibility = View.VISIBLE
                binding.itemSpecificsRecyclerView.visibility = View.VISIBLE
                itemSpecsAdapter.updateItems(specs)
            }
        } ?: run {
            binding.itemSpecificsLabel.visibility = View.GONE
            binding.itemSpecificsRecyclerView.visibility = View.GONE
        }

        // Variants
        setupVariants(product)

        // Favorite button with proper color tinting - show it when product is loaded
        binding.favoriteButton.visibility = View.VISIBLE
        binding.shareButton.visibility = View.VISIBLE
        val isFavorite = product.is_favorite ?: false
        binding.favoriteButton.text = if (isFavorite) "Remove from Favorites" else "Add to Favorites"
        if (isFavorite) {
            binding.favoriteButton.setIconResource(R.drawable.ic_favorite_filled)
            binding.favoriteButton.iconTint = android.content.res.ColorStateList.valueOf(0xFFFF4444.toInt())
        } else {
            binding.favoriteButton.setIconResource(R.drawable.ic_favorite_border)
            binding.favoriteButton.iconTint = android.content.res.ColorStateList.valueOf(0xFF808080.toInt())
        }

        // Add to cart button visibility
        val points = product.points ?: 0.0
        binding.addToCartButton.visibility = if (points > 0) View.VISIBLE else View.GONE
        
        // Show main image
        binding.mainProductImage.visibility = View.VISIBLE
    }
    
    private fun updateLoadingState(isLoading: Boolean) {
        if (isLoading) {
            // Show skeleton placeholders
            binding.skeletonImage.visibility = View.VISIBLE
            binding.skeletonDetailsRow1.visibility = View.VISIBLE
            binding.skeletonDetailsRow2.visibility = View.VISIBLE
            binding.skeletonDetailsRow3.visibility = View.VISIBLE
            
            // Hide actual content
            binding.mainProductImage.visibility = View.GONE
            binding.productTitle.visibility = View.GONE
            binding.productSubtitle.visibility = View.GONE
            binding.productPoints.visibility = View.GONE
            binding.favoriteButton.visibility = View.GONE
            binding.addToCartButton.visibility = View.GONE
            binding.shareButton.visibility = View.GONE
            
            // ShimmerView handles its own animation automatically
        } else {
            // Hide skeleton placeholders
            binding.skeletonImage.visibility = View.GONE
            binding.skeletonDetailsRow1.visibility = View.GONE
            binding.skeletonDetailsRow2.visibility = View.GONE
            binding.skeletonDetailsRow3.visibility = View.GONE
        }
    }

    private var variantSpinners = mutableMapOf<String, Spinner>()
    private var pendingVariationRestore: Map<String, String>? = null
    
    private fun setupVariants(product: ProductDetail) {
        android.util.Log.d("ProductDetailFragment", "=== setupVariants START ===")
        val variantsContainer = binding.variantsContainer
        variantsContainer.removeAllViews()
        variantSpinners.clear()
        android.util.Log.d("ProductDetailFragment", "Cleared variantSpinners, now empty")

        val variants = product.variants ?: run {
            android.util.Log.d("ProductDetailFragment", "Product has no variants, hiding container")
            binding.variantsContainer.visibility = View.GONE
            return
        }
        
        android.util.Log.d("ProductDetailFragment", "Product variants: ${variants.keys}")
        
        if (variants.isEmpty()) {
            android.util.Log.d("ProductDetailFragment", "Variants map is empty, hiding container")
            binding.variantsContainer.visibility = View.GONE
            return
        }

        // Filter variants that have more than one option
        val multiOptionVariants = variants.filter { it.value.size > 1 }
        android.util.Log.d("ProductDetailFragment", "Multi-option variants: ${multiOptionVariants.keys}, options: ${multiOptionVariants.mapValues { it.value.size }}")
        
        if (multiOptionVariants.isEmpty()) {
            android.util.Log.d("ProductDetailFragment", "No multi-option variants, hiding container")
            binding.variantsContainer.visibility = View.GONE
            return
        }

        binding.variantsContainer.visibility = View.VISIBLE
        android.util.Log.d("ProductDetailFragment", "Creating spinners for: ${multiOptionVariants.keys}")

        multiOptionVariants.forEach { (variantType, options) ->
            android.util.Log.d("ProductDetailFragment", "Creating spinner for variantType: '$variantType' with options: $options")
            val label = TextView(requireContext()).apply {
                text = "$variantType: *"
                textSize = 14f
                setPadding(0, 8, 0, 4)
            }
            variantsContainer.addView(label)

            val spinner = Spinner(requireContext()).apply {
                val adapter = ArrayAdapter(requireContext(), android.R.layout.simple_spinner_item, mutableListOf("Choose $variantType").apply { addAll(options) })
                adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
                this.adapter = adapter

                onItemSelectedListener = object : android.widget.AdapterView.OnItemSelectedListener {
                    override fun onItemSelected(parent: android.widget.AdapterView<*>?, view: View?, position: Int, id: Long) {
                        if (position > 0) {
                            val selectedValue = options[position - 1]
                            viewModel.selectVariant(variantType, selectedValue)
                        } else {
                            viewModel.selectVariant(variantType, "")
                        }
                    }

                    override fun onNothingSelected(parent: android.widget.AdapterView<*>?) {}
                }
            }
            variantsContainer.addView(spinner)
            variantSpinners[variantType] = spinner
            android.util.Log.d("ProductDetailFragment", "Spinner created and added for '$variantType', total spinners: ${variantSpinners.size}")
        }
        
        android.util.Log.d("ProductDetailFragment", "All spinners created. Total: ${variantSpinners.size}, types: ${variantSpinners.keys}")
        android.util.Log.d("ProductDetailFragment", "pendingVariationRestore: $pendingVariationRestore")
        
        // If there's a pending variation restore, do it now that spinners are created
        pendingVariationRestore?.let { variationMap ->
            android.util.Log.d("ProductDetailFragment", "=== RESTORING VARIATIONS IN setupVariants ===")
            android.util.Log.d("ProductDetailFragment", "Restoring variations after setupVariants (spinners created): $variationMap")
            android.util.Log.d("ProductDetailFragment", "Available spinner types: ${variantSpinners.keys}")
            android.util.Log.d("ProductDetailFragment", "Variation map keys: ${variationMap.keys}")
            // Small delay to ensure spinners are fully initialized
            binding.root.postDelayed({
                if (variantSpinners.isNotEmpty() && pendingVariationRestore != null) {
                    android.util.Log.d("ProductDetailFragment", "Executing variation restoration in setupVariants (postDelayed)")
                    restoreVariationSelections(pendingVariationRestore!!)
                    pendingVariationRestore = null
                } else {
                    android.util.Log.w("ProductDetailFragment", "Variation restoration in setupVariants failed - spinners or variationMap not ready")
                }
            }, 50) // Small delay to ensure spinners are fully initialized
        } ?: run {
            // No pending variation restore - auto-select default variation from item_specifics
            // This applies when opening from catalog/favorites (not from cart)
            android.util.Log.d("ProductDetailFragment", "No pending variation restore - checking for default variation from item_specifics")
            product.item_specifics?.let { itemSpecs ->
                android.util.Log.d("ProductDetailFragment", "Product has item_specifics: $itemSpecs")
                // Build a map of default values from item_specifics for variant types
                val defaultVariationMap = mutableMapOf<String, String>()
                variantSpinners.keys.forEach { variantType ->
                    val defaultValue = itemSpecs[variantType]
                    if (!defaultValue.isNullOrEmpty()) {
                        android.util.Log.d("ProductDetailFragment", "Found default value for '$variantType': '$defaultValue'")
                        defaultVariationMap[variantType] = defaultValue
                    } else {
                        // Try case-insensitive match
                        val caseInsensitiveMatch = itemSpecs.entries.find { 
                            it.key.trim().equals(variantType.trim(), ignoreCase = true) 
                        }
                        caseInsensitiveMatch?.let {
                            android.util.Log.d("ProductDetailFragment", "Found case-insensitive default value for '$variantType': '${it.value}'")
                            defaultVariationMap[variantType] = it.value
                        }
                    }
                }
                
                if (defaultVariationMap.isNotEmpty()) {
                    android.util.Log.d("ProductDetailFragment", "=== AUTO-SELECTING DEFAULT VARIATION ===")
                    android.util.Log.d("ProductDetailFragment", "Default variation map: $defaultVariationMap")
                    // Small delay to ensure spinners are fully initialized
                    binding.root.postDelayed({
                        if (variantSpinners.isNotEmpty()) {
                            android.util.Log.d("ProductDetailFragment", "Executing default variation selection")
                            restoreVariationSelections(defaultVariationMap)
                        }
                    }, 50)
                } else {
                    android.util.Log.d("ProductDetailFragment", "No default variation found in item_specifics for variant types: ${variantSpinners.keys}")
                }
            } ?: run {
                android.util.Log.d("ProductDetailFragment", "Product has no item_specifics, cannot auto-select default variation")
            }
        }
    }
    
    private fun restoreVariationSelections(variationMap: Map<String, String>) {
        android.util.Log.d("ProductDetailFragment", "=== restoreVariationSelections START ===")
        android.util.Log.d("ProductDetailFragment", "restoreVariationSelections called with: $variationMap")
        android.util.Log.d("ProductDetailFragment", "Available spinners: ${variantSpinners.keys}")
        android.util.Log.d("ProductDetailFragment", "Variation map keys: ${variationMap.keys}")
        android.util.Log.d("ProductDetailFragment", "Variation map entries: ${variationMap.entries.map { "${it.key} -> ${it.value}" }}")
        
        if (variantSpinners.isEmpty()) {
            android.util.Log.w("ProductDetailFragment", "No spinners available yet, storing variationMap for later")
            pendingVariationRestore = variationMap
            return
        }
        
        var restoredCount = 0
        variantSpinners.forEach { (variantType, spinner) ->
            android.util.Log.d("ProductDetailFragment", "--- Processing variantType: '$variantType' ---")
            // Try to find matching key in variationMap (handle case/whitespace differences)
            val directMatch = variationMap[variantType]
            val caseInsensitiveMatch = variationMap.entries.find { 
                it.key.trim().equals(variantType.trim(), ignoreCase = true) 
            }?.value
            
            val selectedValue = directMatch ?: caseInsensitiveMatch
            
            android.util.Log.d("ProductDetailFragment", "Direct match for '$variantType': '$directMatch'")
            android.util.Log.d("ProductDetailFragment", "Case-insensitive match: '$caseInsensitiveMatch'")
            android.util.Log.d("ProductDetailFragment", "Final selectedValue: '$selectedValue'")
            
            if (!selectedValue.isNullOrEmpty()) {
                val adapter = spinner.adapter as? ArrayAdapter<*> ?: run {
                    android.util.Log.w("ProductDetailFragment", "Spinner adapter is null for $variantType")
                    return@forEach
                }
                android.util.Log.d("ProductDetailFragment", "Spinner adapter has ${adapter.count} items for $variantType")
                android.util.Log.d("ProductDetailFragment", "All adapter items: ${(0 until adapter.count).map { adapter.getItem(it)?.toString() }}")
                
                // Normalize the selected value for comparison (trim whitespace)
                val normalizedSelected = selectedValue.trim()
                android.util.Log.d("ProductDetailFragment", "Normalized selected value: '$normalizedSelected'")
                
                // Find the index of the selected value (skip first item which is "Choose X")
                var found = false
                for (i in 1 until adapter.count) {
                    val item = adapter.getItem(i)
                    val itemString = item?.toString()?.trim()
                    android.util.Log.d("ProductDetailFragment", "Checking item at index $i: '$itemString' vs selected: '$normalizedSelected'")
                    android.util.Log.d("ProductDetailFragment", "  Exact match: ${itemString == normalizedSelected}")
                    android.util.Log.d("ProductDetailFragment", "  Case-insensitive match: ${itemString?.equals(normalizedSelected, ignoreCase = true)}")
                    android.util.Log.d("ProductDetailFragment", "  Contains check (selected contains item): ${normalizedSelected.contains(itemString ?: "", ignoreCase = true)}")
                    android.util.Log.d("ProductDetailFragment", "  Contains check (item contains selected): ${itemString?.contains(normalizedSelected, ignoreCase = true)}")
                    
                    // Try exact match first
                    if (itemString == normalizedSelected) {
                        android.util.Log.d("ProductDetailFragment", "✓✓✓ Found EXACT match at index $i for $variantType = '$normalizedSelected' ✓✓✓")
                        spinner.setSelection(i, false) // false to prevent triggering listener during restore
                        android.util.Log.d("ProductDetailFragment", "Spinner selection set to index $i")
                        // Manually trigger the selection to update the ViewModel with the original value from adapter
                        val valueToSet = itemString ?: normalizedSelected
                        android.util.Log.d("ProductDetailFragment", "Calling viewModel.selectVariant('$variantType', '$valueToSet')")
                        viewModel.selectVariant(variantType, valueToSet)
                        android.util.Log.d("ProductDetailFragment", "ViewModel selectVariant called")
                        restoredCount++
                        found = true
                        break
                    }
                    // Try case-insensitive match
                    else if (itemString?.equals(normalizedSelected, ignoreCase = true) == true) {
                        android.util.Log.d("ProductDetailFragment", "✓✓✓ Found CASE-INSENSITIVE match at index $i for $variantType ✓✓✓")
                        spinner.setSelection(i, false)
                        val valueToSet = itemString ?: normalizedSelected
                        android.util.Log.d("ProductDetailFragment", "Calling viewModel.selectVariant('$variantType', '$valueToSet')")
                        viewModel.selectVariant(variantType, valueToSet)
                        restoredCount++
                        found = true
                        break
                    }
                    // Try partial match - check if normalizedSelected contains the itemString or vice versa
                    else if (!itemString.isNullOrEmpty()) {
                        // Check if selected value contains this option (for comma-separated values)
                        if (normalizedSelected.contains(itemString, ignoreCase = true)) {
                            android.util.Log.d("ProductDetailFragment", "✓✓✓ Found PARTIAL match (selected contains option) at index $i for $variantType ✓✓✓")
                            spinner.setSelection(i, false)
                            android.util.Log.d("ProductDetailFragment", "Calling viewModel.selectVariant('$variantType', '$itemString')")
                            viewModel.selectVariant(variantType, itemString)
                            restoredCount++
                            found = true
                            break
                        }
                        // Check if option contains selected value (for cases where stored value is subset)
                        else if (itemString.contains(normalizedSelected, ignoreCase = true)) {
                            android.util.Log.d("ProductDetailFragment", "✓✓✓ Found PARTIAL match (option contains selected) at index $i for $variantType ✓✓✓")
                            spinner.setSelection(i, false)
                            android.util.Log.d("ProductDetailFragment", "Calling viewModel.selectVariant('$variantType', '$itemString')")
                            viewModel.selectVariant(variantType, itemString)
                            restoredCount++
                            found = true
                            break
                        }
                    }
                }
                
                if (!found) {
                    android.util.Log.w("ProductDetailFragment", "✗✗✗ Could not find matching value '$normalizedSelected' for variantType '$variantType' in spinner ✗✗✗")
                    android.util.Log.w("ProductDetailFragment", "Available spinner options: ${(1 until adapter.count).map { adapter.getItem(it)?.toString() }}")
                } else {
                    android.util.Log.d("ProductDetailFragment", "✓ Successfully restored variantType '$variantType'")
                }
            } else {
                android.util.Log.d("ProductDetailFragment", "No selected value for variantType '$variantType' in variation map")
            }
        }
        android.util.Log.d("ProductDetailFragment", "=== restoreVariationSelections END ===")
        android.util.Log.d("ProductDetailFragment", "Restored $restoredCount out of ${variationMap.size} variations")
        android.util.Log.d("ProductDetailFragment", "Final ViewModel variantSelections: ${viewModel.variantSelections.value}")
        android.util.Log.d("ProductDetailFragment", "Final ViewModel selectedVariation: ${viewModel.selectedVariation.value?.variants}")
    }

    private fun updateAvailabilityBadges(product: ProductDetail) {
        binding.lowStockBadge.visibility = View.GONE
        binding.outOfStockBadge.visibility = View.GONE
        binding.availableBadge.visibility = View.GONE

        when {
            product.no_stock == true -> {
                binding.outOfStockBadge.visibility = View.VISIBLE
            }
            product.low_stock == true -> {
                binding.lowStockBadge.visibility = View.VISIBLE
                product.stock_qty?.let {
                    binding.lowStockBadge.text = "Low stock ($it)"
                }
            }
            product.available == true -> {
                binding.availableBadge.visibility = View.VISIBLE
            }
        }
    }

    private fun updateDisplayForVariation(variation: VariationDetail) {
        // Update image
        variation.image?.let {
            loadMainImage(it)
        }

        // Update thumbnail gallery
        val allImages = mutableListOf<String>()
        variation.image?.let { allImages.add(it) }
        variation.additional_images?.let { allImages.addAll(it) }
        if (allImages.size > 1) {
            binding.thumbnailRecyclerView.visibility = View.VISIBLE
            thumbnailAdapter.updateItems(allImages.take(6))
        }

        // Update price/points - need to convert price to points
        variation.price?.let { price ->
            // Convert price to points and round to nearest 10
            val rawPoints = price * 100.0
            val estimatedPoints = (kotlin.math.round(rawPoints / 10.0) * 10.0).toInt()
            binding.productPoints.text = "$estimatedPoints pts"
        }

        // Update availability badges
        when {
            variation.no_stock == true -> {
                binding.lowStockBadge.visibility = View.GONE
                binding.outOfStockBadge.visibility = View.VISIBLE
                binding.availableBadge.visibility = View.GONE
            }
            variation.low_stock == true -> {
                binding.lowStockBadge.visibility = View.VISIBLE
                binding.outOfStockBadge.visibility = View.GONE
                binding.availableBadge.visibility = View.GONE
                variation.stock_qty?.let {
                    binding.lowStockBadge.text = "Low stock ($it)"
                }
            }
            variation.available == true -> {
                binding.lowStockBadge.visibility = View.GONE
                binding.outOfStockBadge.visibility = View.GONE
                binding.availableBadge.visibility = View.VISIBLE
            }
        }
        
        // Update item specifics with variation-specific values
        viewModel.product.value?.let { baseProduct ->
            val baseSpecs = baseProduct.item_specifics ?: emptyMap()
            val variationVariants = variation.variants ?: emptyMap()
            
            // Merge variation variants into base specs, overriding matching keys
            val updatedSpecs = baseSpecs.toMutableMap()
            variationVariants.forEach { (key, value) ->
                updatedSpecs[key] = value
            }
            
            // Update the item specifics table
            if (updatedSpecs.isNotEmpty()) {
                binding.itemSpecificsLabel.visibility = View.VISIBLE
                binding.itemSpecificsRecyclerView.visibility = View.VISIBLE
                itemSpecsAdapter.updateItems(updatedSpecs)
            } else {
                binding.itemSpecificsLabel.visibility = View.GONE
                binding.itemSpecificsRecyclerView.visibility = View.GONE
            }
        }
    }

    private fun updateDisplayForBaseProduct(product: ProductDetail) {
        loadMainImage(product.image)
        product.image?.let { mainImage ->
            val allImages = mutableListOf(mainImage)
            product.additional_images?.let { allImages.addAll(it) }
            if (allImages.size > 1) {
                thumbnailAdapter.updateItems(allImages.take(6))
            }
        }
        binding.productPoints.text = product.display_points ?: "${product.points?.toInt() ?: 0} pts"
        updateAvailabilityBadges(product)
        
        // Reset item specifics to base product specs
        product.item_specifics?.let { specs ->
            if (specs.isNotEmpty()) {
                binding.itemSpecificsLabel.visibility = View.VISIBLE
                binding.itemSpecificsRecyclerView.visibility = View.VISIBLE
                itemSpecsAdapter.updateItems(specs)
            } else {
                binding.itemSpecificsLabel.visibility = View.GONE
                binding.itemSpecificsRecyclerView.visibility = View.GONE
            }
        } ?: run {
            binding.itemSpecificsLabel.visibility = View.GONE
            binding.itemSpecificsRecyclerView.visibility = View.GONE
        }
    }

    private fun shareProduct(product: ProductDetail) {
        val shareMessage = buildShareMessage(product)
        val shareSubject = product.title?.takeIf { it.isNotBlank() } ?: getString(R.string.share_product_default_subject)
        val shareIntent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_SUBJECT, shareSubject)
            putExtra(Intent.EXTRA_TEXT, shareMessage)
        }

        try {
            startActivity(Intent.createChooser(shareIntent, getString(R.string.share_product_chooser_title)))
        } catch (e: ActivityNotFoundException) {
            Toast.makeText(requireContext(), R.string.share_product_no_apps, Toast.LENGTH_SHORT).show()
        }
    }

    private fun buildShareMessage(product: ProductDetail): String {
        val title = product.title?.takeIf { it.isNotBlank() } ?: getString(R.string.share_product_default_subject)
        val points = product.display_points ?: product.points?.toInt()?.takeIf { it > 0 }?.let { "$it pts" }
        val url = product.url?.takeIf { it.isNotBlank() }

        val builder = StringBuilder()
        builder.append(getString(R.string.share_product_message_template, title))
        points?.let {
            builder.append("\n")
            builder.append(getString(R.string.share_product_points_line, it))
        }
        url?.let {
            builder.append("\n")
            builder.append(it)
        }
        return builder.toString()
    }

    private fun loadMainImage(imageUrl: String?) {
        if (!imageUrl.isNullOrEmpty()) {
            Glide.with(requireContext())
                .load(imageUrl)
                .placeholder(R.drawable.ic_catalog)
                .error(R.drawable.ic_catalog)
                .into(binding.mainProductImage)
        } else {
            binding.mainProductImage.setImageResource(R.drawable.ic_catalog)
        }
    }

    private fun navigateToProductDetail(itemId: String) {
        if (itemId.isNotEmpty()) {
            val bundle = Bundle().apply {
                putString("itemId", itemId)
            }
            findNavController().navigate(R.id.action_product_detail_to_product_detail, bundle)
        }
    }

    override fun onDestroyView() {
        // ShimmerView handles its own cleanup
        super.onDestroyView()
        _binding = null
    }
}

// Thumbnail adapter for image gallery
class ThumbnailAdapter(
    private val onThumbnailClick: (String) -> Unit
) : RecyclerView.Adapter<ThumbnailAdapter.ThumbnailViewHolder>() {

    private var items = mutableListOf<String>()

    fun updateItems(newItems: List<String>) {
        items.clear()
        items.addAll(newItems)
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ThumbnailViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_thumbnail, parent, false)
        return ThumbnailViewHolder(view)
    }

    override fun onBindViewHolder(holder: ThumbnailViewHolder, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount(): Int = items.size

    inner class ThumbnailViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val imageView: android.widget.ImageView = itemView.findViewById(R.id.thumbnail_image)

        fun bind(imageUrl: String) {
            Glide.with(itemView.context)
                .load(imageUrl)
                .placeholder(R.drawable.ic_catalog)
                .error(R.drawable.ic_catalog)
                .centerCrop()
                .into(imageView)

            itemView.setOnClickListener {
                onThumbnailClick(imageUrl)
            }
        }
    }
}

// Item specs adapter for product details table
class ItemSpecsAdapter : RecyclerView.Adapter<ItemSpecsAdapter.ItemSpecViewHolder>() {

    private var items = mutableListOf<Pair<String, String>>()

    fun updateItems(specs: Map<String, String>) {
        items.clear()
        items.addAll(specs.map { (key, value) -> Pair(key, value) })
        notifyDataSetChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ItemSpecViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_spec_row, parent, false)
        return ItemSpecViewHolder(view)
    }

    override fun onBindViewHolder(holder: ItemSpecViewHolder, position: Int) {
        holder.bind(items[position])
    }

    override fun getItemCount(): Int = items.size

    inner class ItemSpecViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val keyView: TextView = itemView.findViewById(R.id.spec_key)
        private val valueView: TextView = itemView.findViewById(R.id.spec_value)

        fun bind(spec: Pair<String, String>) {
            keyView.text = spec.first
            valueView.text = spec.second
        }
    }
}
