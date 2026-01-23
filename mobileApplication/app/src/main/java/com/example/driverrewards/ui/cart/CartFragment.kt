package com.example.driverrewards.ui.cart

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.Observer
import androidx.navigation.fragment.findNavController
import androidx.recyclerview.widget.LinearLayoutManager
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentCartBinding

class CartFragment : Fragment() {

    private var _binding: FragmentCartBinding? = null
    private val binding get() = _binding!!
    private lateinit var cartViewModel: CartViewModel
    private lateinit var cartAdapter: CartAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        cartViewModel = ViewModelProvider(requireActivity())[CartViewModel::class.java]
        _binding = FragmentCartBinding.inflate(inflater, container, false)
        val root: View = binding.root

        setupRecyclerView()
        setupObservers()
        setupClickListeners()

        // Load cart data
        cartViewModel.loadCart()

        return root
    }

    private fun setupRecyclerView() {
        cartAdapter = CartAdapter(
            items = emptyList(),
            onQuantityChanged = { itemId, newQuantity ->
                cartViewModel.updateQuantity(itemId, newQuantity)
            },
            onRemove = { itemId ->
                cartViewModel.removeItem(itemId)
            },
            onItemClick = { externalItemId ->
                // Use the exact same logic as OrderDetailFragment.handleOrderItemClick()
                if (externalItemId.isEmpty()) {
                    Toast.makeText(requireContext(), "Unable to open product details", Toast.LENGTH_SHORT).show()
                    return@CartAdapter
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
                    null
                }
                
                android.util.Log.d("CartFragment", "=== NAVIGATING TO PRODUCT DETAIL ===")
                android.util.Log.d("CartFragment", "  ExternalItemId: $externalItemId")
                android.util.Log.d("CartFragment", "  BaseItemId: $baseItemId")
                android.util.Log.d("CartFragment", "  VariationInfo: $variationInfo")
                
                // Navigate to product detail with variation info
                val bundle = Bundle().apply {
                    putString("itemId", baseItemId)
                    android.util.Log.d("CartFragment", "  Bundle itemId set to: $baseItemId")
                    variationInfo?.let {
                        android.util.Log.d("CartFragment", "  Adding variationInfo to bundle: $it")
                        putString("variationInfo", it)
                        android.util.Log.d("CartFragment", "  Bundle variationInfo set to: $it")
                    } ?: run {
                        android.util.Log.w("CartFragment", "  No variationInfo to add to bundle")
                    }
                }
                
                android.util.Log.d("CartFragment", "  Bundle contents - itemId: '${bundle.getString("itemId")}', variationInfo: '${bundle.getString("variationInfo")}'")
                
                try {
                    android.util.Log.d("CartFragment", "  Calling navigate with action_cart_to_product_detail")
                    findNavController().navigate(R.id.action_cart_to_product_detail, bundle)
                } catch (e: Exception) {
                    android.util.Log.e("CartFragment", "Error navigating to product detail: ${e.message}", e)
                    Toast.makeText(requireContext(), "Error opening product details", Toast.LENGTH_SHORT).show()
                }
            }
        )
        val layoutManager = LinearLayoutManager(requireContext())
        binding.recyclerView.layoutManager = layoutManager
        binding.recyclerView.adapter = cartAdapter
        
        // Restore scroll position after data loads
        binding.recyclerView.post {
            val scrollPos = cartViewModel.getScrollPosition()
            if (scrollPos > 0 && layoutManager.itemCount > scrollPos) {
                layoutManager.scrollToPosition(scrollPos)
            }
        }
        
        // Save scroll position when scrolling
        binding.recyclerView.addOnScrollListener(object : androidx.recyclerview.widget.RecyclerView.OnScrollListener() {
            override fun onScrolled(recyclerView: androidx.recyclerview.widget.RecyclerView, dx: Int, dy: Int) {
                super.onScrolled(recyclerView, dx, dy)
                val layoutManager = recyclerView.layoutManager as? LinearLayoutManager ?: return
                val firstVisible = layoutManager.findFirstVisibleItemPosition()
                if (firstVisible >= 0) {
                    cartViewModel.setScrollPosition(firstVisible)
                }
            }
        })
    }

    private fun setupObservers() {
        cartViewModel.cartItems.observe(viewLifecycleOwner, Observer { items ->
            cartAdapter = CartAdapter(
                items = items,
                onQuantityChanged = { itemId, newQuantity ->
                    cartViewModel.updateQuantity(itemId, newQuantity)
                },
                onRemove = { itemId ->
                    cartViewModel.removeItem(itemId)
                },
                onItemClick = { externalItemId ->
                    // Navigate to product detail
                    val bundle = Bundle().apply {
                        putString("itemId", externalItemId)
                    }
                    findNavController().navigate(R.id.action_cart_to_product_detail, bundle)
                }
            )
            binding.recyclerView.adapter = cartAdapter
            
            // Restore scroll position after adapter update
            binding.recyclerView.post {
                val layoutManager = binding.recyclerView.layoutManager as? LinearLayoutManager ?: return@post
                val scrollPos = cartViewModel.getScrollPosition()
                if (scrollPos > 0 && layoutManager.itemCount > scrollPos) {
                    layoutManager.scrollToPosition(scrollPos)
                }
            }
            
            // Show/hide empty message
            if (items.isEmpty()) {
                binding.emptyCartMessage.visibility = View.VISIBLE
                binding.recyclerView.visibility = View.GONE
            } else {
                binding.emptyCartMessage.visibility = View.GONE
                binding.recyclerView.visibility = View.VISIBLE
            }
        })

        cartViewModel.totalPoints.observe(viewLifecycleOwner, Observer { total ->
            binding.totalPoints.text = "Total: $total pts"
        })

        cartViewModel.itemCount.observe(viewLifecycleOwner, Observer { count ->
            binding.checkoutButton.isEnabled = count > 0
        })
        
        // Check balance for checkout button
        cartViewModel.totalPoints.observe(viewLifecycleOwner, Observer { total ->
            cartViewModel.driverPoints.observe(viewLifecycleOwner, Observer { balance ->
                val hasItems = cartViewModel.itemCount.value ?: 0 > 0
                binding.checkoutButton.isEnabled = hasItems && total <= balance
            })
        })

        cartViewModel.isLoading.observe(viewLifecycleOwner, Observer { isLoading ->
            binding.progressBar.visibility = if (isLoading) View.VISIBLE else View.GONE
        })

        cartViewModel.errorMessage.observe(viewLifecycleOwner, Observer { error ->
            error?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_SHORT).show()
            }
        })
    }

    private fun setupClickListeners() {
        binding.checkoutButton.setOnClickListener {
            val totalPoints = cartViewModel.totalPoints.value ?: 0
            val itemCount = cartViewModel.itemCount.value ?: 0
            
            // Navigate to checkout fragment
            val bundle = Bundle().apply {
                putInt("totalPoints", totalPoints)
                putInt("itemCount", itemCount)
            }
            findNavController().navigate(R.id.action_cart_to_checkout, bundle)
        }

        binding.clearButton.setOnClickListener {
            cartViewModel.clearCart()
        }
    }

    override fun onResume() {
        super.onResume()
        cartViewModel.loadCart()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
