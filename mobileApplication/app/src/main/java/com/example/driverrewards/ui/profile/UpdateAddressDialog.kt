package com.example.driverrewards.ui.profile

import android.os.Bundle
import android.text.TextUtils
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.DialogFragment
import com.example.driverrewards.databinding.DialogUpdateAddressBinding
import com.example.driverrewards.network.ProfileService
import com.example.driverrewards.network.UpdateProfileRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class UpdateAddressDialog : DialogFragment() {
    
    private var _binding: DialogUpdateAddressBinding? = null
    private val binding get() = _binding!!
    
    private var onAddressUpdatedListener: (() -> Unit)? = null
    private var currentAddress: String? = null
    
    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = DialogUpdateAddressBinding.inflate(inflater, container, false)
        return binding.root
    }
    
    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        
        setupClickListeners()
        populateCurrentAddress()
    }
    
    private fun setupClickListeners() {
        binding.cancelButton.setOnClickListener {
            dismiss()
        }
        
        binding.updateAddressButton.setOnClickListener {
            updateAddress()
        }
    }
    
    private fun populateCurrentAddress() {
        // Parse current address if available
        currentAddress?.let { address ->
            val parts = address.split(",").map { it.trim() }
            
            when (parts.size) {
                1 -> binding.streetText.setText(parts[0])
                2 -> {
                    binding.streetText.setText(parts[0])
                    binding.cityText.setText(parts[1])
                }
                3 -> {
                    binding.streetText.setText(parts[0])
                    binding.cityText.setText(parts[1])
                    binding.stateText.setText(parts[2])
                }
                4 -> {
                    binding.streetText.setText(parts[0])
                    binding.cityText.setText(parts[1])
                    binding.stateText.setText(parts[2])
                    binding.postalText.setText(parts[3])
                }
                5 -> {
                    binding.streetText.setText(parts[0])
                    binding.cityText.setText(parts[1])
                    binding.stateText.setText(parts[2])
                    binding.postalText.setText(parts[3])
                    binding.countryText.setText(parts[4])
                }
            }
        }
    }
    
    private fun updateAddress() {
        val street = binding.streetText.text?.toString()?.trim() ?: ""
        val city = binding.cityText.text?.toString()?.trim() ?: ""
        val state = binding.stateText.text?.toString()?.trim() ?: ""
        val postal = binding.postalText.text?.toString()?.trim() ?: ""
        val country = binding.countryText.text?.toString()?.trim() ?: ""
        
        // Validate inputs
        if (!validateInputs(street, city, state, postal, country)) {
            return
        }
        
        // Build address string
        val addressParts = mutableListOf<String>()
        if (street.isNotEmpty()) addressParts.add(street)
        if (city.isNotEmpty()) addressParts.add(city)
        if (state.isNotEmpty()) addressParts.add(state)
        if (postal.isNotEmpty()) addressParts.add(postal)
        if (country.isNotEmpty()) addressParts.add(country)
        
        val fullAddress = addressParts.joinToString(", ")
        
        // Show loading state
        binding.updateAddressButton.isEnabled = false
        binding.updateAddressButton.text = "Updating..."
        
        // Make API call
        CoroutineScope(Dispatchers.Main).launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    ProfileService().updateProfile(
                        UpdateProfileRequest(
                            firstName = null,
                            lastName = null,
                            wholeName = null,
                            shippingAddress = fullAddress,
                            licenseNumber = null,
                            licenseIssueDate = null,
                            licenseExpirationDate = null
                        )
                    )
                }
                
                if (result.success) {
                    Toast.makeText(requireContext(), "Address updated successfully!", Toast.LENGTH_SHORT).show()
                    onAddressUpdatedListener?.invoke()
                    dismiss()
                } else {
                    Toast.makeText(requireContext(), result.message ?: "Failed to update address", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                // Reset button state
                binding.updateAddressButton.isEnabled = true
                binding.updateAddressButton.text = "Update Address"
            }
        }
    }
    
    private fun validateInputs(street: String, city: String, state: String, postal: String, country: String): Boolean {
        var isValid = true
        
        // Clear previous errors
        binding.streetLayout.error = null
        binding.cityLayout.error = null
        binding.stateLayout.error = null
        binding.postalLayout.error = null
        binding.countryLayout.error = null
        
        // Validate street address (required)
        if (TextUtils.isEmpty(street)) {
            binding.streetLayout.error = "Street address is required"
            isValid = false
        }
        
        // Validate city (required)
        if (TextUtils.isEmpty(city)) {
            binding.cityLayout.error = "City is required"
            isValid = false
        }
        
        // Validate state (required)
        if (TextUtils.isEmpty(state)) {
            binding.stateLayout.error = "State/Province is required"
            isValid = false
        }
        
        // Validate postal code (required)
        if (TextUtils.isEmpty(postal)) {
            binding.postalLayout.error = "Postal code is required"
            isValid = false
        }
        
        // Country is optional, but if provided, validate it
        if (country.isNotEmpty() && country.length < 2) {
            binding.countryLayout.error = "Country name must be at least 2 characters"
            isValid = false
        }
        
        return isValid
    }
    
    fun setCurrentAddress(address: String?) {
        currentAddress = address
    }
    
    fun setOnAddressUpdatedListener(listener: () -> Unit) {
        onAddressUpdatedListener = listener
    }
    
    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
    
    companion object {
        fun newInstance(currentAddress: String? = null): UpdateAddressDialog {
            val dialog = UpdateAddressDialog()
            dialog.setCurrentAddress(currentAddress)
            return dialog
        }
    }
}
