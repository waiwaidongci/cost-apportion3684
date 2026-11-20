"""共用仪器阶梯计费引擎。

口径要点：
- 用量在 [start, end) 内均匀发生，速率 = quantity / (end-start)。
- 重叠用量的速率相加，共同推动合同累计用量跨档（边际阶梯价）。
- 分段点 = 各用量起止点 ∪ 跨档点 ∪ 跨月边界，绝不逐秒展开，复杂度近线性。
- 跨月段按月边界切开，费用按发生时间归到对应月份。
- 每月精确费用四舍五入到分，再按部门精确费用的余数用最大余数法分回，
  余数相同按部门名升序。
全部金额用 Decimal 精确计算，避免浮点误差。
"""
from decimal import Decimal,ROUND_HALF_UP,getcontext
from datetime import datetime,timezone,timedelta
getcontext().prec=60

D=Decimal
ZERO=D('0')
QZERO=D('0.0000000000')
CENT=D('0.01')


def _d(value):
 return D(str(value))


def validate_tiers(tiers):
 """阶梯：[{from: 含下限, unit_price: 单价(元/单位)}]，from 升序且首档为0。"""
 if not isinstance(tiers,list) or not tiers:
  raise ValueError('阶梯价至少需要一档')
 normalized=[]
 last_from=None
 for i,t in enumerate(tiers):
  if not isinstance(t,dict) or 'from' not in t or 'unit_price' not in t:
   raise ValueError('阶梯必须包含 from 与 unit_price')
  frm=_d(t['from']);price=_d(t['unit_price'])
  if frm<0 or price<0:
   raise ValueError('阶梯下限与单价不能为负')
  if i==0 and frm!=0:
   raise ValueError('首档下限必须为0')
  if last_from is not None and frm<=last_from:
   raise ValueError('阶梯下限必须严格递增')
  normalized.append({'from':frm,'unit_price':price})
  last_from=frm
 return normalized


def validate_usage_record(u):
 if not isinstance(u,dict):
  raise ValueError('用量记录必须是对象')
 if 'start' in u and 'end' in u:
  # 已校验并转换过的记录，原样返回
  return u
 for key in ('department','start_at','end_at','quantity'):
  if key not in u:
   raise ValueError('用量缺少字段 '+key)
 if not isinstance(u['department'],str) or not u['department'].strip():
  raise ValueError('部门名不合法')
 start=_d(u['start_at']);end=_d(u['end_at']);qty=_d(u['quantity'])
 if end<=start:
  raise ValueError('用量结束时刻必须晚于开始时刻')
 if qty<=0:
  raise ValueError('用量必须为正数')
 return {'department':u['department'].strip(),'start':start,'end':end,'quantity':qty}


def month_key(epoch):
 """Asia/Shanghai (UTC+8) 固定时区下的归属月份 YYYY-MM。"""
 dt=datetime.fromtimestamp(float(epoch),tz=timezone(timedelta(hours=8)))
 return f'{dt.year:04d}-{dt.month:02d}'


def month_bounds(key):
 """返回该月（UTC+8）起止的 epoch 秒。"""
 y,m=map(int,key.split('-'))
 tz=timezone(timedelta(hours=8))
 start=datetime(y,m,1,tzinfo=tz)
 if m==12:
  end=datetime(y+1,1,1,tzinfo=tz)
 else:
  end=datetime(y,m+1,1,tzinfo=tz)
 return start.timestamp(),end.timestamp()


def add_months(key,delta):
 y,m=map(int,key.split('-'))
 total=(y*12+(m-1))+delta
 return f'{total//12:04d}-{total%12+1:02d}'


def _tier_price(tiers,cumulative):
 price=tiers[0]['unit_price']
 for t in tiers:
  if cumulative>=t['from']:
   price=t['unit_price']
  else:
   break
 return price


def _format_q(x):
 return float(x.quantize(QZERO))


