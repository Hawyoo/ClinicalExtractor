(() => {
  const host = document.getElementById('processing-progress');
  if (!host) return;
  const states = {queued:'排队中', running:'处理中', completed:'已完成', failed:'失败'};
  const forms = Array.from(document.querySelectorAll('[data-process-report]'));
  function processStage(form) {
    if (['ocr', 'llm'].includes(form.dataset.processStage)) return form.dataset.processStage;
    return new URL(form.action, location.href).pathname.endsWith('/llm') ? 'llm' : 'ocr';
  }
  function reportLabel(job) {
    const row=Array.from(document.querySelectorAll('[data-report-row]')).find(row=>row.dataset.reportRow===String(job.report_id));
    if (row?.dataset.reportLabel) return row.dataset.reportLabel;
    if (host.dataset.report===String(job.report_id) && host.dataset.label) return host.dataset.label;
    return job.file_name ? job.label : String(job.label || '报告').split(' · ')[0];
  }
  function setReportStatus(reportId, status) {
    if (host.dataset.report === String(reportId)) {
      const label = document.getElementById('report-status');
      if (label) label.textContent = status;
    }
    for (const form of forms.filter(f => f.dataset.processReport === String(reportId))) {
      const label = form.closest('tr')?.querySelector('.status');
      if (label) label.textContent = status;
      if (['OCR已完成','待审核','已审核'].includes(status)) {
        const button = form.querySelector('button');
        if (button) button.textContent = processStage(form) === 'llm' ? '重新 AI' : '重新 OCR';
      }
    }
  }
  for (const form of forms) {
    const stage = processStage(form);
    const button = form.querySelector('button');
    const status = form.closest('tr')?.querySelector('.status')?.textContent || document.getElementById('report-status')?.textContent;
    if (button && ['OCR已完成','待审核','已审核'].includes(status?.trim())) {
      button.textContent = stage === 'llm' ? '重新 AI' : '重新 OCR';
    }
    form.addEventListener('submit', async event => {
      if (event.defaultPrevented) return;
      event.preventDefault();
      if (form.dataset.submitting) return;
      form.dataset.submitting = '1';
      if (button) button.disabled = true;
      let accepted = false;
      try {
        const response = await fetch(form.action, {method:'POST', headers:{Accept:'application/json'}});
        if (!response.ok) throw new Error('提交失败，请重试');
        const result = await response.json();
        if (!result.accepted) throw new Error('提交失败，请重试');
        accepted = true;
        setReportStatus(form.dataset.processReport, stage === 'llm' ? 'AI排队中' : 'OCR排队中');
        await poll(false);
      } catch (error) {
        window.alert(error.message || '提交失败，请重试');
      } finally {
        delete form.dataset.submitting;
        if (button && !accepted) button.disabled = false;
      }
    });
  }
  function currentStep(job) {
    if (job.state !== 'running') return states[job.state] || '处理中';
    const message = job.message || '';
    if (message.includes('保存')) return '保存结果';
    if (message.includes('校验原文')) return '校验结果';
    if (message.includes('连接 Ollama')) return '加载 AI 模型';
    if (message.includes('加载')) return '加载模型';
    if (message.includes('匹配') || message.includes('模板')) return '校验模板';
    if (message.includes('核对项目名称')) return 'AI 核对';
    if (message.includes('AI') || message.includes('Ollama')) return 'AI 处理';
    if (message.includes('定位表格') || message.includes('恢复行列')) return '整理表格';
    if (message.includes('整理')) return '整理结果';
    if (message.includes('OCR 完成')) return '整理结果';
    if (message.includes('识别')) return '识别文字';
    if (message.includes('读取')) return '准备处理';
    return job.stage === 'llm' ? 'AI 处理' : 'OCR 处理';
  }
  async function poll(schedule = true) {
    try {
      const response = await fetch('/jobs', {cache:'no-store'});
      if (!response.ok) throw new Error('进度读取失败');
      const data = await response.json();
      for (const job of data.jobs) {
        if (job.report_status) setReportStatus(job.report_id, job.report_status);
      }
      document.dispatchEvent(new CustomEvent('report-states', {detail: data.report_states ||
        data.jobs.map(job=>({id:job.report_id,status:job.report_status}))}));
      const jobs = data.jobs.filter(j => host.dataset.report
        ? String(j.report_id) === host.dataset.report
        : ['queued','running'].includes(j.state)).sort((a,b)=>
          (a.state==='running'?0:a.state==='queued'?1:2)-(b.state==='running'?0:b.state==='queued'?1:2)
          || a.created-b.created);
      host.replaceChildren();
      const active = data.jobs.filter(j=>['queued','running'].includes(j.state));
      if (active.length) {
        const overview=document.createElement('section');overview.className='card';overview.style.gridColumn='1 / -1';
        for (const [stage,label] of [['ocr','OCR'],['llm','AI']]) {
          const current=active.find(j=>j.stage===stage && j.state==='running');
          const queued=active.filter(j=>j.stage===stage && j.state==='queued').length;
          if (!current && !queued) continue;
          const line=document.createElement('p');
          line.textContent=current ? `${label}：${currentStep(current)} · ${reportLabel(current)}；后续 ${queued} 份排队`
            : `${label}：${queued} 份排队，等待开始`;
          overview.append(line);
        }
        host.append(overview);
      }
      if (data.total_timer?.started) {
        const summary=document.createElement('p');summary.className='processing-total';
        summary.style.gridColumn='1 / -1';
        summary.textContent=`总用时：${Math.floor(data.total_timer.elapsed)} 秒`;
        host.append(summary);
      }
      const lanes = {};
      for (const [stage,label] of [['ocr','OCR 工序'],['llm','AI 工序']]) {
        const laneJobs=jobs.filter(j=>j.stage===stage);
        if (!laneJobs.length) continue;
        const group=document.createElement('div');group.className='processing-lane';
        const heading=document.createElement('h2');
        heading.textContent=`${label}（处理中 ${laneJobs.filter(j=>j.state==='running').length} · 排队 ${laneJobs.filter(j=>j.state==='queued').length}）`;
        group.append(heading);host.append(group);lanes[stage]=group;
      }
      document.querySelectorAll('[data-process-report]').forEach(form=>{
        const stage=processStage(form);
        const busy=jobs.some(j=>String(j.report_id)===form.dataset.processReport && j.stage===stage && ['queued','running'].includes(j.state));
        form.querySelectorAll('button').forEach(b=>b.disabled=busy || Boolean(form.dataset.submitting));
      });
      for (const job of jobs) {
        const panel = document.createElement('section'); panel.className='card';
        const title = document.createElement('h2'); title.textContent=reportLabel(job);
        const status = document.createElement('p');
        status.textContent=job.state==='running'
          ? `${currentStep(job)} · 用时 ${Math.floor(job.elapsed)} 秒`
          : currentStep(job);
        panel.append(title,status);
        if (job.state==='failed') {
          const error=document.createElement('p');error.className='error';error.textContent=job.message;panel.append(error);
        }
        (lanes[job.stage]||host).append(panel);
        if (['completed','failed'].includes(job.state)) {
          const link=document.createElement('a');link.href=host.dataset.report ? location.pathname : '/';
          link.textContent='刷新查看最新结果';panel.append(link);
        }
      }
    } catch (_) {
      if (!host.textContent) host.textContent='暂时无法获取处理进度，请检查程序是否正在运行。';
    }
    if (schedule) setTimeout(poll,1000);
  }
  poll();
})();
