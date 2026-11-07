(() => {
  const form = document.getElementById('report-metadata');
  if (!form) return;
  const button = form.querySelector('[data-save-metadata]');
  const fields = [form.elements.namedItem('patient_id'), form.elements.namedItem('profile')];
  const original = fields.map(field => field.tagName === 'SELECT'
    ? Array.from(field.options).find(option => option.defaultSelected)?.value ?? field.options[0].value
    : field.defaultValue);
  const update = () => {
    button.hidden = fields.every((field, index) => field.value === original[index]);
  };
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  form.addEventListener('reset', () => queueMicrotask(update));
  form.addEventListener('submit', event => {
    update();
    if (button.hidden) event.preventDefault();
  });
  update();
})();
