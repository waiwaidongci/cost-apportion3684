from pydantic import BaseModel,Field
class Login(BaseModel): email:str; password:str
class DataInput(BaseModel): data:dict
class RunInput(BaseModel): name:str=Field(min_length=2,max_length=120); policy_id:int; period:str='全部'
class ReviewInput(BaseModel): note:str=Field(min_length=4,max_length=2000)
class ScheduleInput(BaseModel): name:str=Field(min_length=2,max_length=120); run_id:int; interval_seconds:int=Field(ge=5,le=86400)
class ContractInput(BaseModel):
 code:str=Field(min_length=1,max_length=120); version:str=Field(min_length=1,max_length=120)
 instrument:str=Field(min_length=1,max_length=120); unit:str=Field(default='次',max_length=40)
 tiers:list=Field(min_length=1)
class UsageInput(BaseModel):
 contract_id:int; department:str=Field(min_length=1,max_length=120)
 start_at:float; end_at:float; quantity:float=Field(gt=0); backfilled:bool=False
class RecomputeInput(BaseModel):
 contract_id:int; start_at:float; end_at:float
 name:str=Field(default='',max_length=120); trigger:str=Field(default='recompute',max_length=20)
class PreviewInput(BaseModel): tiers:list=Field(min_length=1); usages:list=Field(min_length=1)
