package com.example.driverrewards.ui.orders

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.Observer
import androidx.navigation.fragment.findNavController
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentOrderDetailBinding
import com.example.driverrewards.network.CartItem
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import java.text.SimpleDateFormat
import java.util.*

class OrderDetailFragment : Fragment() {

    private var _binding: FragmentOrderDetailBinding? = null
    private val binding get() = _binding!!
    private lateinit var ordersViewModel: OrdersViewModel
    private lateinit var orderItemsAdapter: OrderItemsAdapter
    private lateinit var cartViewModel: com.example.driverrewards.ui.cart.CartViewModel
    private var currentOrder: com.example.driverrewards.network.OrderData? = null

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        ordersViewModel = ViewModelProvider(requireActivity())[OrdersViewModel::class.java]
        cartViewModel = ViewModelProvider(requireActivity())[com.example.driverrewards.ui.cart.CartViewModel::class.java]
        _binding = FragmentOrderDetailBinding.inflate(inflater, container, false)

        val orderId = arguments?.getString("orderId") ?: ""
        if (orderId.isEmpty()) {
            Toast.makeText(requireContext(), "Invalid order ID", Toast.LENGTH_SHORT).show()
            findNavController().navigateUp()
            return binding.root
        }

        setupRecyclerView()
        setupObservers()
        setupClickListeners()
        loadOrderDetail(orderId)

