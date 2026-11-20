import {heading} from '../components/common/header.js';
import {table} from '../components/common/table.js';
import {esc,fmt} from '../utils/format.js';
import {yuan,dt} from '../stores/billing.js';
import {STATUSES} from '../constants/enums.js';

// 本地表格：单元格允许受信 HTML（操作按钮）；用户数据在构造行时已 esc。
function htable(rows){
 if(!rows.length)return '<p class="empty">暂无记录。</p>';
 const cols=Object.keys(rows[0]);
 return '<div class="table-wrap"><table><thead><tr>'+cols.map(k=>`<th>${esc(k)}</th>`).join('')
  +'</tr></thead><tbody>'+rows.map(r=>'<tr>'+cols.map(k=>{
    const v=r[k];return `<td>${(typeof v==='number')?fmt(v):(v??'')}</td>`;
   }).join('')+'</tr>').join('')+'</tbody></table></div>';
}

const tierRows=(tiers=[])=>tiers.map((t,i)=>`<div class="policy-row" data-tier="${i}">
 <label>阶梯下限(含)<input name="tier_from" type="number" step="any" min="0" value="${esc(t.from??'')}" ${i===0?'readonly':''} required></label>
 <label>单价(元/单位)<input name="tier_price" type="number" step="any" min="0" value="${esc(t.unit_price??'')}" required></label>
 <button type="button" class="remove-tier" ${i===0?'disabled':''}>删除该档</button></div>`).join('');

function contracts(c,d){
 const list=d.contracts;
 return `<details open><summary>合同与阶梯价（固定合同，仅新增版本，不覆盖旧合同）</summary>
 <form id="contract-form">
  <div class="form-grid">
   <label>合同编号<input name="code" value="INS-NEW" required></label>
   <label>合同版本<input name="version" value="v1" required></label>
   <label>仪器名称<input name="instrument" value="共用光谱仪" required></label>
   <label>计量单位<input name="unit" value="次" required></label>
  </div>
  <h3>边际阶梯价（按合同累计用量跨档）</h3>
  <div id="tier-rows">${tierRows([{from:0,unit_price:10},{from:100,unit_price:8},{from:300,unit_price:5}])}</div>
  <button type="button" id="add-tier">增加一档</button><button>保存合同</button>
 </form></details>
 <h2>已固定合同</h2>${table(list.map(x=>({编号:x.id,合同:x.code,版本:x.version,仪器:x.instrument,单位:x.unit,阶梯:x.tiers.map(t=>`≥${t.from} @${t.unit_price}`).join(' / ')})))}`;
}

function usages(c,d){
 const cid=d.selectedContract;
 const contract=d.contracts.find(x=>x.id===cid);
 if(!contract)return '<p class="empty">请先保存并选择一个合同。</p>';
 const now=Math.floor(Date.now()/1000);
 return `<details open><summary>用量录入与补录（保存即排队重算受影响月份）</summary>
 <form id="usage-form" data-contract="${cid}">
  <div class="form-grid">
   <label>部门<input name="department" value="光学研究" required></label>
   <label>开始时间(epoch秒)<input name="start_at" type="number" step="any" value="${now}" required></label>
   <label>结束时间(epoch秒)<input name="end_at" type="number" step="any" value="${now+86400}" required></label>
   <label>区间总用量<input name="quantity" type="number" step="any" min="0" value="120" required></label>
   <label class="weekday"><input name="backfilled" type="checkbox">补录旧用量（重算后续月份）</label>
  </div>
  <button>保存并入队重算</button>
 </form></details>
 <h2>合同 ${esc(contract.code)} 的用量（重叠区间按各自速率共同跨档）</h2>
 ${htable(d.usages.map(u=>({编号:u.id,部门:esc(u.department),开始:dt(u.start_at),结束:dt(u.end_at),用量:u.quantity,补录:u.backfilled?'是':'否',操作:`<button class="del-usage" data-id="${u.id}">删除并重算</button>`})))}`;
}

function ledgerView(c,d){
 const rows=d.ledger;
 return `<h2>月度台账（版本化，各月费用原子切换；旧报告照常查看）</h2>
 ${htable(rows.map(l=>({月份:esc(l.month),版本:'v'+l.version,月费:esc(yuan(l.total_cents)),精确费用:l.exact_cost,总用量:l.total_quantity,现行:l.is_current?'是':'历史',作业:l.job_id,跨档依据:`<button class="show-trace" data-id="${l.id}">查看跨档依据</button>`})))}
 <div id="trace-box"></div>`;
}

function jobsView(c,d){
 return `<h2>重算作业队列（FIFO 串行；旧核算不得顶掉新账）</h2>`+
  table(d.jobs.map(j=>({序号:j.seq,作业:j.name,触发:j.trigger,状态:STATUSES[j.status]||j.status,区间:`${j.month_from}~${j.month_to}`,月份:(j.months||[]).join(','),创建:dt(j.created),错误:j.error||''})));
}

function preview(c){
 const now=Math.floor(Date.now()/1000);
 return `<details><summary>短时段手算核对（不落库，直接验证重叠跨档与跨月）</summary>
 <form id="preview-form">
  <div class="form-grid">
   <label>阶梯JSON <input name="tiers" value='[{"from":0,"unit_price":10},{"from":100,"unit_price":8}]'></label>
   <label>用量JSON <input name="usages" value='[{"department":"甲","start_at":'+now+',"end_at":'+(now+3600)+',"quantity":60},{"department":"乙","start_at":'+now+',"end_at":'+(now+1800)+',"quantity":60}]'></label>
  </div>
  <button>试算</button>
 </form><div id="preview-box"></div></details>`;
}

export function billing(c,d){
 const contracts2=d.contracts;
 const contractOptions=contracts2.map(x=>`<option value="${x.id}" ${x.id===d.selectedContract?'selected':''}>${esc(x.code)} / ${esc(x.version)} · ${esc(x.instrument)}</option>`).join('');
 return heading('SHARED METER / 07','共用仪器阶梯计费','用量在区间内均匀发生，重叠时按各自速率共同跨档；跨月按发生时间归费。月费四舍五入到分，按部门余数最大余数法分回，同余数按部门名。')
 +`<form id="contract-pick" class="inline-form"><label>选择合同<select name="contract_id">${contractOptions||'<option>暂无合同</option>'}</select></label></form>`
 +contracts(c,d)+usages(c,d)+ledgerView(c,d)+jobsView(c,d)+preview(c);
}
