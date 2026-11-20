import time,json,traceback
from pathlib import Path
import redis
from src.config.database import Base,engine,Session
from src.config.settings import REDIS_URL
from src.models import identity,source,run,billing
from src.models.run import Run
from src.services.calculation import calculate
from src.services.delivery import tick
from src.services.billing import process_job
Base.metadata.create_all(engine)
r=redis.Redis.from_url(REDIS_URL)
while True:
 Path('/tmp/worker-heartbeat').write_text(str(time.time()))
 try:
  item=r.lpop('report-jobs')
  if item:
   with Session() as db:
    job=db.get(Run,int(item))
    if job and job.status=='queued':
     job.status='running';db.commit()
     try: job.result=calculate(job.snapshot['sources'],job.snapshot['policy']);job.status='completed'
     except Exception as exc: job.status='failed';job.error=str(exc);traceback.print_exc()
     db.commit()
  # 共用仪器阶梯计费作业：FIFO 串行，单作业内各月费用原子切换
  bitem=r.lpop('billing-jobs')
  if bitem:
   try: process_job(int(bitem))
   except Exception: traceback.print_exc()
  with Session() as db: tick(db)
 except Exception: traceback.print_exc()
 time.sleep(1)
