package com.example.driverrewards.ui.profile

import android.app.Dialog
import android.content.Context
import android.os.Bundle
import android.text.TextUtils
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.fragment.app.DialogFragment
import com.example.driverrewards.databinding.DialogChangePasswordBinding
import com.example.driverrewards.network.AuthService
import com.example.driverrewards.network.ProfileService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class ChangePasswordDialog : DialogFragment() {
    
    private var _binding: DialogChangePasswordBinding? = null
    private val binding get() = _binding!!
    
    private var onPasswordChangedListener: (() -> Unit)? = null
    
    interface OnPasswordChangedListener {
        fun onPasswordChanged()
    }
    
    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = DialogChangePasswordBinding.inflate(inflater, container, false)
        return binding.root
    }
    
    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        
        setupClickListeners()
    }
    
    private fun setupClickListeners() {
        binding.cancelButton.setOnClickListener {
            dismiss()
        }
        
        binding.changePasswordButton.setOnClickListener {
            changePassword()
        }
    }
    
    private fun changePassword() {
        val currentPassword = binding.currentPasswordText.text?.toString() ?: ""
        val newPassword = binding.newPasswordText.text?.toString() ?: ""
        val confirmPassword = binding.confirmPasswordText.text?.toString() ?: ""
        
        // Validate inputs
        if (!validateInputs(currentPassword, newPassword, confirmPassword)) {
            return
        }
        
        // Show loading state
        binding.changePasswordButton.isEnabled = false
        binding.changePasswordButton.text = "Changing..."
        
        // Make API call
        CoroutineScope(Dispatchers.Main).launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    ProfileService().changePassword(
                        com.example.driverrewards.network.ChangePasswordRequest(
                            currentPassword = currentPassword,
                            newPassword = newPassword
                        )
                    )
                }
                
                if (result.success) {
                    Toast.makeText(requireContext(), "Password changed successfully!", Toast.LENGTH_SHORT).show()
                    onPasswordChangedListener?.invoke()
                    dismiss()
                } else {
                    Toast.makeText(requireContext(), result.message ?: "Failed to change password", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                Toast.makeText(requireContext(), "Error: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                // Reset button state
                binding.changePasswordButton.isEnabled = true
                binding.changePasswordButton.text = "Change Password"
            }
        }
    }
    
    private fun validateInputs(currentPassword: String, newPassword: String, confirmPassword: String): Boolean {
        var isValid = true
        
        // Clear previous errors
        binding.currentPasswordLayout.error = null
        binding.newPasswordLayout.error = null
        binding.confirmPasswordLayout.error = null
        
        // Validate current password
        if (TextUtils.isEmpty(currentPassword)) {
            binding.currentPasswordLayout.error = "Current password is required"
            isValid = false
        }
        
        // Validate new password
        if (TextUtils.isEmpty(newPassword)) {
            binding.newPasswordLayout.error = "New password is required"
            isValid = false
        } else if (newPassword.length < 8) {
            binding.newPasswordLayout.error = "Password must be at least 8 characters"
            isValid = false
        } else if (!isValidPassword(newPassword)) {
            binding.newPasswordLayout.error = "Password must contain letters and numbers"
            isValid = false
        }
        
        // Validate confirm password
        if (TextUtils.isEmpty(confirmPassword)) {
            binding.confirmPasswordLayout.error = "Please confirm your new password"
            isValid = false
        } else if (newPassword != confirmPassword) {
            binding.confirmPasswordLayout.error = "Passwords do not match"
            isValid = false
        }
        
        // Check if new password is same as current
        if (currentPassword == newPassword) {
            binding.newPasswordLayout.error = "New password must be different from current password"
            isValid = false
        }
        
        return isValid
    }
    
    private fun isValidPassword(password: String): Boolean {
        // Check if password contains at least one letter and one number
        val hasLetter = password.any { it.isLetter() }
        val hasDigit = password.any { it.isDigit() }
        return hasLetter && hasDigit
    }
    
    fun setOnPasswordChangedListener(listener: () -> Unit) {
        onPasswordChangedListener = listener
    }
    
    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
    
    companion object {
        fun newInstance(): ChangePasswordDialog {
            return ChangePasswordDialog()
        }
    }
}
