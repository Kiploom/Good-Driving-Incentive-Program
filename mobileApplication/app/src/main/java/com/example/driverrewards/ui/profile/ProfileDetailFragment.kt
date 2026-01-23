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
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.fragment.app.Fragment
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.fragment.findNavController
import com.example.driverrewards.R
import com.example.driverrewards.databinding.FragmentProfileDetailBinding
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

class ProfileDetailFragment : Fragment() {

    private var _binding: FragmentProfileDetailBinding? = null
    private val binding get() = _binding!!
    private lateinit var sessionManager: SessionManager
    private lateinit var profileViewModel: ProfileViewModel
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
        try {
            android.util.Log.d("ProfileDetailFragment", "Creating view")
            _binding = FragmentProfileDetailBinding.inflate(inflater, container, false)
            val root: View = binding.root
            android.util.Log.d("ProfileDetailFragment", "Binding created successfully")

            sessionManager = SessionManager(requireContext())
            profileViewModel = ViewModelProvider(requireActivity())[ProfileViewModel::class.java]
            profileService = com.example.driverrewards.network.ProfileService()
            android.util.Log.d("ProfileDetailFragment", "SessionManager and ViewModel created")
            
            // Setup observers
            setupObservers()
            
            // Setup click listeners
            setupClickListeners()
            
            // Setup profile image click listener
            setupProfileImageClickListener()
            
            // Load profile data
            profileViewModel.loadProfile()
            android.util.Log.d("ProfileDetailFragment", "View created successfully")

            return root
        } catch (e: Exception) {
            android.util.Log.e("ProfileDetailFragment", "Error creating view: ${e.message}", e)
            e.printStackTrace()
            throw e
        }
    }

    private fun setupObservers() {
        profileViewModel.profileData.observe(viewLifecycleOwner) { profileData ->
            profileData?.let {
                displayUserInfo(it)
            }
        }
        
        profileViewModel.isLoading.observe(viewLifecycleOwner) { isLoading ->
            binding.progressBar.visibility = if (isLoading) View.VISIBLE else View.GONE
        }
        
        profileViewModel.errorMessage.observe(viewLifecycleOwner) { errorMessage ->
            errorMessage?.let {
                Toast.makeText(requireContext(), it, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun setupClickListeners() {
        // Make points balance clickable to navigate to points detail
        binding.pointsBalanceText.setOnClickListener {
            findNavController().navigate(R.id.action_profile_detail_to_points_detail)
        }
        
        // Also make the summary card clickable (the entire card area around points)
        binding.summaryCard.setOnClickListener {
            findNavController().navigate(R.id.action_profile_detail_to_points_detail)
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

    private fun displayUserInfo(profileData: com.example.driverrewards.network.ProfileData) {
        try {
            android.util.Log.d("ProfileDetailFragment", "Starting to display user info")
            android.util.Log.d("ProfileDetailFragment", "Age: ${profileData.age} (type: ${profileData.age?.javaClass?.simpleName})")
            android.util.Log.d("ProfileDetailFragment", "Gender: \"${profileData.gender}\" (type: ${profileData.gender?.javaClass?.simpleName})")
            binding.apply {
                // Load profile picture
                profileData.profileImageURL?.let { imageUrl ->
                    // Check if this is the default avatar path - use local resource instead
                    if (imageUrl.contains("/static/img/default_avatar.svg") || imageUrl.endsWith("default_avatar.svg")) {
                        profileImageView.setImageResource(R.drawable.default_avatar)
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
                            .into(profileImageView)
                    }
                } ?: run {
                    // If no profile image URL, set a default placeholder
                    profileImageView.setImageResource(R.drawable.default_avatar)
                }
                
                // Display basic account information
                emailText.setText(profileData.email)
                usernameText.setText(profileData.username)
                accountIdText.setText(profileData.accountId)
                driverIdText.setText(profileData.driverId)
                
                // Display age
                profileData.age?.let { age ->
                    ageText.setText(age.toString())
                } ?: run {
                    ageText.setText("Not provided")
                }
                
                // Display gender
                profileData.gender?.let { gender ->
                    val genderDisplayText = when (gender.uppercase()) {
                        "M" -> "Male"
                        "F" -> "Female"
                        "O" -> "Other"
                        else -> gender
                    }
                    genderText.setText(genderDisplayText)
                } ?: run {
                    genderText.setText("Not provided")
                }
                
                // Display driver name
                val displayName = profileData.wholeName ?: 
                    "${profileData.firstName ?: ""} ${profileData.lastName ?: ""}".trim().takeIf { it.isNotBlank() } ?: 
                    profileData.username
                driverNameText.text = displayName
                
                // Display points balance
                pointsBalanceText.text = profileData.pointsBalance.toString()
                
                // Display member since date
                profileData.memberSince?.let { memberSince ->
                    try {
                        val inputFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
                        val outputFormat = SimpleDateFormat("MMM dd, yyyy", Locale.getDefault())
                        val date = inputFormat.parse(memberSince)
                        memberSinceText.text = outputFormat.format(date!!)
                    } catch (e: Exception) {
                        memberSinceText.text = memberSince.substring(0, 10)
                    }
                } ?: run {
                    memberSinceText.text = "Unknown"
                }
                
                // Display shipping address
                shippingAddressText.setText(profileData.shippingAddress ?: "Not provided")
                
                // Display license information if available
                if (profileData.licenseNumber != null) {
                    licenseNumberText.setText(profileData.licenseNumber)
                    licenseNumberLabel.visibility = View.VISIBLE
                    licenseNumberText.visibility = View.VISIBLE
                } else {
                    licenseNumberLabel.visibility = View.GONE
                    licenseNumberText.visibility = View.GONE
                }
                
                if (profileData.licenseIssueDate != null) {
                    licenseIssueDateText.setText(profileData.licenseIssueDate)
                    licenseIssueDateLabel.visibility = View.VISIBLE
                    licenseIssueDateText.visibility = View.VISIBLE
                } else {
                    licenseIssueDateLabel.visibility = View.GONE
                    licenseIssueDateText.visibility = View.GONE
                }
                
                if (profileData.licenseExpirationDate != null) {
                    licenseExpirationDateText.setText(profileData.licenseExpirationDate)
                    licenseExpirationDateLabel.visibility = View.VISIBLE
                    licenseExpirationDateText.visibility = View.VISIBLE
                } else {
                    licenseExpirationDateLabel.visibility = View.GONE
                    licenseExpirationDateText.visibility = View.GONE
                }
                
                // Display sponsor company name
                android.util.Log.d("ProfileDetailFragment", "===== UPDATING SPONSOR COMPANY DISPLAY =====")
                android.util.Log.d("ProfileDetailFragment", "profileData.sponsorCompany: ${profileData.sponsorCompany}")
                if (profileData.sponsorCompany != null) {
                    sponsorCompanyText.setText(profileData.sponsorCompany)
                    sponsorCompanyLabel.visibility = View.VISIBLE
                    sponsorCompanyText.visibility = View.VISIBLE
                    android.util.Log.d("ProfileDetailFragment", "Displaying sponsor company: ${profileData.sponsorCompany}")
                    android.util.Log.d("ProfileDetailFragment", "This should match the ACTIVE sponsor environment")
                } else {
                    sponsorCompanyLabel.visibility = View.GONE
                    sponsorCompanyText.visibility = View.GONE
                    android.util.Log.w("ProfileDetailFragment", "WARNING: sponsorCompany is null, hiding sponsor company display")
                }
                
                android.util.Log.d("ProfileDetailFragment", "User info displayed successfully")
            }
        } catch (e: Exception) {
            android.util.Log.e("ProfileDetailFragment", "Error displaying user info: ${e.message}", e)
            e.printStackTrace()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
