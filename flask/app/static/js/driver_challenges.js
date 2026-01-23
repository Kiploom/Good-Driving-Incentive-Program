(function () {
  const overlay = document.getElementById('driver-challenges-overlay');
  if (!overlay) return;

  const openBtn = document.getElementById('open-driver-challenges');
  const closeBtn = document.getElementById('close-driver-challenges');
  const listContainer = document.getElementById('driver-challenges-list');

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatDate(value) {
    if (!value) return 'No expiration';
    try {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return date.toLocaleString();
    } catch (err) {
      return value;
    }
  }

  async function fetchChallenges() {
    listContainer.innerHTML = '<div class="challenges-empty">Loading challenges...</div>';
    try {
      const response = await fetch('/driver/challenges', { credentials: 'same-origin' });
      const data = await response.json();
      renderChallenges(Array.isArray(data.challenges) ? data.challenges : []);
    } catch (err) {
      console.error(err);
      listContainer.innerHTML = '<div class="challenges-empty">Failed to load challenges. Please try again.</div>';
    }
  }

  function renderChallenges(challenges) {
    if (!challenges.length) {
      listContainer.innerHTML = '<div class="challenges-empty">No active challenges are available right now. Check back soon!</div>';
      return;
    }

    const fragment = document.createDocumentFragment();
    challenges.forEach((challenge) => {
      const item = document.createElement('div');
      item.className = 'challenge-item ' + (challenge.status === 'subscribed' ? 'active' : '');

      const sponsorName = escapeHtml(challenge.sponsor_name || 'Sponsor');
      const title = escapeHtml(challenge.title || 'Challenge');
      const descriptionHtml = challenge.description
        ? escapeHtml(challenge.description).replace(/\n/g, '<br>')
        : '<span class="muted">No description provided.</span>';
      const statusBadge = mapStatusBadge(challenge.status);

      item.innerHTML = `
        <div style="display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap;">
          <div>
            <h4>${title}</h4>
            <div class="muted" style="font-size:13px;">${sponsorName}</div>
          </div>
          ${statusBadge}
        </div>
        <p style="margin:10px 0; color:#374151;">${descriptionHtml}</p>
        <div class="challenge-meta">
          <span><strong>Reward:</strong> ${challenge.reward_points} pts</span>
          <span><strong>Optional:</strong> ${challenge.is_optional ? 'Yes' : 'No'}</span>
          <span><strong>Expires:</strong> ${formatDate(challenge.expires_at)}</span>
        </div>
        <div class="challenge-actions"></div>
      `;

      const actions = item.querySelector('.challenge-actions');
      decorateActions(actions, challenge);
      fragment.appendChild(item);
    });

    listContainer.innerHTML = '';
    listContainer.appendChild(fragment);
  }

  function mapStatusBadge(status) {
    if (!status) return '<span class="challenge-badge optional">Available</span>';
    const normalized = status.toLowerCase();
    const map = {
      subscribed: '<span class="challenge-badge subscribed">Subscribed</span>',
      completed: '<span class="challenge-badge completed">Completed</span>',
      expired: '<span class="challenge-badge">Expired</span>',
      removed: '<span class="challenge-badge">Removed</span>',
    };
    return map[normalized] || '<span class="challenge-badge">' + escapeHtml(status) + '</span>';
  }

  function decorateActions(container, challenge) {
    container.innerHTML = '';
    if (challenge.status && ['subscribed', 'completed'].includes(challenge.status)) {
      const btn = document.createElement('button');
      btn.className = 'close';
      btn.type = 'button';
      btn.textContent = challenge.status === 'completed' ? 'Completed' : 'Subscribed';
      btn.disabled = true;
      container.appendChild(btn);
      return;
    }

    if (!challenge.is_optional) {
      const span = document.createElement('span');
      span.className = 'challenge-badge optional';
      span.textContent = 'Assigned';
      container.appendChild(span);
      return;
    }

    const subscribeBtn = document.createElement('button');
    subscribeBtn.className = 'subscribe';
    subscribeBtn.type = 'button';
    subscribeBtn.innerHTML = '<i class="fas fa-bolt"></i> Subscribe';
    subscribeBtn.addEventListener('click', () => subscribeToChallenge(challenge.challenge_id, subscribeBtn));
    container.appendChild(subscribeBtn);
  }

  async function subscribeToChallenge(challengeId, button) {
    button.disabled = true;
    button.textContent = 'Subscribing...';
    try {
      const response = await fetch(`/driver/challenges/${challengeId}/subscribe`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || 'Subscription failed');
      }
      button.textContent = 'Subscribed!';
      button.classList.remove('subscribe');
      button.classList.add('close');
      await fetchChallenges();
    } catch (err) {
      console.error(err);
      button.disabled = false;
      button.textContent = 'Subscribe';
      alert(err.message || 'Could not subscribe to challenge.');
    }
  }

  function openOverlay() {
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    fetchChallenges();
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


