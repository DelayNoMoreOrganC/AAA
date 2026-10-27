// Independent controller probes; synthetic File objects, no browser/HTTP/storage.
import test from 'node:test'
import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import {createUploadRecovery} from '../src/domain/uploadRecovery.js'

const tick=()=>new Promise(resolve=>setImmediate(resolve))
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}}
const file=(body='synthetic A',name='虚构材料.pdf')=>new File([body],name)
const digest=async item=>createHash('sha256').update(Buffer.from(await item.arrayBuffer())).digest('hex')
async function entry(f,key='entry-1',status='pending'){
  return {request_id:key,filename:f.name,file_size:f.size,sha256:await digest(f),doc_type:'default',status,
    file_id:status==='completed'?'synthetic-file-'+key:null,created_at:'2026-10-24T00:00:00+00:00',updated_at:'2026-10-24T00:00:00+00:00'}
}
async function harness(options={}){
  let remote=(options.items||[]).map(x=>({...x})),state,id=0
  const reads=[],registers=[],uploads=[],cancels=[],hashes=[]
  const control=createUploadRecovery({
    read:async(...args)=>{reads.push(args[0]);if(options.read)return options.read(...args);return {items:remote.map(x=>({...x})),writable:true,notice:''}},
    register:async(caseId,key,body)=>{registers.push({caseId,key,body:{...body}});remote.push({...body,request_id:key,status:'pending',file_id:null});if(options.registerError)throw Error('synthetic registration ACK lost');return remote.at(-1)},
    upload:async(caseId,f,item)=>{uploads.push({caseId,file:f,key:item.request_id});remote=remote.map(x=>x.request_id===item.request_id?{...x,status:'completed',file_id:'synthetic-'+x.request_id}:x);if(options.uploadError)throw Error('synthetic upload ACK lost');return {id:'synthetic-'+item.request_id}},
    cancel:async(caseId,key)=>{cancels.push({caseId,key});remote=remote.map(x=>x.request_id===key?{...x,status:'cancelled'}:x);if(options.cancelError)throw Error('synthetic cancellation ACK lost');return remote.find(x=>x.request_id===key)},
    getCapabilities:()=>({supported_extensions:['.pdf'],max_upload_mb:1}),
    hash:async(f,...args)=>{hashes.push(f);return options.hash?options.hash(f,...args):digest(f)},
    makeId:()=>`synthetic-request-${++id}`,onChange:value=>{state=value}
  })
  control.reset({caseId:'case-A',accountScope:'org:user-A'});await tick()
  return {control,reads,registers,uploads,cancels,hashes,get state(){return state},get remote(){return remote},setRemote(items){remote=items}}
}

test('registration lost ACK is recovered by persisted key before any source upload',async()=>{
  const h=await harness({registerError:true})
  try{
    assert.equal(await h.control.add([file()]),false)
    assert.equal(h.registers.length,1);assert.equal(h.uploads.length,0)
    const key=h.registers[0].key
    assert.deepEqual(Object.keys(h.registers[0].body).sort(),['doc_type','file_size','filename','sha256'])
    assert.equal(await h.control.reload(),true)
    assert.equal(await h.control.retry(),true)
    assert.equal(h.registers.length,1);assert.equal(h.uploads.length,1);assert.equal(h.uploads[0].key,key)
    assert.equal(h.state.pendingCount,0)
  }finally{h.control.dispose()}
})

test('successful upload with a lost response is never reimported after folder re-selection',async()=>{
  const chosen=file(),h=await harness({uploadError:true})
  try{
    assert.equal(await h.control.add([chosen]),true)
    assert.equal(h.uploads.length,1);assert.equal(h.state.pendingCount,0)
    assert.equal(await h.control.recover([file()]),true)
    assert.equal(await h.control.retry(),true)
    assert.equal(h.uploads.length,1);assert.equal(h.registers.length,1)
    assert.equal(h.state.pendingCount,0)
  }finally{h.control.dispose()}
})

test('ordinary folder re-selection binds only unfinished files and does not re-register successes',async()=>{
  const first=file('synthetic A','已完成.pdf'),second=file('synthetic B','待补文件.pdf')
  const h=await harness({items:[await entry(first,'done','completed'),await entry(second,'todo')]})
  try{
    assert.equal(await h.control.recover([first,second]),true)
    assert.equal(h.uploads.length,0)
    assert.equal(h.state.rows.length,1);assert.equal(h.state.rows[0].file,second)
    assert.equal(await h.control.retry(),true)
    assert.deepEqual(h.uploads.map(x=>x.key),['todo']);assert.equal(h.registers.length,0)
    assert.equal(h.state.pendingCount,0)
  }finally{h.control.dispose()}
})

