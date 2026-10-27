'use strict';
// Deterministic composition: all graphic motion is derived from seconds, never frame count.
const scenes = [
  [18,'从一堆材料，到一份卷宗','成果','律师归档，费时间的不只是保存文件，还有辨认文书、整理顺序和填写表格。卷小助希望把已有材料，整理成有依据、可编辑、可交付的卷宗。','先让观众知道最终得到什么。这里是成果结构示意，正式片替换为同案真实成果。','hero'],
  [18,'文件齐了，为什么还没归好？','需求','诉状、合同、证据和裁判文书，可能散落在不同文件里。归档还要找出文书边界、按目录排序、填写表格，并检查材料是否齐备。','四类材料逐渐出现，最后只强调“还差整理”。','problem'],
  [20,'保持原来的办案习惯','定位','有些律所没有自研系统的条件，也不想为了归档改变整个办案流程。卷小助从已经存在的同案材料出发，不要求先补录全过程。','文件夹是起点。只解释独立归档，不展开竞品。','independent'],
  [20,'同案文件夹，一次导入','使用','同一案件的PDF、Word和图片，可以一次选择整个文件夹；一整份扫描PDF也能导入。不必先把每份材料手工分类。','点击导入按钮：光圈→平滑放大→返回全景。动画不声称实际处理耗时。','import'],
  [18,'明确处理方式，再开始','使用','本次演示使用虚构材料。采用云端模型时，先说明发送范围并取得本案授权，再开始整理。用户能知道资料交给了谁处理。','只突出“本案云端授权”。正式录屏保留真实授权步骤。','start'],
  [20,'一条链路，分工完成','机制','系统先转换材料、建立页码来源，再识别文书、提取事实和填写原表，最后检查成果。模型负责理解，程序负责约束，剩余疑点才交给人。','流程每次只点亮一步，不同时展示六段解释。','pipeline'],
  [22,'先理解文书，再组织页面','理解','同一文书可能跨很多页。证据清单后面的连续材料，需要结合标题、页序和上下文判断边界，不能把每一页都拆成一个让人选择的事项。','证据清单与附件逐页汇成文书组。不能只凭前页是清单就吞并后续独立文书。','group'],
  [18,'名字不同，也要找对位置','理解','传票可以对应开庭通知类目录，民事裁定书属于法院裁判文书。归类时保留文书真实名称，不把归档位置当作已经签署、送达或履行的证明。','一次只展示一组文书与目录对应关系。','mapping'],
  [22,'填入的事实，要找得到出处','理解','字段不是凭感觉生成。系统从相关文书提取事实，并关联原文件和页码。遇到冲突，在限定范围补读；依据仍不足，就明确保留疑点。','从诉状原句连到字段，随后突出来源锚点。','source'],
  [24,'填原表，而不是另造一张表','填表','已有立案审批表优先保留，没有原件才补填。案情简介依据诉状写明争议事实和诉讼请求，主体信息也要有来源。文字在原有框格内简要填写。','原框保持静止，文字出现。此表是机制图，正式片换成律所原表实录。','form'],
  [22,'结案小结，讲清办理过程','填表','立案简介讲起因，结案小结讲全过程。它要依据材料总结受托事项、实际办理、法院处理和后续状态，不能只复述裁判主文，更不能编造未记录的工作。','四个节点顺次亮起，右侧形成简要过程摘要。','summary'],
  [20,'只问必要的问题','减负','材料能确定的先整理；确有冲突的，集中呈现原页和建议选项。同一材料的关联问题放在一起，减少重复打开原件，而不是让用户重新做一遍分类。','在建议选项上出现点击光圈和镜头放大。选项是说明交互，不是预设正确答案。','review'],
  [18,'缺一份，补一份，接着做','减负','委托合同尚缺时，日期和收费不能凭空补出。补充合同后继续处理有依据的内容，保留已确认事项和历史成果，不必重新上传全部材料。','补入一个文件，只有关联字段点亮，不演示整案重跑。','supplement'],
  [22,'确认当前版本，交付完整成果','成果','必要核对完成后，确认当前版本，输出整卷PDF、可编辑原表、目录跳转、书签和质检记录。草稿不新增归档页码；定稿从目录后的正文连续编号，位于底部居中。','目录跳转和页脚为示意。正式片用实际PDF、Word和ZIP证明。','output'],
  [20,'与通用AI工作台的区别','对比','WorkBuddy、Codex也能整理文件，配合技能和脚本还能完成复杂流程。卷小助把归档规则、律所原表、来源核对和成果检查预先组织好，减少助理配置与反复检查的负担。','不说通用工作台做不到。突出“预先配置好的归档流程”。','generic'],
  [20,'与办案管理平台的区别','对比','案件云等平台围绕案件信息、工作记录和关联文档组织办案。卷小助聚焦已经存在的材料直接成卷，适合希望保留原工作习惯的使用者。两者定位不同，也可以互补。','案件云同样支持批量文档操作。无对照实测，不声称总耗时一定更短。','platform'],
  [18,'DeepSeek：本片的理解引擎','模型','本次展示选择DeepSeek Flash理解页面和提取事实。模型提供能力，归档规则、原表填写、来源约束和成果校验由产品组织，模型品牌本身并不是我们的创新。','展示实际选用路径，不展示未经测量的速度或准确率。','deepseek'],
  [16,'GLM：保留另一种选择','模型','系统同时保留GLM标准API的视觉适配，便于后续使用同样材料比较与选择。不同模型仍需分别验收，不表示两种模型正在自动交叉复核。','GLM为可选适配，不是默认双模型，也不使用Coding Plan冒充标准API。','glm'],
  [28,'为什么先展示云端？','部署','云端方案降低独立显卡和模型维护的门槛。已有普通工作站也可以接入，但送往模型的页面和文本会离开工作站，因此必须说明发送范围并获得授权。方便接入，并不等于资料没有外发。','箭头明确经过工作站到外部模型。不要画成本地闭环。','cloud'],
  [30,'不能外发时，选择本地路线','部署','有保密要求且具备设备条件的律所，可以采用Ollama本地工作站，多个使用者通过浏览器访问。模型与材料在选定的本地环境处理。硬件档位只是选型起点，实际速度、准确性和外网阻断仍要分别验证。','本地拓扑闭环。展示建议硬件不是本机实测成绩，不能自动切云。','local'],
  [18,'少一套平台投入，不等于零成本','成本','设计方向是不必另购整套办案管理平台。云端主要新增按量API费用；本地可免外部模型调用费，但仍有硬件、电力、维护和人工复核成本。','不使用永久免费、零成本、固定每案价格等未核实说法。','cost'],
  [18,'材料交进来，卷宗带走','收束','卷小助希望让律师保留熟悉的办案方式，把重复整理交给工具。让没有自研条件的律所，也能选择适合自己的智能归档方式，把时间留给法律服务。','最后回到同案成果，品牌停留三秒。正式片替换成果示意，不添加未验证承诺。','end']
].map(([duration,title,chapter,narration,direction,type],i)=>({duration,title,chapter,narration,direction,type,index:i}));
let total=0;for(const s of scenes){s.start=total;total+=s.duration;}if(total!==450)throw Error('Timeline must be 450 seconds');
const $=id=>document.getElementById(id), canvas=$('film'),ctx=canvas.getContext('2d',{alpha:false});
const layer=document.createElement('canvas');layer.width=1920;layer.height=1080;const baseContext=layer.getContext('2d');
const overlay=document.createElement('canvas');overlay.width=1920;overlay.height=1080;const overlayContext=overlay.getContext('2d');let g=baseContext;
const C={bg:'#f5f5f0',ink:'#203130',muted:'#7b8781',accent:'#d87a48',soft:'#f6e6d7',green:'#487c69',line:'#dce2da',white:'#fffef9',blue:'#627d8f'};
let time=0,playing=false,rate=1,last=performance.now(),current=-1,recording=null,recordEnd=0,recordChunks=[],frameRequest=0;
const clips=new Map();let focusMode=false,audio=null,audioContext=null,audioSource=null,audioDest=null,audioUrl=null;
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));const ease=t=>{t=clamp(t);return t*t*(3-2*t);};const lerp=(a,b,t)=>a+(b-a)*t;
const fmt=t=>`${Math.floor(t/60).toString().padStart(2,'0')}:${Math.floor(t%60).toString().padStart(2,'0')}`;
function box(x,y,w,h,fill=C.white,r=24,stroke=null){g.beginPath();g.roundRect(x,y,w,h,r);g.fillStyle=fill;g.fill();if(stroke){g.strokeStyle=stroke;g.lineWidth=2;g.stroke();}}
function text(str,x,y,size=32,color=C.ink,weight=400,align='left'){g.font=`${weight} ${size}px "Microsoft YaHei", "PingFang SC", sans-serif`;g.fillStyle=color;g.textAlign=align;g.textBaseline='middle';g.fillText(str,x,y);}
function line(x,y,xx,yy,color=C.line,width=3){g.beginPath();g.moveTo(x,y);g.lineTo(xx,yy);g.strokeStyle=color;g.lineWidth=width;g.stroke();}
function lines(str,x,y,maxWidth,size=30,color=C.ink,lineHeight=48){let row='',yy=y;for(const ch of str){if(ch==='\n'){if(row)text(row,x,yy,size,color);yy+=lineHeight;row='';continue;}g.font=`400 ${size}px "Microsoft YaHei",sans-serif`;if(g.measureText(row+ch).width>maxWidth&&row){text(row,x,yy,size,color);yy+=lineHeight;row=ch;}else row+=ch;}if(row)text(row,x,yy,size,color);return yy;}
function pill(label,x,y,fill=C.soft,color=C.accent,width=200){box(x,y,width,48,fill,24);text(label,x+width/2,y+24,23,color,500,'center');}
function arrow(x,y,xx,yy,color=C.accent){line(x,y,xx,yy,color,4);const a=Math.atan2(yy-y,xx-x);line(xx,yy,xx-16*Math.cos(a-.5),yy-16*Math.sin(a-.5),color,4);line(xx,yy,xx-16*Math.cos(a+.5),yy-16*Math.sin(a+.5),color,4);}
function tick(x,y,scale=1){g.save();g.translate(x,y);g.scale(scale,scale);line(-13,0,-3,10,C.green,4);line(-3,10,16,-13,C.green,4);g.restore();}
function doc(x,y,w,h,label,color=C.accent){box(x+7,y+10,w,h,'#263b2e0a',16);box(x,y,w,h,C.white,16,C.line);box(x+22,y+22,45,8,color,4);text(label,x+22,y+72,Math.min(26,w/8),C.ink,500);for(let i=0;i<4;i++)line(x+22,y+112+i*22,x+w-(i===3?w*.28:22),y+112+i*22,C.line,4);}
function folder(x,y,w=280,h=210){box(x+15,y,w*.4,40,C.accent,12);box(x,y+24,w,h,C.soft,20,C.accent);text('同案材料',x+w/2,y+h*.62,32,C.accent,600,'center');}
function staged(p,delay,fn){const a=ease((p-delay)*4);if(a<=0)return;g.save();g.globalAlpha=a;g.translate(0,(1-a)*24);fn();g.restore();}
function labelTop(s){text(`AAA / 卷小助`,100,64,26,C.ink,600);text(s.chapter.toUpperCase(),1820,64,23,C.muted,500,'right');line(100,104,1820,104);text(String(s.index+1).padStart(2,'0'),105,166,23,C.accent,600);text(s.title,100,245,66,C.ink,600);}
function caption(s,local){const parts=s.narration.match(/[^。！？；]+[。！？；]?/g)||[s.narration];let acc=0,chosen=parts[parts.length-1];const n=s.narration.length;for(const part of parts){acc+=part.length/n;if(local/s.duration<acc){chosen=part;break;}}box(140,933,1640,92,'#e9ece5',20);lines(chosen,190,978,1540,29,C.ink,36);}
function card(x,y,w,h,title,subtitle,accent=false){box(x,y,w,h,accent?C.soft:C.white,22,C.line);text(title,x+32,y+55,32,accent?C.accent:C.ink,600);if(subtitle)lines(subtitle,x+32,y+112,w-64,26,C.muted,42);}
function uiFrame(){box(180,340,1560,510,C.white,24,C.line);box(180,340,1560,58,'#e9eee7',22);text('AAA  卷小助',210,369,21,C.ink,600);text('交互示意',1700,369,20,C.muted,400,'right');}
function button(label,x,y,w=250){box(x,y,w,68,C.ink,13);text(label,x+w/2,y+34,28,'#fff',500,'center');}
function cursor(x,y,t,click=2){g.save();g.translate(x,y);g.beginPath();g.moveTo(0,0);g.lineTo(0,41);g.lineTo(12,30);g.lineTo(22,48);g.lineTo(33,42);g.lineTo(22,25);g.lineTo(40,24);g.closePath();g.fillStyle=C.ink;g.strokeStyle='#fff';g.lineWidth=3;g.fill();g.stroke();g.restore();const dt=t-click;if(dt>=0&&dt<1.2){g.beginPath();g.arc(x,y,18+dt*65,0,Math.PI*2);g.strokeStyle=`rgba(216,122,72,${1-dt/1.2})`;g.lineWidth=6;g.stroke();}}
function camera(t,duration,target={x:1320,y:650},max=1.65){const z=1+(max-1)*ease((t-2.25)/1.25)*(1-ease((t-duration+4)/1.6));return {z,x:clamp(960-z*target.x,1920-1920*z,0),y:clamp(540-z*target.y,1080-1080*z,0)};}
function renderArtwork(s,t,p){
 switch(s.type){
 case 'hero':case 'end':{
  const a=ease(p*2);doc(205,410,240,330,'PDF / Word');arrow(500,568,805,568);box(850,390,690,380,C.ink,30);text('完整卷宗',1195,487,59,'#fff',600,'center');['按目录整理','原表填写','来源可追溯'].forEach((v,i)=>staged(p,i*.12,()=>{tick(953,571+i*55,.8);text(v,994,571+i*55,30,'#e0e8e1');}));if(s.type==='end')text('AI Archiving Assistant',960,864,34,C.accent,500,'center');else pill('已有材料 → 智能成卷',660,826,C.soft,C.accent,600);break;}
 case 'problem':{
  ['诉状','代理合同','证据附件','裁判文书'].forEach((v,i)=>staged(p,i*.1,()=>doc(195+i*390,390+(i%2)*42,290,290,v,[C.blue,C.accent,C.green,C.blue][i])));staged(p,.45,()=>{text('保存好了 ≠ 归档完成',960,822,45,C.accent,600,'center');});break;}
 case 'independent':{
  folder(240,465,330,235);arrow(635,585,930,585);card(1000,424,620,320,'卷小助','从现有材料直接开始\n保持原来的文件夹习惯',true);pill('无需先建设整套办案系统',620,820,C.soft,C.accent,680);break;}
 case 'import':{
  uiFrame();text('导入同一案件的材料',960,455,40,C.ink,600,'center');['诉状.docx','证据材料.pdf','开庭通知.png'].forEach((v,i)=>{box(315+i*440,505,410,90,'#f0f2ed',16);text(v,520+i*440,550,26,C.muted,400,'center');});button('选择文件夹',1195,676,300);text('或导入一整份扫描 PDF',405,710,29,C.muted);cursor(lerp(1050,1330,ease(t/1.6)),lerp(810,706,ease(t/1.6)),t);break;}
 case 'start':{
  uiFrame();pill('本次为虚构材料',270,439,C.soft,C.accent,280);text('处理方式',280,556,28,C.muted);text('DeepSeek · 云端',500,556,36,C.ink,600);text('将选定页面与文本发送至模型服务',280,624,31,C.ink);box(280,695,32,32,C.soft,7,C.accent);if(t>2)tick(296,711,.7);text('授权本案处理',330,711,30,C.ink);button('开始整理',1275,681,300);cursor(lerp(475,296,ease(t/1.6)),lerp(805,711,ease(t/1.6)),t);break;}
 case 'pipeline':{
 const labels=['导入转换','识别归并','提取事实','填写原表','检查成果'];const k=Math.min(4,Math.floor(p*5));labels.forEach((v,i)=>{const x=125+i*342;box(x,480,300,180,i===k?C.ink:C.white,24,C.line);text(String(i+1).padStart(2,'0'),x+32,525,25,i===k?'#b9ccbb':C.muted);text(v,x+150,587,34,i===k?'#fff':C.ink,500,'center');if(i<4)arrow(x+305,570,x+333,570,C.line);});const desc=['建立文件与原页索引','结合标题、版式和上下文','为字段关联原文来源','保持律所模板与框格','检查页数、排序与完整性'];text(desc[k],960,777,38,C.accent,500,'center');break;}
 case 'group':{
  ['证据清单','附件 1','附件 2','附件 3'].forEach((v,i)=>{const m=ease((p-.24)*2);doc(200+i*370-m*i*20,422,280,300,v);});if(p>.28){g.globalAlpha=ease((p-.28)*3);box(170,778,1490,68,C.soft,14);text('结合连续页与文书边界，作为一组整理',915,812,31,C.accent,500,'center');g.globalAlpha=1;}break;}
 case 'mapping':{
 const second=p>.5;doc(250,425,360,340,second?'民事裁定书':'传票');arrow(690,580,1000,580);card(1080,450,530,240,second?'法院裁判文书':'开庭通知相关目录',second?'保留裁定的程序性质':'保留原文书名称',true);text('归类 ≠ 已签署、已送达或已履行',960,838,32,C.muted,400,'center');break;}
 case 'source':{
  box(180,375,720,440,C.white,24,C.line);text('诉状 · 原文来源',225,431,32,C.ink,600);const sample=['原告诉称双方签订借款合同。','因未按约还款，请求偿还本金','及合同约定范围内的利息。'];sample.forEach((v,i)=>{if(p>.12+i*.13)box(216,479+i*66,635,50,C.soft,6);text(v,232,503+i*66,29,C.ink);});arrow(920,585,1040,585);card(1090,440,650,280,'案情简介','争议事实 ＋ 诉讼请求',true);pill('依据：诉状 第 1—2 页',1125,642,C.white,C.green,570);text('示例内容，仅用于解释来源关联',220,861,24,C.muted);break;}
 case 'form':{
  box(260,365,1400,470,C.white,20,C.line);text('立案审批表 · 填写机制示意',960,412,32,C.ink,600,'center');line(300,458,1620,458);const rows=[['当事人','以委托依据与诉状确认角色'],['案情简介','诉状载明借款争议及还款请求，简要归纳事实与诉求。'],['日期与收费','缺少委托合同依据时，明确待补']];rows.forEach((r,i)=>{const y=475+i*112;line(300,y+100,1620,y+100);line(560,y-17,560,y+100);text(r[0],328,y+43,29,C.muted);if(p>.12+i*.18){g.globalAlpha=ease((p-.12-i*.18)*5);lines(r[1],592,y+43,975,30,i===2?C.accent:C.ink,43);g.globalAlpha=1;}});text('原件优先保留 · 缺失才补填',960,876,31,C.accent,500,'center');break;}
 case 'summary':{
  const values=['受托事项','实际办理','处理结果','后续状态'];values.forEach((v,i)=>{const x=215+i*420;const on=p>(i*.18);g.beginPath();g.arc(x,530,18,0,Math.PI*2);g.fillStyle=on?C.accent:C.line;g.fill();if(i<3)line(x+22,530,x+398,530,C.line,4);text(v,x,598,31,on?C.ink:C.muted,500,'center');});box(320,706,1280,126,C.soft,20);text('依据全卷总结办理过程，不编造未记录的工作',960,769,35,C.accent,500,'center');break;}
 case 'review':{
  uiFrame();box(235,425,670,370,'#f0f2ec',14);text('原页预览',570,479,30,C.muted,500,'center');doc(438,520,240,240,'相关文书');text('建议归档位置',995,463,32,C.ink,600);box(985,515,660,92,t>2?C.soft:'#f2f3ee',12,t>2?C.accent:C.line);text('开庭通知相关目录',1030,560,31,C.ink);box(985,630,660,92,'#f2f3ee',12,C.line);text('其他位置…',1030,675,30,C.muted);cursor(lerp(1420,1200,ease(t/1.6)),lerp(780,562,ease(t/1.6)),t);if(t>3)pill('关联疑点一起查看',995,747,C.soft,C.accent,440);break;}
 case 'supplement':{
  doc(235,423,320,350,'补入：委托合同');arrow(620,580,870,580);card(940,422,720,350,'只更新相关内容','合同日期  →  立案日期默认依据',true);text('收费条款  →  原表收费栏',975,627,30,C.ink);if(p>.35)tick(1590,535);if(p>.55)tick(1590,626);text('已确认事项与历史成果保留',960,853,33,C.green,500,'center');break;}
 case 'output':{
  const values=['整卷 PDF','可编辑原表','目录与书签','质检与 ZIP'];values.forEach((v,i)=>staged(p,i*.13,()=>doc(190+i*400,408,310,330,v)));pill('草稿不加号 → 定稿正文底部连续编号',490,811,C.soft,C.accent,940);break;}
 case 'generic':{
  card(210,410,650,340,'通用 AI 工作台','灵活理解与处理文件\n可配合技能、提示词和脚本');arrow(906,580,1004,580);card(1060,410,650,340,'卷小助','规则、原表、核对与检查\n预先组织成归档流程',true);text('减少非技术使用者的配置负担',960,848,35,C.accent,500,'center');break;}
 case 'platform':{
  card(210,410,700,350,'办案管理平台','案件信息 → 办案记录 → 关联文档');card(1010,410,700,350,'独立归档工具','已有同案材料 → 整理成卷',true);text('定位不同，可互补；不是“谁不能上传文件”',960,846,31,C.muted,400,'center');break;}
 case 'deepseek':case 'glm':{
  const gl=s.type==='glm';box(255,410,600,350,gl?C.soft:C.ink,30);text(gl?'GLM':'DeepSeek',555,538,58,gl?C.accent:'#fff',600,'center');text(gl?'标准 API 可选适配':'本片所选模型',555,640,31,gl?C.accent:'#b9ccbb',400,'center');arrow(915,580,1045,580);card(1105,434,580,300,'产品组织能力','归档规则、原表填写\n来源约束、成果检查');text(gl?'各模型分别验证，不是自动双模型复核':'模型是理解引擎，产品负责归档流程',960,854,32,C.muted,400,'center');break;}
 case 'cloud':case 'local':{
  const local=s.type==='local';box(180,383,local?1560:1000,430,'#e7eee5',30);text(local?'律所本地环境':'律所工作站',220,425,28,C.green,600);card(250,490,350,210,'浏览器','导入 / 核对 / 下载');arrow(630,596,770,596);card(810,490,local?470:300,210,local?'Ollama 模型':'整理服务',local?'本地理解与处理':'资料转换与组卷');if(!local){arrow(1140,596,1370,596);card(1410,490,330,210,'外部模型','页面 / 文本外发',true);pill('需明确本案云端授权',610,851,C.soft,C.accent,700);}else{pill('16G显存＋32G内存起，建议档位需实测',450,851,C.soft,C.accent,1020);}break;}
 case 'cost':{
  card(220,405,700,360,'云端路线','按用量支付模型 API 费用\n仍有工作站与维护投入',true);card(1000,405,700,360,'本地路线','免外部模型调用费\n仍有硬件、电力和维护成本');text('选择适合自己的投入方式',960,848,37,C.accent,500,'center');break;}
 }
}
function draw(t){
 const s=scenes.find(s=>t<s.start+s.duration)||scenes.at(-1),local=clamp(t-s.start,0,s.duration),p=local/s.duration,clip=clips.get(s.index);
 g=baseContext;
 g.globalAlpha=1;g.fillStyle=C.bg;g.fillRect(0,0,1920,1080);
 labelTop(s);let cam={z:1,x:0,y:0};
 if(clip&&clip.video.readyState>=2){
  g.fillStyle='#151d20';g.fillRect(0,0,1920,1080);const v=clip.video,scale=Math.min(1920/v.videoWidth,1080/v.videoHeight),w=v.videoWidth*scale,h=v.videoHeight*scale;g.drawImage(v,(1920-w)/2,(1080-h)/2,w,h);cursor(clip.focus.x,clip.focus.y,local);cam=camera(local,s.duration,clip.focus);if(local>=v.duration){box(50,45,400,54,'#f6e6d7');text('实录已结束 · 末帧停留',250,72,24,C.accent,500,'center');}
 }else{
  renderArtwork(s,local,p);
  if(['import','start','review'].includes(s.type)){const pt=s.type==='import'?{x:1330,y:706}:s.type==='start'?{x:296,y:711}:{x:1200,y:562};cam=camera(local,s.duration,pt,1.48);}
 }
 ctx.fillStyle=C.bg;ctx.fillRect(0,0,1920,1080);ctx.save();ctx.translate(cam.x,cam.y);ctx.scale(cam.z,cam.z);ctx.drawImage(layer,0,0);ctx.restore();
 // Captions and evidence label are in screen space; zoom never clips them.
 g=overlayContext;g.globalAlpha=1;g.clearRect(0,0,1920,1080);caption(s,local);box(1350,117,470,44,clip?'#e4eee4':'#eeeadf',18);text(clip?'用户导入实录 · 真实操作':'机制 / 界面示意 · 非软件实录',1585,139,21,clip?C.green:C.muted,500,'center');
 ctx.drawImage(overlay,0,0);const fade=Math.min(ease(local/.55),ease((s.duration-local)/.4));if(fade<1){ctx.fillStyle=`rgba(245,245,240,${1-fade})`;ctx.fillRect(0,0,1920,1080);}
 ctx.fillStyle=C.accent;ctx.fillRect(0,1075,1920*clamp(t/total),5);updateUI(s);
}
function updateUI(s){$('clock').textContent=`${fmt(time)} / ${fmt(total)}`;$('scrub').value=time;$('play').textContent=playing?'暂停':'播放';if(current!==s.index){current=s.index;$('sceneTitle').textContent=`${String(s.index+1).padStart(2,'0')} · ${s.title}`;$('narration').textContent=s.narration;$('direction').textContent=s.direction;document.querySelectorAll('.scene').forEach((b,i)=>b.classList.toggle('active',i===s.index));}}
function status(s){$('status').textContent=s;}
function currentScene(){return scenes.find(s=>time<s.start+s.duration)||scenes.at(-1);}
function syncMedia(force=false){const s=currentScene();for(const [i,c]of clips){if(i!==s.index||!playing){c.video.pause();}if(i===s.index){const want=Math.min(time-s.start,Math.max(0,c.video.duration-.04));if(force||Math.abs(c.video.currentTime-want)>.35)c.video.currentTime=want;c.video.playbackRate=rate;if(playing&&time-s.start<c.video.duration)c.video.play().catch(()=>{});}}
 if(audio){const want=Math.min(time,Math.max(0,audio.duration-.03));if(force||Math.abs(audio.currentTime-want)>.35)audio.currentTime=want;audio.playbackRate=rate;if(playing&&time<audio.duration)audio.play().catch(()=>status('配音播放被浏览器阻止，请重新点击播放。'));else audio.pause();}}
