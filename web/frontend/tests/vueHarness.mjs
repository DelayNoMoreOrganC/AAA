import * as Vue from 'vue'
import { readFile } from 'node:fs/promises'
import { parse,compileScript } from '@vue/compiler-sfc'
import { transformSync } from 'esbuild'

export { Vue }
export async function loadSfc(relative,imports={},compilerOptions={}){
  const filename=new URL(relative,import.meta.url)
  const source=await readFile(filename,'utf8')
  const {descriptor}=parse(source,{filename:filename.pathname})
  const compiled=compileScript(descriptor,{id:'test-component',inlineTemplate:true,templateOptions:{compilerOptions}})
  const result=transformSync(compiled.content,{loader:'ts',format:'cjs',target:'es2022'})
  const module={exports:{}}
  new Function('require','module','exports',result.code)(name=>{
    if(name==='vue')return Vue
    if(name in imports)return imports[name]
    if(name==='@element-plus/icons-vue')return new Proxy({},{get:()=>Shell})
    if(name==='element-plus')return {ElMessage:{success(){},error(){},warning(){},info(){}},ElMessageBox:{confirm:async()=>{}}}
    if(name.endsWith('.vue'))return {default:Shell,__esModule:true}
    throw new Error('Unmocked dependency '+name)
  },module,module.exports)
  return module.exports.default
}
const node=(type,text='')=>({type,text,props:{},style:{},children:[],parent:null})
export const renderer=Vue.createRenderer({createElement:type=>node(type),createText:text=>node('#text',text),createComment:text=>node('#comment',text),setText:(n,text)=>{n.text=text},setElementText:(n,text)=>{n.text=text;n.children=[]},patchProp:(n,key,old,value)=>{n.props[key]=value},parentNode:n=>n.parent,nextSibling:n=>n.parent?.children[n.parent.children.indexOf(n)+1]||null,insert(n,parent,anchor=null){if(n.parent)n.parent.children.splice(n.parent.children.indexOf(n),1);n.parent=parent;const at=anchor?parent.children.indexOf(anchor):-1;if(at<0)parent.children.push(n);else parent.children.splice(at,0,n)},remove(n){if(n.parent)n.parent.children.splice(n.parent.children.indexOf(n),1);n.parent=null}})
export const Shell={setup:(_,{attrs,slots})=>()=>Vue.h('section',attrs,slots.default?.())}
const Button={props:['disabled','loading','nativeType'],setup:(props,{attrs,slots})=>()=>Vue.h('button',{...attrs,type:props.nativeType||'button',disabled:props.disabled},slots.default?.())}
const Drawer={props:['modelValue','title'],setup:(props,{attrs,slots})=>()=>props.modelValue?Vue.h('aside',attrs,[Vue.h('h2',null,props.title),...(slots.default?.()||[]),...(slots.footer?.()||[])]):null}
const Input={props:['modelValue','disabled','type'],emits:['update:modelValue'],setup:(props,{attrs,emit})=>()=>Vue.h(props.type==='textarea'?'textarea':'input',{...attrs,disabled:props.disabled,value:props.modelValue,onInput:event=>emit('update:modelValue',event.target.value)})}
const Select={props:['modelValue','disabled'],emits:['update:modelValue'],setup:(props,{attrs,slots,emit})=>()=>Vue.h('select',{...attrs,disabled:props.disabled,value:props.modelValue,onChange:event=>emit('update:modelValue',event.target.value)},slots.default?.())}
export function mount(component,props={},components={}){const app=renderer.createApp(component,props);app.config.warnHandler=()=>{};app.directive('loading',{});for(const [name,c] of Object.entries({'el-button':Button,'el-drawer':Drawer,'el-dialog':Drawer,'el-input':Input,'el-select':Select,'el-option':Shell,'el-icon':Shell,'el-alert':Shell,'el-form':Shell,'el-form-item':Shell,'el-tabs':Shell,'el-tab-pane':Shell,'el-dropdown':Shell,'el-dropdown-menu':Shell,'el-dropdown-item':Shell,'el-table':Shell,'el-table-column':Shell,'el-tag':Shell,'router-link':Shell,...components}))app.component(name,c);const root=node('root');app.mount(root);return {app,root}}
export const find=(root,id)=>root.props?.['data-testid']===id?root:root.children.map(child=>find(child,id)).find(Boolean)
export const findType=(root,type)=>root.type===type?root:root.children.map(child=>findType(child,type)).find(Boolean)
export const content=root=>(root.text||'')+root.children.map(content).join('')
export function click(target){if(!target||target.props.disabled)return;let stopped=false;const event={stopPropagation(){stopped=true},preventDefault(){}};for(let n=target;n&&!stopped;n=n.parent)n.props.onClick?.(event)}
export function input(target,value){target.props.onInput?.({target:{value}})}
export async function settle(){for(let i=0;i<12;i++){await Promise.resolve();await Vue.nextTick()}}
export const esm=value=>({default:value,__esModule:true})
