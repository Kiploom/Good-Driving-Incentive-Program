package com.example.driverrewards.ui.cart

import android.os.Bundle
import android.text.TextUtils
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.DialogFragment
import com.example.driverrewards.databinding.DialogCheckoutBinding

class CheckoutDialog : DialogFragment() {
    
    private var _binding: DialogCheckoutBinding? = null
    private val binding get() = _binding!!
    
    private var totalPoints: Int = 0
    private var itemCount: Int = 0
    private var driverPoints: Int = 0
    private var onCheckoutSuccessListener: ((String, String) -> Unit)? = null
    
    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = DialogCheckoutBinding.inflate(inflater, container, false)
        return binding.root
    }
    
    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        
        // Set order summary
        binding.orderItemsSummary.text = "Items: $itemCount"
        binding.orderTotalPoints.text = "Total: $totalPoints pts"
        binding.orderDriverPoints.text = "Balance: $driverPoints pts"
        
        setupClickListeners()
    }
    
    private fun setupClickListeners() {
        binding.cancelButton.setOnClickListener {
            dismiss()
        }
        
        binding.checkoutButton.setOnClickListener {
            processCheckout()
        }
    }
    
    private fun processCheckout() {
        val firstName = binding.firstNameText.text?.toString()?.trim() ?: ""
        val lastName = binding.lastNameText.text?.toString()?.trim() ?: ""
        val email = binding.emailText.text?.toString()?.trim() ?: ""
        val shippingStreet = binding.shippingStreetText.text?.toString()?.trim() ?: ""
        val shippingCity = binding.shippingCityText.text?.toString()?.trim() ?: ""
        val shippingState = binding.shippingStateText.text?.toString()?.trim() ?: ""
        val shippingPostal = binding.shippingPostalText.text?.toString()?.trim() ?: ""
        val shippingCountry = binding.shippingCountryText.text?.toString()?.trim() ?: ""
        
        // Validate inputs
        if (!validateInputs(firstName, lastName, email, shippingStreet, shippingCity, shippingState, shippingPostal, shippingCountry)) {
            return
        }
        
        // Check terms agreement
        if (!binding.termsCheckbox.isChecked) {
            Toast.makeText(requireContext(), "Please agree to the terms and conditions", Toast.LENGTH_SHORT).show()
            return
        }
        
        // Show loading state
        binding.checkoutButton.isEnabled = false
        binding.checkoutButton.text = "Processing..."
        
        // Get CartViewModel and process checkout
        val cartViewModel = androidx.lifecycle.ViewModelProvider(requireActivity())[CartViewModel::class.java]
        cartViewModel.processCheckout(
            firstName = firstName,
            lastName = lastName,
            email = email,
            shippingStreet = shippingStreet,
            shippingCity = shippingCity,
            shippingState = shippingState,
            shippingPostal = shippingPostal,
            shippingCountry = shippingCountry,
            shippingCostPoints = 0 // Default shipping cost, can be calculated if needed
        )
        
        // Observe checkout success
        cartViewModel.checkoutSuccess.observe(viewLifecycleOwner, androidx.lifecycle.Observer { result ->
            result?.let {
                Toast.makeText(requireContext(), "Order placed successfully! Order #${it.orderNumber}", Toast.LENGTH_LONG).show()
                onCheckoutSuccessListener?.invoke(it.orderId, it.orderNumber)
                dismiss()
            }
        })
        
        // Observe errors
        cartViewModel.errorMessage.observe(viewLifecycleOwner, androidx.lifecycle.Observer { error ->
            error?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_LONG).show()
                binding.checkoutButton.isEnabled = true
                binding.checkoutButton.text = "Place Order"
                cartViewModel.clearError()
            }
        })
        
        // Observe loading state
        cartViewModel.isLoading.observe(viewLifecycleOwner, androidx.lifecycle.Observer { isLoading ->
            if (!isLoading && binding.checkoutButton.text == "Processing...") {
                binding.checkoutButton.isEnabled = true
                binding.checkoutButton.text = "Place Order"
            }
        })
    }
    
    private fun validateInputs(
        firstName: String,
        lastName: String,
        email: String,
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
        binding.emailLayout.error = null
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
        
        // Validate email
        if (TextUtils.isEmpty(email)) {
            binding.emailLayout.error = "Email is required"
            isValid = false
        } else if (!android.util.Patterns.EMAIL_ADDRESS.matcher(email).matches()) {
            binding.emailLayout.error = "Invalid email address"
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
    
    fun setOrderSummary(totalPoints: Int, itemCount: Int, driverPoints: Int) {
        this.totalPoints = totalPoints
        this.itemCount = itemCount
        this.driverPoints = driverPoints
    }
    
    fun setOnCheckoutSuccessListener(listener: (String, String) -> Unit) {
        onCheckoutSuccessListener = listener
    }
    
    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
    
    companion object {
        fun newInstance(totalPoints: Int, itemCount: Int, driverPoints: Int): CheckoutDialog {
            val dialog = CheckoutDialog()
            dialog.setOrderSummary(totalPoints, itemCount, driverPoints)
            return dialog
        }
    }
}

