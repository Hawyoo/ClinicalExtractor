const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../static/preferences.js'),'utf8');
function setup(prefs,legacy,blocked=false){
  const clicks={},writes=[],data=new Map(legacy?Object.entries(legacy):[]);
  const storage={getItem:key=>{if(blocked)throw Error('blocked');return data.get(key);},setItem:(key,value)=>{if(blocked)throw Error('blocked');data.set(key,value);}};
  const button={setAttribute(){},addEventListener:(event,fn)=>clicks[event]=fn};
  const document={documentElement:{dataset:{}},getElementById:()=>button};
  const window={clinicalPreferences:{...prefs}};
  vm.runInNewContext(source,{window,document,localStorage:storage,sessionStorage:storage,URLSearchParams,console,
    fetch:async(url,options)=>{writes.push(Object.fromEntries(options.body));return {ok:true};}});
  return {window,document,button,clicks,writes};
}
(async()=>{
  const p=setup({theme:'dark',report_sort:'added'},{'theme-preference':'light'});
  assert.equal(p.document.documentElement.dataset.theme,'dark');
  p.clicks.click();
  await p.window.saveUIPreferences({report_sort:'status'});
  assert.equal(p.document.documentElement.dataset.theme,'light');
  assert.deepEqual(p.writes,[{theme:'light'},{report_sort:'status'}]);
  const legacy=setup({theme:null,report_sort:null},{'theme-preference':'dark'});
  await legacy.window.saveUIPreferences({report_sort:'status'});
  assert.equal(legacy.document.documentElement.dataset.theme,'dark');
  assert.equal(legacy.writes[0].theme,'dark');
  const denied=setup({theme:'dark',report_sort:'status'},null,true);
  denied.clicks.click();
  await denied.window.saveUIPreferences({report_sort:'added'});
  assert.equal(denied.document.documentElement.dataset.theme,'light');
  console.log('PASS: durable preferences, legacy migration, serialized saves and blocked browser storage.');
})().catch(error=>{console.error(error);process.exitCode=1;});
