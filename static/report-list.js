(() => {
  const body=document.getElementById('report-list-body');
  const select=document.getElementById('report-sort');
  if (!body || !select) return;
  const priorities=new Map([
    ['未处理',0],['待处理',0],['待审核',1],['失败',2],['OCR已完成',3],
    ['AI处理中',4],['AI排队中',5],['OCR处理中',6],['OCR排队中',7],['已审核',8]
  ]);
  const rows=()=>Array.from(body.querySelectorAll('[data-report-row]'));
  const added=(a,b)=>Number(a.dataset.reportRow)-Number(b.dataset.reportRow);
  function sortRows() {
    const current=rows();
    const sorted=[...current].sort((a,b)=>select.value==='status'
      ? (priorities.get(a.dataset.reportStatus)??1)-(priorities.get(b.dataset.reportStatus)??1)||added(a,b)
      : added(a,b));
    if (sorted.some((row,index)=>row!==current[index])) sorted.forEach(row=>body.append(row));
  }
  select.value='status';
  try {
    const saved=(typeof window!=='undefined' && window.clinicalPreferences?.report_sort)||sessionStorage.getItem('clinical-report-sort-v2');
    if (['added','status'].includes(saved)) select.value=saved;
  } catch (_) {}
  select.addEventListener('change',()=>{
    try {sessionStorage.setItem('clinical-report-sort-v2',select.value);} catch (_) {}
    if(typeof window!=='undefined'){
      try{localStorage.setItem('clinical-report-sort-v2',select.value);}catch(_){}
      window.saveUIPreferences?.({report_sort:select.value});
    }
    sortRows();
  });
  document.addEventListener('report-states',event=>{
    const byId=new Map(rows().map(row=>[row.dataset.reportRow,row]));
    for (const report of event.detail || []) {
      const row=byId.get(String(report.id));
      if (!row || typeof report.status!=='string') continue;
      row.dataset.reportStatus=report.status;
      const status=row.querySelector('.status');
      if (status) status.textContent=report.status;
      const count=row.querySelector('[data-result-count]');
      if (count && Number.isFinite(report.n)) count.textContent=String(report.n);
    }
    sortRows();
  });
  sortRows();
})();
