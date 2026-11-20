import {esc} from '../utils/format.js';
import {table} from './common/table.js';
import {yuan,dt} from '../stores/billing.js';
export function traceBox(trace){
 if(!trace)return '';
 const l=trace.ledger;
 return `<section class="report"><h3>跨档依据 · ${esc(l.month)} 台账 v${l.version}</h3>
 <p>月费 ${yuan(l.total_cents)} · 总用量 ${l.total_quantity} · 由作业 #${trace.job_id} 的冻结快照生成</p>
 <h4>本月各档用量与费用</h4>
 ${table(trace.tier_usage.map(t=>({单价:t.unit_price,该档用量:t.quantity})))}
 ${table(trace.tier_cost.map(t=>({单价:t.unit_price,该档费用_元:t.cost_yuan})))}
 <h4>跨档点（合同累计用量达到阶梯下限的时刻）</h4>
 ${trace.crossings.length?table(trace.crossings.map(x=>({跨档时刻:dt(x.at_epoch),跨档后累计量:x.cumulative_after,原单价:x.from_tier_price,新单价:x.to_tier_price}))):'<p class="empty">本月未发生跨档。</p>'}
 <h4>部门分回（最大余数法，同余数按部门名）</h4>
 ${table(trace.departments.map(x=>({部门:x.department,精确费用_元:x.exact_cost_yuan,分回_分:x.cents,分回金额:yuan(x.cents)})))}
 <h4>快照内落在本月的用量</h4>
 ${table(trace.month_usages.map(u=>({用量ID:u.id,部门:u.department,开始:dt(u.start_at),结束:dt(u.end_at),用量:u.quantity,补录:u.backfilled?'是':'否'})))}</section>`;
}
export function previewBox(res){
 if(!res)return '';
 const months=res.month_order.map(mk=>{
  const m=res.months[mk];
  return `<h4>${esc(mk)} · 月费 ${yuan(m.total_cents)}（精确 ${m.exact_cost_yuan} 元，用量 ${m.total_quantity}）</h4>`
   +table(m.departments.map(x=>({部门:x.department,精确_元:x.exact_cost_yuan,分回_分:x.cents})))
   +(m.crossings.length?table(m.crossings.map(x=>({跨档时刻:dt(x.at_epoch),累计量:x.cumulative_after,新单价:x.to_tier_price}))):'<p class="empty">该月无跨档。</p>');
 }).join('');
 return `<section class="report">${months}</section>`;
}
