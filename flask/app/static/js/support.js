/**
 * Support Tickets JavaScript
 * Handles client-side functionality for the support ticket system
 */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize support functionality
    initSupportSystem();
});

function initSupportSystem() {
    // Initialize tooltips
    initTooltips();
    
    // Initialize form validation
    initFormValidation();
    
    // Initialize auto-save for forms
    initAutoSave();
    
    // Initialize real-time updates
    initRealTimeUpdates();
    
    // Initialize keyboard shortcuts
    initKeyboardShortcuts();
}

function initTooltips() {
    // Initialize Bootstrap tooltips if available
    if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
        var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }
}

function initFormValidation() {
    // Add real-time validation to forms
    const forms = document.querySelectorAll('form[data-validate]');
    forms.forEach(form => {
        const inputs = form.querySelectorAll('input, textarea, select');
        inputs.forEach(input => {
            input.addEventListener('blur', function() {
                validateField(this);
            });
            
            input.addEventListener('input', function() {
                clearFieldError(this);
            });
        });
        
        form.addEventListener('submit', function(e) {
            if (!validateForm(this)) {
                e.preventDefault();
            }
        });
    });
}

function validateField(field) {
    const value = field.value.trim();
    const fieldName = field.name;
    let isValid = true;
    let errorMessage = '';
    
    // Clear previous errors
    clearFieldError(field);
    
    // Required field validation
    if (field.hasAttribute('required') && !value) {
        isValid = false;
        errorMessage = `${getFieldLabel(field)} is required`;
    }
    
    // Length validation
    if (value && field.hasAttribute('maxlength')) {
        const maxLength = parseInt(field.getAttribute('maxlength'));
        if (value.length > maxLength) {
            isValid = false;
            errorMessage = `${getFieldLabel(field)} must be ${maxLength} characters or less`;
        }
    }
    
    // Email validation
    if (field.type === 'email' && value) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(value)) {
            isValid = false;
            errorMessage = 'Please enter a valid email address';
        }
    }
    
    // Show error if invalid
    if (!isValid) {
        showFieldError(field, errorMessage);
    }
    
    return isValid;
}

function validateForm(form) {
    const inputs = form.querySelectorAll('input, textarea, select');
    let isFormValid = true;
    
    inputs.forEach(input => {
        if (!validateField(input)) {
            isFormValid = false;
        }
    });
    
    return isFormValid;
}

function getFieldLabel(field) {
    const label = field.closest('.form-group')?.querySelector('label');
    return label ? label.textContent.replace('*', '').trim() : field.name;
}

function showFieldError(field, message) {
    const formGroup = field.closest('.form-group');
    if (!formGroup) return;
    
    // Remove existing error
    clearFieldError(field);
    
    // Add error class
    field.classList.add('is-invalid');
    
    // Create error message
    const errorDiv = document.createElement('div');
    errorDiv.className = 'invalid-feedback';
    errorDiv.textContent = message;
    
    formGroup.appendChild(errorDiv);
}

function clearFieldError(field) {
    const formGroup = field.closest('.form-group');
    if (!formGroup) return;
    
    // Remove error class
    field.classList.remove('is-invalid');
    
    // Remove error message
    const errorDiv = formGroup.querySelector('.invalid-feedback');
    if (errorDiv) {
        errorDiv.remove();
    }
}

function initAutoSave() {
    // Auto-save draft messages
    const messageTextareas = document.querySelectorAll('textarea[name="body"]');
    messageTextareas.forEach(textarea => {
        const storageKey = `support_draft_${textarea.name}`;
        
        // Load saved draft
        const savedDraft = localStorage.getItem(storageKey);
        if (savedDraft && !textarea.value) {
            textarea.value = savedDraft;
        }
        
        // Save draft on input
        textarea.addEventListener('input', function() {
            if (this.value.trim()) {
                localStorage.setItem(storageKey, this.value);
            } else {
                localStorage.removeItem(storageKey);
            }
        });
        
        // Clear draft on form submit
        const form = textarea.closest('form');
        if (form) {
            form.addEventListener('submit', function() {
                localStorage.removeItem(storageKey);
            });
        }
    });
}

function initRealTimeUpdates() {
    // Auto-refresh ticket lists every 30 seconds
    const ticketLists = document.querySelectorAll('.ticket-list');
    if (ticketLists.length > 0) {
        setInterval(function() {
            refreshTicketList();
        }, 30000);
    }
    
    // Auto-refresh ticket details every 60 seconds
    const ticketDetail = document.querySelector('.ticket-detail');
    if (ticketDetail) {
        setInterval(function() {
            refreshTicketDetail();
        }, 60000);
    }
}

