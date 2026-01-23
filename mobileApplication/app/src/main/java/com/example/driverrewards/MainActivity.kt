package com.example.driverrewards

import android.animation.ObjectAnimator
import android.content.Intent
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import android.view.View
import android.view.ViewGroup
import android.view.animation.AccelerateDecelerateInterpolator
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.text.TextWatcher
import android.text.Editable
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.RadioGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.widget.SearchView
import androidx.drawerlayout.widget.DrawerLayout
import androidx.appcompat.app.AppCompatDelegate
import androidx.lifecycle.lifecycleScope
import com.google.android.material.bottomnavigation.BottomNavigationView
import androidx.appcompat.app.AppCompatActivity
import androidx.navigation.findNavController
import androidx.navigation.ui.AppBarConfiguration
import androidx.navigation.ui.setupActionBarWithNavController
import androidx.navigation.ui.setupWithNavController
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.Observer
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.example.driverrewards.databinding.ActivityMainBinding
import com.example.driverrewards.network.ProfileService
import com.example.driverrewards.network.CatalogService
import com.example.driverrewards.ui.profile.ProfileViewModel
import com.example.driverrewards.ui.catalog.CatalogViewModel
import com.example.driverrewards.utils.SessionManager
import com.example.driverrewards.work.NotificationPollWorker
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var sessionManager: SessionManager
    private lateinit var profileService: ProfileService
    private lateinit var catalogService: CatalogService
    private lateinit var profileViewModel: ProfileViewModel
    private lateinit var catalogViewModel: CatalogViewModel
    private var pointsDisplayView: View? = null
    private var filterDrawer: View? = null
    private var drawerLayout: DrawerLayout? = null
    private var categoryAdapter: com.example.driverrewards.ui.catalog.CategoryExpandableAdapter? = null
    private var selectedCategoryId: String? = null
    private var selectedCategoryName: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        sessionManager = SessionManager(this)
        profileService = ProfileService()
        catalogService = CatalogService()
        profileViewModel = ViewModelProvider(this)[ProfileViewModel::class.java]
        catalogViewModel = ViewModelProvider(this)[CatalogViewModel::class.java]
        
        // Initialize NetworkClient with context
        com.example.driverrewards.network.NetworkClient.initialize(this)
        
        // Observe profile data for points updates
        profileViewModel.profileData.observe(this, Observer { profileData ->
            profileData?.let {
                updatePointsDisplay(it.pointsBalance.toString())
            }
        })
        
        // Load profile data if not already cached
        profileViewModel.loadProfile()
        
        // Apply dark mode setting
        applyDarkModeSetting()
        
        // Check if user is logged in with valid session
        if (!sessionManager.validateSession()) {
            navigateToLogin()
            return
        }
        
        // Schedule notification worker with error handling
        try {
            scheduleNotificationWorker()
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "Failed to schedule notification worker", e)
            // Don't crash if worker scheduling fails
        }

        val navView: BottomNavigationView = binding.navView

        val navController = findNavController(R.id.nav_host_fragment_activity_main)
        // Passing each menu ID as a set of Ids because each
        // menu should be considered as top level destinations.
        val appBarConfiguration = AppBarConfiguration(
            setOf(
                R.id.navigation_catalog,
                R.id.navigation_cart,
                R.id.navigation_orders,
                R.id.navigation_profile,
                R.id.navigation_favorites,
                R.id.navigation_notifications
            )
        )
        setupActionBarWithNavController(navController, appBarConfiguration)
        navView.setupWithNavController(navController)
        
        // Add navigation listener to handle profile tab clicks when on detail page
        navView.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.navigation_profile -> {
                    // If we're on profile detail page, navigate back to profile
                    if (navController.currentDestination?.id == R.id.navigation_profile_detail) {
                        navController.navigate(R.id.action_profile_detail_to_profile)
                    } else {
                        // Normal navigation handled by setupWithNavController
                        navController.navigate(item.itemId)
                    }
                    true
                }
                R.id.navigation_catalog -> {
                    val currentDestination = navController.currentDestination?.id
                    // If we're already on product detail page, pop back stack to navigate away
                    if (currentDestination == R.id.navigation_product_detail) {
                        // Pop back stack to navigate away from product detail
                        if (navController.popBackStack()) {
                            // After popping, navigate to catalog if not already there
                            binding.root.post {
                                if (navController.currentDestination?.id != R.id.navigation_catalog) {
                                    navController.navigate(R.id.navigation_catalog)
                                }
                            }
                        }
                        true
                    } else {
                        // Check if there's a saved product detail to restore
                        val currentProductId = catalogViewModel.getCurrentProductItemId()
                        if (currentProductId != null) {
                            // Navigate to catalog first (if not already there), then to product detail
                            // This ensures catalog is in the back stack before product detail
                            if (currentDestination != R.id.navigation_catalog) {
                                navController.navigate(R.id.navigation_catalog)
                            }
                            // Use post to navigate to product detail after catalog navigation completes
                            binding.root.post {
                                val bundle = Bundle().apply {
                                    putString("itemId", currentProductId)
                                }
                                navController.navigate(R.id.action_catalog_to_product_detail, bundle)
                            }
                            true
                        } else {
                            // Normal navigation to catalog
                            navController.navigate(item.itemId)
                            true
                        }
                    }
                }
                R.id.navigation_favorites -> {
                    val currentDestination = navController.currentDestination?.id
                    // If we're already on product detail page, pop back stack to navigate away
                    if (currentDestination == R.id.navigation_product_detail) {
                        // Pop back stack to navigate away from product detail
                        if (navController.popBackStack()) {
                            // After popping, navigate to favorites if not already there
                            binding.root.post {
                                if (navController.currentDestination?.id != R.id.navigation_favorites) {
                                    navController.navigate(R.id.navigation_favorites)
                                }
                            }
                        }
                        true
                    } else {
                        // Check if there's a saved product detail to restore
                        val currentProductId = catalogViewModel.getCurrentProductItemId()
                        if (currentProductId != null) {
                            // Navigate to favorites first (if not already there), then to product detail
                            if (currentDestination != R.id.navigation_favorites) {
                                navController.navigate(R.id.navigation_favorites)
                            }
                            // Use post to navigate to product detail after favorites navigation completes
                            binding.root.post {
                                val bundle = Bundle().apply {
                                    putString("itemId", currentProductId)
                                }
                                navController.navigate(R.id.action_favorites_to_product_detail, bundle)
                            }
                            true
                        } else {
                            // Normal navigation to favorites
                            navController.navigate(item.itemId)
                            true
                        }
                    }
                }
                else -> {
                    // Let the default handler take care of other tabs
                    navController.navigate(item.itemId)
                    true
                }
            }
        }
        
        // Add destination change listener for menu visibility and points display
        navController.addOnDestinationChangedListener { _, _, _ ->
            invalidateOptionsMenu()
        }
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
    
    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.top_menu, menu)
        
        // Only show logout menu item when on profile page
        val navController = findNavController(R.id.nav_host_fragment_activity_main)
        val currentDestination = navController.currentDestination
        val isOnProfilePage = currentDestination?.id == R.id.navigation_profile
        val isOnProfileDetailPage = currentDestination?.id == R.id.navigation_profile_detail
        val isOnCatalogPage = currentDestination?.id == R.id.navigation_catalog
        
        val logoutItem = menu.findItem(R.id.action_logout)
        logoutItem?.isVisible = isOnProfilePage
        
        // Set up points display for non-profile pages
        if (!isOnProfilePage && !isOnProfileDetailPage) {
            if (isOnCatalogPage) {
                // For catalog page, set up custom action bar with search and points
                setupCatalogActionBar()
            } else {
                // For other pages, just show points
                setupPointsDisplay()
            }
        } else {
            // Hide points display on profile page and profile detail page
            pointsDisplayView?.let { _ ->
                supportActionBar?.customView = null
                supportActionBar?.setDisplayShowCustomEnabled(false)
                supportActionBar?.setDisplayShowTitleEnabled(true)
            }
        }
        
        // Hide the default search menu item since we're using custom layout
        val searchItem = menu.findItem(R.id.action_search)
        searchItem?.isVisible = false
        
        return true
    }
    
    private fun setupCatalogActionBar() {
        // Create a custom layout for the catalog action bar
        val customView = layoutInflater.inflate(R.layout.catalog_action_bar, null)
        
        // Set up the search view in the custom layout
        val searchView = customView.findViewById<SearchView>(R.id.catalog_search_view)
        searchView?.let { sv ->
            sv.queryHint = "Search products..."
            sv.setOnQueryTextListener(object : SearchView.OnQueryTextListener {
                override fun onQueryTextSubmit(query: String?): Boolean {
                    sendSearchQueryToFragment(query)
                    // Hide the keyboard after search is submitted
                    hideKeyboard()
                    return true
                }
                
                override fun onQueryTextChange(newText: String?): Boolean {
                    return false
                }
            })
        }
        
        // Set up the filter button
        val filterButton = customView.findViewById<ImageButton>(R.id.filter_button)
        filterButton?.setOnClickListener {
            showFilterDrawer()
        }
        
        // Set up the points display in the custom layout
        val pointsValueView = customView.findViewById<TextView>(R.id.catalog_points_value)
        pointsValueView?.setOnClickListener {
            // Navigate to points detail page
            try {
                val navController = findNavController(R.id.nav_host_fragment_activity_main)
                navController.navigate(R.id.navigation_points_detail)
            } catch (e: Exception) {
                android.util.Log.e("MainActivity", "Error navigating to points detail: ${e.message}", e)
            }
        }
        // Make the entire points container clickable
        val pointsContainer = customView.findViewById<View>(R.id.points_container)
        pointsContainer?.setOnClickListener {
            // Navigate to points detail page
            try {
                val navController = findNavController(R.id.nav_host_fragment_activity_main)
                navController.navigate(R.id.navigation_points_detail)
            } catch (e: Exception) {
                android.util.Log.e("MainActivity", "Error navigating to points detail: ${e.message}", e)
            }
        }
        pointsDisplayView = customView
        
        // Set the custom view as the action bar
        supportActionBar?.let { actionBar ->
            actionBar.setDisplayShowCustomEnabled(true)
            actionBar.setDisplayShowTitleEnabled(false)
            actionBar.customView = customView
        }
        
        // Fetch and display points
        fetchAndDisplayPoints()
    }
    
    private fun sendSearchQueryToFragment(query: String?) {
        // Find the current CatalogFragment and send the search query
        val navController = findNavController(R.id.nav_host_fragment_activity_main)
        if (navController.currentDestination?.id == R.id.navigation_catalog) {
            // Get the current fragment and cast it to CatalogFragment
            val fragment = supportFragmentManager.findFragmentById(R.id.nav_host_fragment_activity_main)
            if (fragment is androidx.navigation.fragment.NavHostFragment) {
                val catalogFragment = fragment.childFragmentManager.fragments.firstOrNull()
                if (catalogFragment is com.example.driverrewards.ui.catalog.CatalogFragment) {
                    catalogFragment.performSearch(query)
                }
            }
        }
    }
    
    override fun onSupportNavigateUp(): Boolean {
        val navController = findNavController(R.id.nav_host_fragment_activity_main)
        return when (navController.currentDestination?.id) {
            R.id.navigation_profile_detail -> {
                // Navigate back to profile page from detail page
                navController.navigate(R.id.action_profile_detail_to_profile)
                true
            }
            R.id.navigation_product_detail -> {
                // When navigating back from product detail, clear the saved product ID
                // so it doesn't auto-restore when clicking catalog tab
                catalogViewModel.setCurrentProductItemId(null)
                navController.navigateUp() || super.onSupportNavigateUp()
            }
            else -> navController.navigateUp() || super.onSupportNavigateUp()
        }
    }
    
    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_logout -> {
                logout()
                true
            }
            R.id.action_notifications -> {
                val navController = findNavController(R.id.nav_host_fragment_activity_main)
                navController.navigate(R.id.navigation_notifications)
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }
    
    private fun logout() {
        WorkManager.getInstance(this).cancelUniqueWork(NotificationPollWorker.WORK_NAME)
        // Clear session cookies from NetworkClient
        com.example.driverrewards.network.NetworkClient.clearSessionCookies()
        
        // Clear session data from SessionManager
        sessionManager.logout()
        
        navigateToLogin()
    }
    
    private fun navigateToLogin() {
        val intent = Intent(this, LoginActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        startActivity(intent)
        finish()
    }
    
    private fun setupPointsDisplay() {
        // Remove existing points display if any
        pointsDisplayView?.let { _ ->
            supportActionBar?.customView = null
        }
        
        // Create new points display view
        pointsDisplayView = layoutInflater.inflate(R.layout.points_display, null)
        supportActionBar?.customView = pointsDisplayView
        supportActionBar?.setDisplayShowCustomEnabled(true)
        supportActionBar?.setDisplayShowTitleEnabled(false)
        
        // Fetch and display points
        fetchAndDisplayPoints()
    }
    
    private fun updatePointsDisplay(points: String) {
        // Update points display for regular action bar
        val pointsValue = pointsDisplayView?.findViewById<TextView>(R.id.points_value)
        pointsValue?.text = points
        
        // Update points display for catalog action bar
        val catalogPointsValue = pointsDisplayView?.findViewById<TextView>(R.id.catalog_points_value)
        catalogPointsValue?.text = points
    }

    private fun scheduleNotificationWorker() {
        try {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val workRequest = PeriodicWorkRequestBuilder<NotificationPollWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()

            WorkManager.getInstance(this).enqueueUniquePeriodicWork(
                NotificationPollWorker.WORK_NAME,
                ExistingPeriodicWorkPolicy.UPDATE,
                workRequest
            )
            android.util.Log.d("MainActivity", "Notification worker scheduled successfully")
        } catch (e: Exception) {
            android.util.Log.e("MainActivity", "Error scheduling notification worker", e)
            throw e // Re-throw to be caught by caller
        }
    }
    
    private fun hideKeyboard() {
        val inputMethodManager = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
        val currentFocus = currentFocus
        if (currentFocus != null) {
            inputMethodManager.hideSoftInputFromWindow(currentFocus.windowToken, 0)
        }
    }
    
    private fun showFilterDrawer() {
        if (filterDrawer == null) {
            // Create the filter drawer view
            filterDrawer = layoutInflater.inflate(R.layout.filter_drawer, null)
            setupFilterDrawer()
            
            // Add the drawer to the main layout
            val rootLayout = findViewById<ViewGroup>(android.R.id.content)
            rootLayout.addView(filterDrawer)
            
            // Initially hide the drawer off-screen
            filterDrawer?.findViewById<LinearLayout>(R.id.filter_content)?.translationX = -280f
        }
        
        // Restore selected category in adapter when drawer is shown
        selectedCategoryId?.let { 
            categoryAdapter?.setSelectedCategory(it)
        }
        
        // Show the drawer with animation
        animateFilterDrawer(true)
    }
    
    private fun setupFilterDrawer() {
        filterDrawer?.let { drawer ->
            // Set up close button
            val closeButton = drawer.findViewById<ImageButton>(R.id.close_filter_drawer)
            closeButton?.setOnClickListener {
                hideFilterDrawer()
            }
            
            // Set up apply button
            val applyButton = drawer.findViewById<Button>(R.id.apply_filters)
            applyButton?.setOnClickListener {
                applyFilters()
            }
            
            // Set up "Show Only Affordable" button
            val showAffordableButton = drawer.findViewById<Button>(R.id.show_affordable)
            showAffordableButton?.setOnClickListener {
                showOnlyAffordableItems()
            }
            
            // Set up "View Recommended" button
            val viewRecommendedButton = drawer.findViewById<Button>(R.id.view_recommended)
            viewRecommendedButton?.setOnClickListener {
                viewRecommendedItems()
            }
            
            // Set up category search
            val categorySearch = drawer.findViewById<EditText>(R.id.category_search)
            categorySearch?.addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    categoryAdapter?.filterCategories(s?.toString() ?: "")
                }
                override fun afterTextChanged(s: Editable?) {}
            })
            
            // Set up expand all button
            val expandAllButton = drawer.findViewById<Button>(R.id.expand_all_categories)
            expandAllButton?.setOnClickListener {
                categoryAdapter?.expandAll()
            }
            
            // Set up collapse all button
            val collapseAllButton = drawer.findViewById<Button>(R.id.collapse_all_categories)
            collapseAllButton?.setOnClickListener {
                categoryAdapter?.collapseAll()
            }
            
            // Set up overlay background click to close drawer
            val overlayBackground = drawer.findViewById<View>(R.id.overlay_background)
            overlayBackground?.setOnClickListener {
                hideFilterDrawer()
            }
            
            // Load categories
            loadCategories()
        }
    }
    
    private fun loadCategories() {
        filterDrawer?.let { drawer ->
            val categoriesRecyclerView = drawer.findViewById<androidx.recyclerview.widget.RecyclerView>(R.id.categories_recycler_view)
            val categoriesLoading = drawer.findViewById<TextView>(R.id.categories_loading)
            val categoriesEmpty = drawer.findViewById<TextView>(R.id.categories_empty)
            
            categoriesLoading?.visibility = View.VISIBLE
            categoriesEmpty?.visibility = View.GONE
            categoriesRecyclerView?.visibility = View.GONE
            
            lifecycleScope.launch(Dispatchers.Main) {
                try {
                    val response = catalogService.getCategories()
                    
                    categoriesLoading?.visibility = View.GONE
                    
                    if (response.success) {
                        // Parse category tree if available, otherwise use flat list
                        val categoryGroups = if (response.category_tree != null) {
                            parseCategoryTree(response.category_tree, response.parent_categories ?: emptyMap())
                        } else {
                            // Fallback to flat list grouped by first letter or similar
                            groupCategoriesFlat(response.categories, response.parent_categories ?: emptyMap())
                        }
                        
                        if (categoryGroups.isNotEmpty()) {
                            categoriesEmpty?.visibility = View.GONE
                            categoriesRecyclerView?.visibility = View.VISIBLE
                            
                            categoriesRecyclerView?.apply {
                                layoutManager = androidx.recyclerview.widget.LinearLayoutManager(context)
                                val adapter = com.example.driverrewards.ui.catalog.CategoryExpandableAdapter(
                                    categoryGroups.toMutableList(),
                                    onCategorySelected = { categoryId, categoryName ->
                                        selectCategory(categoryId, categoryName)
                                    }
                                )
                                // Restore selected category if any
                                selectedCategoryId?.let { adapter.setSelectedCategory(it) }
                                this.adapter = adapter
                                categoryAdapter = adapter
                            }
                        } else {
                            categoriesEmpty?.visibility = View.VISIBLE
                            categoriesEmpty?.text = response.message ?: "No categories available"
                            categoriesRecyclerView?.visibility = View.GONE
                        }
                    } else {
                        categoriesEmpty?.visibility = View.VISIBLE
                        categoriesEmpty?.text = response.message ?: "No categories available"
                        categoriesRecyclerView?.visibility = View.GONE
                    }
                } catch (e: Exception) {
                    android.util.Log.e("MainActivity", "Error loading categories: ${e.message}", e)
                    categoriesLoading?.visibility = View.GONE
                    categoriesEmpty?.visibility = View.VISIBLE
                    categoriesEmpty?.text = "Error loading categories"
                    categoriesRecyclerView?.visibility = View.GONE
                }
            }
        }
    }
    
    private fun parseCategoryTree(tree: Map<String, Any>, parentCategories: Map<String, String>): List<com.example.driverrewards.ui.catalog.CategoryGroup> {
        val groups = mutableListOf<com.example.driverrewards.ui.catalog.CategoryGroup>()
        
        // Recursively process a node and return a list of CategoryNodes (either Leaf or Group)
        fun processNode(categoryName: String, node: Any, level: Int = 0): List<com.example.driverrewards.ui.catalog.CategoryNode> {
            val nodes = mutableListOf<com.example.driverrewards.ui.catalog.CategoryNode>()
            
            when (node) {
                is Map<*, *> -> {
                    val values = node.values.toList()
                    val allValuesAreStrings = values.isNotEmpty() && values.all { it is String }
                    
                    if (allValuesAreStrings) {
                        // Leaf categories: keys are IDs, values are names
                        node.forEach { (key, value) ->
                            if (key is String && value is String) {
                                nodes.add(
                                    com.example.driverrewards.ui.catalog.CategoryNode.Leaf(
                                        com.example.driverrewards.network.CategoryItem(
                                            id = key,
                                            name = value,
                                            is_parent = false
                                        )
                                    )
                                )
                            }
                        }
                    } else {
                        // Nested structure - create nested groups
                        node.forEach { (subName, subNode) ->
                            if (subName is String && subNode != null) {
                                val subId: String? = parentCategories[subName]
                                
                                // Process nested node recursively
                                val nestedNodes = processNode(subName, subNode as Any, level + 1)
                                
                                if (nestedNodes.isNotEmpty() || subId != null) {
                                    // Create a nested CategoryGroup
                                    val nestedGroup = com.example.driverrewards.ui.catalog.CategoryGroup(
                                        parentName = subName,
                                        parentId = subId,
                                        subcategories = nestedNodes,
                                        isExpanded = false,
                                        isVisible = true,
                                        level = level + 1
                                    )
                                    nodes.add(com.example.driverrewards.ui.catalog.CategoryNode.Group(nestedGroup))
                                }
                            }
                        }
                    }
                }
            }
            
            return nodes
        }
        
        // Process top-level categories
        tree.forEach { (categoryName, node) ->
            val parentId = parentCategories[categoryName]
            val subcategories = processNode(categoryName, node, 0)
            
            if (subcategories.isNotEmpty() || parentId != null) {
                groups.add(
                    com.example.driverrewards.ui.catalog.CategoryGroup(
                        parentName = categoryName,
                        parentId = parentId,
                        subcategories = subcategories,
                        isExpanded = false,
                        isVisible = true,
                        level = 0
                    )
                )
            }
        }
        
        return groups.sortedBy { it.parentName }
    }
    
    private fun groupCategoriesFlat(categories: List<com.example.driverrewards.network.CategoryItem>, parentCategories: Map<String, String>): List<com.example.driverrewards.ui.catalog.CategoryGroup> {
        // Group categories by their parent or create single-item groups
        val groups = mutableListOf<com.example.driverrewards.ui.catalog.CategoryGroup>()
        val parentMap = mutableMapOf<String, MutableList<com.example.driverrewards.network.CategoryItem>>()
        
        categories.forEach { category ->
            // Find parent category name for this category
            var parentName: String? = null
            for ((name, id) in parentCategories) {
                // Check if this category might belong to this parent
                // This is a simplified grouping - in reality we'd need the full tree
                if (category.is_parent == true) {
                    parentName = category.name
                    break
                }
            }
            
            // Create a group for this category
            val groupName = parentName ?: category.name
            if (!parentMap.containsKey(groupName)) {
                parentMap[groupName] = mutableListOf()
            }
            parentMap[groupName]!!.add(
                com.example.driverrewards.network.CategoryItem(
                    id = category.id,
                    name = category.name,
                    is_parent = category.is_parent ?: false
                )
            )
        }
        
        parentMap.forEach { (parentName: String, subcategories: MutableList<com.example.driverrewards.network.CategoryItem>) ->
            val parentId = parentCategories[parentName]
            // Convert CategoryItems to CategoryNode.Leaf and filter out parent
            val categoryNodes = subcategories
                .filter { it.id != parentId } // Don't include parent as subcategory
                .map { com.example.driverrewards.ui.catalog.CategoryNode.Leaf(it) }
            groups.add(
                com.example.driverrewards.ui.catalog.CategoryGroup(
                    parentName = parentName,
                    parentId = parentId,
                    subcategories = categoryNodes,
                    isExpanded = false,
                    isVisible = true,
                    level = 0
                )
            )
        }
        
        return groups.sortedBy { it.parentName }
    }
    
    private fun selectCategory(categoryId: String, categoryName: String) {
        android.util.Log.d("MainActivity", "Category selected: $categoryName ($categoryId)")
        
        // Guard against null or empty values
        if (categoryId.isBlank()) {
            return
        }
        
        // Store selection
        selectedCategoryId = categoryId
        selectedCategoryName = categoryName
        
        // Update adapter to show selection (but don't trigger callback to avoid recursion)
        categoryAdapter?.setSelectedCategory(categoryId)
        
        // Don't close drawer - let user see the selection and optionally apply filters
        // Apply the category filter immediately and update browsing indicator
        sendFiltersToFragment("best_match", null, null, listOf(categoryId))
        updateBrowsingIndicatorInFragment(categoryName)
    }
    
    fun clearCategorySelection() {
        selectedCategoryId = null
        selectedCategoryName = null
        categoryAdapter?.setSelectedCategory(null)
    }
    
    private fun updateBrowsingIndicatorInFragment(categoryName: String) {
        val navController = findNavController(R.id.nav_host_fragment_activity_main)
        if (navController.currentDestination?.id == R.id.navigation_catalog) {
            val fragment = supportFragmentManager.findFragmentById(R.id.nav_host_fragment_activity_main)
            if (fragment is androidx.navigation.fragment.NavHostFragment) {
                val catalogFragment = fragment.childFragmentManager.fragments.firstOrNull()
                if (catalogFragment is com.example.driverrewards.ui.catalog.CatalogFragment) {
                    catalogFragment.updateBrowsingIndicator(listOf(selectedCategoryId ?: ""), categoryName)
                }
            }
        }
    }
    
    private fun animateFilterDrawer(show: Boolean) {
        filterDrawer?.let { drawer ->
            val filterContent = drawer.findViewById<LinearLayout>(R.id.filter_content)
            if (filterContent != null) {
                val targetX = if (show) 0f else -filterContent.width.toFloat()
                
                val animator = ObjectAnimator.ofFloat(filterContent, "translationX", filterContent.translationX, targetX)
                animator.duration = 300
                animator.interpolator = AccelerateDecelerateInterpolator()
                
                if (!show) {
                    // Animate overlay background fade out
                    val overlayBackground = drawer.findViewById<View>(R.id.overlay_background)
                    val overlayAnimator = ObjectAnimator.ofFloat(overlayBackground, "alpha", 0.5f, 0f)
                    overlayAnimator.duration = 300
                    overlayAnimator.start()
                    
                    animator.addListener(object : android.animation.AnimatorListenerAdapter() {
                        override fun onAnimationEnd(animation: android.animation.Animator) {
                            // Hide the drawer completely when animation ends
                            drawer.visibility = View.GONE
                        }
                    })
                } else {
                    drawer.visibility = View.VISIBLE
                    // Animate overlay background fade in
                    val overlayBackground = drawer.findViewById<View>(R.id.overlay_background)
                    val overlayAnimator = ObjectAnimator.ofFloat(overlayBackground, "alpha", 0f, 0.5f)
                    overlayAnimator.duration = 300
                    overlayAnimator.start()
                }
                
                animator.start()
            }
        }
    }
    
    private fun hideFilterDrawer() {
        // Hide the filter drawer with animation
        animateFilterDrawer(false)
    }
    
    private fun viewRecommendedItems() {
        // Clear category selection when viewing recommended
        selectedCategoryId = null
        selectedCategoryName = null
        categoryAdapter?.setSelectedCategory(null)
        
        // Navigate to catalog and show recommended items
        hideFilterDrawer()
        
        // Find the current CatalogFragment and trigger recommended view
        val navController = findNavController(R.id.nav_host_fragment_activity_main)
        if (navController.currentDestination?.id == R.id.navigation_catalog) {
            val fragment = supportFragmentManager.findFragmentById(R.id.nav_host_fragment_activity_main)
            if (fragment is androidx.navigation.fragment.NavHostFragment) {
                val catalogFragment = fragment.childFragmentManager.fragments.firstOrNull()
                if (catalogFragment is com.example.driverrewards.ui.catalog.CatalogFragment) {
                    catalogFragment.viewRecommendedItems()
                }
            }
        }
    }
    
    private fun applyFilters() {
        filterDrawer?.let { drawer ->
            // Get filter values
            val sortRadioGroup = drawer.findViewById<RadioGroup>(R.id.sort_radio_group)
            val minPoints = drawer.findViewById<EditText>(R.id.min_points)?.text?.toString()
            val maxPoints = drawer.findViewById<EditText>(R.id.max_points)?.text?.toString()
            
            // Get selected sort option
            val selectedSortId = sortRadioGroup?.checkedRadioButtonId
            val sortOption = when (selectedSortId) {
                R.id.sort_points_asc -> "points_asc"
                R.id.sort_points_desc -> "points_desc"
                R.id.sort_stock_asc -> "stock_asc"
                R.id.sort_stock_desc -> "stock_desc"
                R.id.sort_newest -> "newest"
                else -> "best_match"
            }
            
            // Get selected categories from the adapter
            // Note: Categories are now selected via the adapter's onCategorySelected callback,
            // so we don't need to collect them from checkboxes here.
            // The selected category is applied immediately when selected.
            val selectedCategories = mutableListOf<String>()
            
            android.util.Log.d("MainActivity", "===== APPLYING FILTERS =====")
            android.util.Log.d("MainActivity", "minPoints (raw): '$minPoints'")
            android.util.Log.d("MainActivity", "maxPoints (raw): '$maxPoints'")
            android.util.Log.d("MainActivity", "sortOption: $sortOption")
            android.util.Log.d("MainActivity", "selectedCategories: $selectedCategories")
            
            // Send filters to CatalogFragment
            sendFiltersToFragment(sortOption, minPoints, maxPoints, selectedCategories)
            
            hideFilterDrawer()
        }
    }
    
    private fun sendFiltersToFragment(sort: String, minPoints: String?, maxPoints: String?, categories: List<String>) {
        // Find the current CatalogFragment and send the filter parameters
        val navController = findNavController(R.id.nav_host_fragment_activity_main)
        if (navController.currentDestination?.id == R.id.navigation_catalog) {
            val fragment = supportFragmentManager.findFragmentById(R.id.nav_host_fragment_activity_main)
            if (fragment is androidx.navigation.fragment.NavHostFragment) {
                val catalogFragment = fragment.childFragmentManager.fragments.firstOrNull()
                if (catalogFragment is com.example.driverrewards.ui.catalog.CatalogFragment) {
                    catalogFragment.applyFilters(sort, minPoints, maxPoints, categories)
                }
            }
        }
    }
    
    private fun showOnlyAffordableItems() {
        // Use cached profile data from ViewModel
        val cachedProfile = profileViewModel.profileData.value
        if (cachedProfile != null) {
            val pointsBalance = cachedProfile.pointsBalance
            
            // Set max points to user's balance
            filterDrawer?.let { drawer ->
                val maxPointsField = drawer.findViewById<EditText>(R.id.max_points)
                maxPointsField?.setText(pointsBalance.toString())
            }
            
            // Apply the filter immediately
            applyFilters()
        } else {
            // If not cached, trigger load and try again
            profileViewModel.loadProfile()
            Toast.makeText(this, "Loading points balance...", Toast.LENGTH_SHORT).show()
        }
    }
    
    private fun fetchAndDisplayPoints() {
        // Only fetch points if we have valid session data
        if (!sessionManager.hasValidSessionData()) {
            updatePointsDisplay("0")
            return
        }
        
        // Use cached profile data from ViewModel
        val cachedProfile = profileViewModel.profileData.value
        if (cachedProfile != null) {
            updatePointsDisplay(cachedProfile.pointsBalance.toString())
        } else {
            // If not cached, trigger load (observer will update display)
            profileViewModel.loadProfile()
            // Show 0 as fallback until data loads
            updatePointsDisplay("0")
        }
    }
    
    fun refreshPointsDisplay() {
        // Force refresh of profile data to get updated points
        profileViewModel.refreshProfile()
    }
}