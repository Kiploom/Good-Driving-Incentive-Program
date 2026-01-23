package com.example.driverrewards.ui.cart

import android.os.Bundle
import android.text.TextUtils
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.Observer
import androidx.navigation.fragment.findNavController
import com.example.driverrewards.databinding.FragmentCheckoutBinding
import com.example.driverrewards.ui.profile.ProfileViewModel
import com.example.driverrewards.network.OrdersService
import com.example.driverrewards.network.ReorderCheckoutRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class CheckoutFragment : Fragment() {
    
    private var _binding: FragmentCheckoutBinding? = null
    private val binding get() = _binding!!
    
    private lateinit var cartViewModel: CartViewModel
    private lateinit var profileViewModel: ProfileViewModel
    private val ordersService = OrdersService()
    
    private var totalPoints: Int = 0
    private var itemCount: Int = 0
    private var orderId: String? = null // If present, this is a re-order checkout
    
    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        cartViewModel = ViewModelProvider(requireActivity())[CartViewModel::class.java]
        profileViewModel = ViewModelProvider(requireActivity())[ProfileViewModel::class.java]
        
        _binding = FragmentCheckoutBinding.inflate(inflater, container, false)
        
        // Get cart summary from arguments or ViewModel
        totalPoints = arguments?.getInt("totalPoints") ?: (cartViewModel.totalPoints.value ?: 0)
        itemCount = arguments?.getInt("itemCount") ?: (cartViewModel.itemCount.value ?: 0)
        orderId = arguments?.getString("orderId")
        
        return binding.root
    }
    
    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        
        // Set order summary
        binding.orderItemsSummary.text = "Items: $itemCount"
        binding.orderTotalPoints.text = "Total: $totalPoints pts"
        
        // Check balance and disable checkout button if insufficient
        cartViewModel.driverPoints.observe(viewLifecycleOwner, Observer { balance ->
            if (totalPoints > balance) {
                binding.checkoutButton.isEnabled = false
                binding.checkoutButton.text = "Insufficient Points"
            } else {
                binding.checkoutButton.isEnabled = true
                binding.checkoutButton.text = "Place Order"
            }
        })
        
        setupClickListeners()
        setupObservers()
        autofillFromProfile()
    }
    
    private fun autofillFromProfile() {
        profileViewModel.profileData.observe(viewLifecycleOwner, Observer { profileData ->
            profileData?.let {
                // Fill in name
                it.firstName?.let { firstName ->
                    binding.firstNameText.setText(firstName)
                }
                it.lastName?.let { lastName ->
                    binding.lastNameText.setText(lastName)
                }
                
                
                // Parse and fill shipping address
                it.shippingAddress?.let { address ->
                    parseAndFillAddress(address)
                }
            }
        })
        
        // Load profile if not already loaded
        if (profileViewModel.profileData.value == null) {
            profileViewModel.loadProfile()
        } else {
            // If profile is already cached, use it immediately
            profileViewModel.profileData.value?.let { profileData ->
                profileData.firstName?.let { binding.firstNameText.setText(it) }
                profileData.lastName?.let { binding.lastNameText.setText(it) }
                profileData.shippingAddress?.let { parseAndFillAddress(it) }
            }
        }
    }
    
    private fun parseAndFillAddress(address: String) {
        // Try to parse address - format is typically "Street, City, State, Postal, Country"
        val parts = address.split(",").map { it.trim() }
        
        when (parts.size) {
            1 -> {
                if (parts[0].isNotEmpty()) {
                    binding.shippingStreetText.setText(parts[0])
                }
            }
            2 -> {
                binding.shippingStreetText.setText(parts[0])
                binding.shippingCityText.setText(parts[1])
            }
            3 -> {
                binding.shippingStreetText.setText(parts[0])
                binding.shippingCityText.setText(parts[1])
                binding.shippingStateText.setText(parts[2])
            }
            4 -> {
                binding.shippingStreetText.setText(parts[0])
                binding.shippingCityText.setText(parts[1])
                binding.shippingStateText.setText(parts[2])
                binding.shippingPostalText.setText(parts[3])
            }
            else -> {
                if (parts.size >= 1) binding.shippingStreetText.setText(parts[0])
                if (parts.size >= 2) binding.shippingCityText.setText(parts[1])
                if (parts.size >= 3) binding.shippingStateText.setText(parts[2])
                if (parts.size >= 4) binding.shippingPostalText.setText(parts[3])
                if (parts.size >= 5) binding.shippingCountryText.setText(parts[4])
            }
        }
    }
    
    private fun setupClickListeners() {
        binding.cancelButton.setOnClickListener {
            findNavController().navigateUp()
        }
        
        binding.checkoutButton.setOnClickListener {
            processCheckout()
        }
    }
    
    private fun setupObservers() {
        cartViewModel.checkoutSuccess.observe(viewLifecycleOwner, Observer { result ->
            result?.let {
                Toast.makeText(requireContext(), "Order placed successfully! Order #${it.orderNumber}", Toast.LENGTH_LONG).show()
                // Refresh points display in MainActivity
                (requireActivity() as? com.example.driverrewards.MainActivity)?.refreshPointsDisplay()
                // Refresh profile if on profile page
                profileViewModel.refreshProfile()
                // Navigate back to cart or orders
                findNavController().navigateUp()
            }
        })
        
        cartViewModel.errorMessage.observe(viewLifecycleOwner, Observer { error ->
            error?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_LONG).show()
                cartViewModel.clearError()
            }
        })
        
        cartViewModel.isLoading.observe(viewLifecycleOwner, Observer { isLoading ->
            binding.checkoutButton.isEnabled = !isLoading
            binding.checkoutButton.text = if (isLoading) "Processing..." else "Place Order"
        })
    }
    
    private fun processCheckout() {
        val firstName = binding.firstNameText.text?.toString()?.trim() ?: ""
        val lastName = binding.lastNameText.text?.toString()?.trim() ?: ""
        // Get email from profile
        val email = profileViewModel.profileData.value?.email ?: ""
        val shippingStreet = binding.shippingStreetText.text?.toString()?.trim() ?: ""
        val shippingCity = binding.shippingCityText.text?.toString()?.trim() ?: ""
        val shippingState = binding.shippingStateText.text?.toString()?.trim() ?: ""
        val shippingPostal = binding.shippingPostalText.text?.toString()?.trim() ?: ""
        val shippingCountry = binding.shippingCountryText.text?.toString()?.trim() ?: ""
        
        // Validate inputs
        if (!validateInputs(firstName, lastName, shippingStreet, shippingCity, shippingState, shippingPostal, shippingCountry)) {
            return
        }
        
        // Check terms agreement
        if (!binding.termsCheckbox.isChecked) {
            Toast.makeText(requireContext(), "Please agree to the terms and conditions", Toast.LENGTH_SHORT).show()
            return
        }
        
        // If orderId is present, this is a re-order checkout (don't touch cart)
        if (!orderId.isNullOrEmpty()) {
            processReorderCheckout(firstName, lastName, email, shippingStreet, shippingCity, shippingState, shippingPostal, shippingCountry)
        } else {
            // Normal checkout from cart
            cartViewModel.processCheckout(
                firstName = firstName,
                lastName = lastName,
                email = email,
                shippingStreet = shippingStreet,
                shippingCity = shippingCity,
                shippingState = shippingState,
                shippingPostal = shippingPostal,
                shippingCountry = shippingCountry,
                shippingCostPoints = 0
            )
        }
    }
    
    private fun processReorderCheckout(
        firstName: String,
        lastName: String,
        email: String,
        shippingStreet: String,
        shippingCity: String,
        shippingState: String,
        shippingPostal: String,
        shippingCountry: String
    ) {
        binding.checkoutButton.isEnabled = false
        binding.checkoutButton.text = "Processing..."
        
        CoroutineScope(Dispatchers.Main).launch {
            try {
                val request = ReorderCheckoutRequest(
                    firstName = firstName,
                    lastName = lastName,
                    email = email,
                    shippingStreet = shippingStreet,
                    shippingCity = shippingCity,
                    shippingState = shippingState,
                    shippingPostal = shippingPostal,
                    shippingCountry = shippingCountry,
                    shippingCostPoints = 0
                )
                
                val response = ordersService.reorderCheckout(orderId!!, request)
                
                if (response.success) {
                    Toast.makeText(requireContext(), "Re-order placed successfully! Order #${response.orderNumber}", Toast.LENGTH_LONG).show()
                    // Refresh points display in MainActivity
                    (requireActivity() as? com.example.driverrewards.MainActivity)?.refreshPointsDisplay()
                    // Refresh profile
                    profileViewModel.refreshProfile()
                    // Navigate back
                    findNavController().navigateUp()
                } else {
                    Toast.makeText(requireContext(), response.message ?: "Failed to place re-order", Toast.LENGTH_LONG).show()
                    binding.checkoutButton.isEnabled = true
                    binding.checkoutButton.text = "Place Order"
                }
            } catch (e: Exception) {
                android.util.Log.e("CheckoutFragment", "Error processing re-order checkout: ${e.message}", e)
                Toast.makeText(requireContext(), "Error processing re-order: ${e.message}", Toast.LENGTH_LONG).show()
                binding.checkoutButton.isEnabled = true
                binding.checkoutButton.text = "Place Order"
            }
        }
    }
    
    private fun validateInputs(
        firstName: String,
        lastName: String,
        shippingStreet: String,
        shippingCity: String,
        shippingState: String,
        shippingPostal: String,
        shippingCountry: String
    ): Boolean {
        var isValid = true
        
        // Clear previous errors
        binding.firstNameLayout.error = null
        binding.lastNameLayout.error = null
        binding.shippingStreetLayout.error = null
        binding.shippingCityLayout.error = null
        binding.shippingStateLayout.error = null
        binding.shippingPostalLayout.error = null
        binding.shippingCountryLayout.error = null
        
        // Validate first name
        if (TextUtils.isEmpty(firstName)) {
            binding.firstNameLayout.error = "First name is required"
            isValid = false
        }
        
        // Validate last name
        if (TextUtils.isEmpty(lastName)) {
            binding.lastNameLayout.error = "Last name is required"
            isValid = false
        }
        
        // Validate street address
        if (TextUtils.isEmpty(shippingStreet)) {
            binding.shippingStreetLayout.error = "Street address is required"
            isValid = false
        }
        
        // Validate city
        if (TextUtils.isEmpty(shippingCity)) {
            binding.shippingCityLayout.error = "City is required"
            isValid = false
        }
        
        // Validate state
        if (TextUtils.isEmpty(shippingState)) {
            binding.shippingStateLayout.error = "State/Province is required"
            isValid = false
        }
        
        // Validate postal code
        if (TextUtils.isEmpty(shippingPostal)) {
            binding.shippingPostalLayout.error = "Postal code is required"
            isValid = false
        }
        
        // Validate country
        if (TextUtils.isEmpty(shippingCountry)) {
            binding.shippingCountryLayout.error = "Country is required"
            isValid = false
        }
        
        return isValid
    }
    
    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

