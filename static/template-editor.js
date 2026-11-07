(() => {
  const panel = document.getElementById('template-editor');
  if (!panel) return;
  const form = document.getElementById('template-item-form');
  const select = document.getElementById('template-item-select');
  const feedback = document.getElementById('template-save-feedback');
  const save = form.querySelector('[type=submit]');
  const reload = document.getElementById('reload-template-catalog');
  const field = name => form.elements.namedItem(name);
  let catalog, loading, saving = false;
  function populate(code = '') {
    const item = catalog.items.find(item => item.code === code);
    field('target_code').value = item?.code || '';
    field('expected_revision').value = catalog.revision;
    field('display_name').value = item?.display_name || item?.name || '';
    field('section').value = item?.section || catalog.sections[0] || '';
    field('abbreviation').value = item?.abbreviation || item?.code || '';
    field('aliases').value = (item?.aliases || []).join('\n');
    field('reference_ranges').value = item
      ? [item.reference_range, ...(item.alternative_reference_ranges || [])].filter(Boolean).join('\n')
      : '';
    field('unit').value = item?.expected_unit || '';
    field('alternative_units').value = (item?.alternative_units || []).join('\n');
    select.value = item?.code || '';
  }
  function renderOptions() {
    const selected = select.value;
    const selectedSection = field('section').value;
    select.replaceChildren(new Option('新增指标', ''));
    const sections = field('section');
    sections.replaceChildren();
    for (const section of catalog.sections) {
      sections.append(new Option(section, section));
      const group = document.createElement('optgroup');
      group.label = section;
      for (const item of catalog.items.filter(item => item.section === section)) {
        group.append(new Option(`${item.display_name || item.name} · ${item.abbreviation || item.code}`, item.code));
      }
      select.append(group);
    }
    select.value = selected;
    sections.value = catalog.sections.includes(selectedSection) ? selectedSection : catalog.sections[0] || '';
  }
  async function readResponse(response) {
    if (response.status === 404) throw Error('当前后台尚未加载模板接口，请先退出程序再重新启动；便携版需重新构建后启动。');
    if (!(response.headers.get('content-type') || '').includes('application/json')) throw Error('模板接口未就绪，请退出程序后重新启动。');
    const result = await response.json();
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : '模板操作失败，请检查程序日志或重新启动。');
    if (!Array.isArray(result.items) || !Array.isArray(result.sections)) throw Error('模板数据格式不完整，请重启程序后重试。');
    return result;
  }
  async function load(force = false) {
    if (catalog && !force) return catalog;
    if (loading) return loading;
    save.disabled = true;
    loading = (async () => {
      const response = await fetch('/templates/catalog', {cache:'no-store', headers:{Accept:'application/json'}});
      catalog = await readResponse(response);
      renderOptions();
      populate();
      save.disabled = false;
      return catalog;
    })();
    try { return await loading; } finally { loading = null; }
  }
  panel.addEventListener('toggle', () => {
    if (panel.open) load(true).catch(error => feedback.textContent = error.message);
  });
  select.addEventListener('change', () => { populate(select.value); feedback.textContent = ''; });
  reload.addEventListener('click', async () => {
    if (saving) return;
    try { await load(true); feedback.textContent = '模板已重新加载'; }
    catch (error) { feedback.textContent = error.message; }
  });
  const sectionFields = document.getElementById('new-template-section-fields');
  const sectionName = document.getElementById('new-template-section-name');
  const addSection = document.getElementById('save-template-section');
  document.getElementById('new-template-section').addEventListener('click', () => {
    if (!catalog || saving) return;
    sectionFields.hidden = false;
    sectionName.focus();
  });
  document.getElementById('cancel-template-section').addEventListener('click', () => {
    sectionFields.hidden = true;
    sectionName.value = '';
  });
  sectionName.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); addSection.click(); }
  });
  addSection.addEventListener('click', async () => {
    if (saving || !catalog) return;
    if (!sectionName.value.trim()) { feedback.textContent = '请填写新分类名称'; return; }
    saving = true;
    save.disabled = reload.disabled = select.disabled = addSection.disabled = true;
    try {
      const response = await fetch('/templates/sections', {method:'POST',
        body:new URLSearchParams({section:sectionName.value.trim(),expected_revision:catalog.revision}),
        headers:{Accept:'application/json'}});
      const result = await readResponse(response);
      catalog = result;
      renderOptions();
      field('section').value = result.section;
      field('expected_revision').value = result.revision;
      sectionFields.hidden = true;
      sectionName.value = '';
      feedback.textContent = '分类已新建并选中，当前指标编辑内容已保留。';
    } catch (error) { feedback.textContent = error.message; }
    finally { saving = false; save.disabled = reload.disabled = select.disabled = addSection.disabled = false; }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || !catalog) return;
    saving = true;
    save.disabled = reload.disabled = select.disabled = true;
    feedback.textContent = '正在保存模板…';
    const values = new FormData(form);
    try {
      const response = await fetch(form.action, {method:'POST', body:values, headers:{Accept:'application/json'}});
      const result = await readResponse(response);
      if (!result.saved) throw Error('模板保存失败，请检查填写内容');
      catalog = result;
      renderOptions();
      // Preserve any edits typed during the save rather than silently discarding them.
      const changed = [...values].some(([name, value]) => field(name)?.value !== value);
      if (!changed) populate(result.item.code);
      else {
        field('expected_revision').value = result.revision;
        field('target_code').value = result.item.code;
        select.value = result.item.code;
      }
      feedback.textContent = changed ? '提交的模板已保存；当前新修改的内容尚未保存。'
        : '模板已保存。后续匹配立即使用；刷新页面可查看展示名称变化。报告结果和审核状态未改动。';
    } catch (error) { feedback.textContent = error.message || '模板保存失败，请重试'; }
    finally { saving = false; save.disabled = reload.disabled = select.disabled = false; }
  });
})();
