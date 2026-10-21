let TOKEN = localStorage.getItem('panel_token') || '';
let ws = null, termEl = null, curTask = null;

async function api(path, post) {
  const opt = post ? {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(Object.assign({token:TOKEN}, post||{}))} : {};
  const u = post ? path : path + (path.includes('?') ? '&' : '?') + 'token=' + TOKEN;
  const r = await fetch(u, opt);
  if (r.status === 401) { TOKEN=''; showLogin(); return {}; }
  return r.json();
}
function showLogin(){ document.getElementById('login').classList.remove('hide'); document.getElementById('app').classList.add('hide'); }
function showApp(){ document.getElementById('login').classList.add('hide'); document.getElementById('app').classList.remove('hide'); }
function toast(m){ const d=document.createElement('div'); d.className='toast'; d.textContent=m; document.body.appendChild(d);
  setTimeout(()=>d.remove(), 2200); }
function human(n){ const u=['B','KB','MB','GB','TB']; let i=0; n=+n||0;
  while(n>=1024&&i<u.length-1){n/=1024;i++;} return n.toFixed(1)+' '+u[i]; }
function upStr(s){ const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
  return (d?d+'天':'')+(h?h+'小时':'')+m+'分钟'; }

async function login(){
  const pw = document.getElementById('pw').value;
  const r = await fetch('/api/login', {method:'POST',headers:{'Content-Type':'application/json'},
    body: JSON.stringify({password: pw})});
  const j = await r.json();
  if (j.ok) { TOKEN=j.token; localStorage.setItem('panel_token',TOKEN); showApp(); init(); }
  else alert('密码错误');
}

function setBar(id, pct){ const b=document.getElementById(id); b.className='bar'+(pct>85?' bad':pct>65?' warn':'');
  b.firstElementChild.style.width=Math.min(pct,100)+'%'; }

function draw(cv, series){
  const c=document.getElementById(cv); if(!c) return;
  const w=c.width=c.clientWidth, h=c.height=c.clientHeight;
  const g=c.getContext('2d'); g.clearRect(0,0,w,h);
  g.strokeStyle='#e8ecf2'; g.lineWidth=1;
  for(let i=1;i<4;i++){ g.beginPath(); g.moveTo(0,h*i/4); g.lineTo(w,h*i/4); g.stroke(); }
  series.forEach(s=>{
    const d=s.data; if(!d||d.length<2) return;
    const max=Math.max(...d, s.max||1);
    g.beginPath(); g.strokeStyle=s.color; g.lineWidth=2;
    d.forEach((v,i)=>{ const x=i/(d.length-1)*w, y=h-(v/max)*(h-10)-5;
      i?g.lineTo(x,y):g.moveTo(x,y); });
    g.stroke();
    g.lineTo(w,h); g.lineTo(0,h); g.closePath();
    g.fillStyle=s.fill||'rgba(30,94,255,.08)'; g.fill();
  });
}

let lastStats = null;
async function stats(){
  const s = await api('/api/stats'); if(!s.cpu_info) return;
  lastStats = s;
  document.getElementById('k_cpu').textContent = s.cpu+'%';
  document.getElementById('k_cpu_d').textContent = s.cpu_info.cores+' 核 · '+s.cpu_info.model.slice(0,28);
  setBar('b_cpu', s.cpu);
  document.getElementById('k_mem').textContent = s.mem.percent+'%';
  document.getElementById('k_mem_d').textContent = human(s.mem.used)+' / '+human(s.mem.total);
  setBar('b_mem', s.mem.percent);
  document.getElementById('k_disk').textContent = s.disk.percent+'%';
  document.getElementById('k_disk_d').textContent = human(s.disk.used)+' / '+human(s.disk.total)+' ('+s.disk.mount+')';
  setBar('b_disk', s.disk.percent);
  document.getElementById('k_net').textContent = human(s.net_rate.rx)+'/s';
  document.getElementById('k_net_d').textContent = '↓'+human(s.net_rate.rx)+'  ↑'+human(s.net_rate.tx);
  document.getElementById('t_load').textContent = s.load.join(' / ');
  document.getElementById('t_up').textContent = upStr(s.uptime);
  document.getElementById('t_host').textContent = s.hostname;
  draw('c_cpu', [{data:s.cpu_hist, color:'#1e5eff', fill:'rgba(30,94,255,.12)'}]);
  draw('c_mem', [{data:s.mem_hist, color:'#1e5eff', fill:'rgba(30,94,255,.08)'},
                 {data:s.net_rx_hist, color:'#10b981', fill:'rgba(16,185,129,.06)'},
                 {data:s.net_tx_hist, color:'#f59e0b', fill:'rgba(245,158,11,.06)'}]);
  const rows=[['主机名',s.hostname],['操作系统',s.system],['内核版本',s.kernel],
    ['CPU',s.cpu_info.model+' ('+s.cpu_info.cores+' 核)'],['公网 IP',s.ip||'-'],
    ['内存',human(s.mem.total)],['磁盘',human(s.disk.total)+' ('+s.disk.mount+')'],
    ['系统负载',s.load.join(' / ')],['运行时长',upStr(s.uptime)]];
  document.getElementById('sys_body').innerHTML = rows.map(r=>'<tr><th style="width:130px">'+r[0]+'</th><td>'+r[1]+'</td></tr>').join('');
}

