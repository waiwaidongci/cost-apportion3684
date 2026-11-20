"""共用仪器阶梯计费演示数据：自然键幂等，不覆盖用户修改。

含重叠用量（共同跨档）、跨月用量（按发生时间归费）与一条补录记录，
入队后由 worker 重算出版本化台账。
"""
import json
from datetime import datetime,timezone,timedelta
from src.config.database import Base,engine,Session
from src.models.billing import BillingContract,BillingUsage
from src.services import billing as svc

TZ=timezone(timedelta(hours=8))
def ep(y,m,d,h=0):
 return datetime(y,m,d,h,tzinfo=TZ).timestamp()

DEMO_TIERS=[{'from':0,'unit_price':10},{'from':100,'unit_price':8},{'from':300,'unit_price':5}]
DEMO_USAGES=[
 # 重叠：两部门 1/10 当天并行，速率叠加共同跨档
 ('demo-use-1','光学研究',ep(2026,1,10),ep(2026,1,11),480,False),
 ('demo-use-2','材料研究',ep(2026,1,10),ep(2026,1,10)+43200,120,False),
 # 跨月：1/31 12:00 至 2/1 12:00，按月边界切开归费
 ('demo-use-3','工艺研究',ep(2026,1,31,12),ep(2026,2,1,12),240,False),
 # 补录旧用量
 ('demo-use-4','光学研究',ep(2026,1,5),ep(2026,1,6),60,True),
]

class _Actor:
 email='seed@demo.local'

def seed_billing():
 Base.metadata.create_all(engine)
 with Session() as db:
  contract=db.query(BillingContract).filter_by(code='INS-DEMO',version='v1').first()
  if not contract:
   contract=svc.save_contract(db,_Actor(),{'code':'INS-DEMO','version':'v1',
    'instrument':'共用高分辨光谱仪','unit':'次','tiers':DEMO_TIERS})
  cid=contract.id
  lo=min(u[2] for u in DEMO_USAGES);hi=max(u[3] for u in DEMO_USAGES)
  created=False
  for key,dept,s,e,qty,backfill in DEMO_USAGES:
   if not db.query(BillingUsage).filter_by(natural_key=key).first():
    obj,_=svc.save_usage(db,_Actor(),{'contract_id':cid,'department':dept,
      'start_at':s,'end_at':e,'quantity':qty},backfilled=backfill)
    obj.natural_key=key;created=True
  # 仅在首次写入演示用量后排队一次全量重算，重复执行幂等不重复入队
  if created:
   svc.enqueue_recompute(db,_Actor(),cid,lo,hi,name='演示数据初始化重算',trigger='seed')
  db.commit()
  print(json.dumps({'billing_contracts':db.query(BillingContract).count(),
   'billing_usages':db.query(BillingUsage).count()},ensure_ascii=False))

if __name__=='__main__':
 seed_billing()