        return binding.root
    }
    
    private fun setupClickListeners() {
        binding.reorderButton.setOnClickListener {
            currentOrder?.let { order ->
                reorderItems(order)
            }
        }
        
        binding.addAllToCartButton.setOnClickListener {
            currentOrder?.let { order ->
                addAllToCart(order)
            }
        }
    }

    private fun setupRecyclerView() {
        orderItemsAdapter = OrderItemsAdapter(
            items = emptyList(),
            onItemClick = { orderItem ->
                handleOrderItemClick(orderItem)
            }
        )
        binding.orderItemsRecycler.layoutManager = LinearLayoutManager(requireContext())
        binding.orderItemsRecycler.adapter = orderItemsAdapter
    }
    
    private fun handleOrderItemClick(orderItem: com.example.driverrewards.network.OrderItem) {
        val externalItemId = orderItem.externalItemId ?: orderItem.title ?: ""
        if (externalItemId.isEmpty()) {
            Toast.makeText(requireContext(), "Unable to open product details", Toast.LENGTH_SHORT).show()
            return
        }
        
        // Extract base item ID (before ::) and variation info
        val baseItemId = if (externalItemId.contains("::")) {
            externalItemId.substringBefore("::")
        } else {
            externalItemId
        }
        
        // Get variation info if present
        val variationInfo = if (externalItemId.contains("::")) {
            externalItemId.substringAfter("::")
        } else {
            // Also check if variationInfo is stored separately in the order item
            orderItem.variationInfo
        }
        
        android.util.Log.d("OrderDetailFragment", "Navigating to product detail")
        android.util.Log.d("OrderDetailFragment", "  ExternalItemId: $externalItemId")
        android.util.Log.d("OrderDetailFragment", "  BaseItemId: $baseItemId")
        android.util.Log.d("OrderDetailFragment", "  VariationInfo: $variationInfo")
        
        // Navigate to product detail with variation info
        val bundle = Bundle().apply {
            putString("itemId", baseItemId)
            variationInfo?.let {
                android.util.Log.d("OrderDetailFragment", "  Adding variationInfo to bundle: $it")
                putString("variationInfo", it)
            }
        }
        
        try {
            findNavController().navigate(R.id.action_order_detail_to_product_detail, bundle)
        } catch (e: Exception) {
            android.util.Log.e("OrderDetailFragment", "Error navigating to product detail: ${e.message}", e)
            Toast.makeText(requireContext(), "Error opening product details", Toast.LENGTH_SHORT).show()
        }
    }

    private fun setupObservers() {
        ordersViewModel.isLoading.observe(viewLifecycleOwner, Observer { isLoading ->
            binding.progressBar.visibility = if (isLoading) View.VISIBLE else View.GONE
        })

        ordersViewModel.errorMessage.observe(viewLifecycleOwner, Observer { error ->
            error?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_SHORT).show()
            }
        })
        
        ordersViewModel.refundSuccess.observe(viewLifecycleOwner, Observer { success ->
            if (success == true) {
                // Refresh points display in MainActivity
                (requireActivity() as? com.example.driverrewards.MainActivity)?.refreshPointsDisplay()
                try {
                    val profileViewModel = androidx.lifecycle.ViewModelProvider(requireActivity())[com.example.driverrewards.ui.profile.ProfileViewModel::class.java]
                    profileViewModel.refreshProfile()
                } catch (e: Exception) {
                    // ProfileViewModel might not be available, that's okay
                }
            }
        })
        
        ordersViewModel.cancelSuccess.observe(viewLifecycleOwner, Observer { success ->
            if (success == true) {
                // Refresh points display in MainActivity
                (requireActivity() as? com.example.driverrewards.MainActivity)?.refreshPointsDisplay()
                try {
                    val profileViewModel = androidx.lifecycle.ViewModelProvider(requireActivity())[com.example.driverrewards.ui.profile.ProfileViewModel::class.java]
                    profileViewModel.refreshProfile()
                } catch (e: Exception) {
                    // ProfileViewModel might not be available, that's okay
                }
            }
        })
    }

    private fun loadOrderDetail(orderId: String) {
        ordersViewModel.getOrderDetail(orderId,
            onSuccess = { order ->
                displayOrder(order)
            },
            onError = { error ->
                Toast.makeText(requireContext(), error, Toast.LENGTH_SHORT).show()
                findNavController().navigateUp()
            }
        )
    }

    private fun displayOrder(order: com.example.driverrewards.network.OrderData) {
        // Store current order for re-order functionality
        currentOrder = order
        
        binding.orderNumber.text = "Order #${order.orderNumber ?: "Unknown"}"
        
        // Status badge
        val status = order.status ?: "unknown"
        binding.orderStatus.text = status.replaceFirstChar { it.uppercase() }
        val context = requireContext()
        when (status.lowercase()) {
            "completed" -> {
                binding.orderStatus.setBackgroundColor(ContextCompat.getColor(context, R.color.status_completed_bg))
                binding.orderStatus.setTextColor(ContextCompat.getColor(context, R.color.status_completed_text))
            }
            "pending" -> {
                binding.orderStatus.setBackgroundColor(ContextCompat.getColor(context, R.color.status_pending_bg))
                binding.orderStatus.setTextColor(ContextCompat.getColor(context, R.color.status_pending_text))
            }
            "refunded", "cancelled" -> {
                binding.orderStatus.setBackgroundColor(ContextCompat.getColor(context, R.color.status_refunded_bg))
                binding.orderStatus.setTextColor(ContextCompat.getColor(context, R.color.status_refunded_text))
            }
            else -> {
                binding.orderStatus.setBackgroundColor(ContextCompat.getColor(context, R.color.status_default_bg))
                binding.orderStatus.setTextColor(ContextCompat.getColor(context, R.color.status_default_text))
            }
        }

        // Date
        try {
            if (order.createdAt != null) {
                val inputFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
                val outputFormat = SimpleDateFormat("MMM dd, yyyy 'at' h:mm a", Locale.getDefault())
                val date = inputFormat.parse(order.createdAt)
                binding.orderDate.text = "Date: ${date?.let { outputFormat.format(it) } ?: order.createdAt}"
            } else {
                binding.orderDate.text = "Date: Unknown"
            }
        } catch (e: Exception) {
            binding.orderDate.text = "Date: ${order.createdAt ?: "Unknown"}"
        }

        binding.orderTotal.text = "Total: ${order.totalPoints} pts"

        // Order items - update adapter with new items (callback is already set in setupRecyclerView)
        orderItemsAdapter.updateItems(order.orderItems)

        // Cancel/Refund buttons
        when (status.lowercase()) {
            "pending" -> {
                binding.cancelButton.visibility = View.VISIBLE
                binding.refundButton.visibility = View.GONE
                binding.cancelButton.setOnClickListener {
                    showCancelDialog(order.orderId ?: "")
                }
            }
            "completed" -> {
                binding.cancelButton.visibility = View.GONE
                if (order.canRefund) {
                    binding.refundButton.visibility = View.VISIBLE
                    binding.refundButton.setOnClickListener {
                        showRefundDialog(order.orderId ?: "")
                    }
                } else {
                    binding.refundButton.visibility = View.GONE
                }
            }
            else -> {
                binding.cancelButton.visibility = View.GONE
                binding.refundButton.visibility = View.GONE
            }
        }
    }

    private fun showCancelDialog(orderId: String) {
        MaterialAlertDialogBuilder(requireContext())
            .setTitle("Cancel Order")
            .setMessage("Are you sure you want to cancel this order? Points will be returned to your account.")
            .setPositiveButton("Cancel Order") { _, _ ->
                ordersViewModel.cancelOrder(orderId)
                // Refresh points display after cancel
                (requireActivity() as? com.example.driverrewards.MainActivity)?.refreshPointsDisplay()
                try {
                    val profileViewModel = androidx.lifecycle.ViewModelProvider(requireActivity())[com.example.driverrewards.ui.profile.ProfileViewModel::class.java]
                    profileViewModel.refreshProfile()
                } catch (e: Exception) {
                    // ProfileViewModel might not be available, that's okay
                }
                findNavController().navigateUp()
            }
            .setNegativeButton("Keep Order", null)
            .show()
    }

    private fun showRefundDialog(orderId: String) {
        MaterialAlertDialogBuilder(requireContext())
            .setTitle("Refund Order")
            .setMessage("Are you sure you want to refund this order? Points will be returned to your account.")
            .setPositiveButton("Refund") { _, _ ->
                ordersViewModel.refundOrder(orderId)
                // Refresh points display after refund
                (requireActivity() as? com.example.driverrewards.MainActivity)?.refreshPointsDisplay()
                try {
                    val profileViewModel = androidx.lifecycle.ViewModelProvider(requireActivity())[com.example.driverrewards.ui.profile.ProfileViewModel::class.java]
                    profileViewModel.refreshProfile()
                } catch (e: Exception) {
                    // ProfileViewModel might not be available, that's okay
                }
                findNavController().navigateUp()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }
    
    private fun reorderItems(order: com.example.driverrewards.network.OrderData) {
        if (order.orderItems.isEmpty()) {
            Toast.makeText(requireContext(), "No items to re-order", Toast.LENGTH_SHORT).show()
            return
        }
        
        // Navigate directly to checkout with orderId (no cart operations)
        val orderId = order.orderId
        if (orderId.isNullOrEmpty()) {
            Toast.makeText(requireContext(), "Invalid order ID", Toast.LENGTH_SHORT).show()
            return
        }
        
        // Calculate item count
        val itemCount = order.orderItems.sumOf { it.quantity }
        
        // Navigate to checkout with orderId and order totals
        val bundle = Bundle().apply {
            putString("orderId", orderId)
            putInt("totalPoints", order.totalPoints)
            putInt("itemCount", itemCount)
        }
        
        try {
            findNavController().navigate(R.id.action_order_detail_to_checkout, bundle)
        } catch (e: Exception) {
            android.util.Log.e("OrderDetailFragment", "Error navigating to checkout: ${e.message}", e)
            Toast.makeText(requireContext(), "Error navigating to checkout", Toast.LENGTH_SHORT).show()
        }
    }
    
    private fun addAllToCart(order: com.example.driverrewards.network.OrderData) {
        if (order.orderItems.isEmpty()) {
            Toast.makeText(requireContext(), "No items to add", Toast.LENGTH_SHORT).show()
            return
        }
        
        // Show loading state
        binding.addAllToCartButton.isEnabled = false
        binding.addAllToCartButton.text = "Adding items..."
        
        // Add items directly without clearing cart or navigating
        addOrderItemsToCart(order.orderItems, navigateToCheckout = false)
    }
    
    private fun addOrderItemsToCart(items: List<com.example.driverrewards.network.OrderItem>, navigateToCheckout: Boolean = false) {
        if (items.isEmpty()) {
            // Restore button states
            binding.reorderButton.isEnabled = true
            binding.reorderButton.text = "Re-order"
            binding.addAllToCartButton.isEnabled = true
            binding.addAllToCartButton.text = "Add all to cart"
            
            // Navigate to checkout only if requested (for re-order)
            if (navigateToCheckout) {
                navigateToCheckout()
            } else {
                Toast.makeText(requireContext(), "Items added to cart", Toast.LENGTH_SHORT).show()
            }
            return
        }
        
        val item = items[0]
        val remainingItems = items.drop(1)
        
        // Use externalItemId, or construct from title if not available
        val itemId = item.externalItemId ?: item.title ?: ""
        if (itemId.isEmpty()) {
            // Skip this item and continue with remaining
            addOrderItemsToCart(remainingItems)
            return
        }
        
        // Add item to cart
        cartViewModel.addToCart(
            itemId = itemId,
            title = item.title ?: "Unknown Item",
            imageUrl = "", // Not available in order item, will use placeholder
            itemUrl = "", // Not available in order item
            points = item.unitPoints,
            quantity = item.quantity
        )
        
        // Wait for add to cart to complete
        cartViewModel.addToCartSuccess.observe(viewLifecycleOwner, object : androidx.lifecycle.Observer<Boolean?> {
            override fun onChanged(success: Boolean?) {
                if (success != null) {
                    cartViewModel.addToCartSuccess.removeObserver(this)
                    if (success == true) {
                        // Successfully added, continue with next item
                        cartViewModel.clearAddToCartSuccess()
                        addOrderItemsToCart(remainingItems, navigateToCheckout)
                    } else {
                        // Failed to add this item, but continue with others
                        addOrderItemsToCart(remainingItems, navigateToCheckout)
                    }
                }
            }
        })
    }
    
    private fun navigateToCheckout() {
        // Wait a moment for cart to finish updating, then navigate
        binding.root.postDelayed({
            try {
                val totalPoints = cartViewModel.totalPoints.value ?: 0
                val itemCount = cartViewModel.itemCount.value ?: 0
                
                val bundle = Bundle().apply {
                    putInt("totalPoints", totalPoints)
                    putInt("itemCount", itemCount)
                }
                
                // Navigate to checkout
                findNavController().navigate(R.id.action_order_detail_to_checkout, bundle)
            } catch (e: Exception) {
                android.util.Log.e("OrderDetailFragment", "Error navigating to checkout: ${e.message}", e)
                // Try navigation without bundle
                try {
                    findNavController().navigate(R.id.action_order_detail_to_checkout)
                } catch (e2: Exception) {
                    Toast.makeText(requireContext(), "Error navigating to checkout", Toast.LENGTH_SHORT).show()
                }
            } finally {
                binding.reorderButton.isEnabled = true
                binding.reorderButton.text = "Re-order"
            }
        }, 500)
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

