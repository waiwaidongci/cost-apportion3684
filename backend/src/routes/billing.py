"""共用仪器阶梯计费路由：合同、用量、补录重算作业、台账与跨档依据。"""
from fastapi import APIRouter,Depends,HTTPException
from src.config.database import database
from src.controllers.auth import current,editor
from src.models.billing import BillingContract,BillingUsage,BillingJob,BillingLedger
from src.schemas.requests import ContractInput,UsageInput,RecomputeInput,PreviewInput
from src.services import billing as svc
from src.services.billing_pricing import bill_contract,validate_tiers,validate_usage_record
from src.utils.serialize import row
router=APIRouter(prefix='/billing')

@router.get('/contracts')
def contracts(db=Depends(database),u=Depends(current)):
 return [row(x) for x in db.query(BillingContract).order_by(BillingContract.id).all()]

@router.post('/contracts')
def create_contract(b:ContractInput,db=Depends(database),u=Depends(editor)):
 return row(svc.save_contract(db,u,b.model_dump()))

@router.put('/contracts/{id}')
def update_contract(id:int,b:ContractInput,db=Depends(database),u=Depends(editor)):
 return row(svc.save_contract(db,u,b.model_dump(),id))

@router.get('/usages')
def usages(contract_id:int|None=None,db=Depends(database),u=Depends(current)):
 q=db.query(BillingUsage).order_by(BillingUsage.start_at)
 if contract_id:
  q=q.filter_by(contract_id=contract_id)
 return [row(x) for x in q.limit(5000).all()]

@router.post('/usages')
def create_usage(b:UsageInput,db=Depends(database),u=Depends(editor)):
 obj,contract=svc.save_usage(db,u,b.model_dump(),backfilled=b.backfilled)
 job=svc.enqueue_recompute(db,u,contract.id,b.start_at,b.end_at,
   name=('补录重算' if b.backfilled else '用量入账重算'),
   trigger=('backfill' if b.backfilled else 'usage'))
 return {'usage':row(obj),'job':row(job)}

@router.put('/usages/{id}')
def update_usage(id:int,b:UsageInput,db=Depends(database),u=Depends(editor)):
 obj,contract=svc.save_usage(db,u,b.model_dump(),id=id,backfilled=b.backfilled)
 job=svc.enqueue_recompute(db,u,contract.id,min(b.start_at,obj.start_at),b.end_at,
   name='用量修改重算',trigger='usage')
 return {'usage':row(obj),'job':row(job)}

@router.delete('/usages/{id}')
def remove_usage(id:int,db=Depends(database),u=Depends(editor)):
 obj=db.get(BillingUsage,id)
 if not obj:
  raise HTTPException(404,'用量记录不存在')
 start,end,cid=obj.start_at,obj.end_at,obj.contract_id
 svc.delete_usage(db,u,id)
 job=svc.enqueue_recompute(db,u,cid,start,end,name='用量删除重算',trigger='usage')
 return {'deleted':id,'job':row(job)}

@router.post('/recompute')
def recompute(b:RecomputeInput,db=Depends(database),u=Depends(editor)):
 return row(svc.enqueue_recompute(db,u,b.contract_id,b.start_at,b.end_at,
   b.name or None,b.trigger))

@router.get('/jobs')
def jobs(db=Depends(database),u=Depends(current)):
 return [row(x) for x in db.query(BillingJob).order_by(BillingJob.id.desc()).limit(200).all()]

@router.get('/jobs/{id}')
def job_detail(id:int,db=Depends(database),u=Depends(current)):
 obj=db.get(BillingJob,id)
 if not obj:
  raise HTTPException(404,'作业不存在')
 return row(obj)

@router.get('/ledger')
def ledger(contract_id:int,month:str|None=None,current_only:bool=True,
           db=Depends(database),u=Depends(current)):
 q=db.query(BillingLedger).filter_by(contract_id=contract_id)
 if month:
  q=q.filter_by(month=month)
 if current_only:
  q=q.filter_by(is_current=True)
 return [row(x) for x in q.order_by(BillingLedger.month,BillingLedger.version).all()]

@router.get('/ledger/{lid}/trace')
def ledger_trace(lid:int,db=Depends(database),u=Depends(current)):
 """跨档依据：返回该台账版本对应作业快照中落在本月的用量、跨档点与各档用量。"""
 obj=db.get(BillingLedger,lid)
 if not obj:
  raise HTTPException(404,'台账不存在')
 job=db.get(BillingJob,obj.job_id) if obj.job_id else None
 usages=[]
 if job:
  for x in job.snapshot['usages']:
   if x['start_at'] < _month_end(obj.month) and x['end_at'] > _month_start(obj.month):
    usages.append(x)
 return {'ledger':row(obj),'job_id':obj.job_id,'month_usages':usages,
         'crossings':obj.crossings,'tier_usage':obj.tier_usage,'tier_cost':obj.tier_cost,
         'departments':obj.departments}

@router.post('/preview')
def preview(b:PreviewInput,db=Depends(database),u=Depends(editor)):
 """短时段手算核对：不落库，直接返回连续时段计费明细。"""
 tiers=validate_tiers(b.tiers)
 usages=[validate_usage_record(x) for x in b.usages]
 return bill_contract(usages,tiers)


def _month_start(mk):
 from src.services.billing_pricing import month_bounds
 return month_bounds(mk)[0]
def _month_end(mk):
 from src.services.billing_pricing import month_bounds
 return month_bounds(mk)[1]
