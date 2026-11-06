// Local Edge/Chromium CDP inspection. Node >=22, no npm dependencies.
// Only navigation controls are clicked; never trigger business operations.
import {mkdir, writeFile} from 'node:fs/promises';
const base = process.env.UI_REVIEW_URL || 'http://127.0.0.1:8511';
const tabs = await (await fetch('http://127.0.0.1:9223/json')).json();
const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
await new Promise(resolve => ws.addEventListener('open', resolve, {once:true}));
let serial = 0;
const pending = new Map();
ws.addEventListener('message', e => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) {
    const {resolve,reject} = pending.get(msg.id); pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  }
});
const send = (method,params={}) => new Promise((resolve,reject) => {
  const id = ++serial; pending.set(id,{resolve,reject}); ws.send(JSON.stringify({id,method,params}));
});
const evaluate = async expression => {
  const result = await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
};
const pause = ms => new Promise(r => setTimeout(r,ms));
async function waitFor(expression) {
  for(let i=0;i<120;i++) { if(await evaluate(expression)) return; await pause(250); }
  throw new Error('Timed out: '+expression);
}
await mkdir('reports/ui_review',{recursive:true});
async function screenshot(name) {
  const {data} = await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  await writeFile('reports/ui_review/'+name+'.png',Buffer.from(data,'base64'));
}
try {
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  if (process.argv.includes('--controls')) {
    await send('Page.navigate',{url:'http://127.0.0.1:8512'});
    await waitFor(`document.querySelectorAll('[data-testid="stMetric"]').length === 4 && document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') === 'notRunning'`);
    await waitFor(`!!document.querySelector('[data-testid="stDownloadButton"] button')`);
    const colors = await evaluate(`Array.from(document.querySelectorAll('[data-testid="stMain"] :is([data-testid="stButton"],[data-testid="stFormSubmitButton"],[data-testid="stDownloadButton"]) button')).map(e=>({text:e.innerText,fg:getComputedStyle(e.querySelector('p')||e).color,bg:getComputedStyle(e).backgroundColor,opacity:getComputedStyle(e).opacity,disabled:e.disabled}))`);
    function luminance(rgb) { return rgb.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0); }
    for(const c of colors) {
      const [a,b]=[luminance(c.fg),luminance(c.bg)].sort((a,b)=>a-b);
      c.contrast=(b+.05)/(a+.05);
      if(c.contrast < 4.5 || c.opacity !== '1') throw new Error('Unreadable control: '+JSON.stringify(c));
    }
    console.log('control contrasts',JSON.stringify(colors));
    if(colors.length!==6) throw new Error('Expected six control states');
    if(await evaluate(`getComputedStyle(document.querySelector('[data-testid="stCaptionContainer"]')).opacity !== '1'`)) throw new Error('Caption opacity regression');
    const box=await evaluate(`(()=>{const r=document.querySelector('[data-testid="stMain"] [data-testid="stButton"] button').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',...box}); await pause(300);
    console.log('hover',await evaluate(`JSON.stringify({color:getComputedStyle(document.querySelector('[data-testid="stMain"] [data-testid="stButton"] button p')).color,bg:getComputedStyle(document.querySelector('[data-testid="stMain"] [data-testid="stButton"] button')).backgroundColor})`));
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
    console.log('focus',await evaluate(`(()=>{const e=document.activeElement;return {tag:e.tagName,outline:getComputedStyle(e).outlineStyle,width:getComputedStyle(e).outlineWidth}})()`));
    await screenshot('controls-desktop');
    await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
    console.log('reduced motion',await evaluate(`getComputedStyle(document.querySelector('[data-testid="stMain"] [data-testid="stButton"] button')).transitionDuration`));
    await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
    await pause(400);
    console.log('collapse markup',await evaluate(`document.querySelector('[data-testid="stSidebarCollapseButton"]')?.outerHTML`));
    const c = await evaluate(`(()=>{const b=document.querySelector('[data-testid="stSidebarCollapseButton"] button')||document.querySelector('button[data-testid="stSidebarCollapseButton"]');if(!b)return null;const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    console.log('collapse box',c);
    if(c) { await send('Input.dispatchMouseEvent',{type:'mouseMoved',...c}); await send('Input.dispatchMouseEvent',{type:'mousePressed',...c,button:'left',clickCount:1}); await send('Input.dispatchMouseEvent',{type:'mouseReleased',...c,button:'left',clickCount:1}); }
    await pause(500);
    await evaluate(`document.querySelector('[data-testid="stMain"]').scrollTop=0`);
    if(await evaluate(`document.querySelector('.hb-page-header h1').getBoundingClientRect().top < document.querySelector('[data-testid="stHeader"]').getBoundingClientRect().bottom`)) throw new Error('Toolbar obscures mobile title');
    await screenshot('controls-mobile');
    const widths=await evaluate(`({viewport:innerWidth,document:document.documentElement.scrollWidth,sidebar:document.querySelector('[data-testid="stSidebar"]')?.getAttribute('aria-expanded')})`);
    console.log('mobile',widths);
    if(widths.document>widths.viewport)throw new Error('Mobile horizontal overflow');
  } else {
  await send('Page.navigate',{url:base});
  await waitFor(`document.querySelector('.hb-page-header') && document.querySelectorAll('[data-testid="stMetric"]').length > 0`);
  await pause(800);
  await waitFor(`document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') === 'notRunning'`);
  await screenshot('desktop-overview');
  const result = await evaluate(`(() => {
    const inspect = s => [...document.querySelectorAll(s)].map(e => {const c=getComputedStyle(e),r=e.getBoundingClientRect(); return {text:e.innerText,color:c.color,bg:c.backgroundColor,width:r.width,height:r.height,display:c.display};});
    return {captions:[...document.querySelectorAll('[data-testid="stCaptionContainer"]')].map(e=>({html:e.outerHTML,color:getComputedStyle(e).color,child:e.firstElementChild && getComputedStyle(e.firstElementChild).color})),header:inspect('.hb-page-header'),sidebar:inspect('[data-testid="stSidebar"]'),nav:inspect('[data-testid="stSidebar"] [role="radiogroup"] label'),metrics:inspect('[data-testid="stMetricValue"]'),buttons:inspect('[data-testid="stButton"] button')};
  })()`);
  console.log(JSON.stringify(result,null,2));
  const labels = await evaluate(`Array.from(document.querySelectorAll('[data-testid="stSidebar"] [role="radiogroup"] label')).map(e=>e.innerText)`);
  for (const index of [1,2,3,4,5,6,7]) {
    await evaluate(`document.querySelectorAll('[data-testid="stSidebar"] [role="radiogroup"] label')[${index}].click()`);
    await waitFor(`document.querySelector('.hb-page-header h1')?.innerText.includes(${JSON.stringify(labels[index].replace(/^\S+\s/,''))})`);
    await waitFor(`document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') === 'notRunning'`);
    await pause(300);
    await screenshot('desktop-page-'+index);
    console.log('page',index,await evaluate(`JSON.stringify({heading:document.querySelector('.hb-page-header h1').innerText,exceptions:[...document.querySelectorAll('[data-testid="stException"]')].map(e=>e.innerText),buttons:[...document.querySelectorAll('[data-testid="stMain"] [data-testid="stButton"] button')].map(e=>({text:e.innerText,color:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor,disabled:e.disabled}))})`));
  }
  await evaluate(`document.querySelectorAll('[data-testid="stSidebar"] [role="radiogroup"] label')[5].click()`);
  await waitFor(`document.querySelector('.hb-page-header h1')?.innerText.includes(${JSON.stringify('Dự báo')}) && document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') === 'notRunning'`);
  console.log('containers',await evaluate(`JSON.stringify([...document.querySelectorAll('[data-testid="stMain"] [data-testid="stLayoutWrapper"]')].map(e=>({class:e.className,style:e.getAttribute('style'),child:e.firstElementChild?.outerHTML.slice(0,350)})).slice(0,15))`));
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
  await pause(700);
  console.log('mobile collapse controls',await evaluate(`JSON.stringify([...document.querySelectorAll('button')].filter(e=>e.closest('[data-testid="stSidebar"]')).map(e=>({title:e.title,label:e.getAttribute('aria-label'),testid:e.dataset.testid,text:e.innerText})))`));
  const collapse = await evaluate(`(()=>{const b=document.querySelector('[data-testid="stSidebarCollapseButton"] button'); if(!b)return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
  if(collapse) {
    await send('Input.dispatchMouseEvent',{type:'mousePressed',...collapse,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',...collapse,button:'left',clickCount:1});
  }
  await pause(600);
  await screenshot('mobile-forecast');
  console.log('mobile widths',await evaluate(`JSON.stringify({viewport:innerWidth,document:document.documentElement.scrollWidth,main:document.querySelector('[data-testid="stMain"]')?.scrollWidth,cols:[...document.querySelectorAll('[data-testid="stColumn"]')].map(e=>e.getBoundingClientRect().width)})`));
  }
} finally { ws.close(); }
