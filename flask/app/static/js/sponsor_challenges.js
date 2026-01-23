(function () {
  const state = {
    sponsorId: null,
    templates: [],
    selectedTemplateId: null,
    filter: 'all',
  };

  function csrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function isoOrNull(value) {
    if (!value) return null;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    return date.toISOString();
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

  function formatDescription(value) {
    if (!value) return '<em>No description provided.</em>';
    return escapeHtml(value).replace(/\n/g, '<br>');
  }

  function formatDate(value) {
    if (!value) return 'No expiration';
    try {
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return 'Invalid date';
      return d.toLocaleString();
    } catch (err) {
      return value;
    }
  }

  let toastHideTimer = null;

  function showToast(message, tone = 'success') {
    const toast = document.getElementById('challenge-toast');
    if (!toast) return;
    toast.textContent = message;
    if (tone === 'error') {
      toast.setAttribute('data-tone', 'error');
    } else {
      toast.removeAttribute('data-tone');
    }
    toast.style.display = 'block';
    if (toastHideTimer) {
      clearTimeout(toastHideTimer);
    }
    toastHideTimer = setTimeout(() => {
      toast.style.display = 'none';
      toast.removeAttribute('data-tone');
    }, 3200);
  }

  async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken(),
        ...(options.headers || {}),
      },
      ...options,
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || 'Request failed');
      error.response = response;
      throw error;
    }
    return data;
  }

  async function loadTemplates() {
    try {
      const data = await fetchJSON('/sponsor/challenge-templates');
      state.templates = Array.isArray(data) ? data : [];
      renderTemplatePills();
    } catch (err) {
      console.error(err);
      showToast(err.message || 'Failed to load templates', 'error');
    }
  }

  function renderTemplatePills() {
    const container = document.getElementById('template-pills');
    if (!container) return;
    container.innerHTML = '';

    if (!state.templates.length) {
      container.innerHTML = '<p class="text-muted">No templates available. Please contact support.</p>';
      return;
    }

    state.templates.forEach((template) => {
      const pill = document.createElement('button');
      pill.type = 'button';
      pill.className = 'template-pill' + (state.selectedTemplateId === template.id ? ' active' : '');
      pill.textContent = template.title;
      pill.addEventListener('click', () => {
        state.selectedTemplateId = template.id;
        fillFormFromTemplate(template);
        renderTemplatePills();
      });
      container.appendChild(pill);
    });
  }

  function fillFormFromTemplate(template) {
    const form = document.getElementById('challenge-create-form');
    if (!form || !template) return;
    if (template.title) form.querySelector('input[name="title"]').value = template.title;
    if (template.description) form.querySelector('textarea[name="description"]').value = template.description;
    if (template.default_reward_points != null) {
      form.querySelector('input[name="reward_points"]').value = template.default_reward_points;
    }
  }

  async function createChallenge(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;

    const payload = {
      template_id: state.selectedTemplateId,
      title: form.title.value.trim(),
      description: form.description.value.trim() || null,
      reward_points: form.reward_points.value ? parseInt(form.reward_points.value, 10) : null,
      is_optional: form.is_optional.value === 'true',
      starts_at: isoOrNull(form.starts_at.value),
      expires_at: isoOrNull(form.expires_at.value),
    };

    try {
      if (!payload.title) {
        throw new Error('Title is required.');
      }
      if (!payload.reward_points || Number.isNaN(payload.reward_points) || payload.reward_points <= 0) {
        throw new Error('Reward points must be a positive number.');
      }
      await fetchJSON('/sponsor/challenges', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      showToast('Challenge created successfully.');
      form.reset();
      state.selectedTemplateId = null;
      renderTemplatePills();
      loadChallenges();
    } catch (err) {
      console.error(err);
      showToast(err.message || 'Failed to create challenge', 'error');
    } finally {
      btn.disabled = false;
    }
  }

  async function loadChallenges() {
    try {
      const query = state.filter && state.filter !== 'all' ? `?status=${encodeURIComponent(state.filter)}` : '';
      const data = await fetchJSON(`/sponsor/challenges${query}`);
      renderChallenges(data.challenges || []);
    } catch (err) {
      console.error(err);
      showToast(err.message || 'Failed to load challenges', 'error');
    }
  }

  function statusKey(value) {
    return (value || '').toString().toLowerCase() || 'unknown';
  }

  function statusLabel(value) {
    const key = statusKey(value);
    switch (key) {
      case 'active':
        return 'Active';
      case 'upcoming':
        return 'Upcoming';
      case 'expired':
        return 'Expired';
      case 'deactivated':
        return 'Deactivated';
      default:
        return key ? key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) : 'Status';
    }
  }

  function renderChallenges(challenges) {
    const list = document.getElementById('challenge-list');
    if (!list) return;
    list.innerHTML = '';

    if (!challenges.length) {
      list.innerHTML = '<div class="empty-state">No challenges found for this filter.</div>';
      return;
    }

    challenges.forEach((challenge) => {
      const card = document.createElement('div');
      card.className = 'card challenge-card';
      card.dataset.challengeId = challenge.id;

      const statusClass = `challenge-status challenge-status--${statusKey(challenge.status)}`;
      const optionalLabel = challenge.is_optional ? 'Optional' : 'Required';
      const titleSafe = escapeHtml(challenge.title || 'Untitled Challenge');
      const descHtml = formatDescription(challenge.description);
      const startsAt = challenge.starts_at ? formatDate(challenge.starts_at) : 'Immediately';
      const expiresAt = challenge.expires_at ? formatDate(challenge.expires_at) : 'No expiration';

      card.innerHTML = `
        <div class="challenge-card__header">
          <div>
            <h3 class="challenge-card__title">${titleSafe}</h3>
            <div class="challenge-card__meta">
              <span>${challenge.template_id ? 'Template-based' : 'Custom'}</span>
              <span aria-hidden="true">&middot;</span>
              <span>${optionalLabel}</span>
            </div>
          </div>
          <span class="${statusClass}">${statusLabel(challenge.status)}</span>
        </div>

        <p class="challenge-card__description text-muted">${descHtml}</p>

        <div class="challenge-card__grid">
          <div class="challenge-card__grid-item">
            <strong>Reward</strong>
            <span>${challenge.reward_points || 0} pts</span>
          </div>
          <div class="challenge-card__grid-item">
            <strong>Starts</strong>
            <span>${startsAt}</span>
          </div>
          <div class="challenge-card__grid-item">
            <strong>Expires</strong>
            <span>${expiresAt}</span>
          </div>
        </div>

        <div class="challenge-card__actions">
          <button class="btn btn-secondary" type="button" data-action="toggle-edit">Edit</button>
          <button class="btn btn-danger" type="button" data-action="deactivate" ${statusKey(challenge.status) === 'deactivated' ? 'disabled' : ''}>Deactivate</button>
        </div>

        <form class="challenge-edit" novalidate>
          <div class="form-grid">
            <label>Title<input type="text" name="title" value="${escapeHtml(challenge.title || '')}" required></label>
            <label>Reward Points<input type="number" name="reward_points" min="1" value="${challenge.reward_points || ''}" required></label>
            <label>Optional?<select name="is_optional">
              <option value="true" ${challenge.is_optional ? 'selected' : ''}>Optional</option>
              <option value="false" ${challenge.is_optional ? '' : 'selected'}>Required</option>
            </select></label>
            <label>Starts At<input type="datetime-local" name="starts_at" value="${challenge.starts_at ? localValue(challenge.starts_at) : ''}"></label>
            <label>Expires At<input type="datetime-local" name="expires_at" value="${challenge.expires_at ? localValue(challenge.expires_at) : ''}"></label>
          </div>
          <label>Description<textarea name="description">${escapeHtml(challenge.description || '')}</textarea></label>
          <div class="challenge-edit__actions">
            <button class="btn btn-info" type="submit">Save Changes</button>
            <button class="btn btn-secondary" type="button" data-action="cancel-edit">Cancel</button>
          </div>
        </form>
      `;

      list.appendChild(card);
    });

    attachCardListeners();
  }

  function localValue(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function attachCardListeners() {
    const list = document.getElementById('challenge-list');
    if (!list) return;

    list.querySelectorAll('[data-action="toggle-edit"]').forEach((button) => {
      button.addEventListener('click', () => {
        const card = button.closest('.challenge-card');
        if (!card) return;
        const form = card.querySelector('.challenge-edit');
        if (!form) return;
        const isOpen = form.classList.contains('is-open');
        form.classList.toggle('is-open', !isOpen);
      });
    });

    list.querySelectorAll('[data-action="cancel-edit"]').forEach((button) => {
      button.addEventListener('click', () => {
        const form = button.closest('.challenge-edit');
        if (!form) return;
        form.classList.remove('is-open');
      });
    });

    list.querySelectorAll('[data-action="deactivate"]').forEach((button) => {
      button.addEventListener('click', async () => {
        const card = button.closest('.challenge-card');
        const id = card.dataset.challengeId;
        if (!id) return;
        if (!confirm('Deactivate this challenge? Drivers will immediately lose access.')) return;
        button.disabled = true;
        try {
          await fetchJSON(`/sponsor/challenges/${id}/deactivate`, { method: 'PATCH', body: '{}' });
          showToast('Challenge deactivated.');
          loadChallenges();
        } catch (err) {
          console.error(err);
          showToast(err.message || 'Failed to deactivate challenge', 'error');
        } finally {
          button.disabled = false;
        }
      });
    });

    list.querySelectorAll('.challenge-edit').forEach((form) => {
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const card = form.closest('.challenge-card');
        const id = card.dataset.challengeId;
        const submitBtn = form.querySelector('button[type="submit"]');
        submitBtn.disabled = true;
        const payload = {
          title: form.title.value.trim(),
          description: form.description.value.trim(),
          reward_points: form.reward_points.value ? parseInt(form.reward_points.value, 10) : null,
          is_optional: form.is_optional.value === 'true',
          starts_at: isoOrNull(form.starts_at.value),
          expires_at: isoOrNull(form.expires_at.value),
        };
        try {
          await fetchJSON(`/sponsor/challenges/${id}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
          });
          showToast('Challenge updated.');
          form.classList.remove('is-open');
          loadChallenges();
        } catch (err) {
          console.error(err);
          showToast(err.message || 'Failed to update challenge', 'error');
        } finally {
          submitBtn.disabled = false;
        }
      });
    });
  }

  function bindEvents() {
    const form = document.getElementById('challenge-create-form');
    if (form) {
      form.addEventListener('submit', createChallenge);
    }

    const resetBtn = document.getElementById('reset-form-btn');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        if (form) form.reset();
        state.selectedTemplateId = null;
        renderTemplatePills();
      });
    }

    const filterSelect = document.getElementById('challenge-filter');
    if (filterSelect) {
      filterSelect.addEventListener('change', () => {
        state.filter = filterSelect.value;
        loadChallenges();
      });
    }
  }

  window.SponsorChallenges = {
    init(options = {}) {
      state.sponsorId = options.sponsorId || null;
      bindEvents();
      loadTemplates();
      loadChallenges();
    },
  };
})();


