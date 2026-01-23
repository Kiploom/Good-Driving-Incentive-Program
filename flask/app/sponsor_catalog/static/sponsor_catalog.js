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
      sort: document.getElementById('sort'), // May not exist - sidebar sort is primary
      minPrice: document.getElementById('sidebar-min-price'),
      maxPrice: document.getElementById('sidebar-max-price'),
      viewToggleBtn: document.getElementById('view-toggle-btn'),
      searchBtn: document.getElementById('search-btn'),
      cardTpl: document.getElementById('card'),
      filterSet: document.getElementById('sidebar-filter-set'),
      recommendedBtn: document.getElementById('sidebar-recommended-btn'),
    };
    const filterToggleBtn = document.getElementById('catalog-filter-toggle');
    const sidebar = document.getElementById('catalog-sidebar');
    const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');
    const sidebarExpandBtn = document.getElementById('sidebar-expand-btn');
    
    const rootEl = document.getElementById('catalog-root');
    if (!rootEl) {
      return;
    }

    const config = {
      mode: rootEl.dataset.mode || 'catalog',
      dataEndpoint: rootEl.dataset.dataEndpoint || '/sponsor-catalog/preview/data',
    };

    // Read URL parameters on page load
    function getURLParams() {
      const params = new URLSearchParams(window.location.search);
      return {
        q: params.get('q') || '',
        sort: params.get('sort') || 'best_match',
        page: parseInt(params.get('page')) || 1,
        page_size: 24,
        min_price: params.get('min_price') ? Number(params.get('min_price')) : null,
        max_price: params.get('max_price') ? Number(params.get('max_price')) : null,
        category_id: params.get('category_id') || null,
      };
    }

    const urlParams = getURLParams();
    
    // Fetch active filter set from backend
    let activeFilterSetId = null;
    async function loadActiveFilterSet() {
      try {
        const response = await fetch('/sponsor-catalog/active-set.json', {
          credentials: 'same-origin'
        });
        if (response.ok) {
          const data = await response.json();
          activeFilterSetId = data.selected_filter_set_id || null;
        } else {
          activeFilterSetId = '__recommended_only__';
        }
      } catch (error) {
        activeFilterSetId = '__recommended_only__';
      }
    }

    // Initialize state - filter_set_id will be set after loading active filter set
    // Don't set filter_set_id from URL params on initial load - user must select a browsing option
    const state = {
      page: urlParams.page,
      pageSize: 24,
      sort: urlParams.sort,
      q: urlParams.q,
      min_price: urlParams.min_price,
      max_price: urlParams.max_price,
      filter_set_id: null, // Will be set when user selects a browsing option
      category_id: null, // Don't load from URL on initial load - user must select
      recommended_mode: false,
      view_mode: 'grid',
      hasMore: false,
      total: null,
    };

    // Initialize form fields from URL params
    if (els.q) {
      els.q.value = state.q;
    }
    // Sidebar sort is primary - initialize it
    const sidebarSortEl = document.getElementById('sidebar-sort');
    if (sidebarSortEl) {
      sidebarSortEl.value = state.sort;
    }
    if (els.sort) {
      els.sort.value = state.sort;
    }
    if (state.min_price !== null && els.minPrice) els.minPrice.value = state.min_price;
    if (state.max_price !== null && els.maxPrice) els.maxPrice.value = state.max_price;
    
    // Filter set dropdown removed - preview always uses active filter set
    // Categories section and recommended button will be initialized after active filter set is loaded

    // Update browser URL to persist search state
    function updateBrowserURL() {
      const params = new URLSearchParams();
      if (state.q) params.set('q', state.q);
      params.set('sort', state.sort);
      params.set('page', String(state.page));
      params.set('page_size', String(state.pageSize));
      if (state.min_price !== null && state.min_price !== '' && !isNaN(state.min_price) && state.min_price > 0) {
        params.set('min_price', String(state.min_price));
      }
      if (state.max_price !== null && state.max_price !== '' && !isNaN(state.max_price) && state.max_price > 0) {
        params.set('max_price', String(state.max_price));
      }
      if (state.filter_set_id) {
        params.set('filter_set_id', state.filter_set_id);
      }
      if (state.category_id) {
        params.set('category_id', state.category_id);
      }
      
      const newURL = `${window.location.pathname}?${params.toString()}`;
      window.history.replaceState({}, '', newURL);
    }

    function buildURL() {
      const endpoint = config.dataEndpoint || '/sponsor-catalog/preview/data';
      const u = new URL(endpoint, window.location.origin);
      
      u.searchParams.set('page', String(state.page));
      u.searchParams.set('sort', state.sort);
      
      if (state.q) {
        u.searchParams.set('q', state.q);
      } else {
        u.searchParams.delete('q');
      }

      // PRICE FILTER: Validate and set min_price
      if (state.min_price !== null && state.min_price !== '' && !isNaN(state.min_price) && state.min_price > 0) {
        u.searchParams.set('min_price', String(state.min_price));
      } else {
        u.searchParams.delete('min_price');
      }
      // PRICE FILTER: Validate and set max_price
      if (state.max_price !== null && state.max_price !== '' && !isNaN(state.max_price) && state.max_price > 0) {
        u.searchParams.set('max_price', String(state.max_price));
      } else {
        u.searchParams.delete('max_price');
      }
      
      // Always set filter_set_id - handle __recommended_only__ and __no_filter__ explicitly
      if (state.filter_set_id === '__recommended_only__') {
        u.searchParams.set('filter_set_id', '__recommended_only__');
      } else if (state.filter_set_id && state.filter_set_id !== '__no_filter__') {
        u.searchParams.set('filter_set_id', state.filter_set_id);
      } else {
        // For __no_filter__ or empty, explicitly set it so backend knows to include pinned items
        u.searchParams.set('filter_set_id', '__no_filter__');
      }
      
      if (state.category_id) {
        u.searchParams.set('category_id', state.category_id);
      } else {
        u.searchParams.delete('category_id');
      }
      
      // PRICE FILTER DEBUGGING
      console.log('[PRICE FILTER] buildURL - Price filter state:', {
        min_price: state.min_price,
        min_price_type: typeof state.min_price,
        min_price_isNaN: isNaN(state.min_price),
        max_price: state.max_price,
        max_price_type: typeof state.max_price,
        max_price_isNaN: isNaN(state.max_price),
        min_price_in_url: u.searchParams.get('min_price'),
        max_price_in_url: u.searchParams.get('max_price')
      });
      
      const finalUrl = u.toString();
      console.log('[PRICE FILTER] buildURL - Final URL:', finalUrl);
      return finalUrl;
    }

    // Modal elements
    const modal = document.getElementById('item-modal');
    const imgEl = document.getElementById('modal-img');
    const titleEl = document.getElementById('modal-title');
    const costEl = document.getElementById('modal-cost');
    const descEl = document.getElementById('modal-desc');
    const linkEl = document.getElementById('modal-link');
    const recommendBtnFilled = document.getElementById('modal-recommend-btn-filled');
    const recommendBtnUnfilled = document.getElementById('modal-recommend-btn-unfilled');
    const reportBtn = document.getElementById('modal-report-btn');

    // Report modal elements
    const reportModal = document.getElementById('report-modal');
    const reportForm = document.getElementById('report-form');
    const reportReason = document.getElementById('report-reason');
    const reportDescription = document.getElementById('report-description');

    // Helper: best-guess eBay link
    function getEbayLink(item) {
      if (item.url && typeof item.url === 'string' && item.url.trim()) {
        return item.url.trim();
      }
      const itemId = item.id || item.itemId || item.ebay_item_id || item.listingId;
      if (itemId) {
        return `https://www.ebay.com/itm/${itemId}`;
      }
      return null;
    }

    function openModal(it) {
      titleEl.textContent = it.title || '';
      imgEl.src = it.image || '';

      // Sponsor shows cost in price
      costEl.textContent = (it.price != null) ? `$${Number(it.price).toFixed(2)}` : '';

      const desc = it.shortDescription || it.subtitle || it.description || '';
      descEl.textContent = desc;

      const href = getEbayLink(it);
      if (href) {
        linkEl.href = href;
        linkEl.style.display = '';
      } else {
        linkEl.removeAttribute('href');
        linkEl.style.display = 'none';
      }
    
      // Recommend buttons - show filled if pinned, unfilled if not
      const isPinned = it.is_pinned === true || it.pinned === true;
      
      if (it.id) {
        if (recommendBtnFilled) {
          if (isPinned) {
            recommendBtnFilled.style.display = '';
            recommendBtnFilled.onclick = (e) => {
              e.preventDefault();
              e.stopPropagation();
              unrecommendProduct(it);
              closeModal();
            };
          } else {
            recommendBtnFilled.style.display = 'none';
          }
        }
        
        if (recommendBtnUnfilled) {
          if (!isPinned) {
            recommendBtnUnfilled.style.display = '';
            recommendBtnUnfilled.onclick = (e) => {
              e.preventDefault();
              e.stopPropagation();
              recommendProduct(it);
              closeModal();
            };
          } else {
            recommendBtnUnfilled.style.display = 'none';
          }
        }
      } else {
        if (recommendBtnFilled) recommendBtnFilled.style.display = 'none';
        if (recommendBtnUnfilled) recommendBtnUnfilled.style.display = 'none';
      }

      // Store current item data for reporting
      modal.currentItem = it;

      // Show report button
      if (reportBtn) {
        reportBtn.style.display = '';
      }

      modal.classList.remove('hidden');
    }

    function closeModal() {
      modal.classList.add('hidden');
    }

    function openReportModal() {
      reportModal.classList.remove('hidden');
      // Reset form when opening
      reportForm.reset();
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

    reportModal.addEventListener('click', (e) => {
      if (e.target.dataset.close) closeReportModal();
    });
    window.addEventListener('keydown', (e) => {
      if (!reportModal.classList.contains('hidden') && e.key === 'Escape') closeReportModal();
    });

    reportBtn.addEventListener('click', () => {
      closeModal();
      openReportModal();
    });

    reportForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      
      const item = modal.currentItem;
      if (!item) {
        console.error('[SPONSOR CATALOG] No item stored in modal for reporting');
        return;
      }
      
      console.log('[SPONSOR CATALOG] Report form submitted for item:', item.id, item.title?.substring(0, 50));
      
      const reason = reportReason.value;
      const description = reportDescription.value;
      
      if (!reason) {
        console.error('[SPONSOR CATALOG] Report reason not selected');
        alert('Please select a reason for reporting');
        return;
      }
      
      console.log('[SPONSOR CATALOG] Report reason:', reason, 'description:', description?.substring(0, 50));
      
      // Get CSRF token from meta tag (matching driver catalog implementation)
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
      
      // Get eBay URL
      const ebayUrl = item.url || getEbayLink(item) || `https://www.ebay.com/itm/${item.id}`;
      
      try {
        const response = await fetch(`/sponsor-catalog/report/${encodeURIComponent(item.id)}`, {
          method: 'POST',
          headers: headers,
          credentials: 'same-origin',
          body: JSON.stringify({
            reason: reason,
            description: description || '',
            title: item.title || '',
            image: item.image || '',
            url: ebayUrl
          })
        });
        
        // Check if response is OK before parsing JSON
        if (!response.ok) {
          const errorText = await response.text();
          alert('Error reporting item: ' + (response.statusText || 'Unknown error'));
          return;
        }
        
        const data = await response.json();
        
        if (data.ok) {
          alert('Item reported successfully. Thank you for your feedback!');
          closeReportModal();
        } else {
          const errorMsg = data.message || 'Unknown error';
          alert('Error reporting item: ' + errorMsg);
        }
      } catch (error) {
        alert('Error reporting item. Please try again.');
      }
    });

    function updateEmptyState() {
      if (!els.grid || !els.status) return;
      const hasCards = !!els.grid.querySelector('.card:not(.skeleton)');
      
      // If no browsing option has been selected, show the initial message
      if (!hasCards && !state.filter_set_id && !state.category_id) {
        els.status.textContent = 'Select a browsing option from the sidebar to browse products.';
        els.status.style.display = '';
      } else if (!hasCards) {
        els.status.textContent = 'No items found.';
        els.status.style.display = '';
      } else {
        els.status.style.display = 'none';
      }
    }

    // Show/hide UI elements based on whether a browsing option is selected
    function updateUIElementsVisibility() {
      const hasBrowsingOption = !!(state.filter_set_id || state.category_id);
      
      // Get all pager-wrapper elements
      const pagerWrappers = document.querySelectorAll('.pager-wrapper');
      const searchRow = document.querySelector('.catalog-search-row');
      const viewToggle = document.querySelector('.catalog-view-toggle');
      
      if (hasBrowsingOption) {
        // Show elements when browsing option is selected
        pagerWrappers.forEach(el => el.classList.add('show'));
        if (searchRow) searchRow.classList.add('show');
        if (viewToggle) viewToggle.classList.add('show');
      } else {
        // Hide elements when no browsing option is selected
        pagerWrappers.forEach(el => el.classList.remove('show'));
        if (searchRow) searchRow.classList.remove('show');
        if (viewToggle) viewToggle.classList.remove('show');
      }
    }

    function render(items) {
      
      // Filter out recommended/pinned products when browsing by category
      let filteredItems = items || [];
      if (state.category_id && items && items.length > 0) {
        const beforeCount = filteredItems.length;
        filteredItems = items.filter(item => {
          // Exclude items that are pinned/recommended when browsing by category
          // Check multiple ways items might be marked as pinned
          const isPinned = item.is_pinned === true || 
                          item.pinned === true || 
                          item.isPinned === true;
          
          // Also check for items with no price that appear at the top (likely pinned items)
          // Pinned items often have price: null and appear first in results
          const hasNoPrice = (item.price === null || item.price === undefined);
          const isLikelyPinned = hasNoPrice && items.indexOf(item) < 5; // First 5 items with no price are likely pinned
          
          if (isPinned || isLikelyPinned) {
            return false; // Filter out
          }
          return true; // Keep
        });
      }
      
      els.grid.innerHTML = '';
      if (!filteredItems || filteredItems.length === 0) {
        updateEmptyState();
        return;
      }
      els.status.style.display = 'none';

      let renderedCount = 0;
      for (const it of filteredItems) {
        if (!els.cardTpl || !els.cardTpl.content) {
          return;
        }
        
        const node = els.cardTpl.content.firstElementChild.cloneNode(true);
        
        if (!node) {
          continue;
        }
        
        if (!it.id) {
          continue;
        }
        
        node.dataset.itemId = it.id;
        const detailUrl = `/sponsor-catalog/product/${encodeURIComponent(it.id)}`;
        node.dataset.detailUrl = detailUrl;
        node.setAttribute('aria-label', it.title ? `View details for ${it.title}` : 'View item details');
        
        const img = node.querySelector('img');
        if (img) {
          img.src = it.image || '';
          img.loading = 'lazy';
          img.alt = it.title || 'Product image';
        }
        
        const titleEl = node.querySelector('.title');
        if (titleEl) {
          titleEl.textContent = it.title || '';
        }
        
        // Show price instead of points
        const pointsEl = node.querySelector('.points');
        if (pointsEl) {
          const numberEl = pointsEl.querySelector('.number');
          const labelEl = pointsEl.querySelector('.label');
          if (numberEl && labelEl) {
            numberEl.textContent = it.price != null ? `$${Number(it.price).toFixed(2)}` : '';
            labelEl.textContent = '';
          } else {
            pointsEl.textContent = (it.price != null ? `$${Number(it.price).toFixed(2)}` : '');
          }
        }
        
        const lowStockBadge = node.querySelector('[data-low-stock]');
        const noStockBadge = node.querySelector('[data-no-stock]');
        const recommendBtnFilled = node.querySelector('.recommend-btn-icon.filled');
        const recommendBtnUnfilled = node.querySelector('.recommend-btn-icon.unfilled');
        const reportBtnIcon = node.querySelector('.report-btn-icon');
        
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
        
        // Show/hide recommend buttons based on is_pinned state
        const isPinned = it.is_pinned === true || it.pinned === true;
        
        if (recommendBtnFilled) {
          if (isPinned) {
            recommendBtnFilled.style.display = '';
            recommendBtnFilled.setAttribute('aria-label', `Remove ${it.title || 'item'} from recommended`);
            recommendBtnFilled.addEventListener('click', (e) => {
              e.preventDefault();
              e.stopPropagation();
              unrecommendProduct(it, node);
            });
          } else {
            recommendBtnFilled.style.display = 'none';
          }
        }
        
        if (recommendBtnUnfilled) {
          if (!isPinned) {
            recommendBtnUnfilled.style.display = '';
            recommendBtnUnfilled.setAttribute('aria-label', `Add ${it.title || 'item'} to recommended`);
            recommendBtnUnfilled.addEventListener('click', (e) => {
              e.preventDefault();
              e.stopPropagation();
              recommendProduct(it, node);
            });
          } else {
            recommendBtnUnfilled.style.display = 'none';
          }
        }
        
        // Show report button
        if (reportBtnIcon) {
          reportBtnIcon.style.display = '';
          reportBtnIcon.setAttribute('aria-label', `Report ${it.title || 'item'}`);
          reportBtnIcon.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            modal.currentItem = it;
            openReportModal();
          });
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
        renderedCount++;
      }
      
      updateEmptyState();
    }

    // AbortController for cancelling in-flight requests
    let currentAbortController = null;
    
    let savedScrollPosition = 0;
    
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
      // PRICE FILTER DEBUGGING
      console.log('[PRICE FILTER] load() called with state:', {
        min_price: state.min_price,
        min_price_type: typeof state.min_price,
        max_price: state.max_price,
        max_price_type: typeof state.max_price,
        filter_set_id: state.filter_set_id,
        category_id: state.category_id
      });
      
      if (maintainScroll) {
        savedScrollPosition = window.scrollY;
      }
      
      const url = buildURL();
      const urlObj = new URL(url);
      urlObj.searchParams.set('fast', '1');
      urlObj.searchParams.set('page_size', String(state.pageSize));
      
      const finalUrl = urlObj.toString();
      console.log('[PRICE FILTER] Final fetch URL:', finalUrl);
      console.log('[PRICE FILTER] URL params check:', {
        min_price_param: urlObj.searchParams.get('min_price'),
        max_price_param: urlObj.searchParams.get('max_price'),
        all_params: Array.from(urlObj.searchParams.entries())
      });
      
      showSkeletonLoaders();
      disablePaginationButtons(true);
      
      if (currentAbortController) {
        currentAbortController.abort();
      }
      
      currentAbortController = new AbortController();
      
      els.grid.setAttribute('aria-busy', 'true');
      updateBrowserURL();
      
      const fetchStartTime = performance.now();
      try {
        urlObj.searchParams.set('page_size', String(state.pageSize));
        
        const resp = await fetch(urlObj.toString(), {
          signal: currentAbortController.signal
        });
        
        // PRICE FILTER DEBUGGING: Check response
        console.log('[PRICE FILTER] Response status:', resp.status, resp.statusText);
        
        if (!resp.ok) {
          const errorText = await resp.text();
          throw new Error(`HTTP ${resp.status}: ${errorText.substring(0, 200)}`);
        }
        
        const data = await resp.json();
        
        // PRICE FILTER DEBUGGING: Check response data
        console.log('[PRICE FILTER] Response data:', {
          items_count: data.items?.length || 0,
          total: data.total,
          page: data.page,
          total_pages: data.total_pages,
          has_more: data.has_more,
          items_sample: data.items?.slice(0, 3).map(item => ({
            id: item.id,
            price: item.price,
            title: item.title?.substring(0, 30)
          })) || []
        });
        
        const items = data.items || [];
        
        render(items);
        updatePagination(data);
        
        // Update UI elements visibility after loading
        updateUIElementsVisibility();
        
        if (maintainScroll && savedScrollPosition) {
          requestAnimationFrame(() => {
            window.scrollTo(0, savedScrollPosition);
          });
        }
      } catch (e) {
        if (e.name === 'AbortError') {
          return;
        }
        els.status.style.display = '';
        els.status.textContent = `Failed to load items: ${e.message}`;
      } finally {
        els.grid.removeAttribute('aria-busy');
        disablePaginationButtons(false);
        currentAbortController = null;
      }
    }
    
    function updatePagination(data) {
      state.hasMore = !!data.has_more;
      state.total = data.total ?? null;
      
      const pageText = `Page ${state.page}`;
      if (els.pageInfo) {
        els.pageInfo.textContent = pageText;
      }
      if (els.pageInfoTop) {
        els.pageInfoTop.textContent = pageText;
      }
      
      if (els.prev) {
        els.prev.disabled = state.page <= 1;
      }
      if (els.next) {
        els.next.disabled = !state.hasMore;
      }
      if (els.prevTop) {
        els.prevTop.disabled = state.page <= 1;
      }
      if (els.nextTop) {
        els.nextTop.disabled = !state.hasMore;
      }
    }
    
    function showSkeletonLoaders() {
      els.grid.innerHTML = '';
      els.status.style.display = 'none';
      
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
      
      const pagers = document.querySelectorAll('.pager');
      pagers.forEach(pager => {
        if (disabled) {
          pager.classList.add('loading');
        } else {
          pager.classList.remove('loading');
        }
      });
    }
    
    if (els.searchBtn) {
      els.searchBtn.addEventListener('click', () => {
        state.q = els.q ? els.q.value.trim() : '';
        state.min_price = els.minPrice && els.minPrice.value ? Number(els.minPrice.value) : null;
        state.max_price = els.maxPrice && els.maxPrice.value ? Number(els.maxPrice.value) : null;
        state.page = 1;
        load();
      });
    }

    if (filterToggleBtn && sidebar) {
      console.log('[SPONSOR CATALOG] Toggle button and sidebar found:', {
        toggleBtn: !!filterToggleBtn,
        sidebar: !!sidebar,
        sidebarId: sidebar.id,
        toggleBtnId: filterToggleBtn.id,
        initialSidebarState: sidebar.classList.contains('hidden') ? 'hidden' : 'visible'
      });

      const showSidebar = () => {
        console.log('[SPONSOR CATALOG] showSidebar() called');
        const wasHidden = sidebar.classList.contains('hidden');
        const computedBefore = window.getComputedStyle(sidebar);
        sidebar.classList.remove('hidden');
        // Force a reflow to ensure CSS is applied
        sidebar.offsetHeight;
        filterToggleBtn.setAttribute('aria-expanded', 'true');
        if (sidebarExpandBtn) {
          sidebarExpandBtn.style.display = 'none';
        }
        if (window.innerWidth < 1024) {
          document.body.style.overflow = 'hidden';
        }
        // Use requestAnimationFrame to get computed styles after DOM update
        requestAnimationFrame(() => {
          const computedAfter = window.getComputedStyle(sidebar);
          const catalogMain = document.querySelector('.catalog-main');
          const mainComputed = catalogMain ? window.getComputedStyle(catalogMain) : null;
          console.log('[SPONSOR CATALOG] Sidebar shown:', {
            wasHidden,
            nowVisible: !sidebar.classList.contains('hidden'),
            ariaExpanded: filterToggleBtn.getAttribute('aria-expanded'),
            windowWidth: window.innerWidth,
            transformBefore: computedBefore.transform,
            transformAfter: computedAfter.transform,
            sidebarClasses: Array.from(sidebar.classList),
            catalogMainMarginLeft: mainComputed ? mainComputed.marginLeft : 'N/A',
            hasHiddenClass: sidebar.classList.contains('hidden')
          });
        });
      };

      const hideSidebar = () => {
        console.log('[SPONSOR CATALOG] hideSidebar() called');
        const wasVisible = !sidebar.classList.contains('hidden');
        const computedBefore = window.getComputedStyle(sidebar);
        sidebar.classList.add('hidden');
        // Force a reflow to ensure CSS is applied
        sidebar.offsetHeight;
        filterToggleBtn.setAttribute('aria-expanded', 'false');
        if (sidebarExpandBtn) {
          sidebarExpandBtn.style.display = 'flex';
        }
        document.body.style.overflow = '';
        // Use requestAnimationFrame to get computed styles after DOM update
        requestAnimationFrame(() => {
          const computedAfter = window.getComputedStyle(sidebar);
          const catalogMain = document.querySelector('.catalog-main');
          const mainComputed = catalogMain ? window.getComputedStyle(catalogMain) : null;
          console.log('[SPONSOR CATALOG] Sidebar hidden:', {
            wasVisible,
            nowHidden: sidebar.classList.contains('hidden'),
            ariaExpanded: filterToggleBtn.getAttribute('aria-expanded'),
            transformBefore: computedBefore.transform,
            transformAfter: computedAfter.transform,
            sidebarClasses: Array.from(sidebar.classList),
            catalogMainMarginLeft: mainComputed ? mainComputed.marginLeft : 'N/A',
            hasHiddenClass: sidebar.classList.contains('hidden')
          });
        });
      };

      const toggleSidebar = (e) => {
        console.log('[SPONSOR CATALOG] toggleSidebar() called - button clicked!', {
          event: e,
          target: e.target,
          currentTarget: e.currentTarget,
          sidebarState: sidebar.classList.contains('hidden') ? 'hidden' : 'visible',
          sidebarClasses: Array.from(sidebar.classList),
          buttonId: filterToggleBtn.id,
          buttonClasses: Array.from(filterToggleBtn.classList)
        });
        // Stop event propagation to prevent any parent handlers
        if (e) {
          e.preventDefault();
          e.stopPropagation();
          e.stopImmediatePropagation();
        }
        const isCurrentlyHidden = sidebar.classList.contains('hidden');
        console.log('[SPONSOR CATALOG] Toggling sidebar:', {
          currentState: isCurrentlyHidden ? 'hidden' : 'visible',
          willChangeTo: isCurrentlyHidden ? 'visible' : 'hidden'
        });
        // Use the same direct approach as collapse/expand buttons
        if (isCurrentlyHidden) {
          showSidebar();
        } else {
          hideSidebar();
        }
        // Force a reflow after toggling
        requestAnimationFrame(() => {
          const computed = window.getComputedStyle(sidebar);
          const catalogMain = document.querySelector('.catalog-main');
          const mainComputed = catalogMain ? window.getComputedStyle(catalogMain) : null;
          console.log('[SPONSOR CATALOG] Toggle complete. New sidebar state:', {
            isHidden: sidebar.classList.contains('hidden'),
            ariaExpanded: filterToggleBtn.getAttribute('aria-expanded'),
            computedTransform: computed.transform,
            computedDisplay: computed.display,
            computedVisibility: computed.visibility,
            sidebarClasses: Array.from(sidebar.classList),
            catalogMainMarginLeft: mainComputed ? mainComputed.marginLeft : 'N/A',
            sidebarOffsetWidth: sidebar.offsetWidth,
            sidebarOffsetHeight: sidebar.offsetHeight
          });
        });
      };

      console.log('[SPONSOR CATALOG] Attaching click event listener to toggle button');
      // Use capture phase to ensure we handle the event before anything else
      filterToggleBtn.addEventListener('click', toggleSidebar, true);
      console.log('[SPONSOR CATALOG] Click event listener attached successfully');
      if (sidebarCollapseBtn) {
        console.log('[SPONSOR CATALOG] Attaching click event listener to collapse button');
        sidebarCollapseBtn.addEventListener('click', (e) => {
          console.log('[SPONSOR CATALOG] Collapse button clicked');
          e.preventDefault();
          e.stopPropagation();
          hideSidebar();
        });
      } else {
        console.warn('[SPONSOR CATALOG] Collapse button not found!');
      }
      if (sidebarExpandBtn) {
        console.log('[SPONSOR CATALOG] Attaching click event listener to expand button');
        sidebarExpandBtn.addEventListener('click', (e) => {
          console.log('[SPONSOR CATALOG] Expand button clicked');
          e.preventDefault();
          e.stopPropagation();
          showSidebar();
        });
      } else {
        console.warn('[SPONSOR CATALOG] Expand button not found!');
      }

      // Prevent sidebar clicks from closing it (only close on overlay click)
      sidebar.addEventListener('click', (event) => {
        // Only close if clicking directly on the sidebar background (not on content)
        if (event.target === sidebar) {
          hideSidebar();
        }
      });

      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !sidebar.classList.contains('hidden')) {
          hideSidebar();
        }
      });

      // Initially show sidebar on desktop, hide on mobile
      console.log('[SPONSOR CATALOG] Setting initial sidebar state based on window width:', {
        windowWidth: window.innerWidth,
        willShow: window.innerWidth >= 1024
      });
      if (window.innerWidth >= 1024) {
        showSidebar();
      } else {
        hideSidebar();
      }
      console.log('[SPONSOR CATALOG] Initial sidebar state set:', {
        isHidden: sidebar.classList.contains('hidden'),
        ariaExpanded: filterToggleBtn.getAttribute('aria-expanded')
      });
      
      // Handle window resize
      let resizeTimeout;
      window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
          const shouldShow = window.innerWidth >= 1024;
          const isCurrentlyHidden = sidebar.classList.contains('hidden');
          console.log('[SPONSOR CATALOG] Window resized:', {
            newWidth: window.innerWidth,
            shouldShow,
            isCurrentlyHidden,
            willChange: (shouldShow && isCurrentlyHidden) || (!shouldShow && !isCurrentlyHidden)
          });
          if (shouldShow && isCurrentlyHidden) {
            console.log('[SPONSOR CATALOG] Resize: Showing sidebar (desktop size)');
            showSidebar();
          } else if (!shouldShow && !isCurrentlyHidden) {
            console.log('[SPONSOR CATALOG] Resize: Hiding sidebar (mobile size)');
            hideSidebar();
          }
        }, 250);
      });
    }

    // Main sort dropdown (if it exists) - sync with sidebar sort
    if (els.sort) {
      els.sort.addEventListener('change', () => {
        state.sort = els.sort.value;
        const sidebarSort = document.getElementById('sidebar-sort');
        if (sidebarSort && sidebarSort.value !== state.sort) {
          sidebarSort.value = state.sort;
        }
        state.page = 1;
        load();
      });
    }

    const debouncedLoad = debounce(() => {
      state.page = 1;
      load(true);
    }, 250);
    
    if (els.q) {
      els.q.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
          state.q = els.q.value.trim();
          state.page = 1;
          load(true);
        }
      });
    }
    
    // PRICE FILTER: Input event handlers - only update state, don't trigger load
    // The filter will only be applied when the "Apply Filter" button is clicked
    if (els.minPrice) {
      els.minPrice.addEventListener('input', () => {
        // Just update the input field value, don't update state or trigger load
        // State will be updated when "Apply Filter" button is clicked
      });
    }

    if (els.maxPrice) {
      els.maxPrice.addEventListener('input', () => {
        // Just update the input field value, don't update state or trigger load
        // State will be updated when "Apply Filter" button is clicked
      });
    }

    // PRICE FILTER: Apply button handler with debugging
    const applyPriceBtn = document.getElementById('apply-price-filter');
    if (applyPriceBtn) {
      applyPriceBtn.addEventListener('click', () => {
        const minVal = els.minPrice && els.minPrice.value ? els.minPrice.value.trim() : '';
        const maxVal = els.maxPrice && els.maxPrice.value ? els.maxPrice.value.trim() : '';
        const minNum = minVal ? Number(minVal) : null;
        const maxNum = maxVal ? Number(maxVal) : null;
        
        console.log('[PRICE FILTER] Apply button clicked:', {
          min_input: minVal,
          min_number: minNum,
          min_isNaN: isNaN(minNum),
          max_input: maxVal,
          max_number: maxNum,
          max_isNaN: isNaN(maxNum)
        });
        
        state.min_price = (minVal && !isNaN(minNum) && minNum > 0) ? minNum : null;
        state.max_price = (maxVal && !isNaN(maxNum) && maxNum > 0) ? maxNum : null;
        state.page = 1;
        
        console.log('[PRICE FILTER] State after apply button:', {
          min_price: state.min_price,
          max_price: state.max_price
        });
        
        load();
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

    // Filter set selector removed - preview always uses active filter set from backend
    // All filter set dropdown code has been removed

    // Recommended products button - always switches to recommended mode (not a toggle)
    if (els.recommendedBtn) {
      console.log('[SPONSOR CATALOG] Recommended button found, attaching handler');
      els.recommendedBtn.addEventListener('click', async (e) => {
        console.log('[SPONSOR CATALOG] Recommended button clicked!');
        e.preventDefault();
        e.stopPropagation();
        
        // Always switch to recommended products mode (not a toggle)
        console.log('[SPONSOR CATALOG] Switching to recommended products mode');
        state.filter_set_id = '__recommended_only__';
        state.category_id = null; // Clear category when switching to recommended
        state.page = 1;
        
        els.recommendedBtn.classList.add('active');
        
        // Show UI elements (pager, search, view toggle)
        updateUIElementsVisibility();
        
        // Update browsing indicator
        const indicator = document.getElementById('browsing-indicator');
        const categoryNameEl = document.getElementById('browsing-category-name');
        const browsingText = document.getElementById('browsing-text');
        if (indicator) {
          if (categoryNameEl) {
            categoryNameEl.textContent = 'Recommended Products';
            const textEl = document.getElementById('browsing-text');
            if (textEl) textEl.style.display = '';
          } else if (browsingText) {
            browsingText.style.display = '';
            const nameEl = browsingText.querySelector('#browsing-category-name');
            if (nameEl) nameEl.textContent = 'Recommended Products';
          }
        }
        
        console.log('[SPONSOR CATALOG] Updated state:', {
          filter_set_id: state.filter_set_id,
          category_id: state.category_id,
          page: state.page
        });
        
        console.log('[SPONSOR CATALOG] Calling load()...');
        load();
      });
    } else {
      console.warn('[SPONSOR CATALOG] Recommended button NOT found!');
    }

    // Sidebar sort handler - sync with main sort dropdown
    const sidebarSortHandler = document.getElementById('sidebar-sort');
    if (sidebarSortHandler) {
      sidebarSortHandler.value = state.sort;
      sidebarSortHandler.addEventListener('change', () => {
        state.sort = sidebarSortHandler.value;
        // Also update main sort dropdown if it exists
        if (els.sort && els.sort.value !== state.sort) {
          els.sort.value = state.sort;
        }
        state.page = 1;
        load();
      });
    }
    
    // Sync main sort dropdown with sidebar sort (if main sort exists)
    if (els.sort) {
      els.sort.addEventListener('change', () => {
        state.sort = els.sort.value;
        const sidebarSortSync = document.getElementById('sidebar-sort');
        if (sidebarSortSync && sidebarSortSync.value !== state.sort) {
          sidebarSortSync.value = state.sort;
        }
        state.page = 1;
        load();
      });
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

    if (els.prevTop) {
      els.prevTop.addEventListener('click', () => {
        if (state.page > 1) {
          state.page -= 1;
          load();
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
      });
    }
    if (els.nextTop) {
      els.nextTop.addEventListener('click', () => {
        state.page += 1;
        load();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }

    // Recommend product function
    async function recommendProduct(item, cardNode) {
      console.log('[SPONSOR CATALOG] recommendProduct called for item:', item.id, item.title?.substring(0, 50));
      
      if (!item.id) {
        console.error('[SPONSOR CATALOG] Cannot recommend: item missing id');
        alert('Cannot recommend this product (no ID)');
        return;
      }
      
      // Get CSRF token (matching driver catalog implementation)
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                       document.querySelector('meta[name="csrf-token"]')?.content ||
                       null;
      
      if (!csrfToken) {
        console.error('[SPONSOR CATALOG] CSRF token not found');
        alert('Security token missing. Please refresh the page.');
        return;
      }
      
      console.log('[SPONSOR CATALOG] Pinning product with CSRF token:', csrfToken ? 'present' : 'missing');
      
      const fd = new FormData();
      fd.append('item_id', item.id);
      fd.append('title', item.title || '');
      fd.append('image', item.image || '');
      // Include CSRF token in FormData for Flask-WTF compatibility
      if (csrfToken) {
        fd.append('csrf_token', csrfToken);
      }
      
      // Disable button during request
      let recommendBtnUnfilled, recommendBtnFilled;
      if (cardNode) {
        recommendBtnUnfilled = cardNode.querySelector('.recommend-btn-icon.unfilled');
        if (recommendBtnUnfilled) {
          recommendBtnUnfilled.disabled = true;
          console.log('[SPONSOR CATALOG] Disabled recommend button');
        }
      }
      
      try {
        console.log('[SPONSOR CATALOG] Sending POST request to /sponsor-catalog/pin-product');
        const r = await fetch("/sponsor-catalog/pin-product", {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken
          }
        });
        
        console.log('[SPONSOR CATALOG] Pin response status:', r.status, r.statusText);
        
        const data = await r.json().catch(() => ({}));
        console.log('[SPONSOR CATALOG] Pin response data:', data);
        
        if (r.ok && data.ok) {
          console.log('[SPONSOR CATALOG] Product pinned successfully, reloading...');
          // Reload the page to show updated state
          load();
        } else {
          const errorMsg = data.message || 'Failed to recommend product';
          console.error('[SPONSOR CATALOG] Pin failed:', errorMsg);
          alert(errorMsg);
          if (recommendBtnUnfilled) {
            recommendBtnUnfilled.disabled = false;
          }
        }
      } catch (e) {
        console.error('[SPONSOR CATALOG] Error pinning product:', e);
        alert('Error recommending product. Please try again.');
        if (recommendBtnUnfilled) {
          recommendBtnUnfilled.disabled = false;
        }
      }
    }
    
    async function unrecommendProduct(item, cardNode) {
      console.log('[SPONSOR CATALOG] unrecommendProduct called for item:', item.id, item.title?.substring(0, 50));
      
      if (!item.id) {
        console.error('[SPONSOR CATALOG] Cannot unrecommend: item missing id');
        alert('Cannot unrecommend this product (no ID)');
        return;
      }
      
      // Get CSRF token (matching driver catalog implementation)
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                       document.querySelector('meta[name="csrf-token"]')?.content ||
                       null;
      
      if (!csrfToken) {
        console.error('[SPONSOR CATALOG] CSRF token not found');
        alert('Security token missing. Please refresh the page.');
        return;
      }
      
      console.log('[SPONSOR CATALOG] Unpinning product with CSRF token:', csrfToken ? 'present' : 'missing');
      
      console.log('[SPONSOR CATALOG] Unpinning product, fetching pin_id for item:', item.id);
      
      // Disable buttons during request
      let recommendBtnFilled;
      if (cardNode) {
        recommendBtnFilled = cardNode.querySelector('.recommend-btn-icon.filled');
        if (recommendBtnFilled) {
          recommendBtnFilled.disabled = true;
          console.log('[SPONSOR CATALOG] Disabled card unrecommend button');
        }
      }
      
      // Also disable modal button if open
      const modalBtnFilled = document.getElementById('modal-recommend-btn-filled');
      if (modalBtnFilled && modalBtnFilled.style.display !== 'none') {
        modalBtnFilled.disabled = true;
        console.log('[SPONSOR CATALOG] Disabled modal unrecommend button');
      }
      
      // First, get the pin_id by fetching the pinned product info
      try {
        console.log('[SPONSOR CATALOG] Fetching pin info from /sponsor-catalog/pinned-product/' + encodeURIComponent(item.id));
        const getPinResponse = await fetch(`/sponsor-catalog/pinned-product/${encodeURIComponent(item.id)}`, {
          method: 'GET',
          credentials: 'same-origin',
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        });
        
        console.log('[SPONSOR CATALOG] Get pin response status:', getPinResponse.status, getPinResponse.statusText);
        
        if (!getPinResponse.ok) {
          const errorData = await getPinResponse.json().catch(() => ({}));
          console.error('[SPONSOR CATALOG] Failed to get pin info:', errorData);
          alert(errorData.message || 'Product is not currently recommended');
          if (recommendBtnFilled) recommendBtnFilled.disabled = false;
          if (modalBtnFilled) modalBtnFilled.disabled = false;
          return;
        }
        
        const pinData = await getPinResponse.json();
        console.log('[SPONSOR CATALOG] Pin data received:', pinData);
        
        if (!pinData.ok || !pinData.pin || !pinData.pin.id) {
          console.error('[SPONSOR CATALOG] Invalid pin data:', pinData);
          alert('Could not find pin information for this product');
          if (recommendBtnFilled) recommendBtnFilled.disabled = false;
          if (modalBtnFilled) modalBtnFilled.disabled = false;
          return;
        }
        
        const pinId = pinData.pin.id;
        console.log('[SPONSOR CATALOG] Found pin_id:', pinId, 'for item:', item.id);
        
        // Now unpin using the pin_id
        console.log('[SPONSOR CATALOG] Sending POST request to /sponsor-catalog/unpin-product/' + pinId);
        const r = await fetch(`/sponsor-catalog/unpin-product/${pinId}`, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken
          }
        });
        
        console.log('[SPONSOR CATALOG] Unpin response status:', r.status, r.statusText);
        
        // Check if response is OK before parsing JSON
        if (!r.ok) {
          const errorText = await r.text();
          console.error('[SPONSOR CATALOG] Unpin failed with status', r.status, ':', errorText);
          // Try to parse as JSON if possible
          let errorMsg = 'Failed to unrecommend product';
          try {
            const errorData = JSON.parse(errorText);
            errorMsg = errorData.message || errorMsg;
          } catch {
            // If not JSON, use the status text
            errorMsg = r.statusText || errorMsg;
          }
          alert(errorMsg);
          if (recommendBtnFilled) recommendBtnFilled.disabled = false;
          if (modalBtnFilled) modalBtnFilled.disabled = false;
          return;
        }
        
        const data = await r.json();
        console.log('[SPONSOR CATALOG] Unpin response data:', data);
        
        if (data.ok) {
          console.log('[SPONSOR CATALOG] Product unpinned successfully, reloading...');
          // Reload the page to show updated state
          load();
        } else {
          const errorMsg = data.message || 'Failed to unrecommend product';
          console.error('[SPONSOR CATALOG] Unpin failed:', errorMsg);
          alert(errorMsg);
          if (recommendBtnFilled) recommendBtnFilled.disabled = false;
          if (modalBtnFilled) modalBtnFilled.disabled = false;
        }
      } catch (e) {
        console.error('[SPONSOR CATALOG] Error unpinning product:', e, e.stack);
        alert('Error unrecommending product. Please try again.');
        if (recommendBtnFilled) recommendBtnFilled.disabled = false;
        if (modalBtnFilled) modalBtnFilled.disabled = false;
      }
    }

    // Category selection handler (called from category browser)
    window.selectSponsorCategory = function(categoryId, categoryName) {
      console.log('[SPONSOR CATALOG] selectSponsorCategory called:', categoryId, categoryName);
      
      // Clear filter set and recommended mode when selecting a category
      state.filter_set_id = '__no_filter__'; // Use __no_filter__ instead of empty string to ensure backend treats it correctly
      state.category_id = categoryId;
      state.page = 1;
      
      console.log('[SPONSOR CATALOG] Category selection state:', {
        filter_set_id: state.filter_set_id,
        category_id: state.category_id,
        page: state.page
      });
      
      // Deactivate recommended button when category is selected (but don't hide it)
      if (els.recommendedBtn) {
        els.recommendedBtn.classList.remove('active');
        console.log('[SPONSOR CATALOG] Recommended button deactivated (category selected)');
      }
      
      // Update browsing indicator
      const indicator = document.getElementById('browsing-indicator');
      const categoryNameEl = document.getElementById('browsing-category-name');
      const browsingText = document.getElementById('browsing-text');
      if (indicator) {
        if (categoryNameEl) {
          categoryNameEl.textContent = categoryName;
          const textEl = document.getElementById('browsing-text');
          if (textEl) textEl.style.display = '';
        } else if (browsingText) {
          browsingText.style.display = '';
          const nameEl = browsingText.querySelector('#browsing-category-name');
          if (nameEl) nameEl.textContent = categoryName;
        }
      }
      
      // Show UI elements (pager, search, view toggle)
      updateUIElementsVisibility();
      
      console.log('[SPONSOR CATALOG] Calling load() after category selection...');
      load();
    };

    // Initialize: Load active filter set first, then start the catalog
    async function initializeCatalog() {
      console.log('[SPONSOR CATALOG] Initializing catalog with active filter set...');
      
      // Load active filter set from backend (for reference, but don't auto-load products)
      await loadActiveFilterSet();
      
      // Store the active filter set ID for later use, but don't set state.filter_set_id yet
      // User must explicitly select a browsing option
      let storedActiveFilterSetId = activeFilterSetId;
      
      // Show categories section by default (user can select a category or recommended products)
      const initialCategorySection = document.getElementById('categories-sidebar-section');
      if (initialCategorySection) {
        initialCategorySection.classList.remove('hidden');
        initialCategorySection.style.removeProperty('display');
        initialCategorySection.style.setProperty('display', 'block', 'important');
        const categoryBrowser = initialCategorySection.querySelector('.sponsor-category-browser');
        if (categoryBrowser) {
          categoryBrowser.classList.remove('hidden');
          categoryBrowser.style.removeProperty('display');
          categoryBrowser.style.setProperty('display', 'block', 'important');
        }
        console.log('[SPONSOR CATALOG] Categories section shown (waiting for user selection)');
        
        // Load categories for the active filter set (if available) so user can browse
        if (window.loadSponsorCategories && storedActiveFilterSetId && storedActiveFilterSetId !== '__recommended_only__') {
          window.loadSponsorCategories(storedActiveFilterSetId);
        } else if (window.loadSponsorCategories && !storedActiveFilterSetId) {
          // If no active filter set, load with __no_filter__ to show all categories
          window.loadSponsorCategories('__no_filter__');
        }
      }
      
      // Don't load products automatically - show empty state message instead
      console.log('[SPONSOR CATALOG] Waiting for user to select a browsing option...');
      console.log('[SPONSOR CATALOG] Initial state:', state);
      
      // Show the initial empty state message
      // Ensure status element is visible on initial load
      if (els.status) {
        els.status.textContent = 'Select a browsing option from the sidebar to browse products.';
        els.status.style.display = '';
      }
      updateEmptyState();
      
      // Hide UI elements (pager, search, view toggle) by default
      updateUIElementsVisibility();
      
      // Expose load function and state for sidebar integration
      window.sponsorCatalogLoad = load;
      window.sponsorCatalogState = state;
      window.sponsorCatalogConfig = config;
      console.log('[SPONSOR CATALOG] Initialization complete. Exposed load function and state.');
    }
    
    // Start initialization
    initializeCatalog();
  })();