def bill_contract(usages,tiers):
 """对单个合同的全部用量做连续时段计费。

 返回 {months: {月份: {total_quantity, exact_cost, total_cents,
     departments: {部门: {exact_cost, cents}}, tier_usage, tier_cost,
     crossings}}, crossings: 全局跨档明细, month_order: [...]}
 """
 tiers=validate_tiers(tiers)
 records=[validate_usage_record(u) for u in usages]
 if not records:
  return {'months':{},'crossings':[],'month_order':[]}

 # 1) 事件扫描线求速率分段（起止点），维护各部门当前速率，O(n log n)。
 events=[]
 for r in records:
  rate=r['quantity']/(r['end']-r['start'])
  events.append((r['start'],1,r['department'],rate))
  events.append((r['end'],-1,r['department'],rate))
 events.sort(key=lambda e:e[0])
 segments=[]
 dept_rate={};total_rate=ZERO;cursor=events[0][0];i=0
 while i<len(events):
  t=events[i][0]
  if t>cursor and total_rate>0:
   segments.append({'start':cursor,'end':t,'rate':total_rate,
                    'dept_rate':dict(dept_rate)})
  while i<len(events) and events[i][0]==t:
   _,sign,dept,rate=events[i]
   dept_rate[dept]=dept_rate.get(dept,ZERO)+(rate if sign==1 else -rate)
   if dept_rate[dept]==0:
    del dept_rate[dept]
   total_rate+=(rate if sign==1 else -rate)
   i+=1
  cursor=t

 # 2) 按累计用量找跨档点，把分段切成不跨档的小段。
 cumulative=ZERO
 pieces=[]
 crossings=[]
 for seg in segments:
  cur_start=seg['start'];remain=seg['rate']*(seg['end']-seg['start'])
  while remain>0:
   price=_tier_price(tiers,cumulative)
   next_tier=None
   for t in tiers:
    if t['from']>cumulative:
     next_tier=t
     break
   if next_tier is None:
    cap=None
   else:
    cap=next_tier['from']-cumulative
   if cap is None or remain<=cap:
    q=remain
    pieces.append({'start':cur_start,'end':cur_start+remain/seg['rate'],'quantity':q,
                   'rate':seg['rate'],'dept_rate':seg['dept_rate'],'unit_price':price})
    cumulative+=q
    remain=ZERO
   else:
    span=cap/seg['rate']
    pieces.append({'start':cur_start,'end':cur_start+span,'quantity':cap,
                   'rate':seg['rate'],'dept_rate':seg['dept_rate'],'unit_price':price})
    crossings.append({'at_epoch':float(cur_start+span),'cumulative_after':_format_q(cumulative+cap),
                       'from_tier_price':float(price),'to_tier_price':float(next_tier['unit_price'])})
    cumulative+=cap
    remain-=cap
    cur_start+=span

 # 3) 按跨月边界再切，归到月份；同时按部门速率比例拆分每段精确费用。
 months={}
 def charge(cur_mk,seg_start,seg_end):
  duration=seg_end-seg_start
  if duration<=0:
   return
  q=p['rate']*duration
  cost=q*p['unit_price']
  bucket=months.setdefault(cur_mk,{'total_quantity':ZERO,'exact_cost':ZERO,
      'dept_cost':{},'tier_quantity':{},'tier_cost':{},'crossings':[]})
  bucket['total_quantity']+=q
  bucket['exact_cost']+=cost
  key=float(p['unit_price'])
  bucket['tier_quantity'][key]=bucket['tier_quantity'].get(key,ZERO)+q
  bucket['tier_cost'][key]=bucket['tier_cost'].get(key,ZERO)+cost
  for dept,rate in p['dept_rate'].items():
   bucket['dept_cost'][dept]=bucket['dept_cost'].get(dept,ZERO)+cost*(rate/p['rate'])

 for p in pieces:
  sub_start=p['start'];sub_end=p['end']
  while True:
   cur_mk=month_key(sub_start)
   _,mb_end=month_bounds(cur_mk)
   cut=min(sub_end,_d(str(mb_end)))
   charge(cur_mk,sub_start,cut)
   sub_start=cut
   if cut>=sub_end:
    break

 # 4) 把跨档点归到发生月份。
 for cr in crossings:
  mk=month_key(_d(str(cr['at_epoch'])))
  if mk in months:
   months[mk]['crossings'].append(cr)

 # 5) 月费四舍五入到分；部门按精确费用余数最大余数法分回，同余数按部门名。
 result={}
 for mk,bucket in months.items():
  total_cents=int((bucket['exact_cost']/CENT).to_integral_value(rounding=ROUND_HALF_UP))
  raw={dept:cost for dept,cost in bucket['dept_cost'].items()}
  # 以月费总额为守恒目标做最大余数分配，保证部门分回之和等于月费（分）。
  floor={dept:int((cost/CENT).to_integral_value(rounding='ROUND_FLOOR')) for dept,cost in raw.items()}
  remainder=total_cents-sum(floor.values())
  order=sorted(raw,key=lambda d:(-(raw[d]/CENT-floor[d]),d))
  alloc=dict(floor)
  for dept in order[:max(0,remainder)]:
   alloc[dept]+=1
  assert sum(alloc.values())==total_cents,(sum(alloc.values()),total_cents)
  tier_usage=[{'unit_price':k,'quantity':_format_q(v)} for k,v in sorted(bucket['tier_quantity'].items())]
  tier_cost=[{'unit_price':k,'cost_yuan':float(v.quantize(CENT,rounding=ROUND_HALF_UP))}
             for k,v in sorted(bucket['tier_cost'].items())]
  result[mk]={'total_quantity':_format_q(bucket['total_quantity']),
   'exact_cost_yuan':float(bucket['exact_cost'].quantize(CENT,rounding=ROUND_HALF_UP)),
   'total_cents':total_cents,
   'departments':[{'department':d,'exact_cost_yuan':float(raw[d].quantize(CENT,rounding=ROUND_HALF_UP)),
                   'cents':alloc[d]} for d in sorted(alloc)],
   'tier_usage':tier_usage,'tier_cost':tier_cost,
   'crossings':sorted(bucket['crossings'],key=lambda x:x['at_epoch'])}
 return {'months':result,'crossings':crossings,'month_order':sorted(result)}
