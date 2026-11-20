from sqlalchemy import Column,Integer,String,JSON,Text,Float,Numeric,Boolean,Index
from src.config.database import Base

class BillingContract(Base):
 __tablename__='billing_contracts'
 id=Column(Integer,primary_key=True)
 natural_key=Column(String(120),unique=True,nullable=False)
 code=Column(String(120),nullable=False)
 version=Column(String(120),nullable=False)
 instrument=Column(String(200),nullable=False)
 unit=Column(String(40),default='次')
 tiers=Column(JSON,nullable=False)
 active=Column(Boolean,default=True)
 created=Column(Float)

class BillingUsage(Base):
 __tablename__='billing_usages'
 id=Column(Integer,primary_key=True)
 natural_key=Column(String(120),unique=True,nullable=False)
 contract_id=Column(Integer,nullable=False,index=True)
 department=Column(String(120),nullable=False,index=True)
 start_at=Column(Float,nullable=False,index=True)
 end_at=Column(Float,nullable=False,index=True)
 quantity=Column(Numeric(30,10),nullable=False)
 backfilled=Column(Boolean,default=False)
 created=Column(Float)

class BillingJob(Base):
 __tablename__='billing_jobs'
 id=Column(Integer,primary_key=True)
 name=Column(String(120))
 trigger=Column(String(20),default='recompute')
 status=Column(String(20),index=True)
 contract_id=Column(Integer,index=True)
 month_from=Column(String(7))
 month_to=Column(String(7))
 months=Column(JSON)
 snapshot=Column(JSON)
 checksum=Column(String(64))
 result=Column(JSON)
 error=Column(Text)
 seq=Column(Integer,index=True)
 created=Column(Float)
 created_by=Column(String(120))

class BillingLedger(Base):
 __tablename__='billing_ledgers'
 id=Column(Integer,primary_key=True)
 contract_id=Column(Integer,nullable=False)
 month=Column(String(7),nullable=False)
 version=Column(Integer,nullable=False,default=1)
 is_current=Column(Boolean,nullable=False,default=True)
 job_id=Column(Integer)
 total_cents=Column(Integer,nullable=False)
 exact_cost=Column(Numeric(30,10),nullable=False)
 total_quantity=Column(Numeric(30,10),nullable=False)
 departments=Column(JSON,nullable=False)
 tier_usage=Column(JSON,nullable=False)
 tier_cost=Column(JSON,nullable=False)
 crossings=Column(JSON,nullable=False)
 created=Column(Float)
 __table_args__=(Index('ix_ledger_contract_month','contract_id','month'),)