function refreshTicketList() {
    // Only refresh if user is not actively interacting
    if (document.activeElement && 
        (document.activeElement.tagName === 'INPUT' || 
         document.activeElement.tagName === 'TEXTAREA' || 
         document.activeElement.tagName === 'SELECT')) {
        return;
    }
    
    // Make AJAX request to refresh ticket list
    const currentUrl = new URL(window.location);
    currentUrl.searchParams.set('ajax', '1');
    
    fetch(currentUrl.toString())
        .then(response => response.text())
        .then(html => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            const newTicketList = doc.querySelector('.ticket-list');
            const currentTicketList = document.querySelector('.ticket-list');
            
            if (newTicketList && currentTicketList) {
                currentTicketList.innerHTML = newTicketList.innerHTML;
            }
        })
        .catch(error => {
            console.log('Failed to refresh ticket list:', error);
        });
}

function refreshTicketDetail() {
    // Only refresh if user is not actively interacting
    if (document.activeElement && 
        (document.activeElement.tagName === 'INPUT' || 
         document.activeElement.tagName === 'TEXTAREA' || 
         document.activeElement.tagName === 'SELECT')) {
        return;
    }
    
    const ticketId = getTicketIdFromUrl();
    if (!ticketId) return;
    
    // Make AJAX request to refresh ticket detail
    const currentUrl = new URL(window.location);
    currentUrl.searchParams.set('ajax', '1');
    
    fetch(currentUrl.toString())
        .then(response => response.text())
        .then(html => {
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            const newMessages = doc.querySelector('.message-thread');
            const currentMessages = document.querySelector('.message-thread');
            
            if (newMessages && currentMessages) {
                currentMessages.innerHTML = newMessages.innerHTML;
            }
        })
        .catch(error => {
            console.log('Failed to refresh ticket detail:', error);
        });
}

function getTicketIdFromUrl() {
    const pathParts = window.location.pathname.split('/');
    const ticketIndex = pathParts.indexOf('tickets');
    return ticketIndex !== -1 && pathParts[ticketIndex + 1] ? pathParts[ticketIndex + 1] : null;
}

function initKeyboardShortcuts() {
    // Add keyboard shortcuts for common actions
    document.addEventListener('keydown', function(e) {
        // Ctrl/Cmd + N: New ticket
        if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
            e.preventDefault();
            const newTicketLink = document.querySelector('a[href*="/new"]');
            if (newTicketLink) {
                window.location.href = newTicketLink.href;
            }
        }
        
        // Ctrl/Cmd + R: Refresh current page
        if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
            // Let the browser handle this naturally
        }
        
        // Escape: Close modals
        if (e.key === 'Escape') {
            const openModal = document.querySelector('.modal.show');
            if (openModal && typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                const modal = bootstrap.Modal.getInstance(openModal);
                if (modal) {
                    modal.hide();
                }
            }
        }
    });
}

// Utility functions
function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    // Add to page
    document.body.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 5000);
}

function confirmAction(message, callback) {
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        // Use Bootstrap modal for confirmation
        const modalHtml = `
            <div class="modal fade" id="confirmModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">Confirm Action</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            ${message}
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <button type="button" class="btn btn-primary" id="confirmBtn">Confirm</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Remove existing modal
        const existingModal = document.getElementById('confirmModal');
        if (existingModal) {
            existingModal.remove();
        }
        
        // Add new modal
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        
        // Show modal
        const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
        modal.show();
        
        // Handle confirm button
        document.getElementById('confirmBtn').addEventListener('click', function() {
            modal.hide();
            if (callback) callback();
        });
    } else {
        // Fallback to browser confirm
        if (confirm(message)) {
            if (callback) callback();
        }
    }
}

function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) {
        return 'Just now';
    } else if (diffMins < 60) {
        return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;
    } else if (diffHours < 24) {
        return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
    } else if (diffDays < 7) {
        return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
    } else {
        return date.toLocaleDateString();
    }
}

function updateRelativeTimes() {
    const timeElements = document.querySelectorAll('[data-time]');
    timeElements.forEach(element => {
        const timeString = element.getAttribute('data-time');
        if (timeString) {
            element.textContent = formatDate(timeString);
        }
    });
}

// Update relative times on page load and periodically
document.addEventListener('DOMContentLoaded', updateRelativeTimes);
setInterval(updateRelativeTimes, 60000); // Update every minute

// Export functions for global use
window.SupportSystem = {
    showNotification,
    confirmAction,
    formatDate,
    updateRelativeTimes
};
