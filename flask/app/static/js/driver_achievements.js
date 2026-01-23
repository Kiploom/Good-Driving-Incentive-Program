(function () {
  const overlay = document.getElementById('driver-achievements-overlay');
  if (!overlay) return;

  const openBtn = document.getElementById('open-driver-achievements');
  const closeBtn = document.getElementById('close-driver-achievements');
  const bodyEl = document.getElementById('driver-achievements-body');

  const csrfToken = () => document.querySelector('meta[name="csrf-token"]').getAttribute('content');

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderAchievements(data) {
    if (!Array.isArray(data) || !data.length) {
      bodyEl.innerHTML = '<div class="challenges-empty">No achievements to display yet.</div>';
      return;
    }

    const earned = data.filter((item) => item.is_earned);
    const locked = data.filter((item) => !item.is_earned);

    const wrapper = document.createElement('div');
    wrapper.className = 'achievements-wrapper';

    const groups = [
      { title: 'Earned', items: earned, css: 'earned' },
      { title: 'Locked', items: locked, css: 'locked' },
    ];

    groups.forEach((group) => {
      const section = document.createElement('section');
      section.className = 'achievement-group';

      const heading = document.createElement('h4');
      heading.textContent = `${group.title} (${group.items.length})`;
      section.appendChild(heading);

      const list = document.createElement('div');
      list.className = 'achievement-grid';

      if (!group.items.length) {
        const empty = document.createElement('div');
        empty.className = 'challenges-empty';
        empty.style.padding = '24px';
        empty.textContent = group.title === 'Earned' ? 'No achievements earned yet.' : 'All achievements earned!';
        list.appendChild(empty);
      } else {
        group.items.forEach((item) => {
          const card = document.createElement('article');
          card.className = `achievement-card ${item.is_earned ? 'earned' : ''}`;

          const title = document.createElement('h5');
          title.textContent = escapeHtml(item.title);
          card.appendChild(title);

          const description = document.createElement('p');
          description.className = 'achievement-requirement';
          description.innerHTML = escapeHtml(item.description || '');
          card.appendChild(description);

          const tag = document.createElement('span');
          tag.className = `achievement-tag ${item.is_earned ? 'earned' : 'locked'}`;
          if (item.is_earned) {
            const earnedAt = item.earned_at ? new Date(item.earned_at).toLocaleString() : 'Now';
            tag.textContent = `Earned • ${earnedAt}`;
          } else if (item.is_points_based && item.points_threshold) {
            tag.textContent = `Earn at ${item.points_threshold.toLocaleString()} pts`;
          } else {
            tag.textContent = 'Locked';
          }
          card.appendChild(tag);

          list.appendChild(card);
        });
      }

      section.appendChild(list);
      wrapper.appendChild(section);
    });

    bodyEl.innerHTML = '';
    bodyEl.appendChild(wrapper);
  }

  async function loadAchievements() {
    bodyEl.innerHTML = '<div class="challenges-empty">Loading achievements...</div>';
    try {
      const response = await fetch('/driver/achievements', {
        method: 'GET',
        credentials: 'same-origin',
        headers: {
          'Accept': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Failed to load achievements');
      }

      renderAchievements(data.achievements);
    } catch (err) {
      console.error(err);
      bodyEl.innerHTML = `<div class="challenges-empty">${escapeHtml(err.message || 'Failed to load achievements.')}</div>`;
    }
  }

  function openOverlay() {
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    loadAchievements();
  }

  function closeOverlay() {
    overlay.classList.remove('active');
    document.body.style.overflow = '';
  }

  if (openBtn) {
    openBtn.addEventListener('click', openOverlay);
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', closeOverlay);
  }

  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) {
      closeOverlay();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && overlay.classList.contains('active')) {
      closeOverlay();
    }
  });
})();


