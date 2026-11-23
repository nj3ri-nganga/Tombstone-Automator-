import {build, context} from 'esbuild';
import {copyFile, mkdir, cp} from 'node:fs/promises';
import {watch} from 'node:fs';
import {fileURLToPath} from 'node:url';
process.chdir(fileURLToPath(new URL('../',import.meta.url)));
await mkdir('dist',{recursive:true});
const copyAssets=()=>Promise.all([...['index.html','style.css'].map(name=>copyFile(name,`dist/${name}`)),cp('assets','dist/assets',{recursive:true})]);
await copyAssets();
const options={entryPoints:['app-source.js'],bundle:true,minify:true,outfile:'dist/app.js',logLevel:'info'};
if(process.argv.includes('--serve')){
 const ctx=await context(options);
 await ctx.watch();
 for(const asset of ['index.html','style.css'])watch(asset,()=>copyAssets().catch(console.error));
 const port=Number(process.env.PORT||5173);
 if(!Number.isInteger(port)||port<1||port>65535)throw Error('PORT must be between 1 and 65535.');
 await ctx.serve({servedir:'dist',host:'127.0.0.1',port});
 console.log(`Tombstone Studio: http://127.0.0.1:${port}`);
}else await build(options);