async function loadProc(){
  const j = await api('/api/processes'); if(!j.list) return;
  document.getElementById('proc_body').innerHTML = j.list.map(p=>
    '<tr><td>'+p.pid+'</td><td>'+p.name+'</td><td>'+p.cpu+'%</td><td>'+human(p.rss)+'</td><td>'+p.state+
    '</td><td style="color:#888;font-size:12px">'+p.cmd+'</td><td><button class="btn r" onclick="kill('+p.pid+')">结束</button></td></tr>').join('');
}
async function kill(pid){ await api('/api/kill',{pid}); toast('已结束 '+pid); loadProc(); }

let appList=[], sel=new Set();
async function loadApps(){
  const j = await api('/api/apps'); if(!j.apps) return;
  appList=j.apps;
  document.getElementById('apps').innerHTML = j.apps.map((a,i)=>
    '<div class="app" id="a'+i+'" onclick="tog('+i+')"><input type="checkbox" id="c'+i+'" style="margin-top:3px">'+
    '<div><div class="nm">'+a.name+' <span class="tag">'+a.cat+'</span></div><div class="pk">'+a.pkg+'</div></div></div>').join('');
}
function tog(i){ const a=appList[i], el=document.getElementById('a'+i);
  const cb=document.getElementById('c'+i); cb.checked=!cb.checked;
  el.classList.toggle('sel', cb.checked);
  cb.checked?sel.add(a.pkg):sel.delete(a.pkg); }
async function install(){
  if(!sel.size){ alert('请先勾选要安装的软件'); return; }
  const j = await api('/api/install',{pkgs:[...sel]});
  if(j.ok){ curTask=j.task; toast('已开始安装'); pollTask(); } else alert(j.msg||'失败');
}
async function pollTask(){
  const j = await api('/api/task',{id:curTask});
  const el=document.getElementById('ilog'); el.textContent=j.log||'…';
  el.scrollTop=el.scrollHeight;
  if(j.status==='running') setTimeout(pollTask,2000);
  else toast('安装任务结束');
}
async function sysUpdate(){ const j=await api('/api/exec',{cmd:'sudo apt-get update -qq 2>&1 | tail -5'});
  document.getElementById('ilog').textContent=j.out||j.msg; toast('软件源已更新'); }

let cmdBuf=[];
function termInit(){
  termEl=document.getElementById('term');
  if(ws) return;
  const proto = location.protocol==='https:'?'wss':'ws';
  ws = new WebSocket(proto+'://'+location.host+'/ws/terminal?token='+TOKEN);
  ws.onopen=()=>{ termEl.textContent='[已连接] 云面板远程终端\r\n'; toast('终端已连接'); };
  ws.onmessage=e=>{ termEl.textContent+=e.data; termEl.scrollTop=termEl.scrollHeight; };
  ws.onclose=()=>{ termEl.textContent+='\r\n[连接已断开，刷新页面重连]'; };
  ws.onerror=()=>{ termEl.textContent='[WebSocket 连接失败，可用上方「快速命令」或软件商店]'; };
}
function sendCmd(){ const i=document.getElementById('cmd'); const c=i.value; if(!c) return;
  if(ws&&ws.readyState===1){ ws.send(JSON.stringify({cmd:c+'\n'})); }
  else { api('/api/exec',{cmd:c}).then(j=>{ termEl.textContent+='$ '+c+'\n'+(j.out||j.msg)+'\n'; termEl.scrollTop=termEl.scrollHeight; }); }
  i.value=''; }
function quick(c){ const i=document.getElementById('cmd'); i.value=c; sendCmd(); }
function clearTerm(){ termEl.textContent=''; }

async function loadFiles(){
  const p=document.getElementById('fpath').value||'/';
  const j=await api('/api/files?path='+encodeURIComponent(p));
  if(!j.ok){ alert(j.msg); return; }
  document.getElementById('file_body').innerHTML = j.list.map(f=>
    '<tr><td>'+f.name+'</td><td>'+(f.dir?'目录':'文件')+'</td><td>'+(f.dir?'-':human(f.size))+
    '</td><td>'+f.mtime+'</td><td>'+(f.dir?'<button class="btn" onclick="openDir(\''+p.replace(/\/$/,'')+'/'+f.name+'\')">进入</button>':'')+'</td></tr>').join('');
}
function openDir(p){ document.getElementById('fpath').value=p; loadFiles(); }

function go(p){
  document.querySelectorAll('.side a').forEach(a=>a.classList.toggle('on',a.dataset.p===p));
  ['home','proc','store','term','file','sys'].forEach(x=>
    document.getElementById('p_'+x).classList.toggle('hide', x!==p));
  if(p==='proc') loadProc();
  if(p==='store') loadApps();
  if(p==='term') termInit();
  if(p==='file') loadFiles();
  if(p==='home'||p==='sys') stats();
}

function init(){
  document.querySelectorAll('.side a').forEach(a=>a.onclick=e=>{e.preventDefault();go(a.dataset.p);});
  stats(); loadApps(); loadProc();
  setInterval(()=>{ if(!document.getElementById('p_home').classList.contains('hide')||
    !document.getElementById('p_sys').classList.contains('hide')) stats(); }, 3000);
  setInterval(()=>{ if(!document.getElementById('p_proc').classList.contains('hide')) loadProc(); }, 5000);
}
if(TOKEN){ fetch('/api/stats?token='+TOKEN).then(r=>{ if(r.status===401){showLogin();} else {showApp(); init();} }); }
else showLogin();
