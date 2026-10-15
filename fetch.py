# -*- coding: utf-8 -*-
"""
外盘涨跌统计 · 云端抓取脚本（GitHub Actions 版 v1.3）
======================================================
v1.3 更新（2026-10-15）：
  - 美股指数（标普/道指/纳指）口径修正为"最近一个收盘价 vs 更早一个收盘价"
    （两个收盘价相差 1 个交易日，如 10-14 收 vs 10-13 收），不再用当日开盘价做基准；
    "收盘价"列=更早一个收盘价，"最新价"列=最近一个收盘价。与行情站常见口径一致。
  - 移除 富时A50：该品种仅东财有源（现被限流），新浪/腾讯/雪球等均无覆盖，
    按用户指示删除（页面 25 个品种全部不依赖东财，稳定性拉满）。
  - 美股指数不再使用 ES/YM/NQ 期货快照（sina_code 已清零），日K 接口失败时显示"缺"。

v1.2 更新（2026-10-15）：
  - 修复"星号（※）大偏差"根因：参考价（新浪）与现价（东财）跨源混用，
    两源的连续/主力合约选择不一致（天然气差 18%、豆粉差 5%，已用腾讯源交叉验证）。
    现改为：现价也优先新浪快照（与参考价同源），东财仅作兜底；两源差 >0.5% 仍标 ※。
  - 美股指数（标普/道指/纳指）改为"最近一根已收盘日线"口径：
    展示该日线的 开盘价→收盘价 对比涨跌，全天不随盘中波动
    （如美东 10-14 日线：北京 10-14 晚开盘 → 10-15 早收盘，收盘后即定格）。
    "收盘价"列=该日线开盘价（对比基准），"最新价"列=该日线收盘价，
    时间区间列标注如 "10-14美"。数据源：新浪美股日K（.INX/.DJI/.IXIC）。
  - 富时A50 维持原逻辑（新浪无此品种数据源，仅东财有）。

v1.1 更新（2026-10-15）：
  - 新增新浪"当日分时"数据源（GlobalFuturesService.getGlobalFuturesMinLine）
    作为参考价主源。原因：东财 K 线接口对云端（尤其 GitHub 海外 IP）限流严重，
    实测一轮 24 个品种只成功 3 个；新浪分时实测覆盖 23/24 个品种，
    且与新浪快照价格口径完全一致（同一数据体系）。
  - 参考价优先级：新浪分时（主）→ 东财 K 线（兜底）。
  - 当前价优先级：东财快照 → 新浪快照 → 新浪分时末根（新增第三兜底）。
  - 美铜（hf_HG）新浪分时价格需美分→美元换算（与快照换算保持同口径）。
  - 伦铅接入新浪源（symbol=PBD）；美原糖加日K 昨收兜底（15:30 开盘后旧时段数据被顶掉）。

v1.0（2026-10-14）：
  从本机版 v1.7 移植核心逻辑：时间统一 UTC+8；结果直接写 data.json；
  不做轮内重试补拉，每轮由 Actions 定时重跑，失败品种下一轮自动补。
"""
import os, sys, json, time, re, random
import urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

# ---------------- 北京时间（服务器是 UTC，必须显式换算） ----------------
CN_TZ = timezone(timedelta(hours=8))
def now_cn():
    return datetime.now(CN_TZ).replace(tzinfo=None)

