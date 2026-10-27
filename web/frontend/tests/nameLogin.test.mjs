import test from 'node:test'
import assert from 'node:assert/strict'
import {loadSfc,mount,find,input,settle,content,esm} from './vueHarness.mjs'

async function screen({available=true,fail=false,loginFails=false}={}){
  const names=[],routes=[];let release
  const pending=new Promise(resolve=>{release=resolve})
  const Login=await loadSfc('../src/views/Login.vue',{
    'vue-router':{useRouter:()=>({replace:p=>routes.push(p)})},
    '../stores/auth':{useAuthStore:()=>({loginByName:async n=>{names.push(n);await pending;if(loginFails)throw new Error("offline")},login:async()=>{}})},
    '../api/client':esm({get:async path=>{if(fail&&path.includes('options'))throw {response:{status:404}};return {data:path.includes('setup')?{required:false}:{name_login_enabled:available}}}})
  })
  const h=mount(Login);await settle();return {...h,names,routes,release}
}
test('name entry submits once, waits for session and opens own workspace',async()=>{
  const h=await screen();try{
    assert.match(content(h.root),/怎么称呼你/);assert.doesNotMatch(content(h.root),/PASSWORD/)
    input(find(h.root,'profile-name'),'  虚构助理  ');await settle()
    const submit=()=>find(h.root,'entry-form').props.onSubmit({preventDefault(){}})
    const first=submit();submit();await settle();assert.deepEqual(h.names,['虚构助理']);assert.deepEqual(h.routes,[])
    const started=performance.now();h.release();await settle();assert.ok(find(h.root,'entry-welcome'));assert.deepEqual(h.routes,[]);await first;await settle();assert.ok(performance.now()-started>=2500);assert.deepEqual(h.routes,['/cases'])
  }finally{h.app.unmount()}
})
test('old backend shows unavailable instead of pretending name login succeeded',async()=>{
  const h=await screen({fail:true});try{
    assert.equal(find(h.root,'enter-workspace').props.disabled,true)
    assert.match(content(h.root),/尚未启用/);assert.deepEqual(h.names,[])
  }finally{h.app.unmount()}
})

test('leaving during entrance cancels delayed navigation',async()=>{
 const h=await screen();input(find(h.root,'profile-name'),'虚构助理');await settle();const pending=find(h.root,'entry-form').props.onSubmit({preventDefault(){}});h.release();await settle();assert.ok(find(h.root,'entry-welcome'));h.app.unmount();await pending;assert.deepEqual(h.routes,[])
})
test('failed login does not show success entrance or navigate',async()=>{
 const h=await screen({loginFails:true});try{input(find(h.root,'profile-name'),'虚构助理');await settle();const pending=find(h.root,'entry-form').props.onSubmit({preventDefault(){}});h.release();await pending;await settle();assert.equal(find(h.root,'entry-welcome'),undefined);assert.deepEqual(h.routes,[]);assert.match(content(h.root),/未能进入/)}finally{h.app.unmount()}
})
