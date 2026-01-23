package com.example.driverrewards.ui.profile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.MediaStore
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.fragment.findNavController
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentProfileBinding
import com.example.driverrewards.network.AuthService
import com.example.driverrewards.utils.SessionManager
import com.bumptech.glide.Glide
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.text.SimpleDateFormat
import java.util.*
import android.webkit.MimeTypeMap

class ProfileFragment : Fragment() {

    private var _binding: FragmentProfileBinding? = null
    private val binding get() = _binding!!
    private lateinit var sessionManager: SessionManager
    private lateinit var profileViewModel: ProfileViewModel
    private lateinit var authService: AuthService
    private lateinit var profileService: com.example.driverrewards.network.ProfileService
    
    private var cameraImageUri: Uri? = null
    private var currentCameraImageFile: File? = null
    
    // Image picker launcher
    private val imagePickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == android.app.Activity.RESULT_OK) {
            result.data?.data?.let { uri ->
                handleImageSelection(uri)
            }
        }
    }
    
    private val cameraLauncher = registerForActivityResult(
        ActivityResultContracts.TakePicture()
    ) { success ->
        if (success) {
            val cleanupFile = currentCameraImageFile
            cameraImageUri?.let { uri ->
                handleImageSelection(uri, cleanupFile)
            } ?: cleanupFile?.delete()
        } else {
            currentCameraImageFile?.delete()
        }
        currentCameraImageFile = null
        cameraImageUri = null
    }
    
    private val cameraPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (isGranted) {
            openCamera()
        } else {
            Toast.makeText(
                requireContext(),
                "Camera permission is required to take a new profile picture",
                Toast.LENGTH_LONG
            ).show()
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater,
        container: ViewGroup?,
        savedInstanceState: Bundle?
    ): View {
        _binding = FragmentProfileBinding.inflate(inflater, container, false)
        val root: View = binding.root

        sessionManager = SessionManager(requireContext())
        profileViewModel = ViewModelProvider(requireActivity())[ProfileViewModel::class.java]
        authService = AuthService()
        profileService = com.example.driverrewards.network.ProfileService()
        
        // Setup observers
        setupObservers()
        
        // Setup profile image click listener
        setupProfileImageClickListener()
        
        // Setup dark mode switch
        setupDarkModeSwitch()
        
        // Setup MFA switch
        setupMfaSwitch()
        
        // Setup profile card click listener
        setupProfileCardClickListener()
        
        // Setup account actions
        setupAccountActions()
        
        // Load profile data
        profileViewModel.loadProfile()

        return root
    }
    
    private fun setupObservers() {
        profileViewModel.profileData.observe(viewLifecycleOwner) { profileData ->
            profileData?.let {
                updateProfileSummary(it)
            }
        }
        
        profileViewModel.isLoading.observe(viewLifecycleOwner) { isLoading ->
            binding.progressBar.visibility = if (isLoading) View.VISIBLE else View.GONE
        }
        
        profileViewModel.errorMessage.observe(viewLifecycleOwner) { errorMessage ->
            errorMessage?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_LONG).show()
                
                // If session expired, log out and navigate to login
                if (it.contains("Session expired", ignoreCase = true) || 
                    it.contains("Not authenticated", ignoreCase = true)) {
                    // Clear session and navigate to login
                    sessionManager.logout()
                    requireActivity().finish()
                }
            }
        }
    }
    
    private fun setupProfileImageClickListener() {
        binding.profileImageView.setOnClickListener {
            showImageSourceDialog()
        }
    }
    
    private fun showImageSourceDialog() {
        val options = arrayOf("Choose from gallery", "Take a photo")
        AlertDialog.Builder(requireContext())
            .setTitle("Update Profile Picture")
            .setItems(options) { dialog, which ->
                when (which) {
                    0 -> openImagePicker()
                    1 -> checkCameraPermissionAndOpenCamera()
                }
                dialog.dismiss()
            }
            .show()
    }

    private fun checkCameraPermissionAndOpenCamera() {
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED) {
            openCamera()
        } else {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }
    
    private fun openCamera() {
        try {
            val imageFile = createImageFile()
            currentCameraImageFile = imageFile
            val imageUri = FileProvider.getUriForFile(
                requireContext(),
                "${requireContext().packageName}.fileprovider",
                imageFile
            )
            cameraImageUri = imageUri
            cameraLauncher.launch(imageUri)
        } catch (e: IOException) {
            Toast.makeText(
                requireContext(),
                "Unable to launch camera: ${e.message}",
                Toast.LENGTH_LONG
            ).show()
        }
    }
    
    private fun createImageFile(): File {
        val storageDir = File(requireContext().cacheDir, "camera_images").apply {
            if (!exists()) mkdirs()
        }
        val timeStamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
        return File.createTempFile("profile_image_$timeStamp", ".jpg", storageDir)
    }
    
    private fun openImagePicker() {
        val intent = Intent(Intent.ACTION_PICK, MediaStore.Images.Media.EXTERNAL_CONTENT_URI).apply {
            type = "image/*"
            putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("image/jpeg", "image/jpg", "image/png", "image/webp", "image/x-icon", "image/ico"))
        }
        imagePickerLauncher.launch(intent)
    }
    
    private fun handleImageSelection(uri: Uri, cleanupFile: File? = null) {
        viewLifecycleOwner.lifecycleScope.launch(Dispatchers.IO) {
            var tempOutputFile: File? = null
            try {
                val extension = getFileExtension(uri)
                val allowedExtensions = setOf("jpg", "jpeg", "png", "webp", "ico")
                
                if (extension !in allowedExtensions) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(
                            requireContext(),
                            "Invalid file type. Please select JPG, JPEG, PNG, WEBP, or ICO image.",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                    return@launch
                }
                
                tempOutputFile = File.createTempFile("profile_image_", ".$extension", requireContext().cacheDir)
                val inputStream: InputStream? = requireContext().contentResolver.openInputStream(uri)
                if (inputStream == null) {
                    throw IllegalArgumentException("Unable to read selected image.")
                }
                inputStream.use { input ->
                    FileOutputStream(tempOutputFile!!).use { output ->
                        input.copyTo(output)
                    }
                }
                
                withContext(Dispatchers.Main) {
                    binding.progressBar.visibility = View.VISIBLE
                }
                
                val response = profileService.uploadProfilePicture(tempOutputFile!!)
                
                withContext(Dispatchers.Main) {
                    binding.progressBar.visibility = View.GONE
                    
                    if (response.success) {
                        Toast.makeText(
                            requireContext(),
                            response.message ?: "Profile picture updated successfully",
                            Toast.LENGTH_SHORT
                        ).show()
                        
                        profileViewModel.refreshProfile()
                    } else {
                        Toast.makeText(
                            requireContext(),
                            response.message ?: "Failed to upload profile picture",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    binding.progressBar.visibility = View.GONE
                    Toast.makeText(
                        requireContext(),
                        "Error processing image: ${e.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
            } finally {
                tempOutputFile?.delete()
                cleanupFile?.delete()
            }
        }
    }
    
    private fun getFileName(uri: Uri): String? {
        var result: String? = null
        if (uri.scheme == "content") {
            requireContext().contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val nameIndex = cursor.getColumnIndex(MediaStore.Images.Media.DISPLAY_NAME)
                    if (nameIndex >= 0) {
                        result = cursor.getString(nameIndex)
                    }
                }
            }
        }
        if (result == null) {
            result = uri.path?.let {
                val cut = it.lastIndexOf('/')
                if (cut != -1) {
                    it.substring(cut + 1)
                } else {
                    it
                }
            }
        }
        return result
    }
    
    private fun getFileExtension(uri: Uri): String {
        val nameExtension = getFileName(uri)
            ?.substringAfterLast('.', "")
            ?.lowercase()
            ?.takeIf { it.isNotBlank() }
        if (nameExtension != null) {
            return nameExtension
        }
        val mimeType = requireContext().contentResolver.getType(uri)
        return mimeType?.let { MimeTypeMap.getSingleton().getExtensionFromMimeType(it) }?.lowercase()
            ?: "jpg"
    }
    
    private fun updateProfileSummary(profileData: com.example.driverrewards.network.ProfileData) {
        android.util.Log.d("ProfileFragment", "===== UPDATING PROFILE SUMMARY =====")
        android.util.Log.d("ProfileFragment", "Profile data received:")
        android.util.Log.d("ProfileFragment", "  - pointsBalance: ${profileData.pointsBalance}")
        android.util.Log.d("ProfileFragment", "  - sponsorCompany: ${profileData.sponsorCompany}")
        android.util.Log.d("ProfileFragment", "  - driverId: ${profileData.driverId}")
        
        // Load profile picture
        profileData.profileImageURL?.let { imageUrl ->
            // Check if this is the default avatar path - use local resource instead
            if (imageUrl.contains("/static/img/default_avatar.svg") || imageUrl.endsWith("default_avatar.svg")) {
                binding.profileImageView.setImageResource(R.drawable.default_avatar)
            } else {
                // Construct full URL if it's a relative path
                val fullUrl = if (imageUrl.startsWith("http://") || imageUrl.startsWith("https://")) {
                    imageUrl
                } else {
                    "${com.example.driverrewards.network.NetworkClient.baseUrl}$imageUrl"
                }
                Glide.with(requireContext())
                    .load(fullUrl)
                    .circleCrop()
                    .placeholder(R.drawable.default_avatar)
                    .error(R.drawable.default_avatar)
                    .into(binding.profileImageView)
            }
        } ?: run {
            // If no profile image URL, set a default placeholder
            binding.profileImageView.setImageResource(R.drawable.default_avatar)
        }
        
        // Update driver name
        val displayName = profileData.wholeName ?: 
            "${profileData.firstName ?: ""} ${profileData.lastName ?: ""}".trim().takeIf { it.isNotBlank() } ?: 
            profileData.username
        binding.driverNameText.text = displayName
        
        // Update points balance (large and prominent)
        binding.pointsBalanceText.text = profileData.pointsBalance.toString()
        android.util.Log.d("ProfileFragment", "Updated points balance display: ${profileData.pointsBalance}")
        
        // Update member since date
        profileData.memberSince?.let { memberSince ->
            try {
                val inputFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
                val outputFormat = SimpleDateFormat("MMM yyyy", Locale.getDefault())
                val date = inputFormat.parse(memberSince)
                binding.memberSinceText.text = "Member since ${outputFormat.format(date!!)}"
            } catch (e: Exception) {
                binding.memberSinceText.text = "Member since ${memberSince.substring(0, 7)}"
            }
        } ?: run {
            binding.memberSinceText.text = "Member since unknown"
        }
        
        // Update sponsor company if available
        profileData.sponsorCompany?.let { sponsor ->
            binding.sponsorCompanyText.text = "Sponsored by $sponsor"
            binding.sponsorCompanyText.visibility = View.VISIBLE
            android.util.Log.d("ProfileFragment", "Updated sponsor company display: $sponsor")
        } ?: run {
            binding.sponsorCompanyText.visibility = View.GONE
            android.util.Log.w("ProfileFragment", "WARNING: sponsorCompany is null, hiding sponsor text")
        }
        android.util.Log.d("ProfileFragment", "===== END UPDATE PROFILE SUMMARY =====")
    }
    
    private fun setupProfileCardClickListener() {
        binding.profileCard.setOnClickListener {
            try {
                android.util.Log.d("ProfileFragment", "Profile card clicked, attempting navigation")
                findNavController().navigate(R.id.navigation_profile_detail)
                android.util.Log.d("ProfileFragment", "Navigation successful")
            } catch (e: Exception) {
                // Log the error for debugging
                android.util.Log.e("ProfileFragment", "Navigation error: ${e.message}", e)
                e.printStackTrace()
            }
        }
        
        // Add click listener to points balance text
        binding.pointsBalanceText.setOnClickListener {
            try {
                android.util.Log.d("ProfileFragment", "Points balance clicked, navigating to points detail")
                findNavController().navigate(R.id.action_profile_to_points_detail)
            } catch (e: Exception) {
                android.util.Log.e("ProfileFragment", "Error navigating to points detail: ${e.message}", e)
            }
        }
    }
    
    private fun setupDarkModeSwitch() {
        // Set initial state
        binding.darkModeSwitch.isChecked = sessionManager.isDarkModeEnabled()
        
        // Handle switch changes
        binding.darkModeSwitch.setOnCheckedChangeListener { _, isChecked ->
            sessionManager.setDarkMode(isChecked)
            applyDarkMode(isChecked)
        }
    }
    
    private fun setupMfaSwitch() {
        // Remove any existing listener first to prevent triggering during setup
        binding.mfaSwitch.setOnCheckedChangeListener(null)
        
        // Load current MFA status
        viewLifecycleOwner.lifecycleScope.launch(Dispatchers.IO) {
            val status = authService.getMfaStatus()
            withContext(Dispatchers.Main) {
                // Set switch state without triggering listener
                binding.mfaSwitch.setOnCheckedChangeListener(null)
                binding.mfaSwitch.isChecked = status.mfaEnabled == true
                // Now set the listener after the state is set
                binding.mfaSwitch.setOnCheckedChangeListener { _, isChecked ->
                    // Temporarily remove listener to prevent recursive calls
                    binding.mfaSwitch.setOnCheckedChangeListener(null)
                    
                    if (isChecked) {
                        showEnableMfaPasswordDialog()
                    } else {
                        showDisableMfaDialog()
                    }
                }
            }
        }
    }
    
    private fun setupAccountActions() {
        // Change password button
        binding.changePasswordButton.setOnClickListener {
            showChangePasswordDialog()
        }
        
        // Update address button
        binding.updateAddressButton.setOnClickListener {
            showUpdateAddressDialog()
        }
    }
    
    private fun showChangePasswordDialog() {
        val dialog = ChangePasswordDialog.newInstance()
        dialog.setOnPasswordChangedListener {
            // Password was changed successfully
            Toast.makeText(requireContext(), "Password updated successfully!", Toast.LENGTH_SHORT).show()
        }
        dialog.show(parentFragmentManager, "ChangePasswordDialog")
    }
    
    private fun showUpdateAddressDialog() {
        val currentAddress = profileViewModel.profileData.value?.shippingAddress
        val dialog = UpdateAddressDialog.newInstance(currentAddress)
        dialog.setOnAddressUpdatedListener {
            // Address was updated successfully, refresh profile data
            profileViewModel.refreshProfile()
            Toast.makeText(requireContext(), "Address updated successfully!", Toast.LENGTH_SHORT).show()
        }
        dialog.show(parentFragmentManager, "UpdateAddressDialog")
    }
    
    private fun applyDarkMode(isDarkMode: Boolean) {
        val mode = if (isDarkMode) {
            AppCompatDelegate.MODE_NIGHT_YES
        } else {
            AppCompatDelegate.MODE_NIGHT_NO
        }
        AppCompatDelegate.setDefaultNightMode(mode)
    }
    
    private fun showEnableMfaPasswordDialog() {
        // First check if MFA is already enabled - if so, don't show the dialog
        viewLifecycleOwner.lifecycleScope.launch(Dispatchers.IO) {
            val status = authService.getMfaStatus()
            withContext(Dispatchers.Main) {
                if (status.mfaEnabled == true) {
                    // MFA is already enabled, just reset the switch to on and re-setup listener
                    binding.mfaSwitch.setOnCheckedChangeListener(null)
                    binding.mfaSwitch.isChecked = true
                    setupMfaSwitch()
                    return@withContext
                }
                
                // MFA is not enabled, proceed with showing the dialog
                val dialogView = layoutInflater.inflate(R.layout.dialog_password_entry, null)
                val dialog = android.app.AlertDialog.Builder(requireContext())
                    .setView(dialogView)
                    .setCancelable(true)
                    .create()
                
                val titleTextView = dialogView.findViewById<android.widget.TextView>(R.id.passwordTitle)
                val descriptionTextView = dialogView.findViewById<android.widget.TextView>(R.id.passwordDescription)
                val passwordEditText = dialogView.findViewById<com.google.android.material.textfield.TextInputEditText>(R.id.passwordEditText)
                val continueButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.passwordContinueButton)
                val cancelButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.passwordCancelButton)
                val errorMessage = dialogView.findViewById<android.widget.TextView>(R.id.passwordErrorMessage)
                
                titleTextView?.text = "Enable MFA"
                descriptionTextView?.text = "Enter your password to enable two-factor authentication"
                
                continueButton?.setOnClickListener {
                    val password = passwordEditText?.text?.toString() ?: ""
                    if (password.isEmpty()) {
                        errorMessage?.text = "Password is required"
                        errorMessage?.visibility = android.view.View.VISIBLE
                        return@setOnClickListener
                    }
                    
                    dialog.dismiss()
                    showEnableMfaDialog(password)
                }
                
                cancelButton?.setOnClickListener {
                    dialog.dismiss()
                    binding.mfaSwitch.setOnCheckedChangeListener(null)
                    binding.mfaSwitch.isChecked = false
                    setupMfaSwitch()
                }
                
                dialog.show()
            }
        }
    }
    
    private fun showEnableMfaDialog(password: String) {
        viewLifecycleOwner.lifecycleScope.launch(Dispatchers.IO) {
            val response = authService.enableMfa(password)
            withContext(Dispatchers.Main) {
                if (response.success && response.qrUri != null) {
                    showEnableMfaQrDialog(response.qrUri, response.secret ?: "")
                } else {
                    Toast.makeText(requireContext(), response.message ?: "Failed to enable MFA", Toast.LENGTH_LONG).show()
                    binding.mfaSwitch.isChecked = false
                    setupMfaSwitch()
                }
            }
        }
    }
    
    private fun showEnableMfaQrDialog(qrUri: String, secret: String) {
        val dialogView = layoutInflater.inflate(R.layout.dialog_enable_mfa, null)
        val dialog = android.app.AlertDialog.Builder(requireContext())
            .setView(dialogView)
            .setCancelable(false)
            .create()
        
        val qrCodeImageView = dialogView.findViewById<android.widget.ImageView>(R.id.qrCodeImageView)
        val secretLabel = dialogView.findViewById<android.widget.TextView>(R.id.secretLabel)
        val secretTextView = dialogView.findViewById<android.widget.TextView>(R.id.secretTextView)
        val verifyCodeEditText = dialogView.findViewById<com.google.android.material.textfield.TextInputEditText>(R.id.verifyCodeEditText)
        val progressBar = dialogView.findViewById<android.widget.ProgressBar>(R.id.enableMfaProgressBar)
        val errorMessage = dialogView.findViewById<android.widget.TextView>(R.id.enableMfaErrorMessage)
        val verifyButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.enableMfaVerifyButton)
        val cancelButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.enableMfaCancelButton)
        
        val qrImageUrl = "https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${android.net.Uri.encode(qrUri)}"
        Glide.with(requireContext())
            .load(qrImageUrl)
            .into(qrCodeImageView)
        
        secretLabel?.visibility = android.view.View.VISIBLE
        secretTextView?.text = secret
        secretTextView?.visibility = android.view.View.VISIBLE
        
        verifyButton?.setOnClickListener {
            val code = verifyCodeEditText?.text?.toString()?.trim() ?: ""
            if (code.isEmpty()) {
                errorMessage?.text = "Please enter the 6-digit code"
                errorMessage?.visibility = android.view.View.VISIBLE
                return@setOnClickListener
            }
            
            verifyButton.isEnabled = false
            progressBar?.visibility = android.view.View.VISIBLE
            errorMessage?.visibility = android.view.View.GONE
            
            viewLifecycleOwner.lifecycleScope.launch(Dispatchers.IO) {
                val response = authService.confirmMfa(code)
                withContext(Dispatchers.Main) {
                    progressBar?.visibility = android.view.View.GONE
                    verifyButton.isEnabled = true
                    
                    if (response.success) {
                        dialog.dismiss()
                        if (response.recoveryCodes != null && response.recoveryCodes.isNotEmpty()) {
                            showRecoveryCodesDialog(response.recoveryCodes)
                        }
                        setupMfaSwitch()
                        Toast.makeText(requireContext(), "MFA enabled successfully!", Toast.LENGTH_SHORT).show()
                    } else {
                        errorMessage?.text = response.message ?: "Invalid code. Try again."
                        errorMessage?.visibility = android.view.View.VISIBLE
                    }
                }
            }
        }
        
        cancelButton?.setOnClickListener {
            dialog.dismiss()
            binding.mfaSwitch.isChecked = false
            setupMfaSwitch()
        }
        
        dialog.show()
    }
    
    private fun showRecoveryCodesDialog(codes: List<String>) {
        val dialogView = layoutInflater.inflate(R.layout.dialog_recovery_codes, null)
        val dialog = android.app.AlertDialog.Builder(requireContext())
            .setView(dialogView)
            .setCancelable(false)
            .create()
        
        val codesTextView = dialogView.findViewById<android.widget.TextView>(R.id.recoveryCodesTextView)
        val gotItButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.recoveryCodesGotItButton)
        
        codesTextView?.text = codes.joinToString("\n")
        
        gotItButton?.setOnClickListener {
            dialog.dismiss()
        }
        
        dialog.show()
    }
    
    private fun showDisableMfaDialog() {
        val dialogView = layoutInflater.inflate(R.layout.dialog_disable_mfa, null)
        val dialog = android.app.AlertDialog.Builder(requireContext())
            .setView(dialogView)
            .setCancelable(true)
            .create()
        
        val passwordEditText = dialogView.findViewById<com.google.android.material.textfield.TextInputEditText>(R.id.disableMfaPasswordEditText)
        val progressBar = dialogView.findViewById<android.widget.ProgressBar>(R.id.disableMfaProgressBar)
        val errorMessage = dialogView.findViewById<android.widget.TextView>(R.id.disableMfaErrorMessage)
        val confirmButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.disableMfaConfirmButton)
        val cancelButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.disableMfaCancelButton)
        
        confirmButton?.setOnClickListener {
            val password = passwordEditText?.text?.toString() ?: ""
            if (password.isEmpty()) {
                errorMessage?.text = "Password is required"
                errorMessage?.visibility = android.view.View.VISIBLE
                return@setOnClickListener
            }
            
            confirmButton.isEnabled = false
            progressBar?.visibility = android.view.View.VISIBLE
            errorMessage?.visibility = android.view.View.GONE
            
            viewLifecycleOwner.lifecycleScope.launch(Dispatchers.IO) {
                val response = authService.disableMfa(password)
                withContext(Dispatchers.Main) {
                    progressBar?.visibility = android.view.View.GONE
                    confirmButton.isEnabled = true
                    
                    if (response.success) {
                        dialog.dismiss()
                        binding.mfaSwitch.isChecked = false
                        setupMfaSwitch()
                        Toast.makeText(requireContext(), "MFA disabled successfully", Toast.LENGTH_SHORT).show()
                    } else {
                        errorMessage?.text = response.message ?: "Failed to disable MFA"
                        errorMessage?.visibility = android.view.View.VISIBLE
                    }
                }
            }
        }
        
        cancelButton?.setOnClickListener {
            dialog.dismiss()
            binding.mfaSwitch.isChecked = true
            setupMfaSwitch()
        }
        
        dialog.show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
