package com.example.driverrewards

import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.lifecycle.lifecycleScope
import com.example.driverrewards.databinding.ActivityLoginBinding
import com.example.driverrewards.network.AuthService
import com.example.driverrewards.utils.BiometricHelper
import com.example.driverrewards.utils.CredentialManager
import com.example.driverrewards.utils.SessionManager
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers

class LoginActivity : AppCompatActivity() {
    
    private lateinit var binding: ActivityLoginBinding
    private lateinit var authService: AuthService
    private lateinit var sessionManager: SessionManager
    private lateinit var credentialManager: CredentialManager
    private lateinit var biometricHelper: BiometricHelper
    
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)
        
        authService = AuthService()
        sessionManager = SessionManager(this)
        credentialManager = CredentialManager(this)
        biometricHelper = BiometricHelper(this)
        
        // Initialize NetworkClient with context
        com.example.driverrewards.network.NetworkClient.initialize(this)
        
        // Apply dark mode setting
        applyDarkModeSetting()
        
        // Check if user is already logged in with valid session
        if (sessionManager.validateSession()) {
            navigateToMain()
            return
        }
        
        setupLoginButton()
        setupBiometricLogin()
    }
    
    private fun applyDarkModeSetting() {
        val isDarkMode = sessionManager.isDarkModeEnabled()
        val mode = if (isDarkMode) {
            AppCompatDelegate.MODE_NIGHT_YES
        } else {
            AppCompatDelegate.MODE_NIGHT_NO
        }
        AppCompatDelegate.setDefaultNightMode(mode)
    }
    
    private fun setupLoginButton() {
        binding.loginButton.setOnClickListener {
            val email = binding.emailEditText.text.toString().trim()
            val password = binding.passwordEditText.text.toString()
            
            if (email.isEmpty() || password.isEmpty()) {
                Toast.makeText(this, "Please enter both email and password", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            
            login(email, password, shouldStoreCredentials = true)
        }
    }
    
    private fun setupBiometricLogin() {
        // Check if biometric is available and credentials are stored
        val hasBiometric = biometricHelper.isBiometricAvailable()
        val hasCredentials = credentialManager.hasStoredCredentials()
        
        if (hasBiometric && hasCredentials) {
            binding.fingerprintButton?.visibility = android.view.View.VISIBLE
            binding.fingerprintButton?.setOnClickListener {
                authenticateWithFingerprint()
            }
        } else {
            binding.fingerprintButton?.visibility = android.view.View.GONE
        }
    }
    
    private fun authenticateWithFingerprint() {
        val credentials = credentialManager.getStoredCredentials()
        if (credentials == null) {
            Toast.makeText(this, "No stored credentials found", Toast.LENGTH_SHORT).show()
            binding.fingerprintButton?.visibility = android.view.View.GONE
            return
        }
        
        val (email, password) = credentials
        
        biometricHelper.authenticate(
            title = "Sign in with Fingerprint",
            subtitle = "Use your fingerprint to sign in to your account",
            negativeButtonText = "Cancel",
            onSuccess = {
                // Fingerprint authentication successful, proceed with login
                login(email, password, shouldStoreCredentials = false)
            },
            onError = { errorMessage ->
                Toast.makeText(this, "Fingerprint authentication failed: $errorMessage", Toast.LENGTH_LONG).show()
            },
            onCancel = {
                // User canceled, do nothing
            }
        )
    }
    
    private fun login(email: String, password: String, shouldStoreCredentials: Boolean = false) {
        binding.loginButton.isEnabled = false
        binding.progressBar.visibility = android.view.View.VISIBLE
        
        println("DEBUG: Starting login process for email: $email")
        
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val result = authService.login(email, password)
                
                println("DEBUG: Login result: success=${result.success}, message=${result.message}")
                
                if (result.success) {
                    // Save session data
                    sessionManager.saveSession(
                        accountId = result.accountId ?: "",
                        driverId = result.driverId ?: "",
                        email = result.email ?: email, // Use email from API response, fallback to input email
                        username = result.username ?: ""
                    )
                    
                    println("DEBUG: Session saved successfully")
                    
                    // If this is a regular login (not fingerprint), ask user if they want to store credentials
                    if (shouldStoreCredentials && biometricHelper.isBiometricAvailable() && !credentialManager.hasStoredCredentials()) {
                        runOnUiThread {
                            askToStoreCredentials(email, password)
                        }
                    } else {
                        runOnUiThread {
                            Toast.makeText(this@LoginActivity, "Login successful!", Toast.LENGTH_SHORT).show()
                            navigateToMain()
                        }
                    }
                } else if (result.mfaRequired == true) {
                    // MFA required - show code entry dialog
                    // Store credentials temporarily for MFA flow
                    runOnUiThread {
                        showMfaDialog(email, password, shouldStoreCredentials)
                    }
                } else {
                    val errorMessage = result.message ?: "Login failed"
                    println("DEBUG: Login failed with message: $errorMessage")
                    runOnUiThread {
                        Toast.makeText(this@LoginActivity, errorMessage, Toast.LENGTH_LONG).show()
                    }
                }
            } catch (e: Exception) {
                println("DEBUG: Exception in login: ${e.javaClass.simpleName} - ${e.message}")
                runOnUiThread {
                    Toast.makeText(this@LoginActivity, "Unexpected error: ${e.message}", Toast.LENGTH_LONG).show()
                }
            } finally {
                runOnUiThread {
                    binding.loginButton.isEnabled = true
                    binding.progressBar.visibility = android.view.View.GONE
                }
            }
        }
    }
    
    private fun askToStoreCredentials(email: String, password: String) {
        AlertDialog.Builder(this)
            .setTitle("Enable Fingerprint Login?")
            .setMessage("Would you like to enable fingerprint login for faster access? Your credentials will be securely stored on this device.")
            .setPositiveButton("Yes") { _, _ ->
                if (credentialManager.storeCredentials(email, password)) {
                    Toast.makeText(this, "Fingerprint login enabled", Toast.LENGTH_SHORT).show()
                    setupBiometricLogin() // Update UI to show fingerprint button and indicator
                } else {
                    Toast.makeText(this, "Failed to store credentials", Toast.LENGTH_SHORT).show()
                }
                navigateToMain()
            }
            .setNegativeButton("No") { _, _ ->
                navigateToMain()
            }
            .setCancelable(false)
            .show()
    }
    
    private fun showMfaDialog(email: String, password: String? = null, shouldStoreCredentials: Boolean = false) {
        val dialogView = layoutInflater.inflate(R.layout.dialog_mfa_code, null)
        val dialog = android.app.AlertDialog.Builder(this)
            .setView(dialogView)
            .setCancelable(false)
            .create()
        
        val mfaCodeEditText = dialogView.findViewById<com.google.android.material.textfield.TextInputEditText>(R.id.mfaCodeEditText)
        val mfaProgressBar = dialogView.findViewById<android.widget.ProgressBar>(R.id.mfaProgressBar)
        val mfaErrorMessage = dialogView.findViewById<android.widget.TextView>(R.id.mfaErrorMessage)
        val verifyButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.mfaVerifyButton)
        val cancelButton = dialogView.findViewById<com.google.android.material.button.MaterialButton>(R.id.mfaCancelButton)
        
        verifyButton.setOnClickListener {
            val code = mfaCodeEditText?.text?.toString()?.trim() ?: ""
            if (code.isEmpty()) {
                mfaErrorMessage?.text = "Please enter the MFA code"
                mfaErrorMessage?.visibility = android.view.View.VISIBLE
                return@setOnClickListener
            }
            
            // Disable button and show progress
            verifyButton.isEnabled = false
            mfaProgressBar?.visibility = android.view.View.VISIBLE
            mfaErrorMessage?.visibility = android.view.View.GONE
            
            // Verify MFA code
            lifecycleScope.launch(Dispatchers.IO) {
                try {
                    val result = authService.verifyMfa(code)
                    runOnUiThread {
                        mfaProgressBar?.visibility = android.view.View.GONE
                        verifyButton.isEnabled = true
                        
                        if (result.success) {
                            // Save session data
                            sessionManager.saveSession(
                                accountId = result.accountId ?: "",
                                driverId = result.driverId ?: "",
                                email = result.email ?: email,
                                username = result.username ?: ""
                            )
                            
                            dialog.dismiss()
                            
                            // If this was a regular login with password, ask to store credentials
                            if (shouldStoreCredentials && password != null && 
                                biometricHelper.isBiometricAvailable() && 
                                !credentialManager.hasStoredCredentials()) {
                                askToStoreCredentials(email, password)
                            } else {
                                Toast.makeText(this@LoginActivity, "Login successful!", Toast.LENGTH_SHORT).show()
                                navigateToMain()
                            }
                        } else {
                            val errorMessage = result.message ?: "MFA verification failed"
                            mfaErrorMessage?.text = errorMessage
                            mfaErrorMessage?.visibility = android.view.View.VISIBLE
                        }
                    }
                } catch (e: Exception) {
                    runOnUiThread {
                        mfaProgressBar?.visibility = android.view.View.GONE
                        verifyButton.isEnabled = true
                        mfaErrorMessage?.text = "Unexpected error: ${e.message}"
                        mfaErrorMessage?.visibility = android.view.View.VISIBLE
                    }
                }
            }
        }
        
        cancelButton.setOnClickListener {
            dialog.dismiss()
            // Re-enable login button
            binding.loginButton.isEnabled = true
            binding.progressBar.visibility = android.view.View.GONE
        }
        
        dialog.show()
    }
    
    private fun navigateToMain() {
        val intent = Intent(this, MainActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        startActivity(intent)
        finish()
    }
}
