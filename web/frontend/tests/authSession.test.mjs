import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import {transformSync} from 'esbuild'
const code=transformSync(readFileSync(new URL('../src/stores/auth.ts',import.meta.url),'utf8'),{loader:'ts',format:'cjs'}).code
function storage(seed={}){const m=new Map(Object.entries(seed));return {getItem:k=>m.get(k)||null,setItem:(k,v)=>m.set(k,v),removeItem:k=>m.delete(k)}}
function load(client,session=storage(),local=storage()){
 const mod={exports:{}};new Function('require','module','exports','sessionStorage','localStorage',code)(n=>n==='pinia'?{defineStore:(_,o)=>o}:{__esModule:true,default:client},mod,mod.exports,session,local)
 const options=mod.exports.useAuthStore,store=options.state();for(const [k,f] of Object.entries(options.actions))store[k]=f.bind(store);return store
}
test('refresh during me read keeps updated display name; logout discards late identity',async()=>{
 let finish;const client={get:()=>new Promise(r=>{finish=r})};const s=load(client)
 s.token='expired';const p=s.fetchMe();s.saveTokens({access_token:'renewed',refresh_token:'r'});finish({data:{id:'a',display_name:'管理员'}});await p;assert.equal(s.user.display_name,'管理员')
 const later=s.fetchMe();s.logout();finish({data:{id:'a',display_name:'旧使用者'}});await later;assert.equal(s.user,null)
})
test('a current tab profile never imports a legacy account identity',()=>{
 const session=storage({v5_token:'new',v5_refresh:'r',v5_user:JSON.stringify({id:'b'})});const local=storage({v5_token:'old',v5_user:JSON.stringify({id:'a'})});const s=load({},session,local);assert.equal(s.user.id,'b');assert.equal(local.getItem('v5_token'),null)
})
