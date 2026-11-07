const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../static/progress.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

async function check(explicitStage) {
  const status = {textContent:'已审核'};
  const host = {dataset:{}, style:{}, replaceChildren(){}, append(){}, textContent:''};
  const forms = ['ocr','llm'].map(stage => {
    const button = {textContent:'', disabled:false};
    const events = {};
    return {dataset:{processReport:'1', ...(explicitStage ? {processStage:stage} : {})},
      action:`http://127.0.0.1:8765/report/1/${stage}?project_id=project-a#section`,
      button, events, querySelector:() => button, querySelectorAll:() => [button],
      closest:() => ({querySelector:() => status}), addEventListener:(name,fn) => events[name]=fn};
  });
  let timer;
  let jobs = [{report_id:1, stage:'llm', state:'completed', report_status:'已审核'}];
  const posts = [];
  const document = {
    getElementById:id => id === 'processing-progress' ? host : status,
    querySelectorAll:selector => selector === '[data-process-report]' ? forms : [],
    createElement:() => ({style:{}, append(){}}), dispatchEvent(){}
  };
  vm.runInNewContext(source, {document, location:{href:'http://127.0.0.1:8765/',pathname:'/'},
    URL, window:{alert:message => {throw Error(message);}},
    CustomEvent:class {}, setTimeout:fn => timer=fn,
    fetch:async (url,options) => {
      if (options?.method === 'POST') {
        posts.push(url);
        return {ok:true,json:async () => ({accepted:true})};
      }
      return {ok:true,json:async () => ({jobs,report_states:[]})};
    }});
  await settle();
  assert.equal(forms[0].button.textContent, '重新 OCR');
  assert.equal(forms[1].button.textContent, '重新 AI');
  jobs = [{report_id:1,stage:'llm',state:'queued',created:1}];
  await timer();
  assert.equal(forms[0].button.disabled, false);
  assert.equal(forms[1].button.disabled, true);
  await forms[1].events.submit({defaultPrevented:false,preventDefault(){}});
  assert.equal(new URL(posts[0]).pathname, '/report/1/llm');
  assert.equal(status.textContent, 'AI排队中');
}

(async () => {
  await check(true);
  await check(false);
  console.log('PASS: project query parameters preserve OCR/AI labels, lane disabling and AI submissions.');
})().catch(error => {console.error(error);process.exitCode=1;});
