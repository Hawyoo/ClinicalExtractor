(() => {
  const allForm=document.getElementById('confirm-all');
  if(!allForm) return;
  const rows=()=>Array.from(document.querySelectorAll('[data-review-row]'));
  const fields=row=>Array.from(row.querySelectorAll('input'));
  let saving=false;
  let confirmingAll=false;
  function updateAllButton(){
    const button=allForm.querySelector('button');
    const current=rows();
    const confirmed=current.length>0 && current.every(row=>row.classList.contains('row-confirmed'));
    button.textContent=confirmingAll?'确认中…':confirmed?'全部已确认':'全部确认';
    button.classList.toggle('confirmed-button',confirmed && !confirmingAll);
    button.setAttribute('aria-busy',String(confirmingAll));
  }
  const controls=()=>[allForm.querySelector('button'),...rows().flatMap(row=>Array.from(row.querySelectorAll('button')))];
  const feedback=document.createElement('div');feedback.className='review-toast';
  feedback.setAttribute('role','status');feedback.setAttribute('aria-live','polite');feedback.hidden=true;
  document.body.append(feedback);
  function notify(text){feedback.textContent=text;feedback.hidden=false;}
  function mark(row){row.classList.add('row-confirmed');const button=row.querySelector('button');button.textContent='已确认';button.classList.add('confirmed-button');}
  async function save(form, selected, data){
    if(saving) return;
    saving=true;
    confirmingAll=form===allForm;updateAllButton();
    const snapshots=selected.map(row=>fields(row).map(input=>input.value));
    const buttons=controls();
    buttons.forEach(button=>button.disabled=true);
    try{
      const response=await fetch(form.action,{method:'POST',body:data,headers:{Accept:'application/json'},cache:'no-store'});
      if(!(response.headers.get('content-type')||'').includes('application/json')) throw new Error('服务版本已更新，请重启程序并刷新网页后再确认。');
      const result=await response.json();
      if(!response.ok || !result.reviewed) throw new Error(typeof result.detail==='string'?result.detail:'保存失败，请重试');
      let changed=false;
      selected.forEach((row,i)=>{
        if(fields(row).every((input,j)=>input.value===snapshots[i][j]))mark(row);
        else changed=true;
      });
      if(result.report_reviewed && !changed && rows().every(row=>row.classList.contains('row-confirmed'))){const status=document.getElementById('report-status');if(status)status.textContent='已审核';}
      notify(changed?'已保存提交内容，刚修改的内容请再次确认。':confirmingAll?'全部结果已保存并确认':'已保存并确认');
    }catch(error){notify(error.message||'保存失败，请重试');}
    finally{saving=false;confirmingAll=false;buttons.forEach(button=>button.disabled=false);updateAllButton();}
  }
  function bindRow(row){
    const form=document.getElementById(`confirm-${row.dataset.reviewRow}`);
    form.addEventListener('submit',event=>{event.preventDefault();save(form,[row],new FormData(form));});
    const deleteForm=row.querySelector('.delete-result-form');
    if(deleteForm) deleteForm.addEventListener('submit',async event=>{
      event.preventDefault();
      if(saving || !confirm('确定删除这条误读结果？原图和其他指标会保留。'))return;
      saving=true;const buttons=controls();buttons.forEach(button=>button.disabled=true);
      try{
        const response=await fetch(deleteForm.action,{method:'POST',headers:{Accept:'application/json'},cache:'no-store'});
        if(!(response.headers.get('content-type')||'').includes('application/json'))throw new Error('请重启程序并刷新页面后重试');
        const result=await response.json();
        if(!response.ok || !result.deleted)throw new Error(result.detail||'删除失败，请重试');
        document.getElementById(`audit-${row.dataset.reviewRow}`)?.remove();row.remove();
        const details=document.getElementById('review-attention-records');
        if(details){const count=details.querySelectorAll('.attention-evidence').length;
          if(count)details.querySelector('summary').textContent=`查看原文证据与识别校正记录（${count} 行需注意）`;
          else {const note=document.createElement('p');note.id='no-review-attention';note.className='muted';note.textContent='没有需要特别核对的识别校正记录。';details.replaceWith(note);}}
        document.querySelector(`#add-extraction option[value="${row.dataset.reviewRow}"]`)?.remove();
        const status=document.getElementById('report-status');if(status)status.textContent=result.report_reviewed?'已审核':'待审核';
        notify('已删除这条结果');
      }catch(error){notify(error.message||'删除失败，请重试');}
      finally{saving=false;buttons.forEach(button=>button.disabled=false);updateAllButton();}
    });
    fields(row).forEach(input=>input.addEventListener('input',()=>{
      row.classList.remove('row-confirmed');const button=row.querySelector('button');button.textContent='确认';button.classList.remove('confirmed-button');
      updateAllButton();
    }));
  }
  rows().forEach(bindRow);
  updateAllButton();
  document.addEventListener('ocr-text-saved',event=>{
    if(!event.detail.changed)return;
    for(const row of rows()){
      row.classList.remove('row-confirmed');
      const button=row.querySelector('button');button.textContent='确认';button.classList.remove('confirmed-button');
    }
    updateAllButton();
  });
  const addForm=document.getElementById('add-extraction');
  if(addForm)addForm.addEventListener('submit',async event=>{
    event.preventDefault();
    if(saving)return;
    saving=true;const button=addForm.querySelector('button');button.disabled=true;
    const inputs=Array.from(addForm.querySelectorAll('input,select'));
    const submitted=inputs.map(input=>input.value);
    try{
      const response=await fetch(addForm.action,{method:'POST',body:new FormData(addForm),headers:{Accept:'application/json'}});
      if(!(response.headers.get('content-type')||'').includes('application/json'))throw new Error('请重启程序并刷新页面后重试');
      const result=await response.json();
      if(!response.ok || !result.added)throw new Error(result.detail||'添加失败');
      const template=document.createElement('template');template.innerHTML=result.html;
      const row=template.content.firstElementChild;
      const body=document.getElementById('review-results');
      body.querySelector('[data-empty-results]')?.remove();
      const previous=document.querySelector(`[data-review-row="${result.after_eid}"]`);
      if(previous)previous.after(row);else body.prepend(row);
      bindRow(row);
      updateAllButton();
      const option=document.createElement('option');option.value=String(result.eid);option.textContent=`${result.display_name} 之后`;
      const select=addForm.querySelector('[name=after_eid]');
      const previousOption=select.querySelector(`option[value="${result.after_eid}"]`);
      if(previousOption)previousOption.after(option);else select.append(option);
      if(result.attention_html){
        document.getElementById('no-review-attention')?.remove();
        let details=document.getElementById('review-attention-records');
        if(!details){details=document.createElement('details');details.id='review-attention-records';details.className='review-evidence';details.append(document.createElement('summary'));body.closest('.review-table-scroll').before(details);}
        template.innerHTML=result.attention_html;
        const evidence=template.content.firstElementChild;
        const before=Array.from(details.querySelectorAll('.attention-evidence')).find(item=>Number(item.dataset.reviewPriority)>Number(evidence.dataset.reviewPriority));
        if(before)before.before(evidence);else details.append(evidence);
        details.querySelector('summary').textContent=`查看原文证据与识别校正记录（${details.querySelectorAll('.attention-evidence').length} 行需注意）`;
      }
      document.getElementById('report-status').textContent='待审核';
      if(inputs.every((input,index)=>input.value===submitted[index]))addForm.reset();
      notify('已添加，请核对并确认');
    }catch(error){notify(error.message||'添加失败，请重试');}
    finally{saving=false;button.disabled=false;}
  });
  allForm.addEventListener('submit',event=>{
    event.preventDefault();const selected=rows();const data=new FormData();
    for(const row of selected){
      data.append('eids',row.dataset.reviewRow);
      data.append('names',row.querySelector('[name=item_standard]').value);
      data.append('values',row.querySelector('[name=value]').value);
      data.append('units',row.querySelector('[name=unit]').value);
    }
    save(allForm,selected,data);
  });
})();
