package com.example.driverrewards.ui.orders

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
import com.example.driverrewards.databinding.FragmentOrdersBinding
import com.google.android.material.dialog.MaterialAlertDialogBuilder

class OrdersFragment : Fragment() {

    private var _binding: FragmentOrdersBinding? = null
    private val binding get() = _binding!!
    private lateinit var ordersViewModel: OrdersViewModel
    private lateinit var ordersAdapter: OrdersAdapter

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        ordersViewModel = ViewModelProvider(requireActivity())[OrdersViewModel::class.java]
        _binding = FragmentOrdersBinding.inflate(inflater, container, false)

        setupRecyclerView()
        setupObservers()
        setupSwipeRefresh()

        // Load orders
        ordersViewModel.loadOrders(refresh = true)

        return binding.root
    }

    private fun setupRecyclerView() {
        ordersAdapter = OrdersAdapter(
            orders = emptyList(),
            onRefundClick = { orderId ->
                // Check order status to determine if it's cancel or refund
                val order = ordersViewModel.orders.value?.find { it.orderId == orderId }
                if (order?.status?.lowercase() == "pending") {
                    showCancelDialog(orderId)
                } else {
                    showRefundDialog(orderId)
                }
            },
            onViewDetailsClick = { orderId ->
                // Navigate to order details
                val bundle = Bundle().apply {
                    putString("orderId", orderId)
                }
                findNavController().navigate(R.id.action_orders_to_order_detail, bundle)
            }
        )
        
        val layoutManager = LinearLayoutManager(requireContext())
        binding.recyclerView.layoutManager = layoutManager
        binding.recyclerView.adapter = ordersAdapter
        
        // Load more when scrolling
        binding.recyclerView.addOnScrollListener(object : androidx.recyclerview.widget.RecyclerView.OnScrollListener() {
            override fun onScrolled(recyclerView: androidx.recyclerview.widget.RecyclerView, dx: Int, dy: Int) {
                super.onScrolled(recyclerView, dx, dy)
                val totalItemCount = layoutManager.itemCount
                val lastVisibleItem = layoutManager.findLastVisibleItemPosition()
                
                if (lastVisibleItem >= totalItemCount - 5) {
                    ordersViewModel.loadMoreOrders()
                }
            }
        })
    }

    private fun setupObservers() {
        ordersViewModel.orders.observe(viewLifecycleOwner, Observer { orders ->
            ordersAdapter = OrdersAdapter(
                orders = orders,
                onRefundClick = { orderId ->
                    // Check order status to determine if it's cancel or refund
                    val order = orders.find { it.orderId == orderId }
                    if (order?.status?.lowercase() == "pending") {
                        showCancelDialog(orderId)
                    } else {
                        showRefundDialog(orderId)
                    }
                },
                onViewDetailsClick = { orderId ->
                    // Navigate to order details
                    val bundle = Bundle().apply {
                        putString("orderId", orderId)
                    }
                    findNavController().navigate(R.id.action_orders_to_order_detail, bundle)
                }
            )
            binding.recyclerView.adapter = ordersAdapter
            
            // Show/hide empty message
            if (orders.isEmpty()) {
                binding.emptyOrdersMessage.visibility = View.VISIBLE
                binding.recyclerView.visibility = View.GONE
            } else {
                binding.emptyOrdersMessage.visibility = View.GONE
                binding.recyclerView.visibility = View.VISIBLE
            }
        })

        ordersViewModel.isLoading.observe(viewLifecycleOwner, Observer { isLoading ->
            binding.progressBar.visibility = if (isLoading) View.VISIBLE else View.GONE
            // Stop swipe refresh when loading completes
            if (!isLoading) {
                binding.swipeRefresh.isRefreshing = false
            }
        })

        ordersViewModel.isLoadingMore.observe(viewLifecycleOwner, Observer { isLoadingMore ->
            binding.loadingMore.visibility = if (isLoadingMore) View.VISIBLE else View.GONE
        })

        ordersViewModel.errorMessage.observe(viewLifecycleOwner, Observer { error ->
            error?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_SHORT).show()
            }
        })

        ordersViewModel.refundSuccess.observe(viewLifecycleOwner, Observer { success ->
            if (success == true) {
                Toast.makeText(requireContext(), "Order refunded successfully", Toast.LENGTH_SHORT).show()
                // Refresh points display in MainActivity
                (requireActivity() as? com.example.driverrewards.MainActivity)?.refreshPointsDisplay()
                // Refresh profile if using ProfileViewModel
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
                Toast.makeText(requireContext(), "Order cancelled successfully", Toast.LENGTH_SHORT).show()
                // Refresh points display in MainActivity
                (requireActivity() as? com.example.driverrewards.MainActivity)?.refreshPointsDisplay()
                // Refresh profile if using ProfileViewModel
                try {
                    val profileViewModel = androidx.lifecycle.ViewModelProvider(requireActivity())[com.example.driverrewards.ui.profile.ProfileViewModel::class.java]
                    profileViewModel.refreshProfile()
                } catch (e: Exception) {
                    // ProfileViewModel might not be available, that's okay
                }
            }
        })
    }

    private fun setupSwipeRefresh() {
        binding.swipeRefresh.setOnRefreshListener {
            ordersViewModel.refreshOrders()
        }
    }

    private fun showRefundDialog(orderId: String) {
        MaterialAlertDialogBuilder(requireContext())
            .setTitle("Refund Order")
            .setMessage("Are you sure you want to refund this order? Points will be returned to your account.")
            .setPositiveButton("Refund") { _, _ ->
                ordersViewModel.refundOrder(orderId)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }
    
    private fun showCancelDialog(orderId: String) {
        MaterialAlertDialogBuilder(requireContext())
            .setTitle("Cancel Order")
            .setMessage("Are you sure you want to cancel this order? Points will be returned to your account.")
            .setPositiveButton("Cancel Order") { _, _ ->
                ordersViewModel.cancelOrder(orderId)
            }
            .setNegativeButton("Keep Order", null)
            .show()
    }

    override fun onResume() {
        super.onResume()
        ordersViewModel.refreshOrders()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