function seek(t){time=clamp(t,0,total-.001);last=performance.now();syncMedia(true);draw(time);}
function playToggle(){if(recording)return;if(time>=total-.03)seek(0);playing=!playing;last=performance.now();syncMedia(true);draw(time);}
function loop(now){const delta=Math.max(0,(now-last)/1000);last=now;if(playing){time=Math.min(total,time+delta*rate);syncMedia();if(recording&&time>=recordEnd)stopRecording(false);if(time>=total){playing=false;syncMedia();}draw(time);}frameRequest=requestAnimationFrame(loop);}
scenes.forEach(s=>{const b=document.createElement('button');b.className='scene';const small=document.createElement('small');small.textContent=fmt(s.start);const span=document.createElement('span');span.textContent=s.title;b.append(small,span);b.onclick=()=>{if(!recording)seek(s.start+.6);};$('scenes').append(b);});
$('play').onclick=playToggle;$('back').onclick=()=>seek(scenes[Math.max(0,currentScene().index-1)].start+.6);$('next').onclick=()=>seek(scenes[Math.min(scenes.length-1,currentScene().index+1)].start+.6);$('scrub').oninput=e=>seek(Number(e.target.value));$('speed').onchange=e=>{rate=Number(e.target.value);syncMedia(true);};
$('full').onclick=()=>canvas.requestFullscreen().catch(()=>status('当前浏览器不支持全屏，请放大窗口预览。'));
canvas.onkeydown=e=>{if(recording)return;if(e.code==='Space'){e.preventDefault();playToggle();}if(e.code==='ArrowLeft'){e.preventDefault();seek(time-5);}if(e.code==='ArrowRight'){e.preventDefault();seek(time+5);}};
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);}
$('poster').onclick=()=>canvas.toBlob(b=>{if(b)download(b,`AAA-镜头${current+1}-${fmt(time).replace(':','-')}.png`);},'image/png');
$('videoFile').onchange=async e=>{const file=e.target.files[0];if(!file)return;playing=false;syncMedia();const index=currentScene().index;const previous=clips.get(index);if(previous){previous.video.pause();URL.revokeObjectURL(previous.url);clips.delete(index);}const url=URL.createObjectURL(file),v=document.createElement('video');v.muted=true;v.playsInline=true;v.preload='auto';v.src=url;v.onloadeddata=()=>{clips.set(index,{video:v,url,focus:{x:1300,y:620}});seek(scenes[index].start+.6);status(`已接入第 ${index+1} 幕实录（${v.duration.toFixed(1)} 秒）。可设置点击位置。`);};v.onseeked=()=>{if(!playing)draw(time);};v.onerror=()=>{URL.revokeObjectURL(url);status('无法读取该录屏，请使用浏览器支持的 MP4 或 WebM。');};};
$('clearClip').onclick=()=>{const c=clips.get(current);if(c){c.video.pause();URL.revokeObjectURL(c.url);clips.delete(current);status('已恢复为明确标注的机制示意。');draw(time);}};
$('focus').onclick=()=>{if(!clips.has(current))return status('先为当前幕导入真实录屏，再设置点击位置。');playing=false;syncMedia();focusMode=true;seek(currentScene().start+1);status('请点击画面中需要放大的按钮或字段。');canvas.style.cursor='crosshair';};
canvas.onclick=e=>{if(!focusMode)return;const r=canvas.getBoundingClientRect(),c=clips.get(current);if(c)c.focus={x:(e.clientX-r.left)/r.width*1920,y:(e.clientY-r.top)/r.height*1080};focusMode=false;canvas.style.cursor='default';status('点击位置已设定。播放本幕即可预览光圈与局部放大。');};
$('audioFile').onchange=e=>{const file=e.target.files[0];if(!file)return;if(audio)audio.pause();if(audioUrl)URL.revokeObjectURL(audioUrl);if(audioSource)audioSource.disconnect();audioUrl=URL.createObjectURL(file);audio=new Audio(audioUrl);audio.preload='auto';audioSource=null;audio.onloadedmetadata=()=>status(`已导入配音 ${fmt(audio.duration)}。请确认与 07:30 时间轴对齐。`);audio.onerror=()=>status('无法读取音频，请改用 MP3、WAV 或兼容格式。');};
async function startRecording(all){
 if(recording)return;if(!canvas.captureStream||!window.MediaRecorder)return status('当前浏览器不支持 Canvas 视频导出，请在新版 Chrome 中打开。');
 const mime=['video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm'].find(m=>MediaRecorder.isTypeSupported(m));if(!mime)return status('此浏览器没有可用 WebM 编码器。');
 const start=all?0:currentScene().start;recordEnd=all?total:currentScene().start+currentScene().duration;playing=false;rate=1;$('speed').value='1';seek(start);const stream=canvas.captureStream(30);
 try{if(audio){audioContext=audioContext||new AudioContext();await audioContext.resume();if(!audioSource){audioSource=audioContext.createMediaElementSource(audio);audioDest=audioContext.createMediaStreamDestination();audioSource.connect(audioDest);audioSource.connect(audioContext.destination);}for(const tr of audioDest.stream.getAudioTracks())stream.addTrack(tr);}
  recordChunks=[];const outputName=`AAA-动画${all?'全片':'镜头'+(current+1)}${audio?'':'-无配音'}.webm`;const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:5000000});recording=recorder;
  recorder.ondataavailable=e=>{if(e.data.size)recordChunks.push(e.data);};recorder.onstop=()=>{if(recordChunks.length)download(new Blob(recordChunks,{type:mime}),outputName);for(const track of stream.getVideoTracks())track.stop();recording=null;lock(false);status('WebM 已导出。正式提交前转换 MP4 并检查配音、字幕、实录及文件大小。');};recorder.onerror=()=>{status('视频编码失败，请换用 Chrome 或缩短单幕导出。');stopRecording(true);};
  lock(true);recorder.start(1000);playing=true;last=performance.now();syncMedia(true);status(`正在导出${all?'全片':'本幕'}，约 ${Math.round(recordEnd-start)} 秒。请保持当前标签可见。${audio?'已包含导入配音。':'当前没有配音。'}`);
 }catch(err){for(const tr of stream.getVideoTracks())tr.stop();recording=null;lock(false);status('无法开始导出：'+err.message);}
}
function lock(on){for(const id of ['play','back','next','scrub','speed','exportScene','exportAll','audioFile','videoFile','focus','clearClip'])$(id).disabled=on;document.querySelectorAll('.scene').forEach(b=>b.disabled=on);$('cancel').hidden=!on;}
function stopRecording(cancelled){playing=false;syncMedia();if(recording&&recording.state!=='inactive')recording.stop();if(cancelled)status('已停止导出；已录部分将保存。');}
$('exportScene').onclick=()=>startRecording(false);$('exportAll').onclick=()=>startRecording(true);$('cancel').onclick=()=>stopRecording(true);
document.addEventListener('visibilitychange',()=>{if(document.hidden&&recording){stopRecording(true);status('标签离开前台，已停止并保存片段，避免产生跳帧成片。');}else if(document.hidden){playing=false;syncMedia();}});
window.addEventListener('beforeunload',()=>{cancelAnimationFrame(frameRequest);for(const c of clips.values())URL.revokeObjectURL(c.url);if(audioUrl)URL.revokeObjectURL(audioUrl);});
seek(.6);requestAnimationFrame(loop);
