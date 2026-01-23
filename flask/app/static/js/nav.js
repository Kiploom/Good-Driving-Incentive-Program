// Navbar JavaScript - Hamburger Menu and Drawer Management

(function() {
  'use strict';

  const hamburger = document.getElementById('nav-hamburger');
  const drawer = document.getElementById('mobile-drawer');
  const drawerOverlay = drawer?.querySelector('.drawer-overlay');
  const drawerClose = drawer?.querySelector('.drawer-close');
  const drawerContent = drawer?.querySelector('.drawer-content');
  const body = document.body;

  if (!hamburger || !drawer) {
    return; // Navbar elements not found
  }

  let isOpen = false;
  let focusableElements = [];
  let previousActiveElement = null;

  // Get all focusable elements inside drawer
  function getFocusableElements() {
    if (!drawerContent) return [];
    const selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return Array.from(drawerContent.querySelectorAll(selector)).filter(el => {
      return el.offsetWidth > 0 && el.offsetHeight > 0;
    });
  }

  // Focus trap
  function trapFocus(e) {
    if (!isOpen) return;

    focusableElements = getFocusableElements();
    if (focusableElements.length === 0) return;

    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];

    if (e.key === 'Tab') {
      if (e.shiftKey) {
        // Shift + Tab
        if (document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        }
      } else {
        // Tab
        if (document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    }
  }

  // Open drawer
  function openDrawer() {
    if (isOpen) return;

    isOpen = true;
    drawer.classList.add('open');
    hamburger.setAttribute('aria-expanded', 'true');
    body.classList.add('drawer-open');

    // Store previous active element
    previousActiveElement = document.activeElement;

    // Get focusable elements
    focusableElements = getFocusableElements();

    // Focus first element or close button
    setTimeout(() => {
      const firstFocusable = drawerClose || focusableElements[0];
      if (firstFocusable) {
        firstFocusable.focus();
      }
    }, 100);

    // Add event listeners
    document.addEventListener('keydown', handleKeyDown);
    drawerContent?.addEventListener('keydown', trapFocus);
  }

  // Close drawer
  function closeDrawer() {
    if (!isOpen) return;

    isOpen = false;
    drawer.classList.remove('open');
    hamburger.setAttribute('aria-expanded', 'false');
    body.classList.remove('drawer-open');

    // Remove event listeners
    document.removeEventListener('keydown', handleKeyDown);
    drawerContent?.removeEventListener('keydown', trapFocus);

    // Return focus to hamburger button
    if (previousActiveElement && previousActiveElement !== hamburger) {
      previousActiveElement.focus();
    } else {
      hamburger.focus();
    }
  }

  // Toggle drawer
  function toggleDrawer() {
    if (isOpen) {
      closeDrawer();
    } else {
      openDrawer();
    }
  }

  // Keyboard handling
  function handleKeyDown(e) {
    if (e.key === 'Escape' && isOpen) {
      e.preventDefault();
      closeDrawer();
    }
  }

  // Event listeners
  hamburger.addEventListener('click', (e) => {
    e.preventDefault();
    toggleDrawer();
  });

  hamburger.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleDrawer();
    }
  });

  if (drawerClose) {
    drawerClose.addEventListener('click', (e) => {
      e.preventDefault();
      closeDrawer();
    });
  }

  if (drawerOverlay) {
    drawerOverlay.addEventListener('click', (e) => {
      if (e.target === drawerOverlay) {
        closeDrawer();
      }
    });
  }

  // Close drawer when clicking on drawer items (navigation)
  const drawerItems = drawerContent?.querySelectorAll('.drawer-item');
  drawerItems?.forEach(item => {
    item.addEventListener('click', () => {
      // Small delay to allow navigation to start
      setTimeout(() => {
        closeDrawer();
      }, 100);
    });
  });

  // Handle window resize - close drawer if it becomes too wide
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (window.innerWidth >= 768 && isOpen) {
        closeDrawer();
      }
    }, 250);
  });

  // Expose close function globally for external use
  window.closeNavDrawer = closeDrawer;
})();

