(() => {
  const projectId = window.clinicalProjectId;
  if (!projectId) return;
  const scopedURL = value => {
    const url = new URL(value, location.href);
    if (url.origin !== location.origin) return value;
    url.searchParams.set('project_id', projectId);
    return url.href;
  };
  // Old tabs retain their project identity; they cannot write into a new one.
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, options = {}) => {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
    if (url.origin !== location.origin) return originalFetch(input, options);
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
    headers.set('X-Clinical-Project', projectId);
    return originalFetch(input, {...options, headers}).then(response => {
      if (response.headers.get('X-Clinical-Project-Changed') === '1') location.replace('/');
      return response;
    });
  };
  const bindForm = form => form.setAttribute('action', scopedURL(form.getAttribute('action') || location.href));
  document.querySelectorAll('form').forEach(bindForm);
  document.addEventListener('submit', event => bindForm(event.target), true);
  document.querySelectorAll('a[href]').forEach(link => {
    const href = link.getAttribute('href');
    if (href.startsWith('/') && !href.startsWith('//')) link.href = scopedURL(href);
  });
  const select = document.getElementById('current-project');
  select?.addEventListener('change', () => document.getElementById('switch-project').requestSubmit());
})();
