const el = id => document.getElementById(id);
let token = '', report;
const labels = {version:'OS version',lacp:'LACP summary',isis:'IS-IS neighbors',history:'OS change history / recorded actor'};
async function api(path, body) {
  const r = await fetch(path, {method:body ? 'POST':'GET', headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'}, ...(body ? {body:JSON.stringify(body)}:{})});
  const data = await r.json(); if (!r.ok) throw Error(data.error); return data;
}
function utcInput(date) { return date.toISOString().slice(0,16); }
el('end').value = utcInput(new Date());
el('start').value = utcInput(new Date(Date.now()-7*86400000));
el('connect').onclick = async () => {
  token = el('token').value; el('run').disabled = true;
  try {
    const c = await api('/api/config');
    for (const [id, values] of [['device',c.devices],['check',c.checks]]) {
      el(id).replaceChildren(...values.map(value => {const o=document.createElement('option');o.value=value;o.textContent=labels[value]||value;return o;}));
    }
    el('status').textContent=`${c.mode.toUpperCase()} | AI: ${c.ai} | Device fallback: ${c.fallback_enabled ? 'enabled':'disabled'}`;
    el('run').disabled=false;
  } catch(e) {el('status').textContent=e.message;}
};
el('form').onsubmit = async event => {
  event.preventDefault(); el('run').disabled=true; el('status').textContent='Querying Kusto and evaluating evidence...';
  try {
    report = await api('/api/investigate',{device:el('device').value,check:el('check').value,question:el('question').value,start:el('start').value+'Z',end:el('end').value+'Z'});
    el('finding').textContent=report.finding;
    el('metadata').textContent=`${report.mode.toUpperCase()} | Run ${report.run_id} | Fallback: ${report.fallback} | AI: ${report.ai_status}`;
    el('interpretation').textContent=report.interpretation;
    el('limitations').replaceChildren(...report.limitations.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
    el('evidence').replaceChildren(...report.evidence.map(item=>{const pre=document.createElement('pre');pre.textContent=JSON.stringify(item,null,2);return pre;}));
    el('result').hidden=false; el('status').textContent='Investigation complete';
  } catch(e) {el('status').textContent=e.message;}
  finally {el('run').disabled=false;}
};
el('download').onclick = () => {const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`investigation-${report.run_id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
