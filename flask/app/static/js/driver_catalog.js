(() => {
    const els = {
      grid: document.getElementById('grid'),
      status: document.getElementById('status'),
      pageInfo: document.getElementById('page-info'),
      pageInfoTop: document.getElementById('page-info-top'),
      prev: document.getElementById('prev'),
      next: document.getElementById('next'),
      prevTop: document.getElementById('prev-top'),
      nextTop: document.getElementById('next-top'),
      q: document.getElementById('q'),
      sort: document.getElementById('sort'),
      minPts: document.getElementById('min-points'),
      maxPts: document.getElementById('max-points'),
      viewToggleBtn: document.getElementById('view-toggle-btn'),
      searchBtn: document.getElementById('search-btn'),
      cardTpl: document.getElementById('card'),
    };
    const filterToggleBtn = document.getElementById('catalog-filter-toggle');
    const filterModal = document.getElementById('catalog-filter-modal');

    const rootEl = document.getElementById('catalog-root');
    if (!rootEl) {
      console.warn('Catalog root element not found.');
      return;
    }

    const config = {
      mode: rootEl.dataset.mode || 'catalog',
      dataEndpoint: rootEl.dataset.dataEndpoint || '/driver-catalog/data',
      toggleEndpoint: (rootEl.dataset.toggleEndpoint || '/driver-catalog/favorites').replace(/\/$/, ''),
      favoritesOnly: rootEl.dataset.favoritesOnly === 'true',
    };
    const isFavoritesMode = config.mode === 'favorites';

    // Read URL parameters on page load
    function getURLParams() {
      const params = new URLSearchParams(window.location.search);
      return {
        q: params.get('q') || '',
        sort: params.get('sort') || 'best_match',
        page: parseInt(params.get('page')) || 1,
        page_size: 24, // Fixed page size - always 24 items per page
        min_points: params.get('min_points') ? Number(params.get('min_points')) : null,
        max_points: params.get('max_points') ? Number(params.get('max_points')) : null,
        favorites_only: config.favoritesOnly
      };
    }

    const urlParams = getURLParams();

    const state = {
      page: urlParams.page,
      pageSize: 24, // Fixed page size - always 24 items per page
      sort: urlParams.sort,
      q: urlParams.q,
      min_points: urlParams.min_points,
      max_points: urlParams.max_points,
      favorites_only: config.favoritesOnly,
      view_mode: 'grid', // 'grid' or 'list'
      hasMore: false,
      total: null,
    };

    if (isFavoritesMode) {
      state.page = 1;
    }

    // Initialize form fields from URL params
    if (els.q) {
      els.q.value = state.q;
    }
    if (els.sort) {
      els.sort.value = state.sort;
    }
    if (state.min_points !== null && els.minPts) els.minPts.value = state.min_points;
    if (state.max_points !== null && els.maxPts) els.maxPts.value = state.max_points;

    // Update browser URL to persist search state
    function updateBrowserURL() {
      const params = new URLSearchParams();
      if (state.q) params.set('q', state.q);
      params.set('sort', state.sort);
      params.set('page', String(state.page));
      params.set('page_size', String(state.pageSize));
      if (state.min_points !== null && state.min_points !== '') {
        params.set('min_points', String(state.min_points));
      }
      if (state.max_points !== null && state.max_points !== '') {
        params.set('max_points', String(state.max_points));
      }
      if (state.favorites_only) {
        params.set('favorites_only', '1');
      }
      
      const newURL = `${window.location.pathname}?${params.toString()}`;
      window.history.replaceState({}, '', newURL);
    }

    function buildURL() {
      // Use the current dataEndpoint from config (may have been updated by sidebar)
      const endpoint = config.dataEndpoint || '/driver-catalog/data';
      const u = new URL(endpoint, window.location.origin);
      
      // Map points sorting to price sorting for backend (points are derived from prices)
      let backendSort = state.sort;
      if (state.sort === 'points_asc') {
        backendSort = 'price_asc';
      } else if (state.sort === 'points_desc') {
        backendSort = 'price_desc';
      }
      
      // Always update params to match current state (don't check if they exist)
      // This ensures page number changes are reflected in the URL
      // NOTE: page_size is NOT added to URL - it's always 24 and sent in request body/params
      u.searchParams.set('page', String(state.page));
      u.searchParams.set('sort', backendSort);
      
      if (state.q) {
        u.searchParams.set('q', state.q);
      } else {
        u.searchParams.delete('q'); // Remove q if empty
      }

      // Include min/max points when provided
      if (state.min_points !== null && state.min_points !== '') {
        u.searchParams.set('min_points', String(state.min_points));
      } else {
        u.searchParams.delete('min_points'); // Remove if empty
      }
      if (state.max_points !== null && state.max_points !== '') {
        u.searchParams.set('max_points', String(state.max_points));
      } else {
        u.searchParams.delete('max_points'); // Remove if empty
      }
      if (state.favorites_only && !u.searchParams.has('favorites_only')) {
        u.searchParams.set('favorites_only', '1');
      }
      
      return u.toString();
    }

      // Modal elements
    const modal = document.getElementById('item-modal');
    const imgEl = document.getElementById('modal-img');
    const titleEl = document.getElementById('modal-title');
    const costEl = document.getElementById('modal-cost');
    const descEl = document.getElementById('modal-desc');
    const linkEl = document.getElementById('modal-link');
    const addToCartBtn = document.getElementById('modal-add-to-cart');
    const reportBtn = document.getElementById('modal-report-btn');

    // Report modal elements
    const reportModal = document.getElementById('report-modal');
    const reportForm = document.getElementById('report-form');
    const reportReason = document.getElementById('report-reason');
    const reportDescription = document.getElementById('report-description');

    // Helper: best-guess eBay link
    function getEbayLink(item) {
      // First priority: direct URL from eBay API
      if (item.url && typeof item.url === 'string' && item.url.trim()) {
        return item.url.trim();
      }

      // Fallback: construct URL from item ID
      const itemId = item.id || item.itemId || item.ebay_item_id || item.listingId;
      if (itemId) {
        return `https://www.ebay.com/itm/${itemId}`;
      }

      return null;
    }

    function openModal(it) {

      // Title & image
      titleEl.textContent = it.title || '';
      imgEl.src = it.image || '';

      // Driver shows cost in points
      costEl.textContent = (it.points != null) ? `${it.points} pts` : '';

      // Description; fallbacks for eBay fields
      const desc = it.shortDescription || it.subtitle || it.description || '';
      descEl.textContent = desc;

      // Link: show if any usable href can be derived
      const href = getEbayLink(it);
      if (href) {
        linkEl.href = href;
        linkEl.style.display = '';
      } else {
        linkEl.removeAttribute('href');
        linkEl.style.display = 'none';
      }
    
    // Add to Cart button
      if (it.points != null && it.points > 0 && !it.no_stock) {
        addToCartBtn.style.display = '';
        addToCartBtn.disabled = false;
        addToCartBtn.classList.remove('disabled');
        addToCartBtn.setAttribute('aria-label', `Add ${it.title || 'item'} to cart`);
        addToCartBtn.textContent = 'Add to Cart';
        addToCartBtn.onclick = () => addToCart(it);
      } else if (it.points != null && it.points > 0 && it.no_stock) {
        // Show button but disabled when out of stock
        addToCartBtn.style.display = '';
        addToCartBtn.disabled = true;
        addToCartBtn.classList.add('disabled');
        addToCartBtn.setAttribute('aria-label', `${it.title || 'Item'} is out of stock`);
        addToCartBtn.textContent = 'Out of Stock';
        addToCartBtn.onclick = null;
      } else {
        addToCartBtn.style.display = 'none';
      }

      // Store current item data for reporting
      modal.currentItem = it;

      // Show report button
      reportBtn.style.display = '';

      // Finally, show the modal
      modal.classList.remove('hidden');
      }


    function closeModal() {
      modal.classList.add('hidden');
    }

    function openReportModal() {
      reportModal.classList.remove('hidden');
    }

    function closeReportModal() {
      reportModal.classList.add('hidden');
      reportForm.reset();
    }

    modal.addEventListener('click', (e) => {
      if (e.target.dataset.close) closeModal();
    });
    window.addEventListener('keydown', (e) => {
      if (!modal.classList.contains('hidden') && e.key === 'Escape') closeModal();
    });

    // Report modal event listeners
    reportModal.addEventListener('click', (e) => {
      if (e.target.dataset.close) closeReportModal();
    });
    window.addEventListener('keydown', (e) => {
      if (!reportModal.classList.contains('hidden') && e.key === 'Escape') closeReportModal();
    });

    // Report button click
    reportBtn.addEventListener('click', () => {
      closeModal();
      openReportModal();
    });

    // Report form submission
    reportForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const item = modal.currentItem;
      if (!item) return;
      
      const reason = reportReason.value;
      const description = reportDescription.value;
      
      // Get CSRF token from meta tag
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                       document.querySelector('meta[name="csrf-token"]')?.content ||
                       null;
      
      const headers = {
        'Content-Type': 'application/json',
      };
      
      // Add CSRF token to headers if available
      if (csrfToken) {
        headers['X-CSRFToken'] = csrfToken;
      }
      
      try {
        const response = await fetch(`/driver-catalog/report/${item.id}`, {
          method: 'POST',
          headers: headers,
          credentials: 'same-origin',  // Include cookies for CSRF
          body: JSON.stringify({
            reason: reason,
            description: description,
            title: item.title,
            image: item.image,
            url: item.url || `https://www.ebay.com/itm/${item.id}`
          })
        });
        
        const data = await response.json();
        
        if (data.ok) {
          alert('Item reported successfully. Thank you for your feedback!');
          closeReportModal();
        } else {
          alert('Error reporting item: ' + (data.message || 'Unknown error'));
        }
      } catch (error) {
        console.error('Error reporting item:', error);
        alert('Error reporting item. Please try again.');
      }
    });

    function updateEmptyState() {
      if (!els.grid || !els.status) return;
      const hasCards = !!els.grid.querySelector('.card:not(.skeleton)');
      els.status.style.display = hasCards ? 'none' : '';
    }

    const pendingRemovalTimers = new Map();

    function clearPendingRemovalTimers() {
      pendingRemovalTimers.forEach(({ timer, card }) => {
        clearTimeout(timer);
        if (card) {
          const unfav = card.querySelector('.favorite-btn.unfavorite');
          if (unfav) {
            unfav.classList.remove('grace-period');
            unfav.disabled = false;
          }
          const fav = card.querySelector('.favorite-btn.filled');
          if (fav) {
            fav.disabled = false;
          }
        }
      });
      pendingRemovalTimers.clear();
    }

    function render(items) {
      clearPendingRemovalTimers();
      els.grid.innerHTML = '';
      if (!items || items.length === 0) {
        updateEmptyState();
        return;
      }
      els.status.style.display = 'none';

      for (const it of items) {
        const node = els.cardTpl.content.firstElementChild.cloneNode(true);
        
        // Add data-item-id for IntersectionObserver
        node.dataset.itemId = it.id;
        const detailUrl = `/driver-catalog/product/${encodeURIComponent(it.id)}`;
        node.dataset.detailUrl = detailUrl;
        node.setAttribute('aria-label', it.title ? `View details for ${it.title}` : 'View item details');
        
        const img = node.querySelector('img');
        img.src = it.image || '';
        img.loading = 'lazy'; // Native lazy loading for performance
        node.querySelector('.title').textContent = it.title || '';
        const pointsEl = node.querySelector('.points');
        if (pointsEl) {
          const numberEl = pointsEl.querySelector('.number');
          const labelEl = pointsEl.querySelector('.label');
          if (numberEl && labelEl) {
            numberEl.textContent = it.points != null ? it.points.toString() : '';
            labelEl.textContent = ' pts';
          } else {
            // Fallback for old structure
            pointsEl.textContent = (it.points != null ? `${it.points} pts` : '');
          }
        }
        const pinnedBadge = node.querySelector('[data-pinned]');
        const lowStockBadge = node.querySelector('[data-low-stock]');
        const noStockBadge = node.querySelector('[data-no-stock]');
        const favoriteBtn = node.querySelector('[data-favorite]');
        const unfavoriteBtn = node.querySelector('[data-unfavorite]');
        
        // Show pinned badge for sponsor-recommended products
        if (pinnedBadge) {
          pinnedBadge.style.display = it.is_pinned ? '' : 'none';
        }
        
        // Show low stock badges
        if (lowStockBadge) {
          if (it.low_stock && it.stock_qty !== null) {
            lowStockBadge.textContent = `Low stock (${it.stock_qty})`;
            lowStockBadge.style.display = '';
          } else if (it.low_stock) {
            lowStockBadge.textContent = 'Low stock';
            lowStockBadge.style.display = '';
          } else {
            lowStockBadge.style.display = 'none';
          }
        }
        
        if (noStockBadge) {
          noStockBadge.style.display = it.no_stock ? '' : 'none';
        }
        
        // Show appropriate favorite button
        if (it.is_favorite) {
          favoriteBtn.style.display = '';
          unfavoriteBtn.style.display = 'none';
        } else {
          favoriteBtn.style.display = 'none';
          unfavoriteBtn.style.display = '';
        }

        // Add favorite button event listeners
        // favoriteBtn (filled heart) = already favorited, click to REMOVE
        favoriteBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          toggleFavorite(it.id, true, it, favoriteBtn, unfavoriteBtn, node);  // true = is currently favorite, so DELETE
        });
        
        // unfavoriteBtn (empty heart) = not favorited, click to ADD
        unfavoriteBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          toggleFavorite(it.id, false, it, favoriteBtn, unfavoriteBtn, node);  // false = not currently favorite, so POST
        });

        // Add to Cart functionality
        const addToCartBtn = node.querySelector('.add-to-cart-btn');
        if (addToCartBtn) {
          if (it.points != null && it.points > 0 && !it.no_stock) {
            addToCartBtn.style.display = '';
            addToCartBtn.disabled = false;
            addToCartBtn.classList.remove('disabled');
            addToCartBtn.setAttribute('aria-label', `Add ${it.title || 'item'} to cart`);
            addToCartBtn.addEventListener('click', (e) => {
              e.preventDefault();
              e.stopPropagation();
              triggerAddToCartAnimation(addToCartBtn);
              addToCart(it);
            });
          } else if (it.points != null && it.points > 0 && it.no_stock) {
            // Show button but disabled when out of stock
            addToCartBtn.style.display = '';
            addToCartBtn.disabled = true;
            addToCartBtn.classList.add('disabled');
            addToCartBtn.setAttribute('aria-label', `${it.title || 'Item'} is out of stock`);
            // Remove any existing click listeners to prevent adding to cart
            const newBtn = addToCartBtn.cloneNode(true);
            addToCartBtn.parentNode.replaceChild(newBtn, addToCartBtn);
          } else {
            addToCartBtn.style.display = 'none';
          }
        }

        const handleCardActivate = () => {
          window.location.href = detailUrl;
        };

        node.addEventListener('click', () => {
          handleCardActivate();
        });

        node.addEventListener('keydown', (event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleCardActivate();
          }
        });

        els.grid.appendChild(node);
      }
      updateEmptyState();
    }

    function triggerAddToCartAnimation(button) {
      if (!button) return;
      const defaultLabel = button.dataset.defaultLabel || button.getAttribute('aria-label') || 'Add to cart';
      button.dataset.defaultLabel = defaultLabel;
      button.classList.remove('animating');
      // Force reflow so the animation can replay
      void button.offsetWidth;
      button.classList.add('animating');
      button.setAttribute('aria-label', 'Added to cart');
      setTimeout(() => {
        button.classList.remove('animating');
        button.setAttribute('aria-label', defaultLabel);
      }, 1200);
    }

    // AbortController for cancelling in-flight requests
    let currentAbortController = null;
    
    // Track scroll position before reload
    let savedScrollPosition = 0;
    
    // Debounce helper: delays function execution until after wait milliseconds
    function debounce(func, wait) {
      let timeout;
      return function executedFunction(...args) {
        const later = () => {
          clearTimeout(timeout);
          func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
      };
    }

    async function load(maintainScroll = false) {
      // PERFORMANCE TIMER: Start timing the page load
      const loadStartTime = performance.now();
      console.log(`[PERF] Starting page load - Page ${state.page}, Query: "${state.q || '(none)'}"`);
      
      // Save scroll position before loading (for re-search)
      if (maintainScroll) {
        savedScrollPosition = window.scrollY;
      }
      
      // Build URL
      const url = buildURL();
      const urlObj = new URL(url);
      urlObj.searchParams.set('fast', '1');  // Fast mode by default
      urlObj.searchParams.set('page_size', String(state.pageSize));  // Add page_size for request
      
      // Show skeleton loaders while loading
      showSkeletonLoaders();
      
      // Disable pagination buttons during loading
      disablePaginationButtons(true);
      
      // Cancel any in-flight request
      if (currentAbortController) {
        currentAbortController.abort();
      }
      
      // Create new abort controller for this request
      currentAbortController = new AbortController();
      
      els.grid.setAttribute('aria-busy', 'true');
      updateBrowserURL(); // Update URL to persist state
      
      const fetchStartTime = performance.now();
      try {
        // URL already built above for cache check
        // urlObj already has 'fast=1' parameter
        // Add page_size to request URL (but not visible in browser URL - it's always 24)
        urlObj.searchParams.set('page_size', String(state.pageSize));
        
        const resp = await fetch(urlObj.toString(), {
          signal: currentAbortController.signal
        });
        
        const data = await resp.json();
        const items = data.items || [];
        
        render(items);
        updatePagination(data);
        
        // Restore scroll position if needed
        if (maintainScroll && savedScrollPosition) {
          requestAnimationFrame(() => {
            window.scrollTo(0, savedScrollPosition);
          });
        }
      } catch (e) {
        // Don't show error if request was aborted (user typed again)
        if (e.name === 'AbortError') {
          console.log('[PERF] Request cancelled');
          return;
        }
        els.status.style.display = '';
        els.status.textContent = 'Failed to load items.';
      } finally {
        els.grid.removeAttribute('aria-busy');
        disablePaginationButtons(false);
        currentAbortController = null;
      }
    }
    
    // Helper function to update pagination UI
    function updatePagination(data) {
      state.hasMore = !!data.has_more;
      state.total = data.total ?? null;
      
      // Show only current page number (no total pages)
      const pageText = `Page ${state.page}`;
      if (els.pageInfo) {
        els.pageInfo.textContent = pageText;
      }
      if (els.pageInfoTop) {
        els.pageInfoTop.textContent = pageText;
      }
      
      // Update button states for both pagers
      if (els.prev) {
        els.prev.disabled = state.page <= 1;
      }
      if (els.next) {
        els.next.disabled = !state.hasMore;  // Disable next if no more pages
      }
      if (els.prevTop) {
        els.prevTop.disabled = state.page <= 1;
      }
      if (els.nextTop) {
        els.nextTop.disabled = !state.hasMore;  // Disable next if no more pages
      }
    }
    
    // Show skeleton loaders while fetching data
    function showSkeletonLoaders() {
      els.grid.innerHTML = '';
      els.status.style.display = 'none';
      
      // Create 14 skeleton cards
      for (let i = 0; i < state.pageSize; i++) {
        const skeleton = document.createElement('li');
        skeleton.className = 'card skeleton';
        skeleton.innerHTML = `
          <div class="card-image-wrapper">
            <div style="width: 100%; aspect-ratio: 4/3; background: var(--bg-hover);"></div>
          </div>
          <div class="card-body">
            <div class="title" style="height: 60px;"></div>
            <div class="meta">
              <span class="points" style="width: 80px; height: 28px;"></span>
              <div class="action-buttons">
                <span class="btn" style="width: 100px; height: 36px;"></span>
              </div>
            </div>
          </div>
        `;
        els.grid.appendChild(skeleton);
      }
    }
    
    // Disable/enable pagination buttons during loading
    function disablePaginationButtons(disabled) {
      if (els.prev) {
        els.prev.disabled = disabled || state.page <= 1;
      }
      if (els.next) {
        els.next.disabled = disabled;
      }
      if (els.prevTop) {
        els.prevTop.disabled = disabled || state.page <= 1;
      }
      if (els.nextTop) {
        els.nextTop.disabled = disabled;
      }
      
      // Add loading class to pagers
      const pagers = document.querySelectorAll('.pager');
      pagers.forEach(pager => {
        if (disabled) {
          pager.classList.add('loading');
        } else {
          pager.classList.remove('loading');
        }
      });
    }
    
    // Wire controls
    if (els.searchBtn) {
      els.searchBtn.addEventListener('click', () => {
        state.q = els.q ? els.q.value.trim() : '';
        state.min_points = els.minPts && els.minPts.value ? Number(els.minPts.value) : null;
        state.max_points = els.maxPts && els.maxPts.value ? Number(els.maxPts.value) : null;
        state.page = 1;
        
        // If we're on recommended products page and a search query is provided,
        // switch to searching all products instead of showing recommended products
        const isRecommendedMode = config.dataEndpoint && config.dataEndpoint.includes('/recommended-data');
        if (isRecommendedMode && state.q) {
          // Switch to data endpoint to search all products
          config.dataEndpoint = '/driver-catalog/data';
          const rootEl = document.getElementById('catalog-root');
          if (rootEl) {
            rootEl.dataset.dataEndpoint = config.dataEndpoint;
          }
          // Update browsing indicator to show search results
          const browsingIndicator = document.getElementById('browsing-indicator');
          const browsingCategoryName = document.getElementById('browsing-category-name');
          if (browsingIndicator && browsingCategoryName) {
            browsingCategoryName.textContent = `Search results for "${state.q}"`;
            const browsingText = document.getElementById('browsing-text');
            if (browsingText) {
              browsingText.style.display = '';
            }
          }
          // Remove active state from recommended button
          const recommendedBtn = document.getElementById('sidebar-recommended-btn');
          if (recommendedBtn) {
            recommendedBtn.classList.remove('active');
          }
        } else if (isRecommendedMode && !state.q) {
          // If search is cleared, go back to recommended products
          config.dataEndpoint = '/driver-catalog/recommended-data';
          const rootEl = document.getElementById('catalog-root');
          if (rootEl) {
            rootEl.dataset.dataEndpoint = config.dataEndpoint;
          }
          // Update browsing indicator back to recommended
          const browsingIndicator = document.getElementById('browsing-indicator');
          const browsingCategoryName = document.getElementById('browsing-category-name');
          if (browsingIndicator && browsingCategoryName) {
            browsingCategoryName.textContent = 'Recommended Products';
          }
          // Restore active state on recommended button
          const recommendedBtn = document.getElementById('sidebar-recommended-btn');
          if (recommendedBtn) {
            recommendedBtn.classList.add('active');
          }
        }
        
        load();
      });
    }

    if (filterToggleBtn && filterModal) {
      const closeButtons = Array.from(filterModal.querySelectorAll('[data-close]'));

      const showModal = () => {
        filterModal.classList.remove('hidden');
        filterToggleBtn.setAttribute('aria-expanded', 'true');
        document.body.style.overflow = 'hidden';
      };

      const hideModal = () => {
        filterModal.classList.add('hidden');
        filterToggleBtn.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
      };

      const toggleModal = () => {
        if (filterModal.classList.contains('hidden')) {
          showModal();
        } else {
          hideModal();
        }
      };

      filterToggleBtn.addEventListener('click', toggleModal);
      closeButtons.forEach(btn => btn.addEventListener('click', hideModal));

      filterModal.addEventListener('click', (event) => {
        if (event.target === filterModal) {
          hideModal();
        }
      });

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !filterModal.classList.contains('hidden')) {
          hideModal();
        }
      });

      hideModal();
    }

    if (els.sort) {
      els.sort.addEventListener('change', () => {
        state.sort = els.sort.value;
        state.page = 1;
        load();
      });
    }

    // Debounced load for input fields (250ms delay) - maintains scroll position
    const debouncedLoad = debounce(() => {
      state.page = 1;
      load(true); // Maintain scroll position for re-search
    }, 250);
    
    // Search input: trigger on Enter key press only
    if (els.q) {
      els.q.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          state.q = els.q.value.trim();
          state.page = 1;
          
          // If we're on recommended products page and a search query is provided,
          // switch to searching all products instead of showing recommended products
          const isRecommendedMode = config.dataEndpoint && config.dataEndpoint.includes('/recommended-data');
          if (isRecommendedMode && state.q) {
            // Switch to data endpoint to search all products
            config.dataEndpoint = '/driver-catalog/data';
            const rootEl = document.getElementById('catalog-root');
            if (rootEl) {
              rootEl.dataset.dataEndpoint = config.dataEndpoint;
            }
            // Update browsing indicator to show search results
            const browsingIndicator = document.getElementById('browsing-indicator');
            const browsingCategoryName = document.getElementById('browsing-category-name');
            if (browsingIndicator && browsingCategoryName) {
              browsingCategoryName.textContent = `Search results for "${state.q}"`;
              const browsingText = document.getElementById('browsing-text');
              if (browsingText) {
                browsingText.style.display = '';
              }
            }
            // Remove active state from recommended button
            const recommendedBtn = document.getElementById('sidebar-recommended-btn');
            if (recommendedBtn) {
              recommendedBtn.classList.remove('active');
            }
          } else if (isRecommendedMode && !state.q) {
            // If search is cleared, go back to recommended products
            config.dataEndpoint = '/driver-catalog/recommended-data';
            const rootEl = document.getElementById('catalog-root');
            if (rootEl) {
              rootEl.dataset.dataEndpoint = config.dataEndpoint;
            }
            // Update browsing indicator back to recommended
            const browsingIndicator = document.getElementById('browsing-indicator');
            const browsingCategoryName = document.getElementById('browsing-category-name');
            if (browsingIndicator && browsingCategoryName) {
              browsingCategoryName.textContent = 'Recommended Products';
            }
            // Restore active state on recommended button
            const recommendedBtn = document.getElementById('sidebar-recommended-btn');
            if (recommendedBtn) {
              recommendedBtn.classList.add('active');
            }
          }
          
          load(true); // Maintain scroll position
        }
      });
    }
    
    // Min/Max points inputs with debounce
    if (els.minPts) {
      els.minPts.addEventListener('input', () => {
        const val = els.minPts.value;
        state.min_points = (val && val.trim()) ? Number(val) : null;
        debouncedLoad();
      });
    }

    if (els.maxPts) {
      els.maxPts.addEventListener('input', () => {
        const val = els.maxPts.value;
        state.max_points = (val && val.trim()) ? Number(val) : null;
        debouncedLoad();
      });
    }


    // View toggle functionality
    if (els.viewToggleBtn && els.grid) {
      const updateToggleButton = (mode) => {
        const isGrid = mode === 'grid';
        els.viewToggleBtn.textContent = isGrid ? '⊞' : '☰';
        const label = isGrid ? 'Switch to list view' : 'Switch to grid view';
        els.viewToggleBtn.title = label;
        els.viewToggleBtn.setAttribute('aria-label', label);
        els.viewToggleBtn.setAttribute('aria-pressed', String(isGrid));
        els.viewToggleBtn.classList.toggle('active', isGrid);
      };

      const setViewMode = (mode) => {
        state.view_mode = mode;
        if (mode === 'grid') {
          els.grid.classList.remove('list-view');
        } else {
          els.grid.classList.add('list-view');
        }
        updateToggleButton(mode);
      };

      els.viewToggleBtn.addEventListener('click', () => {
        const nextMode = state.view_mode === 'grid' ? 'list' : 'grid';
        setViewMode(nextMode);
      });

      setViewMode(state.view_mode);
    }

    function getCsrfToken() {
      const metaToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
      if (metaToken) {
        return metaToken;
      }
      const cookie = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrf_token='));
      return cookie ? cookie.split('=')[1] : null;
    }

    // Favorites functionality
    async function toggleFavorite(itemId, isFavorite, itemData, favoriteBtn, unfavoriteBtn, cardEl) {
      const url = `${config.toggleEndpoint}/${itemId}`;
      const method = isFavorite ? 'DELETE' : 'POST';
      const csrfToken = getCsrfToken();

      // Immediately update UI for instant feedback
      if (isFavorite) {
        favoriteBtn.style.display = 'none';
        unfavoriteBtn.style.display = '';
      } else {
        favoriteBtn.style.display = '';
        unfavoriteBtn.style.display = 'none';
      }

      favoriteBtn.disabled = true;
      unfavoriteBtn.disabled = true;
      if (isFavoritesMode && isFavorite) {
        unfavoriteBtn.classList.add('grace-period');
      }

      const headers = {
        'Accept': 'application/json',
      };
      if (method === 'POST') {
        headers['Content-Type'] = 'application/json';
      }
      if (csrfToken) {
        headers['X-CSRFToken'] = csrfToken;
      }

      try {
        const response = await fetch(url, {
          method,
          headers,
          credentials: 'same-origin',
          body: method === 'POST'
            ? JSON.stringify({
                title: itemData.title,
                image: itemData.image,
                points: itemData.points
              })
            : undefined
        });

        const isJson = response.headers.get('content-type')?.includes('application/json');
        const data = isJson ? await response.json() : null;

        if (!response.ok || !data?.ok) {
          const message = data?.message || `Request failed with status ${response.status}`;
          throw new Error(message);
        }

        if (isFavoritesMode && isFavorite) {
          const pending = pendingRemovalTimers.get(itemId);
          if (pending) {
            clearTimeout(pending.timer);
          }

          const timer = setTimeout(() => {
            const record = pendingRemovalTimers.get(itemId);
            if (!record) {
              return;
            }
            pendingRemovalTimers.delete(itemId);
            const targetCard = record.card ?? favoriteBtn.closest('.card');
            if (targetCard && targetCard.parentElement) {
              targetCard.parentElement.removeChild(targetCard);
              updateEmptyState();
            }
          }, 5000);

          pendingRemovalTimers.set(itemId, { timer, card: cardEl });
          unfavoriteBtn.disabled = false;
          favoriteBtn.disabled = false;
        } else if (isFavoritesMode && !isFavorite) {
          const pending = pendingRemovalTimers.get(itemId);
          if (pending) {
            clearTimeout(pending.timer);
            pendingRemovalTimers.delete(itemId);
          }
          unfavoriteBtn.classList.remove('grace-period');
        }
      } catch (error) {
        console.error('Error toggling favorite:', error);
        if (isFavorite) {
          favoriteBtn.style.display = '';
          unfavoriteBtn.style.display = 'none';
        } else {
          favoriteBtn.style.display = 'none';
          unfavoriteBtn.style.display = '';
        }
        unfavoriteBtn.classList.remove('grace-period');
        const pending = pendingRemovalTimers.get(itemId);
        if (pending) {
          clearTimeout(pending.timer);
          pendingRemovalTimers.delete(itemId);
        }
        alert('Failed to update favorite: ' + error.message);
      } finally {
        if (!isFavoritesMode || !isFavorite) {
          favoriteBtn.disabled = false;
          unfavoriteBtn.disabled = false;
        }
      }
    }

    if (els.prev) {
      els.prev.addEventListener('click', () => {
        if (state.page > 1) {
          state.page -= 1;
          load();
        }
      });
    }

    if (els.next) {
      els.next.addEventListener('click', () => {
        state.page += 1;
        load();
      });
    }

    // Top pager buttons (same functionality)
    if (els.prevTop) {
      els.prevTop.addEventListener('click', () => {
        if (state.page > 1) {
          state.page -= 1;
          load();
          // Scroll to top for better UX
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
      });
    }
    if (els.nextTop) {
      els.nextTop.addEventListener('click', () => {
        state.page += 1;
        load();
        // Scroll to top for better UX
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }

    // Add to Cart function
async function addToCart(item) {
  console.log('Adding to cart:', item);
  
  // Prevent adding out-of-stock items
  if (item.no_stock) {
    alert('This item is currently out of stock.');
    return;
  }
  
  try {
    const cartData = {
      external_item_id: item.id || item.itemId || item.ebay_item_id || item.listingId,
      item_title: item.title || '',
      item_image_url: item.image || '',
      item_url: item.url || item.view_url || '',
      points_per_unit: item.points || 0,
      quantity: 1
    };
    
    // Get CSRF token from meta tag or cookie
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || 
                     document.cookie.split('; ').find(row => row.startsWith('csrf_token='))?.split('=')[1];
    
    const headers = {
      'Content-Type': 'application/json',
    };
    
    if (csrfToken) {
      headers['X-CSRFToken'] = csrfToken;
    }
    
    const response = await fetch('/cart/add', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(cartData)
    });
    
    // Check if response is JSON
    const contentType = response.headers.get('content-type');
    if (!contentType || !contentType.includes('application/json')) {
      const text = await response.text();
      throw new Error(`Server returned HTML instead of JSON. Status: ${response.status}. Response: ${text.substring(0, 200)}...`);
    }
    
    const data = await response.json();
    console.log('Response data:', data);

    if (data.success) {
      // Update cart count
      if (typeof updateCartCount === 'function') {
        updateCartCount();
      }
      console.log('Item added to cart successfully.');
    } else {
      alert('Error: ' + (data.error || 'Unknown error'));
    }
  } catch (error) {
    console.error('Error adding to cart:', error);
    alert('An error occurred while adding the item to cart: ' + error.message);
  }
}

    // Initial load
    load();
    
    // Expose load function for sidebar integration
    window.driverCatalogLoad = load;
    window.driverCatalogState = state;
    window.driverCatalogConfig = config;
  })();
