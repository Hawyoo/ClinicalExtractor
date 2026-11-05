(() => {
  const forms=Array.from(document.querySelectorAll('[data-delete-report]'));
  function setRunning(form,running){
    form.dataset.running=running?'1':'0';
    for(const button of form.querySelectorAll('button')){
      button.disabled=running || form.dataset.deleting==='1';
      button.title=running?'正在处理，完成后可删除':'';
    }
    if(running)reset(form);
  }
  function reset(form){
    delete form.dataset.confirming;
    const toggle=form.querySelector('[type=button]');
    toggle.textContent='删除';toggle.classList.add('report-delete-button');
    const confirm=form.querySelector('[type=submit]');
    confirm.hidden=true;confirm.textContent='确认删除';
  }
  for(const form of forms){
    const button=form.querySelector('[type=submit]');
    const toggle=form.querySelector('[type=button]');
    const feedback=form.closest('.report-actions').nextElementSibling;
    setRunning(form,['OCR处理中','AI处理中'].includes(form.dataset.status));
    toggle.addEventListener('click',()=>{
      if(form.dataset.running==='1' || form.dataset.deleting==='1')return;
      feedback.textContent='';
      if(form.dataset.confirming){reset(form);return;}
      form.dataset.confirming='1';toggle.textContent='取消';
      toggle.classList.remove('report-delete-button');button.hidden=false;
    });
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      if(form.dataset.running==='1' || form.dataset.deleting==='1')return;
      if(!form.dataset.confirming)return;
      form.dataset.deleting='1';button.disabled=true;toggle.disabled=true;button.textContent='删除中…';
      try{
        const response=await fetch(form.action,{method:'POST',headers:{Accept:'application/json'}});
        if(!(response.headers.get('content-type')||'').includes('application/json'))throw new Error('请重启程序并刷新页面后重试');
        const result=await response.json();
        if(!response.ok || !result.deleted){
          if(result.running)setRunning(form,true);
          throw new Error(result.detail||'删除失败，请重试');
        }
        if(form.dataset.list==='1'){
          form.closest('[data-report-row]').remove();
          document.dispatchEvent(new CustomEvent('report-deleted',{detail:{id:Number(form.dataset.deleteReport)}}));
        }else window.location.assign('/');
      }catch(error){feedback.textContent=error.message||'删除失败，请重试';reset(form);}
      finally{delete form.dataset.deleting;setRunning(form,form.dataset.running==='1');}
    });
  }
  document.addEventListener('report-states',event=>{
    const states=new Map((event.detail||[]).map(report=>[String(report.id),report]));
    for(const form of forms){
      const state=states.get(form.dataset.deleteReport);
      if(state)setRunning(form,typeof state.running==='boolean'?state.running:['OCR处理中','AI处理中'].includes(state.status));
    }
  });
})();
