(() => {
  const form=document.getElementById('edit-ocr-text');
  if(!form)return;
  const text=form.querySelector('textarea');
  const feedback=document.getElementById('ocr-text-feedback');
  let saving=false;
  text.addEventListener('keydown',event=>{
    if(event.key==='Tab' && !event.ctrlKey && !event.metaKey && !event.altKey){
      event.preventDefault();text.setRangeText('\t',text.selectionStart,text.selectionEnd,'end');
    }
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(saving)return;saving=true;
    const buttons=Array.from(form.querySelectorAll('button'));buttons.forEach(button=>button.disabled=true);
    const submitted=text.value;
    const data=new FormData(form);data.set('action',event.submitter?.value||'save');
    try{
      const response=await fetch(form.getAttribute('action'),{method:'POST',body:data,headers:{Accept:'application/json'}});
      if(!(response.headers.get('content-type')||'').includes('application/json'))throw new Error('请重启程序并刷新页面后重试');
      const result=await response.json();
      if(!response.ok || !result.saved)throw new Error(result.detail||'保存失败');
      const changedWhileSaving=text.value!==submitted;
      if(!changedWhileSaving)text.value=result.text;
      form.querySelector('[value=restore]').hidden=!result.edited;
      feedback.textContent=result.queued?'文本已保存，AI 已进入队列。':'OCR 文本已保存，可重新执行 AI 更新结果。';
      if(changedWhileSaving)feedback.textContent+=' 当前新修改的文本尚未保存。';
      document.getElementById('report-status').textContent=result.status;
      document.dispatchEvent(new CustomEvent('ocr-text-saved',{detail:result}));
    }catch(error){feedback.textContent=error.message||'保存失败，请重试';}
    finally{saving=false;buttons.forEach(button=>button.disabled=false);}
  });
})();
