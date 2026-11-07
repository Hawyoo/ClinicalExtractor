const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../../static/template-editor.js'),'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function setup(fail = false) {
  const element = () => ({value:'',hidden:true,disabled:false,open:false,textContent:'',events:{},children:[],
    addEventListener(name,fn){this.events[name]=fn;},replaceChildren(...items){this.children=items;},
    append(item){this.children.push(item);},focus(){},scrollIntoView(){}});
  const ids = Object.fromEntries(['template-editor','template-item-form','template-item-select',
    'template-save-feedback','reload-template-catalog','new-template-section-fields',
    'new-template-section-name','save-template-section','new-template-section','cancel-template-section']
    .map(id=>[id,element()]));
  const fields = Object.fromEntries(['target_code','expected_revision','display_name','section','abbreviation',
    'aliases','reference_ranges','unit','alternative_units'].map(name=>[name,element()]));
  const save = element();
  ids['template-item-form'].elements={namedItem:name=>fields[name]};
  ids['template-item-form'].querySelector=()=>save;
  ids['template-item-form'].action='/templates/items?project_id=p1';
  let catalog={revision:'v1',sections:['肾功能'],items:[{code:'CysC',name:'胱抑素C',section:'肾功能',
    aliases:['Cystatin C'],reference_range:'0.50-1.03',expected_unit:'mg/L'}]};
  const posts=[];
  const document={getElementById:id=>ids[id],createElement:element,addEventListener(){}};
  vm.runInNewContext(source,{document,Option:class {constructor(label,value){this.label=label;this.value=value;}},
    URLSearchParams,FormData:class extends Map {constructor(){super(Object.entries(fields).map(([name,el])=>[name,el.value]));}},
    fetch:async(url,options)=>{
      if (fail) return {status:404,ok:false,headers:new Headers({'content-type':'application/json'}),json:async()=>({detail:'Not Found'})};
      if(options?.method==='POST'){
        posts.push(url);
        assert.equal(url,'/templates/sections');
        assert.equal(options.body.get('expected_revision'),'v1');
        catalog={...catalog,revision:'v2',section:options.body.get('section'),sections:[...catalog.sections,options.body.get('section')],saved:true};
      }
      return {status:200,ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>catalog};
    },Headers});
  return {ids,fields,posts,save};
}

(async()=>{
  const ui=setup();
  ui.ids['template-editor'].open=true;
  ui.ids['template-editor'].events.toggle();
  await settle();
  assert.equal(ui.fields.section.children[0].value,'肾功能');
  assert.equal(ui.fields.section.value,'肾功能');
  assert.equal(ui.save.disabled,false);
  ui.fields.display_name.value='尚未保存的指标名称';
  ui.ids['new-template-section'].events.click();
  assert.equal(ui.ids['new-template-section-fields'].hidden,false);
  ui.ids['new-template-section-name'].value='新分类';
  await ui.ids['save-template-section'].events.click();
  assert.equal(ui.fields.section.value,'新分类');
  assert.equal(ui.fields.expected_revision.value,'v2');
  assert.equal(ui.fields.display_name.value,'尚未保存的指标名称');
  assert.equal(ui.ids['new-template-section-fields'].hidden,true);
  assert.equal(ui.posts.length,1);
  const old=setup(true);
  old.ids['template-editor'].open=true;
  old.ids['template-editor'].events.toggle();
  await settle();
  assert.match(old.ids['template-save-feedback'].textContent,/退出程序再重新启动/);
  assert.equal(old.save.disabled,true);
  console.log('PASS: live section dropdown, inline persistent category creation, draft retention and explicit old-backend 404 message.');
})().catch(error=>{console.error(error);process.exitCode=1;});
