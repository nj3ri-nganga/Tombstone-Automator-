import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {jsPDF} from 'jspdf';
import {borderWidth,borderHeight,borderDpi,borderImage} from '../border-asset.js';
test('preserves the exact approved PNG bytes and its original dimensions',()=>{
 const bytes=Buffer.from(borderImage.split(',')[1],'base64');
 assert.equal(createHash('sha256').update(bytes).digest('hex'),'d2145b27d7f7cf288630b8dfdffed6b263665b3517b141233f420b4064d56dd7');
 assert.equal(bytes.readUInt32BE(16),459);assert.equal(bytes.readUInt32BE(20),609);
 assert.equal(borderWidth,459);assert.equal(borderHeight,609);
});
test('PDF uses the original 150 DPI physical dimensions',()=>{
 const pdf=new jsPDF({unit:'in',format:[borderWidth/borderDpi,borderHeight/borderDpi],orientation:'portrait'});
 assert.ok(Math.abs(pdf.internal.pageSize.getWidth()-3.06)<.001);
 assert.ok(Math.abs(pdf.internal.pageSize.getHeight()-4.06)<.001);
});
