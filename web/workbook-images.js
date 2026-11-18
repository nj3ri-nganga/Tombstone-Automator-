import JSZip from 'jszip';
const tags=(doc,name)=>doc?Array.from(doc.getElementsByTagNameNS('*',name)):[];
const parse=s=>{const doc=new DOMParser().parseFromString(s,'application/xml');if(tags(doc,'parsererror').length)throw Error('Workbook image metadata could not be read.');return doc;};
function resolve(base,target){const out=[];for(const part of (target.startsWith('/')?target.slice(1):base.slice(0,base.lastIndexOf('/')+1)+target).split('/')){if(part==='..')out.pop();else if(part!=='.')out.push(part)}return out.join('/')}
async function docAt(zip,path){const entry=zip.file(path);return entry?parse(await entry.async('string')):null}
async function relsAt(zip,path){const relPath=path.slice(0,path.lastIndexOf('/')+1)+'_rels/'+path.slice(path.lastIndexOf('/')+1)+'.rels';return new Map(tags(await docAt(zip,relPath),'Relationship').filter(r=>r.getAttribute('TargetMode')!=='External').map(r=>[r.getAttribute('Id'),resolve(path,r.getAttribute('Target'))]));}
function columnOf(ref){let c=0;for(const ch of ref.match(/^[A-Z]+/)?.[0]||'')c=c*26+ch.charCodeAt(0)-64;return c-1;}
export async function readWorkbookImages(bytes,sheetName,logoColumn=null){
 const zip=await JSZip.loadAsync(bytes),wb=await docAt(zip,'xl/workbook.xml'),wbRels=await relsAt(zip,'xl/workbook.xml');
 const sheet=tags(wb,'sheet').find(s=>s.getAttribute('name')===sheetName),sheetPath=wbRels.get(sheet?.getAttribute('r:id'));
 const result=new Map();if(!sheetPath)return result;
 const sheetDoc=await docAt(zip,sheetPath),sheetRels=await relsAt(zip,sheetPath);
 async function add(row,path){if(!Number.isInteger(row)||row<0||!path||result.has(row)||! /\.(png|jpe?g|webp)$/i.test(path))return;const entry=zip.file(path);if(!entry)return;if(entry._data?.uncompressedSize>5*1024*1024)return;const data=await entry.async('uint8array');if(data.length>5*1024*1024)return;result.set(row,{data,path,type:/\.png$/i.test(path)?'image/png':/\.webp$/i.test(path)?'image/webp':'image/jpeg'});}
 // In-cell images: cell vm (one-based) -> value metadata -> rich future metadata
 // -> rich value -> LocalImageIdentifier -> ordered image relationship.
 const meta=await docAt(zip,'xl/metadata.xml');
 if(meta){
  const types=tags(tags(meta,'metadataTypes')[0],'metadataType');
  const richType=types.findIndex(t=>t.getAttribute('name')==='XLRICHVALUE')+1;
  const valueBlocks=tags(tags(meta,'valueMetadata')[0],'bk');
  const future=tags(meta,'futureMetadata').find(f=>f.getAttribute('name')==='XLRICHVALUE');
  const futureBlocks=tags(future,'bk');
  const values=tags(await docAt(zip,'xl/richData/rdrichvalue.xml'),'rv');
  const structures=tags(await docAt(zip,'xl/richData/rdrichvaluestructure.xml'),'s');
  const richRels=tags(await docAt(zip,'xl/richData/richValueRel.xml'),'rel');
  const imageRels=await relsAt(zip,'xl/richData/richValueRel.xml');
  for(const cell of tags(sheetDoc,'c')){
   if(!cell.hasAttribute('vm'))continue;const ref=cell.getAttribute('r')||'';
   if(logoColumn!==null&&columnOf(ref)!==logoColumn)continue;
   const vm=Number(cell.getAttribute('vm'));if(!Number.isInteger(vm)||vm<1)continue;
   const rc=tags(valueBlocks[vm-1],'rc').find(rc=>Number(rc.getAttribute('t'))===richType);if(!rc||!richType)continue;
   const rvb=tags(futureBlocks[Number(rc.getAttribute('v'))],'rvb')[0];if(!rvb)continue;
   const value=values[Number(rvb.getAttribute('i'))];if(!value)continue;
   const structure=structures[Number(value.getAttribute('s'))];if(structure?.getAttribute('t')!=='_localImage')continue;
   const key=tags(structure,'k').findIndex(k=>k.getAttribute('n')==='_rvRel:LocalImageIdentifier');if(key<0)continue;
   const index=Number(tags(value,'v')[key]?.textContent);if(!Number.isInteger(index)||index<0)continue;
   const path=imageRels.get(richRels[index]?.getAttribute('r:id'));
   await add(Number(ref.match(/\d+$/)?.[0])-1,path);
  }
 }
 // Floating images remain supported. Only inspect anchors in the logo column.
 for(const drawing of tags(sheetDoc,'drawing')){
  const path=sheetRels.get(drawing.getAttribute('r:id'));if(!path)continue;
  const doc=await docAt(zip,path),rels=await relsAt(zip,path);
  for(const anchor of [...tags(doc,'twoCellAnchor'),...tags(doc,'oneCellAnchor')]){
   const from=tags(anchor,'from')[0];if(!from)continue;
   const col=Number(tags(from,'col')[0]?.textContent);if(logoColumn!==null&&col!==logoColumn)continue;
   const row=Number(tags(from,'row')[0]?.textContent),blip=tags(anchor,'blip')[0];
   await add(row,rels.get(blip?.getAttribute('r:embed')));
  }
 }
 return result;
}
