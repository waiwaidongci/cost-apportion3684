import {request} from './client.js';
const base='/billing';
export const loadBilling=async()=>Object.fromEntries(await Promise.all([
 ['contracts',base+'/contracts'],['jobs',base+'/jobs']
].map(async([k,p])=>[k,await request(p)])));
export const saveContract=(data,id)=>request(base+'/contracts'+(id?'/'+id:''),id?'PUT':'POST',data);
export const listUsages=contractId=>request(base+'/usages'+(contractId?('?contract_id='+contractId):''));
export const saveUsage=(data,id)=>request(base+'/usages'+(id?'/'+id:''),id?'PUT':'POST',data);
export const removeUsage=id=>request(base+'/usages/'+id,'DELETE',{});
export const recompute=data=>request(base+'/recompute','POST',data);
export const ledger=(contractId,month)=>request(base+'/ledger?contract_id='+contractId+(month?('&month='+month):''));
export const ledgerTrace=id=>request(base+'/ledger/'+id+'/trace');
export const preview=data=>request(base+'/preview','POST',data);
