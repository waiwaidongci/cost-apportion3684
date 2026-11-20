import {loadBilling,listUsages,ledger} from '../api/billing.js';
export const billingStore={
 data:{contracts:[],jobs:[],usages:[],ledger:[]},
 selectedContract:null,selectedLedger:null,trace:null
};
export async function reloadBilling(){
 billingStore.data=await loadBilling();
 if(!billingStore.selectedContract && billingStore.data.contracts[0]){
  billingStore.selectedContract=billingStore.data.contracts[0].id;
 }
 if(billingStore.selectedContract){
  billingStore.data.usages=await listUsages(billingStore.selectedContract);
  billingStore.data.ledger=await ledger(billingStore.selectedContract);
 }
}
export const yuan=cents=>`¥${(cents/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
export const dt=epoch=>new Date(epoch*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
