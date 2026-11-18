const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('fs');
const assert=require('node:assert/strict');
const html=fs.readFileSync('dist/index.html','utf8').replace('<script src="app.js"></script>','');
const errors=[];
const vc=new VirtualConsole();vc.on('jsdomError',e=>{if(!/getContext/.test(e.message))errors.push(e)});
const dom=new JSDOM(html,{url:'https://studio.test',runScripts:'dangerously',virtualConsole:vc,beforeParse(w){w.structuredClone=structuredClone;w.confirm=()=>true;w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};w.scrollTo=()=>{};w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;}});
const w=dom.window,d=w.document;
async function run(){
w.eval(fs.readFileSync('dist/app.js','utf8'));
const $=id=>d.getElementById(id);
assert.equal($('buyer').value,'Bankwell');assert.equal($('target').value,'Northstead Insurance');assert.equal($('artwork').querySelectorAll('svg').length,1);assert.equal($('png').disabled,false);
$('dealForm').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,0));
assert.equal(JSON.parse(w.localStorage.getItem('tag-tombstone-studio-v1')).deals.length,1);
d.querySelector('[data-page="saved"]').click();assert.equal($('savedPage').hidden,false);assert.equal($('savedGrid').querySelectorAll('.deal-card').length,1);
d.querySelector('[data-copy]').click();assert.match($('title').value,/copy/);$('dealForm').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,0));assert.equal(JSON.parse(w.localStorage.getItem('tag-tombstone-studio-v1')).deals.length,2);
$('advisor').value='This is a very long advisor statement '.repeat(15);$('advisor').dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal($('png').disabled,true);assert.match($('validation').textContent,/exceeds three/);
$('reset').click();d.querySelector('[data-page="library"]').click();$('addCompany').click();$('companyName').value='Acme Insurance';$('companyForm').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,0));assert.equal(JSON.parse(w.localStorage.getItem('tag-tombstone-studio-v1')).companies.length,3);assert.match($('companyGrid').textContent,/Acme Insurance/);
const edit=d.querySelector('[data-edit="demo-bank"]');edit.click();$('companyName').value='Bankwell Updated';$('companyForm').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,0));assert.equal($('buyer').value,'Bankwell Updated');assert.equal(errors.length,0,errors.map(e=>e.stack).join('\n'));
console.log('PASS: initial preview, navigation, saving, duplication, overflow blocking, company creation, company rename and persistence.');dom.window.close();

}
run().catch(e=>{console.error(e);process.exitCode=1;dom.window.close()});
