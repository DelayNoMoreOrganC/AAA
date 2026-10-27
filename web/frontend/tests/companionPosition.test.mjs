import test from 'node:test'
import assert from 'node:assert/strict'
import {Vue,loadSfc,mount,find,click,settle} from './vueHarness.mjs'
import * as positioning from '../src/domain/companionPosition.js'

test('saved placement is bounded on smaller screens and panel stays within viewport at each corner',()=>{
 const viewport={width:320,height:640},size={width:128,height:150}
 for(const point of [{x:-100,y:-100},{x:9999,y:9999}]){
  const p=positioning.clampCompanion(point,viewport,size)
  assert.ok(p.x>=12&&p.x+size.width<=308);assert.ok(p.y>=12&&p.y+size.height<=628)
  const panel=positioning.companionPanel(p,viewport,size)
  assert.ok(parseFloat(panel.left)>=12);assert.ok(parseFloat(panel.left)+parseFloat(panel.width)<=308)
  assert.ok(parseFloat(panel.maxHeight)>0)
 }
 assert.deepEqual(positioning.restoreCompanion({x:'bad',y:NaN},viewport,size),{x:170,y:472})
})

test('drag moves and persists only placement, suppresses click, then normal click works; reset clears placement',async()=>{
 const previous=globalThis.window,stored=new Map();let released=0
 globalThis.window={innerWidth:1000,innerHeight:800,localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}}),addEventListener(){},removeEventListener(){}}
 const Component=await loadSfc('../src/components/ArchiveCompanion.vue',{'../domain/companionPosition.js':positioning})
 const h=mount(Component)
 const event=(x,y)=>({pointerId:1,button:0,isPrimary:true,clientX:x,clientY:y,preventDefault(){},currentTarget:{setPointerCapture(){},releasePointerCapture(){released++}}})
 try{
  await settle();const button=find(h.root,'companion-open')
  button.props.onPointerdown(event(900,700));button.props.onPointermove(event(100,100));button.props.onPointerup(event(100,100));button.props.onClick({detail:1});await settle()
  assert.equal(find(h.root,'companion-panel').style.display,'none');assert.equal(released,1)
  assert.deepEqual([...stored.keys()],['aaa-companion-position-v1']);assert.deepEqual(Object.keys(JSON.parse([...stored.values()][0])),['x','y'])
  button.props.onPointerdown(event(100,100));button.props.onPointerup(event(100,100));button.props.onClick({detail:1});await settle()
  assert.notEqual(find(h.root,'companion-panel').style.display,'none')
  click(find(h.root,'companion-reset'));await settle();assert.equal(stored.size,0)
 }finally{h.app.unmount();globalThis.window=previous}
})
