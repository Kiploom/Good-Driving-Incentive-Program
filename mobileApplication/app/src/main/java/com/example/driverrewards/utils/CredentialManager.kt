package com.example.driverrewards.utils

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class CredentialManager(private val context: Context) {
    
    companion object {
        private const val KEYSTORE_ALIAS = "DriverRewardsCredentials"
        private const val PREFS_NAME = "DriverRewardsCredentials"
        private const val KEY_EMAIL = "encrypted_email"
        private const val KEY_PASSWORD = "encrypted_password"
        private const val KEY_CREDENTIALS_STORED = "credentials_stored"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
    }
    
    private val prefs: SharedPreferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    
    /**
     * Check if credentials are stored
     */
    fun hasStoredCredentials(): Boolean {
        return prefs.getBoolean(KEY_CREDENTIALS_STORED, false) &&
               prefs.getString(KEY_EMAIL, null) != null &&
               prefs.getString(KEY_PASSWORD, null) != null
    }
    
    /**
     * Store encrypted credentials
     */
    fun storeCredentials(email: String, password: String): Boolean {
        return try {
            val secretKey = getOrCreateSecretKey()
            val encryptedEmail = encrypt(secretKey, email)
            val encryptedPassword = encrypt(secretKey, password)
            
            if (encryptedEmail != null && encryptedPassword != null) {
                prefs.edit().apply {
                    putString(KEY_EMAIL, encryptedEmail)
                    putString(KEY_PASSWORD, encryptedPassword)
                    putBoolean(KEY_CREDENTIALS_STORED, true)
                    apply()
                }
                true
            } else {
                false
            }
        } catch (e: Exception) {
            e.printStackTrace()
            false
        }
    }
    
    /**
     * Retrieve and decrypt stored credentials
     */
    fun getStoredCredentials(): Pair<String, String>? {
        return try {
            val encryptedEmail = prefs.getString(KEY_EMAIL, null)
            val encryptedPassword = prefs.getString(KEY_PASSWORD, null)
            
            if (encryptedEmail == null || encryptedPassword == null) {
                return null
            }
            
            val secretKey = getOrCreateSecretKey()
            val email = decrypt(secretKey, encryptedEmail)
            val password = decrypt(secretKey, encryptedPassword)
            
            if (email != null && password != null) {
                Pair(email, password)
            } else {
                // Decryption failed - clear stored credentials
                clearCredentials()
                null
            }
        } catch (e: Exception) {
            e.printStackTrace()
            // If keystore access fails, clear stored credentials
            clearCredentials()
            null
        }
    }
    
    /**
     * Clear stored credentials
     */
    fun clearCredentials() {
        prefs.edit().apply {
            remove(KEY_EMAIL)
            remove(KEY_PASSWORD)
            putBoolean(KEY_CREDENTIALS_STORED, false)
            apply()
        }
    }
    
    /**
     * Get or create the secret key for encryption/decryption
     */
    private fun getOrCreateSecretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE)
        keyStore.load(null)
        
        if (keyStore.containsAlias(KEYSTORE_ALIAS)) {
            val entry = keyStore.getEntry(KEYSTORE_ALIAS, null) as? KeyStore.SecretKeyEntry
            return entry?.secretKey ?: createSecretKey()
        } else {
            return createSecretKey()
        }
    }
    
    /**
     * Create a new secret key in Android Keystore
     */
    private fun createSecretKey(): SecretKey {
        val keyGenerator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        val keyGenParameterSpec = KeyGenParameterSpec.Builder(
            KEYSTORE_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .build()
        
        keyGenerator.init(keyGenParameterSpec)
        return keyGenerator.generateKey()
    }
    
    /**
     * Encrypt data using the secret key
     */
    private fun encrypt(secretKey: SecretKey, plaintext: String): String? {
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, secretKey)
            val iv = cipher.iv
            val ciphertext = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))
            
            // Combine IV and ciphertext
            val combined = ByteArray(iv.size + ciphertext.size)
            System.arraycopy(iv, 0, combined, 0, iv.size)
            System.arraycopy(ciphertext, 0, combined, iv.size, ciphertext.size)
            
            Base64.encodeToString(combined, Base64.DEFAULT)
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }
    
    /**
     * Decrypt data using the secret key
     */
    private fun decrypt(secretKey: SecretKey, encryptedData: String): String? {
        return try {
            val combined = Base64.decode(encryptedData, Base64.DEFAULT)
            
            // Extract IV and ciphertext
            val iv = ByteArray(12) // GCM IV is typically 12 bytes
            val ciphertext = ByteArray(combined.size - iv.size)
            System.arraycopy(combined, 0, iv, 0, iv.size)
            System.arraycopy(combined, iv.size, ciphertext, 0, ciphertext.size)
            
            val cipher = Cipher.getInstance(TRANSFORMATION)
            val spec = GCMParameterSpec(128, iv) // GCM tag length is 128 bits
            cipher.init(Cipher.DECRYPT_MODE, secretKey, spec)
            val plaintext = cipher.doFinal(ciphertext)
            
            String(plaintext, Charsets.UTF_8)
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }
}