# ---------------- 品种表（与 v1.7 完全一致，用户手排顺序勿动） ----------------
VARIETIES = [
    ('WTI原油(23:00)',    'M23',   '102.CL00Y',  'hf_CL'),
    ('WTI原油(02:30)',    'M0230', '102.CL00Y',  'hf_CL'),
    ('布伦特原油(23:00)',  'M23',   '112.B00Y',   'hf_OIL'),
    ('布伦特原油(02:30)',  'M0230', '112.B00Y',   'hf_OIL'),
    ('美黄金',       'M0230', '101.GC00Y',  'hf_GC'),
    ('美白银',       'M0230', '101.SI00Y',  'hf_SI'),
    ('伦敦银现货',    'M0230', None,         'hf_XAG'),
    ('伦铝',        'M01',   '109.LALT',   'hf_AHD'),
    ('伦锌',        'M01',   '109.LZNT',   'hf_ZSD'),
    ('伦镍',        'M01',   '109.LNKT',   'hf_NID'),
    ('伦锡',        'M01',   '109.LTNT',   'hf_SND'),
    ('美铜',        'M01',   '101.HG00Y',  'hf_HG'),
    ('伦铜',        'M01',   '109.LCPT',   'hf_CAD'),
    ('伦铅',        'M01',   '109.LLDT',   'hf_PBD'),  # v1.1: 新浪伦铅代码 PBD
    ('美燃油',       'M23',   '102.HO00Y',  'hf_HO'),
    ('美国天然气',    'M23',   '102.NG00Y',  'hf_NG'),
    ('美大豆',       'M23',   '103.ZS00Y',  'hf_S'),
    ('美黄豆粉',     'M23',   '103.ZM00Y',  'hf_SM'),
    ('美黄豆油',     'M23',   '103.ZL00Y',  'hf_BO'),
    ('美原糖',       'M23',   '108.SB00Y',  'hf_RS'),
    ('美国棉花',     'M23',   '108.CT00Y',  'hf_CT'),
    ('马棕油',       'M23',   '110.MPM00Y', 'hf_FCPO'),
    ('新加坡铁矿石',  'M23',   None,         'hf_FEF'),
    ('日橡胶',       'M23',   '111.JRU00Y', 'hf_RSS3'),
    ('标准普尔',     'M23',   '100.SPX',    None),   # v1.3: 走美股日K口径
    ('道琼工业',     'M23',   '100.DJIA',   None),   # v1.3: 走美股日K口径
    ('纳斯达克',     'M23',   '100.NDX',    None),   # v1.3: 走美股日K口径
]
GROUP_CLOSE = {'M23': (23, 0), 'M01': (1, 0), 'M0230': (2, 30)}
GROUPS = ['M23', 'M01', 'M0230']
INDEX_SECIDS = {'100.SPX', '100.DJIA', '100.NDX'}
# v1.2: 美股指数 → 新浪美股日K symbol（展示"最近一根已收盘日线"的开盘→收盘）
US_INDEX_MAP = {'100.SPX': '.INX', '100.DJIA': '.DJI', '100.NDX': '.IXIC'}

