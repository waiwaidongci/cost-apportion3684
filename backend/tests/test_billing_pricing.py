"""短时段手算核对：重叠跨档、跨月归费、四舍五入与最大余数守恒。

直接运行：python -m tests.test_billing_pricing
不依赖数据库，仅验证纯计费引擎 src.services.billing_pricing。
"""
from decimal import Decimal
from datetime import datetime,timezone,timedelta
from src.services.billing_pricing import bill_contract,month_key,month_bounds

TZ=timezone(timedelta(hours=8))
def ep(y,m,d,h=0):
 return datetime(y,m,d,h,tzinfo=TZ).timestamp()

TIERS=[{'from':0,'unit_price':10},{'from':100,'unit_price':8},{'from':300,'unit_price':5}]
PASS=0
def check(name,got,expect):
 global PASS
 assert got==expect,f'{name}: 期望 {expect}，实际 {got}'
 PASS+=1;print(f'  ✓ {name} = {got}')

def test_overlap_cross_tier():
 print('用例1 重叠用量共同跨档（2026-01-10 00:00 起 24 小时）')
 t0=ep(2026,1,10)
 # A：24h 用量480，速率20/h；B：前12h 用量120，速率10/h。
 # 合计速率：前12h=30/h，后12h=20/h。
 usages=[
  {'department':'光学部','start_at':t0,'end_at':t0+86400,'quantity':480},
  {'department':'材料部','start_at':t0,'end_at':t0+43200,'quantity':120},
 ]
 res=bill_contract(usages,TIERS)
 check('月份数',res['month_order'],['2026-01'])
 m=res['months']['2026-01']
 # 跨档点：累计100（t0+10/30h）、累计300（前12h累计360，故在段内）
 check('跨档次数',len(m['crossings']),2)
 check('第一跨档累计量',m['crossings'][0]['cumulative_after'],100.0)
 check('第二跨档累计量',m['crossings'][1]['cumulative_after'],300.0)
 # 各档用量：档1=100，档2=200，档3=总600-300=300
 tu={x['unit_price']:x['quantity'] for x in m['tier_usage']}
 check('档1用量',tu[10.0],100.0)
 check('档2用量',tu[8.0],200.0)
 check('档3用量',tu[5.0],300.0)
 # 精确费用 100*10+200*8+300*5=4100
 check('精确费用(元)',m['exact_cost_yuan'],4100.0)
 check('月费(分)',m['total_cents'],410000)
 # 部门拆分：A 全程速率20，B 前12h速率10
 # A = 前12h费用(100*10+200*8+60*5=2900)的2/3 + 后12h(240*5=1200)
 check('光学部分回(分)',{d['department']:d['cents'] for d in m['departments']}['光学部'],313333)
 check('材料部分回(分)',{d['department']:d['cents'] for d in m['departments']}['材料部'],96667)
 check('部门分回守恒',sum(d['cents'] for d in m['departments']),m['total_cents'])

def test_cross_month():
 print('用例2 跨月按发生时间归费（用量持续跨档）')
 # 1/20 00:00 到 2/10 00:00（共21天=504h），用量504，速率1/h
 start=ep(2026,1,20);end=ep(2026,2,10)
 usages=[{'department':'光学部','start_at':start,'end_at':end,'quantity':504}]
 res=bill_contract(usages,TIERS)
 check('归属月份',res['month_order'],['2026-01','2026-02'])
 # 1月：1/20~1/31 共12天=288h→用量288；2月：9天=216h→用量216
 check('1月用量',res['months']['2026-01']['total_quantity'],288.0)
 check('2月用量',res['months']['2026-02']['total_quantity'],216.0)
 # 档1前100单位在1月：1月=档1 100*10 + 档2 188*8 = 2504元
 check('1月费用(分)',res['months']['2026-01']['total_cents'],250400)
 # 2月承接累计288：档2再用12单位到300，其余204单位走档3
 # = 12*8 + 204*5 = 1116元
 check('2月费用(分)',res['months']['2026-02']['total_cents'],111600)
 # 全局跨档点100落在1月、300落在2月
 check('全局跨档次数',len(res['crossings']),2)
 check('1月内跨档点',len(res['months']['2026-01']['crossings']),1)
 check('2月内跨档点',len(res['months']['2026-02']['crossings']),1)

def test_rounding_largest_remainder():
 print('用例3 月费四舍五入 + 最大余数按部门余数分回')
 t0=ep(2026,3,1)
 # 两部门并行1小时，各用量30（合计60，档1单价10）
 usages=[
  {'department':'甲部门','start_at':t0,'end_at':t0+3600,'quantity':30},
  {'department':'乙部门','start_at':t0,'end_at':t0+3600,'quantity':30},
 ]
 res=bill_contract(usages,TIERS)
 m=res['months']['2026-03']
 # 精确费用600元=60000分，每部门精确300元，整除无余数
 check('月费(分)',m['total_cents'],60000)
 check('甲部门(分)',m['departments'][0]['cents'],30000)
 # 构造余数：单价改为0.0333 元/单位，总量10，精确总额0.333元→33分；每部门精确1.665分
 tiers=[{'from':0,'unit_price':0.0333}]
 usages2=[
  {'department':'甲部门','start_at':t0,'end_at':t0+3600,'quantity':5},
  {'department':'乙部门','start_at':t0,'end_at':t0+3600,'quantity':5},
 ]
 r2=bill_contract(usages2,tiers)['months']['2026-03']
 check('总额四舍五入(分)',r2['total_cents'],33)
 check('分回守恒',sum(d['cents'] for d in r2['departments']),33)
 # 两部门精确费用相同(同余数)，按部门名升序决定余数归属
 names=[d['department'] for d in r2['departments']]
 check('同余数按部门名升序',names,['乙部门','甲部门'])
 alloc={d['department']:d['cents'] for d in r2['departments']}
 check('排序靠前者乙得余数分',alloc['乙部门'],17)
 check('甲部门',alloc['甲部门'],16)

def test_no_per_second_expansion():
 print('用例4 十万条用量不逐秒展开（复杂度与正确性抽查）')
 import time
 t0=ep(2026,4,1);n=100000
 usages=[]
 for i in range(n):
  s=t0+i*60
  usages.append({'department':f'部门{i%5}','start_at':s,'end_at':s+120,'quantity':1})
 started=time.time()
 res=bill_contract(usages,TIERS)
 elapsed=time.time()-started
 total_q=sum(m['total_quantity'] for m in res['months'].values())
 check('总用量守恒',round(total_q,6),float(n))
 assert elapsed<20,f'十万条计费耗时 {elapsed:.2f}s 过长'
 print(f'  ✓ 十万条计费耗时 {elapsed:.2f}s（扫描线分段，无逐秒展开）')

if __name__=='__main__':
 test_overlap_cross_tier()
 test_cross_month()
 test_rounding_largest_remainder()
 test_no_per_second_expansion()
 print(f'\n全部 {PASS} 项手算核对通过')
