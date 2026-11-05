const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync('static/shutdown.js','utf8');

async function simulate(body) {
  let submit, replaced=false;const alerts=[];
  const button={};
  const form={addEventListener:(_,fn)=>submit=fn,querySelector:()=>button};
  const node=()=>({append(){},addEventListener(){}});
  const document={querySelector:()=>form,createElement:node,body:{replaceChildren(){replaced=true}}};
  const context={document,window:{},setTimeout(){},alert:m=>alerts.push(m),
    fetch:async()=>({ok:true,text:async()=>body}),
    DOMParser:class {parseFromString(html){
      return {title:html.match(/<title>(.*?)<\/title>/)?.[1]||'',
              body:{textContent:html.replace(/<[^>]*>/g,'')}};
    }}
  };
  vm.runInNewContext(code,context);
  await submit({defaultPrevented:false,preventDefault(){}});
  return {replaced,alerts,button};
}

test('JSON shutdown acknowledgement',async()=>{
  const result=await simulate('{"status":"shutting_down"}');
  assert.equal(result.replaced,true);assert.equal(result.alerts.length,0);
});
test('legacy HTML quit page is accepted without JSON parse error',async()=>{
  const result=await simulate('<!doctype html><title>已退出 · ClinicalExtractor</title><h1>程序已退出</h1>');
  assert.equal(result.replaced,true);assert.equal(result.alerts.length,0);
});
test('unrelated HTML is not treated as successful shutdown',async()=>{
  const result=await simulate('<!doctype html><title>Error</title><h1>发生错误</h1>');
  assert.equal(result.replaced,false);assert.equal(result.alerts.length,1);
  assert.equal(result.button.disabled,false);
});