test('same name and size with different bytes never binds to a pending intent',async()=>{
  const original=file('AAAA','同名.pdf'),changed=file('BBBB','同名.pdf')
  const h=await harness({items:[await entry(original)]})
  try{
    await h.control.recover([changed]);await h.control.retry()
    assert.equal(h.state.rows[0].file,null);assert.equal(h.uploads.length,0);assert.equal(h.registers.length,0)
    assert.equal(h.state.pendingCount,1)
  }finally{h.control.dispose()}
})

test('identical selected occurrences are consumed one-to-one without inventing extra copies',async()=>{
  const first=file(),second=file()
  const h=await harness({items:[await entry(first,'pending-a'),await entry(first,'pending-b')]})
  try{
    await h.control.recover([first,second])
    assert.equal(h.state.pendingCount,2)
    assert.equal(new Set(h.state.rows.map(x=>x.file)).size,2)
    assert.ok(h.state.rows.every(x=>x.file===first||x.file===second))
    assert.equal(await h.control.retry(),true)
    assert.deepEqual(h.uploads.map(x=>x.key).sort(),['pending-a','pending-b'])
    assert.equal(h.registers.length,0);assert.equal(h.state.pendingCount,0)
  }finally{h.control.dispose()}
})

test('one File identity repeated in a selection cannot satisfy two pending occurrences',async()=>{
  const chosen=file(),h=await harness({items:[await entry(chosen,'pending-a'),await entry(chosen,'pending-b')]})
  try{
    await h.control.recover([chosen,chosen])
    assert.equal(h.state.rows.filter(x=>x.file).length,1)
    assert.equal(await h.control.retry(),false)
    assert.equal(h.uploads.length,1);assert.equal(h.state.pendingCount,1)
    assert.equal(h.registers.length,0)
  }finally{h.control.dispose()}
})

test('same-content completed and pending occurrences need only one additional upload on folder recovery',async()=>{
  const first=file(),second=file(),extra=file()
  const h=await harness({items:[await entry(first,'done','completed'),await entry(first,'todo')]})
  try{
    await h.control.recover([first,second,extra])
    assert.equal(h.state.rows.length,1);assert.ok(h.state.rows[0].file)
    assert.ok(h.state.matchMessages.some(x=>x.includes('已导入')))
    assert.ok(h.state.matchMessages.some(x=>x.includes('超出')))
    assert.equal(await h.control.retry(),true)
    assert.deepEqual(h.uploads.map(x=>x.key),['todo']);assert.equal(h.registers.length,0)
  }finally{h.control.dispose()}
})

test('a cancellation with a lost response is reconciled, never revived by retry',async()=>{
  const f=file(),h=await harness({items:[await entry(f)],cancelError:true})
  try{
    await h.control.recover([f]);assert.equal(await h.control.remove('entry-1'),false)
    assert.ok(h.state.error)
    assert.equal(await h.control.reload(),true)
    assert.equal(h.state.pendingCount,0)
    await h.control.recover([f]);await h.control.retry()
    assert.equal(h.uploads.length,0);assert.equal(h.registers.length,0)
    assert.equal(h.state.items[0].status,'cancelled')
  }finally{h.control.dispose()}
})

test('a late hash result cannot bind files into a different case or account generation',async()=>{
  const pendingHash=deferred(),f=file(),saved=await entry(f)
  const h=await harness({items:[saved],hash:()=>pendingHash.promise})
  try{
    const restoring=h.control.recover([f]);await tick()
    h.control.reset({caseId:'case-B',accountScope:'org:user-B'});await tick()
    pendingHash.resolve(saved.sha256)
    assert.equal(await restoring,false)
    assert.ok(h.state.rows.every(x=>x.file===null));assert.equal(h.uploads.length,0)
  }finally{h.control.dispose()}
})

test('recovery waiting for initial GET cannot migrate selected files across a scope reset',async()=>{
  const oldGet=deferred(),f=file(),saved=await entry(f)
  const h=await harness({read:async id=>id==='case-A'?oldGet.promise:{items:[saved],writable:true,notice:''}})
  try{
    const restoring=h.control.recover([f])
    h.control.reset({caseId:'case-B',accountScope:'org:user-B'});await tick()
    oldGet.resolve({items:[saved],writable:true,notice:''})
    assert.equal(await restoring,false,'an old recovery action must stop after account/case reset')
    assert.ok(h.state.rows.every(x=>x.file===null),'new scope must not inherit old selected File bytes')
    assert.equal(h.uploads.length,0)
  }finally{h.control.dispose()}
})

test('a normal batch does not re-read and rehash the entire server receipt list per successful item',async()=>{
  const h=await harness()
  try{
    const count=8,files=Array.from({length:count},(_,i)=>file(`synthetic ${i}`,`虚构-${i}.pdf`))
    assert.equal(await h.control.add(files),true)
    assert.equal(h.uploads.length,count);assert.equal(h.registers.length,count)
    assert.equal(h.reads.length,3,'one initial read, one pre-upload reconciliation, one batch-final read')
    assert.equal(h.hashes.length,count)
  }finally{h.control.dispose()}
})
