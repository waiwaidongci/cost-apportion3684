"""端到端集成测试（SQLite + 假Redis），覆盖补录重算、FIFO、并发护栏与原子台账。

运行：python -m tests.test_billing_flow
"""
import sys,types,time
from decimal import Decimal
from datetime import datetime,timezone,timedelta

# ---- 在导入应用代码前注入环境与假 redis ----
import sys,types
# settings 模块在容器内读取 /app/project.json，本地测试预置等价对象
sys.modules['src.config.settings']=types.SimpleNamespace(
 CONFIG={'title':'计费测试'},DATABASE_URL='sqlite:///:memory:',
 REDIS_URL='memory',SECRET='test-secret')
from src.config import database as db_mod
class FakeRedis:
 def __init__(self): self.q=[]
 def rpush(self,k,v): self.q.append(int(v))
 def lpop(self,k): return str(self.q.pop(0)).encode() if self.q else None
 def ping(self): return True
fake=FakeRedis()
sys.modules.setdefault('redis',types.SimpleNamespace(Redis=types.SimpleNamespace(
 from_url=lambda *a,**k:fake)))

import sqlalchemy
db_mod.engine=sqlalchemy.create_engine('sqlite:///:memory:')
db_mod.Session=sqlalchemy.orm.sessionmaker(bind=db_mod.engine,expire_on_commit=False)
import src.config.settings as settings
# SQLite 不支持 SELECT ... FOR UPDATE，测试中降级为空操作
from sqlalchemy.orm import Query
if not hasattr(Query,'_orig_with_for_update'):
 Query._orig_with_for_update=Query.with_for_update
 Query.with_for_update=lambda self,*a,**k:self

from src.config.database import Base,engine,Session
import src.models.billing  # noqa
from src.models.billing import BillingContract,BillingUsage,BillingJob,BillingLedger
from src.models.identity import User
from src.services import billing as svc
from src.services.billing_pricing import month_key
Base.metadata.create_all(engine)

TZ=timezone(timedelta(hours=8))
def ep(y,m,d,h=0): return datetime(y,m,d,h,tzinfo=TZ).timestamp()
class Who:
 def __init__(s,e): s.email=e
admin=Who('admin@demo.local')
TIERS=[{'from':0,'unit_price':10},{'from':100,'unit_price':8},{'from':300,'unit_price':5}]

def drain():
 while fake.q:
  jid=fake.lpop('billing-jobs').decode()
  svc.process_job(int(jid))

with Session() as db:
 c=svc.save_contract(db,admin,{'code':'INS-01','version':'v1','instrument':'光谱仪',
   'unit':'次','tiers':TIERS})
 cid=c.id
 # 初始用量：1月10日全天，甲部门480单位（速率20/h）
 u1,_=svc.save_usage(db,admin,{'contract_id':cid,'department':'甲部门',
   'start_at':ep(2026,1,10),'end_at':ep(2026,1,11),'quantity':480})
 svc.enqueue_recompute(db,admin,cid,ep(2026,1,10),ep(2026,1,11))
 drain()
 led=db.query(BillingLedger).filter_by(contract_id=cid,is_current=True).all()
 assert len(led)==1 and led[0].month=='2026-01'
 v1_total=led[0].total_cents
 # 480单位：100*10+200*8+180*5=3500元
 assert v1_total==350000,v1_total
 print(f'✓ 初始核算 1月费用 {v1_total} 分（台账 v{led[0].version}）')

 # 模拟并发补录：连续插入两条补录（旧区间1月、新区间1月），作业按seq排队
 u2,_=svc.save_usage(db,admin,{'contract_id':cid,'department':'乙部门',
   'start_at':ep(2026,1,10),'end_at':ep(2026,1,10)+43200,'quantity':120},backfilled=True)
 svc.enqueue_recompute(db,admin,cid,ep(2026,1,10),ep(2026,1,10)+43200,trigger='backfill')
 u3,_=svc.save_usage(db,admin,{'contract_id':cid,'department':'丙部门',
   'start_at':ep(2026,1,12),'end_at':ep(2026,1,13),'quantity':60},backfilled=True)
 svc.enqueue_recompute(db,admin,cid,ep(2026,1,12),ep(2026,1,13),trigger='backfill')
 jobs=db.query(BillingJob).order_by(BillingJob.seq).all()
 assert [j.seq for j in jobs]==[1,2,3],[j.seq for j in jobs]
 queued=[j for j in jobs if j.seq>=2]
 assert all(j.status=='queued' for j in queued)
 print(f'✓ 补录排队 FIFO，作业序号 {[j.seq for j in jobs]}')

 # 处理最早作业（seq=1）：存在更新作业，护栏应放弃发布
 svc.process_job(jobs[1].id)
 db.expire_all()
 j1=db.get(BillingJob,jobs[1].id)
 assert j1.status=='failed' and '护栏' in j1.error
 cur=db.query(BillingLedger).filter_by(contract_id=cid,month='2026-01',is_current=True).one()
 assert cur.total_cents==v1_total, '旧核算不得顶掉新账'
 print('✓ 并发护栏：旧补录作业被放弃，现行台账未被覆盖')

 # 依次处理剩余作业
 drain()
 db.expire_all()
 done=db.query(BillingJob).filter_by(status='completed').count()
 assert done==2,done
 cur=db.query(BillingLedger).filter_by(contract_id=cid,month='2026-01',is_current=True).one()
 # 1月总量 480+120+60=660：100*10+200*8+360*5=4400元
 assert cur.total_cents==440000,cur.total_cents
 assert cur.version==2
 # 三部门分回守恒
 assert sum(d['cents'] for d in cur.departments)==440000
 assert {d['department'] for d in cur.departments}=={'甲部门','乙部门','丙部门'}
 print(f'✓ 补录后重算 1月费用 {cur.total_cents} 分（台账 v{cur.version}），三部门守恒')

 # 旧版本台账仍可查看（旧报告照常查看）
 old=db.query(BillingLedger).filter_by(contract_id=cid,month='2026-01',
      is_current=False).order_by(BillingLedger.version).all()
 assert old and old[0].total_cents==350000
 assert len(old[0].crossings)>=1, '跨档依据随版本保留'
 print(f'✓ 历史版本保留可查：v{old[0].version}={old[0].total_cents} 分，跨档点 {len(old[0].crossings)} 个')

 # 原子切换：不存在同合同同月两条 current
 dup=db.query(BillingLedger).filter_by(contract_id=cid,month='2026-01',
     is_current=True).count()
 assert dup==1
 print('✓ 各月费用原子切换：每月仅一条现行版本')

 # 跨月补录：2月用量，产生新月台账
 svc.save_usage(db,admin,{'contract_id':cid,'department':'甲部门',
   'start_at':ep(2026,2,5),'end_at':ep(2026,2,6),'quantity':100},backfilled=True)
 svc.enqueue_recompute(db,admin,cid,ep(2026,2,5),ep(2026,2,6),trigger='backfill')
 drain();db.expire_all()
 feb=db.query(BillingLedger).filter_by(contract_id=cid,month='2026-02',is_current=True).one()
 # 2月承接1月累计660（已在档3），100单位全部档3单价5 = 500元
 assert feb.total_cents==50000,feb.total_cents
 print(f'✓ 跨月归费：2月台账 {feb.total_cents} 分（承接累计量继续走档3）')

 # 作业快照与校验和不可变
 snap_job=db.get(BillingJob,cur.job_id)
 assert len(snap_job.snapshot['usages'])==3 and len(snap_job.checksum)==64
 print('✓ 作业冻结用量快照与 SHA256 校验和')

print('\n全部端到端流程核对通过')