# ---------------- HTTP ----------------
SINA_HEADERS = {'Referer': 'https://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
EM_HEADERS = {'Referer': 'https://quote.eastmoney.com',
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def http_get(url, headers, enc='utf-8', timeout=15):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(enc, errors='replace')

def em_get(url, timeout=15):
    """东财请求：云端串行 + 1.5s 间隔 + 抖动，尽量温和"""
    time.sleep(1.5 + random.uniform(0, 0.6))
    return http_get(url, EM_HEADERS, timeout=timeout)

def em_get_retry(url, tries=2):
    last = None
    for i in range(tries):
        try:
            return em_get(url)
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(6)
    raise last

# ---------------- 快照（当前价） ----------------
def em_snapshot(secids):
    out = {}
    u = ('https://push2.eastmoney.com/api/qt/ulist.np/get?secids=' + ','.join(secids)
         + '&fields=f2,f12,f14,f18&fltt=2')
    d = json.loads(em_get_retry(u))
    for r in (d.get('data') or {}).get('diff') or []:
        code, last, prev = r.get('f12'), r.get('f2'), r.get('f18')
        out[code] = {
            'last': float(last) if isinstance(last, (int, float)) else None,
            'prev_settle': float(prev) if isinstance(prev, (int, float)) else None,
        }
    return out

SINA_CENT_TO_DOLLAR = {'hf_HG'}   # 新浪美铜是美分/磅，东财是美元/磅

def sina_snapshot(codes):
    out = {}
    if not codes:
        return out
    u = 'https://hq.sinajs.cn/list=' + ','.join(codes)
    txt = http_get(u, SINA_HEADERS, enc='gbk')
    for line in txt.strip().split('\n'):
        m = re.search(r'hq_str_(\w+)="([^"]*)"', line)
        if not m:
            continue
        code, body = m.group(1), m.group(2)
        f = body.split(',')
        if len(f) > 13 and f[0]:
            try:
                prev = float(f[7]) if f[7] else None
            except ValueError:
                prev = None
            last = float(f[0])
            if code in SINA_CENT_TO_DOLLAR:
                last /= 100.0
                if prev is not None:
                    prev /= 100.0
            out[code] = {'last': last, 'prev_settle': prev,
                         'time': f[6], 'date': f[12]}
    return out

# ---------------- K线（参考价，东财兜底通道） ----------------
def em_kline5(secid):
    """东财5分钟K（最近约7天）→ [(datetime, close)]，北京时间"""
    u = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=' + secid
         + '&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=5&fqt=0'
           '&beg=0&end=20500101&lmt=300')
    d = json.loads(em_get_retry(u, tries=1))   # 不重试：本轮失败下一轮定时补
    out = []
    for k in (d.get('data') or {}).get('klines') or []:
        p = k.split(',')
        try:
            out.append((datetime.strptime(p[0], '%Y-%m-%d %H:%M'), float(p[2])))
        except (ValueError, IndexError):
            continue
    return out

def sina_5day_minline(symbol):
    u = ('https://stock2.finance.sina.com.cn/futures/api/openapi.php/'
         'GlobalFuturesService.getGlobalFutures5MLine?symbol=' + symbol)
    txt = http_get(u, SINA_HEADERS)
    obj = None
    s = txt.lstrip()
    if s.startswith('{'):
        obj = json.loads(s)
    else:
        m = re.search(r'\((\{.*\})\)', txt, re.S)
        if m:
            obj = json.loads(m.group(1))
    data = ((obj or {}).get('result') or {}).get('data') or {}
    days = data.get(symbol) if isinstance(data, dict) else None
    out = []
    if not isinstance(days, list):
        return out
    for day in days:
        if not isinstance(day, list) or not day:
            continue
        try:
            base = datetime.strptime(day[0][0], '%Y-%m-%d')
        except (ValueError, IndexError, TypeError):
            continue
        cur_date, prev_t = base, None
        for i, e in enumerate(day):
            if i == 0:
                tstr = price = None
                for j, f in enumerate(e):
                    if re.match(r'^\d{2}:\d{2}$', str(f)):
                        tstr = f
                        price = e[j + 1] if j + 1 < len(e) else None
                        break
                if tstr is None or price is None:
                    continue
            elif len(e) >= 2:
                tstr, price = e[0], e[1]
            else:
                continue
            try:
                hh, mm = int(tstr[:2]), int(tstr[3:5])
                p = float(price)
            except (ValueError, IndexError):
                continue
            if prev_t and tstr < prev_t:
                cur_date = cur_date + timedelta(days=1)
            prev_t = tstr
            out.append((cur_date.replace(hour=hh, minute=mm), p))
    out.sort(key=lambda x: x[0])
    return out

def sina_minline_today(symbol):
    """新浪"当日分时"（当前交易时段，含时间戳）→ [(datetime, price)]，北京时间。
    v1.1：这是参考价主源。该接口覆盖全部外盘品种（除伦铅），
    与新浪 hf_ 快照同数据体系，价格口径一致。"""
    u = ('https://stock2.finance.sina.com.cn/futures/api/openapi.php/'
         'GlobalFuturesService.getGlobalFuturesMinLine?symbol=' + symbol
         + '&callback=var%20d=')
    txt = http_get(u, SINA_HEADERS)
    m = re.search(r'\((\{.*\})\)', txt, re.S)
    if not m:
        return []
    obj = json.loads(m.group(1))
    data = (obj.get('result') or {}).get('data') or {}
    arr = data.get('minLine_1d') if isinstance(data, dict) else None
    out = []
    if not isinstance(arr, list) or not arr:
        return out
    day = arr[0][0] if isinstance(arr[0], list) and len(arr[0]) >= 10 else None
    for i, e in enumerate(arr):
        if not isinstance(e, list) or len(e) < 2:
            continue
        pidx = 5 if (i == 0 and len(e) >= 6) else 1
        try:
            p = float(e[pidx])
        except (ValueError, IndexError):
            continue
        ts = e[-1] if isinstance(e[-1], str) and re.match(r'^\d{4}-\d{2}-\d{2} ', e[-1]) else None
        if ts:
            out.append((datetime.strptime(ts[:16], '%Y-%m-%d %H:%M'), p))
        elif day and re.match(r'^\d{2}:\d{2}$', str(e[0])):
            hh, mm = int(e[0][:2]), int(e[0][3:5])
            out.append((datetime.strptime(day, '%Y-%m-%d').replace(hour=hh, minute=mm), p))
    out.sort(key=lambda x: x[0])
    return out

def sina_fef_dailyk():
    u = ('https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20d=/'
         'GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=FEF')
    txt = http_get(u, SINA_HEADERS)
    m = re.search(r'\((\[.*\])\)', txt, re.S)
    return json.loads(m.group(1)) if m else []

def sina_dailyk_last_close(symbol):
    """v1.1: 新浪日K最后一根收盘价（美原糖"开盘点效应"兜底用）"""
    u = ('https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20d=/'
         f'GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={symbol}')
    txt = http_get(u, SINA_HEADERS)
    m = re.search(r'\((\[.*\])\)', txt, re.S)
    if not m:
        return None
    arr = json.loads(m.group(1))
    if not arr:
        return None
    try:
        return float(arr[-1]['close'])
    except (ValueError, KeyError, TypeError):
        return None

def us_index_daily_bars(symbol, now, n=2):
    """v1.3: 取最近 n 根【已收盘】美股指数日线 → [(日期str, 收盘价), ...]（时间升序，新的在后）。
    已收盘判据：日线日期(美东)的次日北京 05:30 之后（覆盖夏/冬令时收盘时间差）。"""
    u = ('https://stock2.finance.sina.com.cn/usstock/api/jsonp.php/var%20d=/'
         f'US_MinKService.getDailyK?symbol={symbol}')
    txt = http_get(u, SINA_HEADERS)
    m = re.search(r'\((\[.*\])\)', txt, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(1))
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out = []
    for k in reversed(arr):
        try:
            d = datetime.strptime(k['d'], '%Y-%m-%d')
            c = float(k['c'])
        except (ValueError, KeyError, TypeError):
            continue
        if now >= d + timedelta(days=1, hours=5, minutes=30):
            out.append((k['d'], c))
            if len(out) >= n:
                break
    out.reverse()
    return out

def fef_ref_from_dailyk(ref_dt):
    dk = sina_fef_dailyk()
    if not dk or ref_dt is None:
        return None, None
    prev_end = None
    for k in dk:
        d = datetime.strptime(k['date'], '%Y-%m-%d')
        end = d.replace(hour=20)
        start = prev_end if prev_end is not None else d - timedelta(days=1)
        if start <= ref_dt < end:
            try:
                return float(k['open']), start
            except (ValueError, KeyError, TypeError):
                return None, None
        prev_end = end
    return None, None

def get_night_calendar():
    u = ('https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20t=/'
         'InnerFuturesNewService.getFewMinLine?symbol=CU0&type=5')
    txt = http_get(u, SINA_HEADERS, enc='gbk')
    m = re.search(r'\((\[.*\])\)', txt, re.S)
    if not m:
        return set(), set()
    arr = json.loads(m.group(1))
    trade_days, night_days = set(), set()
    for e in arr:
        t = e.get('d', '') if isinstance(e, dict) else ''
        if len(t) < 16:
            continue
        day, hm = t[:10], t[11:16]
        if '09:00' <= hm <= '15:05':
            trade_days.add(day)
        if hm >= '21:00':
            night_days.add(day)
    return trade_days, night_days

# ---------------- 参考时点判定（与 v1.7 一致） ----------------
def decide_mode(now, trade_days):
    today = now.date().isoformat()
    t = now.hour * 60 + now.minute
    if trade_days:
        return 'day' if (today in trade_days and 15 * 60 <= t < 23 * 60) else 'night'
    return 'day' if (now.weekday() < 5 and 15 * 60 <= t < 23 * 60) else 'night'

def night_ref_point(group, now, trade_days, night_days):
    h, mi = GROUP_CLOSE[group]
    cand = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    if cand > now:
        cand -= timedelta(days=1)
    for _ in range(20):
        night_day = cand.date() if h >= 21 else (cand.date() - timedelta(days=1))
        if night_day.isoformat() in night_days:
            if h < 3:
                day_close = cand.replace(hour=15, minute=0)
                if day_close <= now and cand.date().isoformat() in trade_days:
                    return day_close, 'day'
            else:
                next_day = cand.date() + timedelta(days=1)
                next_day_close = (cand + timedelta(days=1)).replace(hour=15, minute=0)
                if next_day_close <= now and next_day.isoformat() in trade_days:
                    return next_day_close, 'day'
            return cand, 'night'
        day_close = cand.replace(hour=15, minute=0)
        if cand.date().isoformat() in trade_days and day_close <= now:
            return day_close, 'day'
        cand -= timedelta(days=1)
    return None, None

def index_ref_point(now, trade_days):
    cand = now.replace(hour=15, minute=0, second=0, microsecond=0)
    if cand > now:
        cand -= timedelta(days=1)
    for _ in range(20):
        ok = (cand.date().isoformat() in trade_days) if trade_days else (cand.weekday() < 5)
        if ok:
            return cand, 'day'
        cand -= timedelta(days=1)
    return None, None

def ref_price_from_bars(bars, ref_dt, max_gap_hours=14, now=None, allow_stale=False):
    """从 [(datetime, price)] 里找 <= ref_dt 的最后一根。
    allow_stale=True 时（新浪分时通道用）：gap 超限也放行——
    覆盖"原糖/豆粉"这类白天已收盘、最后成交价即有效参考价的品种。"""
    best = None
    for dt, c in bars:
        if now is not None and dt > now:
            break
        if dt <= ref_dt:
            best = (dt, c)
        else:
            break
    if best is None:
        return None, 'missing'
    if (ref_dt - best[0]) > timedelta(hours=max_gap_hours):
        if allow_stale:
            return best[1], 'ok'
        feed_live = bars and (now or now_cn()) - bars[-1][0] <= timedelta(hours=8)
        if not feed_live:
            return None, 'stale'
    return best[1], 'ok'

# ---------------- 主流程 ----------------
def main():
    t0 = time.time()
    now = now_cn()
    print(f'当前北京时间: {now:%Y-%m-%d %H:%M:%S}')

    # 交易日历
    try:
        trade_days, night_days = get_night_calendar()
        print(f'日历: 交易日 {len(trade_days)} 天, 夜盘日 {len(night_days)} 天')
    except Exception as e:
        print(f'日历失败({type(e).__name__})，按星期退化')
        trade_days, night_days = set(), set()

    mode = decide_mode(now, trade_days)
    ref_map = {}
    if mode == 'day':
        dc = now.replace(hour=15, minute=0, second=0, microsecond=0)
        for g in GROUPS:
            ref_map[g] = (dc, 'day')
        ref_map['IDX'] = (dc, 'day')
        ref_desc = '参考: 今日 15:00'
    else:
        for g in GROUPS:
            ref_map[g] = night_ref_point(g, now, trade_days, night_days)
        ref_map['IDX'] = index_ref_point(now, trade_days)
        parts = []
        for g in GROUPS:
            dt, _ = ref_map[g]
            parts.append(f'{GROUP_CLOSE[g][0]:02d}:{GROUP_CLOSE[g][1]:02d}→{dt:%m-%d %H:%M}' if dt else f'{g}:缺')
        ref_desc = '参考(有色01:00/贵金属02:30/其他23:00): ' + '  '.join(parts)
    print(f'模式: {mode}')

    # 当前价
    secids = sorted({v[2] for v in VARIETIES if v[2]})
    em_snap_ok = True
    try:
        em_map = em_snapshot(secids)
    except Exception as e:
        print(f'东财快照失败({type(e).__name__})')
        em_map, em_snap_ok = {}, False
    try:
        sina_map = sina_snapshot([v[3] for v in VARIETIES if v[3]])
        sina_ok = bool(sina_map)
    except Exception as e:
        print(f'新浪快照失败({type(e).__name__})')
        sina_map, sina_ok = {}, False
    print(f'快照: 东财 {len(em_map)}, 新浪 {len(sina_map)}')

    # v1.1 新增：新浪"当日分时"（参考价主源）
    #   按 symbol 去重拉取；美铜美分→美元换算；间隔 0.35s 温和请求
    #   （铁矿石有自己的 minline + 日K 兜底逻辑，此处跳过）
    ml_by_sym = {}
    ml_ok = 0
    skip_names = {'新加坡铁矿石'}
    for name, group, secid, sina_code in VARIETIES:
        if not sina_code or name in skip_names:
            continue
        sym = sina_code[3:] if sina_code.startswith('hf_') else sina_code
        if sym in ml_by_sym:
            continue
        try:
            bars = sina_minline_today(sym)
            if sym == 'HG':
                bars = [(t, p / 100.0) for t, p in bars]
            ml_by_sym[sym] = bars
            if bars:
                ml_ok += 1
        except Exception:
            ml_by_sym[sym] = []
        time.sleep(0.35)
    print(f'新浪分时: {ml_ok}/{len(ml_by_sym)} 成功')

    # 参考价 K 线（东财兜底通道）：串行拉全部（云端不缓存，每轮独立；失败的下一轮定时补）
    bars_map = {}
    kline_fail = 0
    for secid in secids:
        try:
            bars_map[secid] = em_kline5(secid)
        except Exception:
            bars_map[secid] = []
            kline_fail += 1
    print(f'K线: 成功 {len(secids) - kline_fail}/{len(secids)}')

    # 组装行
    rows = []
    for name, group, secid, sina_code in VARIETIES:
        if mode == 'day' and name.endswith('(02:30)') and '原油' in name:
            continue
        if mode == 'day' and name.endswith('(23:00)') and '原油' in name:
            name = name.split('(')[0]
        ref_dt, _ = ref_map.get('IDX' if secid in INDEX_SECIDS else group, (None, None))
        ref_show = ref_dt
        ref_text = None   # v1.2: 特判品种直接给出 ref 文本（美股指数等）
        sym = (sina_code[3:] if sina_code.startswith('hf_') else sina_code) if sina_code else None
        bars_ml = ml_by_sym.get(sym, []) if sym else []

        last, flag = None, False
        # v1.2: 新浪快照优先（与参考价同源，避免跨源合约口径差产生假涨跌）；东财兜底
        if sina_code and sina_code in sina_map:
            last = sina_map[sina_code]['last']
        if secid and secid.split('.')[-1] in em_map:
            em_last = em_map[secid.split('.')[-1]]['last']
            if last is None or (isinstance(last, (int, float)) and last <= 0):
                last = em_last
            elif em_last and isinstance(last, (int, float)) and last > 0 \
                    and abs(last - em_last) / last > 0.005:
                flag = True
        if last is None and bars_ml:
            last = bars_ml[-1][1]   # 两个快照源都缺时，用新浪分时末根

        close, note = None, ''
        if ref_dt is None:
            note = '缺'
        elif name == '伦敦银现货':
            # v1.1: 新浪当日分时优先（新鲜），5 日线兜底（可跨日）
            if bars_ml:
                try:
                    close, st = ref_price_from_bars(bars_ml, ref_dt, max_gap_hours=26,
                                                    now=now, allow_stale=True)
                except Exception:
                    close = None
            if close is None:
                try:
                    bars5 = sina_5day_minline('XAG')
                    close, st = ref_price_from_bars(bars5, ref_dt, now=now)
                except Exception:
                    close = None
            if close is None:
                note = '缺'
        elif name == '美原糖':
            # v1.1: 原糖时段 15:30 开盘后面临"开盘点效应"（旧时段数据被顶掉，
            # 拿不到 15:00 参考点）→ 用新浪日K 昨交易日收盘兜底（= 今晨时段收盘价）
            if bars_ml:
                try:
                    close, st = ref_price_from_bars(bars_ml, ref_dt, max_gap_hours=26,
                                                    now=now, allow_stale=True)
                except Exception:
                    close = None
            if close is None:
                try:
                    close = sina_dailyk_last_close('RS')
                except Exception:
                    close = None
            if close is None and secid:
                try:
                    close, st = ref_price_from_bars(bars_map.get(secid, []), ref_dt, now=now)
                    if st != 'ok':
                        close = None
                except Exception:
                    close = None
            if close is None:
                note = '缺'
        elif name == '新加坡铁矿石':
            if ref_dt is not None:
                try:
                    bars = sina_minline_today('FEF')
                    close, st = ref_price_from_bars(bars, ref_dt, max_gap_hours=10, now=now)
                except Exception:
                    close = None
            if close is None and ref_dt is not None:
                try:
                    close, ref_show = fef_ref_from_dailyk(ref_dt)
                except Exception:
                    close, ref_show = None, None
            if close is None:
                note = '缺'
        elif secid:
            if secid in US_INDEX_MAP:
                # v1.3: 美股指数（标普/道指/纳指）= 最近一个收盘价 vs 更早一个收盘价
                # （两个收盘价相差 1 个交易日；全天固定，不随盘中波动）
                try:
                    bars_us = us_index_daily_bars(US_INDEX_MAP[secid], now, 2)
                except Exception:
                    bars_us = []
                if len(bars_us) >= 2:
                    (d_prev, c_prev), (d_last, c_last) = bars_us
                    close, last = c_prev, c_last  # "收盘价"列=更早一个收盘价，"最新价"列=最近一个收盘价
                    ref_text = f'{d_last[5:]}美'   # 如 "10-14美"
                    flag = False
                    note = ''
                else:
                    last, note = None, '缺'
            else:
                # 商品：新浪当日分时优先（云端稳定），东财 K 线兜底（v1.1）
                if bars_ml:
                    try:
                        close, st = ref_price_from_bars(bars_ml, ref_dt, max_gap_hours=26,
                                                        now=now, allow_stale=True)
                    except Exception:
                        close = None
                if close is None:
                    try:
                        close, st = ref_price_from_bars(bars_map.get(secid, []), ref_dt, now=now)
                        if st != 'ok':
                            note = '缺' if st == 'missing' else '过'
                    except Exception:
                        note = '缺'
            if close is None and not note:
                note = '缺'

        chg = pct = None
        if close is not None and last is not None and close > 0:
            chg = last - close
            pct = chg / close * 100
        rows.append({
            'name': name, 'close': close, 'last': last, 'chg': chg, 'pct': pct,
            'flag': flag, 'note': note,
            'ref': ref_text if ref_text is not None else (f'{ref_show:%m-%d %H:%M}' if ref_show else None),
        })

    em_ok = em_snap_ok and kline_fail < 3
    data = {
        'generated_at': f'{now:%Y-%m-%d %H:%M}',
        'mode': mode,
        'mode_desc': '日间（对比今日15:00）' if mode == 'day' else '隔夜',
        'ref_desc': ref_desc,
        'em_ok': em_ok,
        'sina_ok': sina_ok,
        'kline_fail': kline_fail,
        'rows': rows,
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    ok_n = sum(1 for r in rows if r['pct'] is not None)
    print(f'完成: {ok_n}/{len(rows)} 个品种有涨跌幅, 耗时 {time.time() - t0:.0f} 秒')
    print(f'已写入 {out}')

if __name__ == '__main__':
    main()
