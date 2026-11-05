(() => {
  const prefs=window.clinicalPreferences||{};
  let pending=Promise.resolve();
  window.saveUIPreferences=patch=>{
    Object.assign(prefs,patch);
    pending=pending.catch(()=>{}).then(async()=>{
      const response=await fetch('/preferences',{method:'POST',body:new URLSearchParams(patch),headers:{Accept:'application/json'},keepalive:true});
      if(!response.ok)throw new Error('界面偏好未保存到软件数据目录');
    });
    pending.catch(error=>console.warn(error.message));
    return pending;
  };
  const migration={};
  try{
    if(!prefs.theme){const legacy=localStorage.getItem('theme-preference');if(['dark','light'].includes(legacy))migration.theme=legacy;}
    if(!prefs.report_sort){const legacy=localStorage.getItem('clinical-report-sort-v2')||sessionStorage.getItem('clinical-report-sort-v2');if(['status','added'].includes(legacy))migration.report_sort=legacy;}
  }catch(_){}
  Object.assign(prefs,migration);
  prefs.theme=prefs.theme||'light';prefs.report_sort=prefs.report_sort||'status';
  window.clinicalPreferences=prefs;
  function applyTheme(){
    const dark=prefs.theme==='dark';
    document.documentElement.dataset.theme=dark?'dark':'light';
    const button=document.getElementById('theme-toggle');
    if(button){button.textContent=dark?'☀️':'🌙';button.setAttribute('aria-pressed',String(dark));button.title=dark?'切换浅色模式':'切换夜间模式';}
    try{localStorage.setItem('theme-preference',prefs.theme);}catch(_){}
  }
  applyTheme();
  if(Object.keys(migration).length)window.saveUIPreferences(migration);
  document.getElementById('theme-toggle')?.addEventListener('click',()=>{
    prefs.theme=prefs.theme==='dark'?'light':'dark';applyTheme();window.saveUIPreferences({theme:prefs.theme});
  });
})();
