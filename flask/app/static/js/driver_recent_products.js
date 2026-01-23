(function () {
  const container =
    document.getElementById('driver-recent-products-overlay') ||
    document.getElementById('driver-recent-products-modal');

  if (!container) return;

  const openBtn = document.getElementById('open-driver-recent-products');
  const bodyEl = document.getElementById('driver-recent-products-body');
  if (!bodyEl) return;

  const closeButtons = Array.from(container.querySelectorAll('[data-close]'));
  const isOverlay = container.classList.contains('recent-products-overlay');

  const showContainer = () => {
    if (isOverlay) {
      container.classList.add('active');
    } else {
      container.classList.remove('hidden');
    }
    document.body.style.overflow = 'hidden';
  };

  const hideContainer = () => {
    if (isOverlay) {
      container.classList.remove('active');
    } else {
      container.classList.add('hidden');
    }
    document.body.style.overflow = '';
  };

  const csrfMeta = document.querySelector('meta[name="csrf-token"]');

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderProducts(products) {
    if (!Array.isArray(products) || !products.length) {
      bodyEl.innerHTML = '<div class="recent-products-empty">No products viewed recently.</div>';
      return;
    }

    const grid = document.createElement('div');
    grid.className = 'recent-products-grid';

    products.forEach((product) => {
      const cardLink = document.createElement(product.detail_path ? 'a' : 'div');
      cardLink.className = 'recent-product-card recent-product-link';
      if (product.detail_path) {
        cardLink.href = product.detail_path;
      }

      if (product.image_url) {
        const img = document.createElement('img');
        img.src = product.image_url;
        img.alt = product.title || 'Product';
        cardLink.appendChild(img);
      }

      const titleEl = document.createElement('h5');
      titleEl.className = 'recent-product-title';
      titleEl.textContent = product.title || 'Product';
      cardLink.appendChild(titleEl);

      const meta = document.createElement('div');
      meta.className = 'recent-product-meta';

      if (product.sponsor_name) {
        const sponsor = document.createElement('span');
        sponsor.textContent = product.sponsor_name;
        meta.appendChild(sponsor);
      }

      if (product.points !== null && product.points !== undefined) {
        const points = document.createElement('span');
        points.textContent = `${product.points.toLocaleString()} pts`;
        meta.appendChild(points);
      } else if (product.price !== null && product.price !== undefined) {
        const price = document.createElement('span');
        price.textContent = `${product.currency || 'USD'} ${Number(product.price).toFixed(2)}`;
        meta.appendChild(price);
      }

      if (product.last_viewed) {
        const date = new Date(product.last_viewed);
        const time = document.createElement('span');
        time.textContent = `Viewed ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
        meta.appendChild(time);
      }

      if (meta.children.length) {
        cardLink.appendChild(meta);
      }

      grid.appendChild(cardLink);
    });

    bodyEl.innerHTML = '';
    bodyEl.appendChild(grid);
  }

  async function loadRecentProducts() {
    bodyEl.innerHTML = '<div class="recent-products-empty">Loading recently viewed products...</div>';
    try {
      const response = await fetch('/driver/recent-products', {
        method: 'GET',
        credentials: 'same-origin',
        headers: {
          'Accept': 'application/json',
          ...(csrfMeta ? { 'X-CSRFToken': csrfMeta.getAttribute('content') } : {}),
        },
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Failed to load recently viewed products.');
      }

      renderProducts(data.products || []);
    } catch (err) {
      console.error(err);
      bodyEl.innerHTML = `<div class="recent-products-empty">${escapeHtml(err.message || 'Failed to load recently viewed products.')}</div>`;
    }
  }

  function openOverlay() {
    showContainer();
    loadRecentProducts();
  }

  function closeOverlay() {
    hideContainer();
  }

  if (openBtn) {
    openBtn.addEventListener('click', openOverlay);
  }

  closeButtons.forEach((btn) => {
    btn.addEventListener('click', closeOverlay);
  });

  if (isOverlay) {
    container.addEventListener('click', (event) => {
      if (event.target === container) {
        closeOverlay();
      }
    });
  }

  document.addEventListener('keydown', (event) => {
    const isOpen = isOverlay
      ? container.classList.contains('active')
      : !container.classList.contains('hidden');
    if (event.key === 'Escape' && isOpen) {
      closeOverlay();
    }
  });
})();
