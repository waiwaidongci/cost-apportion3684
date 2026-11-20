"""共用仪器阶梯计费：合同、用量、补录重算作业与版本化台账。"""
import time,uuid,hashlib,json
from decimal import Decimal
from fastapi import HTTPException
import redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models.billing import BillingContract,BillingUsage,BillingJob,BillingLedger
from src.services.audit import log
from src.services.billing_pricing import (validate_tiers,validate_usage_record,
 bill_contract,add_months,_d)

QUEUE='billing-jobs'


def _next_seq(db):
 last=db.query(BillingJob).order_by(BillingJob.seq.desc()).first()
 return (last.seq+1) if last and last.seq else 1


def save_contract(db,user,data,id=None):
 tiers=validate_tiers(data.get('tiers'))
 for key in ('code','version','instrument'):
  if not isinstance(data.get(key),str) or not 1<=len(data[key])<=120:
   raise ValueError(key+' 不能为空或过长')
 unit=data.get('unit') or '次'
 obj=db.get(BillingContract,id) if id else None
 if obj is None and id:
  raise HTTPException(404,'合同不存在')
 if obj is None:
  obj=BillingContract(natural_key='ctr-'+uuid.uuid4().hex,created=time.time())
 dup=db.query(BillingContract).filter(BillingContract.code==data['code'],
      BillingContract.version==data['version'],BillingContract.id!=obj.id).first()
 if dup:
  raise HTTPException(409,'合同编号+版本已存在')
 obj.code=data['code'];obj.version=data['version'];obj.instrument=data['instrument']
 obj.unit=unit
 # JSON 列只能存原生数值，转成 float 落库；引擎读取时再转回 Decimal 保精度
 obj.tiers=[{'from':float(t['from']),'unit_price':float(t['unit_price'])} for t in tiers]
 obj.active=True
 db.add(obj);db.commit()
 log(db,user.email,'billing.contract.save',f'{obj.code}/{obj.version}')
 db.commit()
 return obj


def save_usage(db,user,data,id=None,backfilled=False):
 rec=validate_usage_record({k:data[k] for k in ('department','start_at','end_at','quantity')})
 contract=db.get(BillingContract,data['contract_id'])
 if not contract:
  raise HTTPException(404,'合同不存在')
 obj=db.get(BillingUsage,id) if id else None
 if obj is None and id:
  raise HTTPException(404,'用量记录不存在')
 if obj is None:
  obj=BillingUsage(natural_key='use-'+uuid.uuid4().hex,created=time.time())
 obj.contract_id=contract.id;obj.department=rec['department']
 obj.start_at=float(rec['start']);obj.end_at=float(rec['end'])
 obj.quantity=Decimal(str(rec['quantity']));obj.backfilled=bool(backfilled)
 db.add(obj);db.commit()
 log(db,user.email,'billing.usage.backfill' if backfilled else 'billing.usage.save',
     f'contract={contract.id} usage={obj.id}')
 db.commit()
 return obj,contract


def delete_usage(db,user,usage_id):
 obj=db.get(BillingUsage,usage_id)
 if not obj:
  raise HTTPException(404,'用量记录不存在')
 cid=obj.contract_id
 db.delete(obj);log(db,user.email,'billing.usage.delete',usage_id);db.commit()
 return cid


def _affected_months(db,contract_id,start_at,end_at):
 # 区间覆盖到的全部月份：跨月用量即便开始于上月，末段也要归入末月，
 # 因此不能只按用量开始月判断，直接取 [首月, 末月] 完整范围。
 from src.services.billing_pricing import month_key
 first=month_key(_d(start_at));last=month_key(_d(end_at))
 months=[];cur=first
 while cur<=last:
  months.append(cur);cur=add_months(cur,1)
 return months


def enqueue_recompute(db,user,contract_id,start_at,end_at,name=None,trigger='recompute'):
 contract=db.get(BillingContract,contract_id)
 if not contract:
  raise HTTPException(404,'合同不存在')
 months=_affected_months(db,contract_id,start_at,end_at)
 if not months:
  raise HTTPException(422,'影响区间内没有可重算的月份')
 usages=[u for u in db.query(BillingUsage).filter_by(contract_id=contract_id)
         .order_by(BillingUsage.start_at).all()]
 snapshot={'contract_id':contract.id,'contract_code':contract.code,
  'contract_version':contract.version,'unit':contract.unit,'tiers':contract.tiers,
  'usages':[{'id':u.id,'department':u.department,'start_at':u.start_at,'end_at':u.end_at,
             'quantity':str(u.quantity),'backfilled':u.backfilled} for u in usages]}
 checksum=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 job=BillingJob(name=name or f'{contract.code} 补录重算 {months[0]}~{months[-1]}',
  trigger=trigger,status='queued',contract_id=contract.id,month_from=months[0],
  month_to=months[-1],months=months,snapshot=snapshot,checksum=checksum,
  seq=_next_seq(db),created=time.time(),created_by=user.email)
 db.add(job);db.commit()
 redis.Redis.from_url(REDIS_URL).rpush(QUEUE,job.id)
 log(db,user.email,'billing.job.queue',f'job={job.id} months={months}')
 db.commit()
 return job


def _publish(db,job):
 """单事务原子发布受影响月份的新台账版本；行锁串行化并发发布。"""
 res=bill_contract(job.snapshot['usages'],job.snapshot['tiers'])
 job.result={'months':res['months'],'crossings':res['crossings'],
             'month_order':res['month_order']}
 target=set(job.months)
 # 行锁锁定该合同全部台账行，串行化同合同的并发发布，保证各月费用原子切换
 existing=db.query(BillingLedger).filter_by(contract_id=job.contract_id).order_by(
   BillingLedger.month,BillingLedger.version).with_for_update().all()
 by_month={}
 for row in existing:
  by_month.setdefault(row.month,[]).append(row)
 for mk in sorted(target):
  rows=by_month.get(mk,[])
  for row in rows:
   row.is_current=False
  if mk in res['months']:
   m=res['months'][mk]
   new_version=(max((r.version for r in rows),default=0)+1)
   db.add(BillingLedger(contract_id=job.contract_id,month=mk,version=new_version,
    is_current=True,job_id=job.id,total_cents=m['total_cents'],
    exact_cost=Decimal(str(m['exact_cost_yuan'])),
    total_quantity=Decimal(str(m['total_quantity'])),departments=m['departments'],
    tier_usage=m['tier_usage'],tier_cost=m['tier_cost'],crossings=m['crossings'],
    created=time.time()))
  # 该月若已无用量则不新建空账，历史版本仍可查看


def process_job(job_id):
 """worker 调用：独立会话处理一个作业，保证 FIFO 与原子切换。"""
 with Session() as db:
  job=db.get(BillingJob,job_id)
  if not job or job.status!='queued':
   return
  # 序号护栏：若已存在比本作业更新的同合同作业，则旧核算不得顶掉新账
  newer=db.query(BillingJob).filter(BillingJob.contract_id==job.contract_id,
   BillingJob.seq>job.seq,BillingJob.status.in_(['queued','running','completed'])).first()
  job.status='running';db.commit()
  try:
   if newer:
    job.status='failed';job.error='已存在更新的重算作业，旧核算按护栏放弃发布'
    db.commit();return
   _publish(db,job)
   job.status='completed';db.commit()
  except Exception as exc:
   db.rollback()
   job=db.get(BillingJob,job_id);job.status='failed';job.error=str(exc);db.commit()
   raise
