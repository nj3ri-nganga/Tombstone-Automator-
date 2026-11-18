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
const dispatch=(id,event='input')=>$(id).dispatchEvent(new w.Event(event,{bubbles:true}));
const save=async()=>{$('dealForm').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await new Promise(r=>setTimeout(r,0))};
const read=()=>JSON.parse(w.localStorage.getItem('tag-tombstone-studio-v1'));
assert.equal($('png').disabled,false);$('layoutPart').value='buyerLogo';dispatch('layoutPart','change');$('layoutSize').value='110';dispatch('layoutSize');assert.equal($('artwork').querySelector('[data-element="buyerLogo"] image').getAttribute('width'),'352');
$('layoutPart').value='targetName';dispatch('layoutPart','change');$('layoutSize').value='22';dispatch('layoutSize');$('layoutAlign').value='left';dispatch('layoutAlign');assert.equal($('artwork').querySelector('[data-element="targetName"] text').getAttribute('font-size'),'22');assert.equal($('artwork').querySelector('[data-element="targetName"] text').getAttribute('text-anchor'),'start');
$('layoutPart').value='transaction';dispatch('layoutPart','change');d.querySelector('[data-nudge="dy:2"]').click();assert.equal($('layoutY').value,'2');
await save();assert.equal(read().deals[0].layout.elements.buyerLogo.size,110);assert.equal(read().deals[0].layout.elements.transaction.dy,2);assert.equal(read().companies[0].scale,100);
d.querySelector('[data-page="saved"]').click();assert.equal($('savedGrid').querySelectorAll('[stroke-dasharray="4 3"]').length,0);d.querySelector('[data-copy]').click();assert.equal($('layoutY').value,'2');$('layoutY').value='4';dispatch('layoutY','change');await save();assert.equal(read().deals.length,2);assert.equal(read().deals[1].layout.elements.transaction.dy,2);assert.equal(read().deals[0].layout.elements.transaction.dy,4);
$('layoutReset').click();assert.equal($('layoutSize').value,'18');assert.equal($('layoutY').value,'0');$('layoutPart').value='buyerLogo';dispatch('layoutPart','change');$('layoutX').value='150';dispatch('layoutX','change');assert.equal($('png').disabled,true);assert.match($('validation').textContent,/outside the frame/);$('layoutCenter').click();assert.equal($('png').disabled,false);
w.prompt=()=> 'My compact layout';$('layoutSpacing').value='95';dispatch('layoutSpacing');$('layoutSaveTemplate').click();await new Promise(r=>setTimeout(r,0));assert.equal(read().layoutTemplates[0].name,'My compact layout');$('layoutReset').click();$('layoutTemplates').value=read().layoutTemplates[0].id;dispatch('layoutTemplates','change');assert.equal($('layoutSpacing').value,'95');
$('reset').click();assert.equal($('layoutSize').value,'100');assert.equal($('layoutSpacing').value,'100');
assert.equal(errors.length,0,errors.map(e=>e.stack).join('\n'));
console.log('PASS: logo resizing, font size, alignment, nudging, per-deal persistence, independent duplication, clean saved previews, frame limits, reset and reusable layouts.');dom.window.close();

}
run().catch(e=>{console.error(e);process.exitCode=1;dom.window.close()});
