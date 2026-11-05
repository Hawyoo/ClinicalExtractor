const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../static/report-list.js'),'utf8');
function page(saved) {
  const events={}, changes={};
  const storage=new Map(saved?[['clinical-report-sort-v2',saved]]:[]);
  function row(id,state) {
    const status={textContent:state},count={textContent:'0'},code={textContent:''};
    const error={hidden:true,querySelector:()=>code};
    return {dataset:{reportRow:String(id),reportStatus:state},status,count,error,code,
      querySelector:s=>s==='.status'?status:s==='[data-result-count]'?count:error};
  }
  const refs=[row(3,'已审核'),row(1,'未处理'),row(2,'OCR处理中')];
  const body={items:[...refs],querySelectorAll(){return this.items;},
    append(item){this.items=this.items.filter(row=>row!==item);this.items.push(item);}};
  const select={value:'added',addEventListener:(name,fn)=>changes[name]=fn};
  vm.runInNewContext(source,{document:{getElementById:id=>id==='report-sort'?select:body,
    addEventListener:(name,fn)=>events[name]=fn},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)}});
  return {body,select,refs,storage,ids:()=>body.items.map(row=>Number(row.dataset.reportRow)),
    choose(value){select.value=value;changes.change();},update(detail){events['report-states']({detail});}};
}
const p=page();
assert.deepEqual(p.ids(),[1,2,3]);
p.choose('status');
assert.deepEqual(p.ids(),[1,2,3]);
p.update([{id:2,status:'已审核',n:5,error:''},{id:3,status:'失败',n:0,error:'需要重新识别'}]);
assert.deepEqual(p.ids(),[1,3,2]);
assert.equal(p.refs[2].count.textContent,'5');
assert.equal(p.refs[0].error.hidden,true);
assert.equal(p.refs[0].code.textContent,'');
p.choose('added');
p.update([{id:3,status:'OCR处理中',n:0,error:''}]);
assert.deepEqual(p.ids(),[1,2,3]);
assert.equal(p.refs[0].error.hidden,true);
assert.equal(p.storage.get('clinical-report-sort-v2'),'added');
assert.deepEqual(page('status').ids(),[1,2,3]);
const ordered=page('status');
ordered.update([{id:1,status:'已审核'},{id:2,status:'OCR处理中'},{id:3,status:'待审核'}]);
assert.deepEqual(ordered.ids(),[3,2,1]);
console.log('PASS: live status sorting/counts; errors omitted; selected order preserved.');

const complete=page();
const states=['已审核','OCR排队中','OCR处理中','AI排队中','AI处理中','待处理','待审核'];
complete.body.items=states.map((state,index)=>({dataset:{reportRow:String(index+1),reportStatus:state},querySelector:()=>null}));
complete.choose('status');
assert.deepEqual(complete.ids(),[6,7,5,4,3,2,1]);
complete.body.items.push({dataset:{reportRow:'8',reportStatus:'OCR已完成'},querySelector:()=>null},{dataset:{reportRow:'9',reportStatus:'失败'},querySelector:()=>null});
complete.choose('status');
assert.deepEqual(complete.ids(),[6,7,9,8,5,4,3,2,1]);
assert.equal(page().select.value,'status');
assert.deepEqual(page('added').ids(),[1,2,3]);
