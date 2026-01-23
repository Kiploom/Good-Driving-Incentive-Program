package com.example.driverrewards.ui.catalog

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView
import com.example.driverrewards.R
import com.example.driverrewards.network.CategoryItem

// Sealed class to represent either a leaf category item or a nested category group
sealed class CategoryNode {
    data class Leaf(val item: CategoryItem) : CategoryNode()
    data class Group(val group: CategoryGroup) : CategoryNode()
}

data class CategoryGroup(
    val parentName: String,
    val parentId: String?,
    val subcategories: List<CategoryNode>, // Can contain both leaf items and nested groups
    var isExpanded: Boolean = false,
    var isVisible: Boolean = true, // For search filtering
    val level: Int = 0 // Nesting level for indentation
)

class CategoryExpandableAdapter(
    private var categories: MutableList<CategoryGroup>,
    private val onCategorySelected: (String, String) -> Unit
) : RecyclerView.Adapter<CategoryExpandableAdapter.ViewHolder>() {

    private var selectedCategoryId: String? = null
    private val radioGroupId = View.generateViewId() // Single RadioGroup for all categories

    class ViewHolder(itemView: View) : RecyclerView.ViewHolder(itemView) {
        val parentName: TextView = itemView.findViewById(R.id.category_parent_name)
        val headerLayout: ViewGroup = itemView.findViewById(R.id.category_header_layout)
        val selectParentButton: Button? = itemView.findViewById(R.id.category_select_parent_button)
        val subcategoriesContainer: ViewGroup = itemView.findViewById(R.id.category_subcategories_container)
        val expandIndicator: TextView = itemView.findViewById(R.id.category_expand_indicator)
        val rootLayout: ViewGroup = itemView as ViewGroup
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_category_group, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val categoryGroup = categories[position]
        
        // Hide if filtered out by search
        holder.rootLayout.visibility = if (categoryGroup.isVisible) View.VISIBLE else View.GONE
        if (!categoryGroup.isVisible) return
        
        holder.parentName.text = categoryGroup.parentName
        
        // Highlight if this parent category is selected
        val isParentSelected = categoryGroup.parentId == selectedCategoryId
        if (isParentSelected) {
            // Use a light gray background for selected category
            val backgroundColor = android.graphics.Color.argb(50, 128, 128, 128)
            holder.rootLayout.setBackgroundColor(backgroundColor)
        } else {
            holder.rootLayout.background = null
        }
        
        // Show/hide select parent button based on whether parent is selectable
        if (categoryGroup.parentId != null) {
            holder.selectParentButton?.visibility = View.VISIBLE
            holder.selectParentButton?.text = "Select"
            holder.selectParentButton?.setOnClickListener {
                // Double-check for null safety
                categoryGroup.parentId?.let { id ->
                    selectCategory(id, categoryGroup.parentName)
                }
            }
        } else {
            holder.selectParentButton?.visibility = View.GONE
        }
        
        // Make parent name clickable if parent is selectable
        if (categoryGroup.parentId != null) {
            holder.parentName.setOnClickListener {
                // Double-check for null safety
                categoryGroup.parentId?.let { id ->
                    selectCategory(id, categoryGroup.parentName)
                }
            }
        } else {
            holder.parentName.setOnClickListener(null)
            holder.parentName.isClickable = false
        }
        
        // Update expand indicator
        holder.expandIndicator.text = if (categoryGroup.isExpanded) "▼" else "▶"
        
        // Show/hide subcategories
        if (categoryGroup.isExpanded && categoryGroup.subcategories.isNotEmpty()) {
            holder.subcategoriesContainer.visibility = View.VISIBLE
            holder.subcategoriesContainer.removeAllViews()
            
            // Create a container for subcategories (can contain both radio buttons and nested groups)
            val subcategoryContainer = android.widget.LinearLayout(holder.itemView.context)
            subcategoryContainer.orientation = android.widget.LinearLayout.VERTICAL
            
            // Render each subcategory (either leaf or nested group)
            categoryGroup.subcategories.forEach { node ->
                when (node) {
                    is CategoryNode.Leaf -> {
                        // Render as radio button
                        val radioButton = RadioButton(holder.itemView.context)
                        radioButton.text = node.item.name
                        radioButton.tag = node.item.id
                        radioButton.textSize = 14f
                        radioButton.id = View.generateViewId()
                        // Fix text color for dark mode
                        val typedArrayText = holder.itemView.context.obtainStyledAttributes(intArrayOf(android.R.attr.textColorPrimary))
                        val textColor = typedArrayText.getColor(0, 0)
                        typedArrayText.recycle()
                        if (textColor != 0) {
                            radioButton.setTextColor(textColor)
                        }
                        
                        // Check if this subcategory is selected
                        if (node.item.id == selectedCategoryId) {
                            radioButton.isChecked = true
                        }
                        
                        val margin = (8 * holder.itemView.context.resources.displayMetrics.density).toInt()
                        val indentLevel = categoryGroup.level + 1
                        // Reduced left padding, no right margin
                        val layoutParams = ViewGroup.MarginLayoutParams(
                            ViewGroup.MarginLayoutParams.MATCH_PARENT,
                            ViewGroup.MarginLayoutParams.WRAP_CONTENT
                        ).apply {
                            setMargins(margin * (1 + indentLevel), margin, 0, margin)
                        }
                        radioButton.layoutParams = layoutParams
                        
                        radioButton.setOnClickListener {
                            // Ensure ID is not null before selecting
                            val subcategoryId = node.item.id
                            if (subcategoryId != null) {
                                selectCategory(subcategoryId, node.item.name)
                            }
                        }
                        
                        subcategoryContainer.addView(radioButton)
                    }
                    is CategoryNode.Group -> {
                        // Render as nested expandable group
                        val nestedGroupView = renderNestedGroup(node.group, holder.itemView.context)
                        subcategoryContainer.addView(nestedGroupView)
                    }
                }
            }
            
            holder.subcategoriesContainer.addView(subcategoryContainer)
        } else {
            holder.subcategoriesContainer.visibility = View.GONE
        }
        
        // Make entire header clickable to expand/collapse
        holder.headerLayout.setOnClickListener {
            categoryGroup.isExpanded = !categoryGroup.isExpanded
            notifyItemChanged(position)
        }
    }

    override fun getItemCount(): Int = categories.size
    
    // Helper function to check if a group has only one leaf option (recursively)
    private fun hasSingleLeafOption(group: CategoryGroup): CategoryItem? {
        if (group.subcategories.isEmpty()) {
            return null
        }
        
        if (group.subcategories.size == 1) {
            val node = group.subcategories[0]
            return when (node) {
                is CategoryNode.Leaf -> node.item
                is CategoryNode.Group -> hasSingleLeafOption(node.group) // Recursively check
            }
        }
        
        return null
    }
    
    // Recursively render a nested category group
    private fun renderNestedGroup(group: CategoryGroup, context: android.content.Context): ViewGroup {
        // Check if this group has only one leaf option - if so, render as radio button instead
        val singleLeaf = hasSingleLeafOption(group)
        if (singleLeaf != null && group.parentId == null) {
            // Render as a simple radio button option (no dropdown)
            val radioButton = RadioButton(context)
            radioButton.text = singleLeaf.name
            radioButton.tag = singleLeaf.id
            radioButton.textSize = 14f
            radioButton.id = View.generateViewId()
            
            if (singleLeaf.id == selectedCategoryId) {
                radioButton.isChecked = true
            }
            
            val margin = (8 * context.resources.displayMetrics.density).toInt()
            val indentLevel = group.level
            // Fix text color for dark mode
            val typedArrayText = context.obtainStyledAttributes(intArrayOf(android.R.attr.textColorPrimary))
            val textColor = typedArrayText.getColor(0, 0)
            typedArrayText.recycle()
            if (textColor != 0) {
                radioButton.setTextColor(textColor)
            }
            // Reduced left padding, no right margin
            val layoutParams = ViewGroup.MarginLayoutParams(
                ViewGroup.MarginLayoutParams.MATCH_PARENT,
                ViewGroup.MarginLayoutParams.WRAP_CONTENT
            ).apply {
                setMargins(margin * (1 + indentLevel), margin, 0, margin)
            }
            radioButton.layoutParams = layoutParams
            
            radioButton.setOnClickListener {
                val subcategoryId = singleLeaf.id
                if (subcategoryId != null) {
                    selectCategory(subcategoryId, singleLeaf.name)
                }
            }
            
            val container = android.widget.LinearLayout(context)
            container.orientation = android.widget.LinearLayout.VERTICAL
            container.addView(radioButton)
            return container
        }
        
        // Otherwise, render as expandable group with same styling as main categories
        val container = android.widget.LinearLayout(context)
        container.orientation = android.widget.LinearLayout.VERTICAL
        container.setPadding(0, 0, 0, 0)
        
        // Create header matching main category layout structure
        val headerLayout = android.widget.LinearLayout(context)
        headerLayout.orientation = android.widget.LinearLayout.HORIZONTAL
        headerLayout.gravity = android.view.Gravity.CENTER_VERTICAL
        headerLayout.isClickable = true
        headerLayout.isFocusable = true
        // Use theme attribute for selectable background
        val typedArrayHeader = context.obtainStyledAttributes(intArrayOf(android.R.attr.selectableItemBackground))
        val backgroundHeaderResource = typedArrayHeader.getResourceId(0, 0)
        typedArrayHeader.recycle()
        if (backgroundHeaderResource != 0) {
            headerLayout.setBackgroundResource(backgroundHeaderResource)
        }
        
        val margin = (8 * context.resources.displayMetrics.density).toInt()
        val indentLevel = group.level
        // Reduced left padding for subcategories
        val headerParams = ViewGroup.MarginLayoutParams(
            ViewGroup.MarginLayoutParams.MATCH_PARENT,
            ViewGroup.MarginLayoutParams.WRAP_CONTENT
        ).apply {
            setMargins(margin * (1 + indentLevel), margin / 2, margin, margin / 2)
        }
        headerLayout.layoutParams = headerParams
        
        // Expand indicator (same as main category - 24dp, centered)
        val expandIndicator = TextView(context)
        expandIndicator.text = if (group.isExpanded) "▼" else "▶"
        expandIndicator.textSize = 12f
        expandIndicator.gravity = android.view.Gravity.CENTER
        // Use theme color to match layout
        val typedArrayIndicator = context.obtainStyledAttributes(intArrayOf(com.google.android.material.R.attr.colorOnSurface))
        val colorOnSurface = typedArrayIndicator.getColor(0, 0)
        typedArrayIndicator.recycle()
        if (colorOnSurface != 0) {
            expandIndicator.setTextColor(colorOnSurface)
        }
        val indicatorParams = ViewGroup.LayoutParams(
            (24 * context.resources.displayMetrics.density).toInt(),
            (24 * context.resources.displayMetrics.density).toInt()
        )
        expandIndicator.layoutParams = indicatorParams
        headerLayout.addView(expandIndicator)
        
        // Category name (same styling as main category - bold, 16sp)
        val categoryName = TextView(context)
        categoryName.text = group.parentName
        categoryName.textSize = 16f
        categoryName.setTypeface(null, android.graphics.Typeface.BOLD)
        // Fix text color for dark mode
        val typedArrayText = context.obtainStyledAttributes(intArrayOf(android.R.attr.textColorPrimary))
        val textColor = typedArrayText.getColor(0, 0)
        typedArrayText.recycle()
        if (textColor != 0) {
            categoryName.setTextColor(textColor)
        }
        categoryName.setPadding(margin, 0, 0, 0)
        categoryName.isClickable = group.parentId != null
        categoryName.isFocusable = group.parentId != null
        if (group.parentId != null) {
            // Use theme attribute for selectable background
            val typedArray = context.obtainStyledAttributes(intArrayOf(android.R.attr.selectableItemBackground))
            val backgroundResource = typedArray.getResourceId(0, 0)
            typedArray.recycle()
            if (backgroundResource != 0) {
                categoryName.setBackgroundResource(backgroundResource)
            }
            categoryName.setOnClickListener {
                selectCategory(group.parentId, group.parentName)
            }
        }
        val nameParams = android.widget.LinearLayout.LayoutParams(
            0,
            ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply {
            weight = 1f
        }
        categoryName.layoutParams = nameParams
        headerLayout.addView(categoryName)
        
        // Select button (same as main category, if selectable)
        if (group.parentId != null) {
            val selectButton = Button(context)
            selectButton.text = "Select"
            selectButton.textSize = 12f
            selectButton.setPadding(
                (12 * context.resources.displayMetrics.density).toInt(),
                (6 * context.resources.displayMetrics.density).toInt(),
                (12 * context.resources.displayMetrics.density).toInt(),
                (6 * context.resources.displayMetrics.density).toInt()
            )
            selectButton.minWidth = 0
            // Use theme attribute for colorPrimaryVariant
            val typedArrayColor = context.theme.obtainStyledAttributes(intArrayOf(com.google.android.material.R.attr.colorPrimaryVariant))
            val colorPrimaryVariant = typedArrayColor.getColor(0, 0)
            typedArrayColor.recycle()
            if (colorPrimaryVariant != 0) {
                selectButton.backgroundTintList = android.content.res.ColorStateList.valueOf(colorPrimaryVariant)
            }
            selectButton.layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            selectButton.setOnClickListener {
                selectCategory(group.parentId, group.parentName)
            }
            headerLayout.addView(selectButton)
        }
        
        // Make entire header clickable to expand/collapse
        headerLayout.setOnClickListener {
            group.isExpanded = !group.isExpanded
            expandIndicator.text = if (group.isExpanded) "▼" else "▶"
            val subcategoriesContainer = expandIndicator.tag as? ViewGroup
            if (subcategoriesContainer != null) {
                renderNestedGroupContent(group, subcategoriesContainer, context, expandIndicator)
            }
        }
        
        // Highlight if selected (same as main category)
        if (group.parentId == selectedCategoryId) {
            val backgroundColor = android.graphics.Color.argb(50, 128, 128, 128)
            headerLayout.setBackgroundColor(backgroundColor)
        }
        
        container.addView(headerLayout)
        
        // Add subcategories container with reduced left margin
        val subcategoriesContainer = android.widget.LinearLayout(context)
        subcategoriesContainer.orientation = android.widget.LinearLayout.VERTICAL
        subcategoriesContainer.visibility = if (group.isExpanded) View.VISIBLE else View.GONE
        // Reduced left padding for subcategories
        val subcategoriesParams = ViewGroup.MarginLayoutParams(
            ViewGroup.MarginLayoutParams.MATCH_PARENT,
            ViewGroup.MarginLayoutParams.WRAP_CONTENT
        ).apply {
            setMargins(margin * (1 + indentLevel + 1), 0, 0, 0)
        }
        subcategoriesContainer.layoutParams = subcategoriesParams
        container.addView(subcategoriesContainer)
        
        // Store reference to subcategoriesContainer in expandIndicator tag
        expandIndicator.tag = subcategoriesContainer
        
        // Render initial content
        renderNestedGroupContent(group, subcategoriesContainer, context, expandIndicator)
        
        return container
    }
    
    private fun renderNestedGroupContent(
        group: CategoryGroup,
        container: ViewGroup,
        context: android.content.Context,
        expandIndicator: TextView
    ) {
        container.removeAllViews()
        
        if (!group.isExpanded) {
            container.visibility = View.GONE
            return
        }
        
        container.visibility = View.VISIBLE
        
        group.subcategories.forEach { node ->
            when (node) {
                is CategoryNode.Leaf -> {
                    // Render as radio button
                    val radioButton = RadioButton(context)
                    radioButton.text = node.item.name
                    radioButton.tag = node.item.id
                    radioButton.textSize = 14f
                    radioButton.id = View.generateViewId()
                    
                    // Check if this subcategory is selected
                    if (node.item.id == selectedCategoryId) {
                        radioButton.isChecked = true
                    }
                    
                    val margin = (8 * context.resources.displayMetrics.density).toInt()
                    val indentLevel = group.level + 1
                    // Fix text color for dark mode
                    val typedArrayText = context.obtainStyledAttributes(intArrayOf(android.R.attr.textColorPrimary))
                    val textColor = typedArrayText.getColor(0, 0)
                    typedArrayText.recycle()
                    if (textColor != 0) {
                        radioButton.setTextColor(textColor)
                    }
                    // Reduced left padding, no right margin
                    val layoutParams = ViewGroup.MarginLayoutParams(
                        ViewGroup.MarginLayoutParams.MATCH_PARENT,
                        ViewGroup.MarginLayoutParams.WRAP_CONTENT
                    ).apply {
                        setMargins(margin * (1 + indentLevel), margin, 0, margin)
                    }
                    radioButton.layoutParams = layoutParams
                    
                    radioButton.setOnClickListener {
                        val subcategoryId = node.item.id
                        if (subcategoryId != null) {
                            selectCategory(subcategoryId, node.item.name)
                        }
                    }
                    
                    container.addView(radioButton)
                }
                is CategoryNode.Group -> {
                    // Check if nested group has only one option - if so, render as radio button
                    val singleLeaf = hasSingleLeafOption(node.group)
                    if (singleLeaf != null && node.group.parentId == null) {
                        // Render as radio button instead of dropdown
                        val radioButton = RadioButton(context)
                        radioButton.text = singleLeaf.name
                        radioButton.tag = singleLeaf.id
                        radioButton.textSize = 14f
                        radioButton.id = View.generateViewId()
                        
                        if (singleLeaf.id == selectedCategoryId) {
                            radioButton.isChecked = true
                        }
                        
                        val margin = (8 * context.resources.displayMetrics.density).toInt()
                        val indentLevel = group.level + 1
                        // Fix text color for dark mode
                        val typedArrayText = context.obtainStyledAttributes(intArrayOf(android.R.attr.textColorPrimary))
                        val textColor = typedArrayText.getColor(0, 0)
                        typedArrayText.recycle()
                        if (textColor != 0) {
                            radioButton.setTextColor(textColor)
                        }
                        // Reduced left padding, no right margin
                        val layoutParams = ViewGroup.MarginLayoutParams(
                            ViewGroup.MarginLayoutParams.MATCH_PARENT,
                            ViewGroup.MarginLayoutParams.WRAP_CONTENT
                        ).apply {
                            setMargins(margin * (1 + indentLevel), margin, 0, margin)
                        }
                        radioButton.layoutParams = layoutParams
                        
                        radioButton.setOnClickListener {
                            val subcategoryId = singleLeaf.id
                            if (subcategoryId != null) {
                                selectCategory(subcategoryId, singleLeaf.name)
                            }
                        }
                        
                        container.addView(radioButton)
                    } else {
                        // Recursively render nested group
                        val nestedGroupView = renderNestedGroup(node.group, context)
                        container.addView(nestedGroupView)
                    }
                }
            }
        }
    }
    
    fun selectCategory(categoryId: String?, categoryName: String?) {
        // Guard against null values
        if (categoryId == null || categoryName == null) {
            return
        }
        
        // Prevent infinite recursion - only call callback if selection actually changed
        if (selectedCategoryId == categoryId) {
            return
        }
        
        selectedCategoryId = categoryId
        notifyDataSetChanged() // Refresh all items to update selection highlighting
        onCategorySelected(categoryId, categoryName)
    }
    
    fun setSelectedCategory(categoryId: String?) {
        selectedCategoryId = categoryId
        notifyDataSetChanged()
    }
    
    fun getSelectedCategoryId(): String? = selectedCategoryId
    
    // Recursively expand all groups
    private fun expandGroupRecursive(group: CategoryGroup) {
        group.isExpanded = true
        group.subcategories.forEach { node ->
            if (node is CategoryNode.Group) {
                expandGroupRecursive(node.group)
            }
        }
    }
    
    // Recursively collapse all groups
    private fun collapseGroupRecursive(group: CategoryGroup) {
        group.isExpanded = false
        group.subcategories.forEach { node ->
            if (node is CategoryNode.Group) {
                collapseGroupRecursive(node.group)
            }
        }
    }
    
    fun expandAll() {
        categories.forEach { expandGroupRecursive(it) }
        notifyDataSetChanged()
    }
    
    fun collapseAll() {
        categories.forEach { collapseGroupRecursive(it) }
        notifyDataSetChanged()
    }
    
    // Recursively check if a group or any of its children match the search term
    private fun groupMatchesSearch(group: CategoryGroup, term: String): Boolean {
        // Check parent name
        if (group.parentName.lowercase().contains(term)) {
            return true
        }
        
        // Check subcategories recursively
        return group.subcategories.any { node ->
            when (node) {
                is CategoryNode.Leaf -> node.item.name.lowercase().contains(term)
                is CategoryNode.Group -> groupMatchesSearch(node.group, term)
            }
        }
    }
    
    // Recursively set visibility and expand matching groups
    private fun filterGroupRecursive(group: CategoryGroup, term: String) {
        val matches = groupMatchesSearch(group, term)
        group.isVisible = matches
        
        if (matches && term.isNotEmpty()) {
            // Expand if matches search
            group.isExpanded = true
        }
        
        // Recursively filter nested groups
        group.subcategories.forEach { node ->
            if (node is CategoryNode.Group) {
                filterGroupRecursive(node.group, term)
            }
        }
    }
    
    fun filterCategories(searchTerm: String) {
        val term = searchTerm.lowercase().trim()
        
        if (term.isEmpty()) {
            // Show all and reset expansion
            categories.forEach { group ->
                group.isVisible = true
                resetExpansionRecursive(group)
            }
        } else {
            categories.forEach { group ->
                filterGroupRecursive(group, term)
            }
        }
        
        notifyDataSetChanged()
    }
    
    // Reset expansion state recursively
    private fun resetExpansionRecursive(group: CategoryGroup) {
        group.isExpanded = false
        group.subcategories.forEach { node ->
            if (node is CategoryNode.Group) {
                resetExpansionRecursive(node.group)
            }
        }
    }
    
    fun updateCategories(newCategories: List<CategoryGroup>) {
        categories.clear()
        categories.addAll(newCategories)
        notifyDataSetChanged()
    }
}
