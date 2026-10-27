import test from 'node:test'
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {createSha256,hashUploadFile} from '../src/domain/fileDigest.js'
const reference=bytes=>createHash('sha256').update(bytes).digest('hex')
test('incremental SHA-256 agrees with published empty and abc vectors',()=>{
  assert.equal(createSha256().hex(),'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
  const hash=createSha256();hash.update(new TextEncoder().encode('abc'));assert.equal(hash.hex(),'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
})
test('SHA-256 padding and varied incremental splits match Node crypto across block boundaries',()=>{
  for(const length of [1,55,56,63,64,65,127,128,129,1024,2*1024*1024+17]){
    const bytes=Uint8Array.from({length},(_,i)=>(i*71+5)&255),hash=createSha256()
    for(let offset=0;offset<length;offset+=37)hash.update(bytes.subarray(offset,offset+37))
    assert.equal(hash.hex(),reference(bytes),'length '+length)
  }
})
test('file hashing reads bounded slices and cancellation never reads another chunk',async()=>{
  const bytes=new Uint8Array(2*1024*1024+5).fill(17),reads=[],file={size:bytes.length,slice(a,b){reads.push([a,b]);return {arrayBuffer:async()=>bytes.slice(a,b).buffer}}}
  assert.equal(await hashUploadFile(file),reference(bytes));assert.deepEqual(reads.map(([a,b])=>b-a),[1048576,1048576,5])
  const controller=new AbortController();let count=0
  await assert.rejects(hashUploadFile({size:bytes.length,slice(a,b){count++;return {arrayBuffer:async()=>{controller.abort();return bytes.slice(a,b).buffer}}}},{signal:controller.signal}),/已取消/)
  assert.equal(count,1)
})
