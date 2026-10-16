# -*- coding: utf-8 -*-
"""
外盘涨跌统计 · 云端抓取脚本（GitHub Actions 版 v1.13）
======================================================
v1.13 更新（2026-10-16 · 海鸥工作区）：
  - 美原糖改为与所有品种统一口径：**基准 = 国内 15:00 收盘时刻的价**。
    原糖 15:00 那一刻没有成交（它 15:30 才开盘）→ day 档取"15:00 之后的第一笔"（≈它今天开盘价），
    时间跨度与其他品种一致；不再退到今晨 01:00 的收盘价（跨 14 小时空档），也不再走日K。
    分时表滚出该笔时由 v1.8 继承机制按同 ref 顶住。

v1.12 更新（2026-10-16 · 海鸥工作区）：
  - 美原糖基准修正（用户口径）：基准取【国内对应品种最近一次收盘时刻】的价，不跟外盘自己的收盘走。
    国内糖（郑糖）收盘时刻：日盘 15:00、夜盘 23:00；原糖自身时段 15:30 → 次日 01:00，
    所以白档（10:15/11:30/15:00）它一律没有价 → 统一退到"最近一个已收盘的 23:00"。
    **删掉**原来"退到它自己 01:00 收盘的日K价"那条路径（那是外盘自己的收盘时刻，不是国内的，用户否掉）。
    原糖在分时表取不到时由 v1.8 继承机制按同 ref 顶住。
    记住这条总口径：**基准 = 国内最近一次对应品种收盘时刻的价**；只有外盘在那个时刻已经收盘
    （如日胶 14:50 收、节点 15:00）才用它自己的收盘价顶上。
  - 品种改名（用户要求，只改显示名，新浪/东财代码一律不动）：
      美黄豆粉 → 美豆粕、美黄豆油 → 美豆油、美国棉花 → 美棉花、美国天然气 → 美天然气
    前端匹配表（NAME2CODE）已同步。改名后第一轮会与上一版名字对不上，
    等于放弃一次继承机会；若恰逢"该品种本轮取不到价"，会显示一次"缺"，下一轮即恢复。

v1.11 更新（2026-10-16 · 海鸥工作区）：
  - 日橡胶基准修正：day 档（15:00 基准）改用"今天日K那根的收盘价"（= 日盘 14:50 收盘价）。
    该品种 14:50 收盘且成交极稀疏，分时表在收盘前常已无成交（实测最后一笔只到 14:11），
    原规则会取到 14:11 的价；而日K"今天"那根的 close 才是真实收盘价（夜盘 16:00 开盘后也不变）。
    「起始时间」列随之如实显示 14:50。仅此一品种、仅 day 档改动，其余数值口径不变。

v1.10 更新（2026-10-16 · 海鸥工作区）：
  - 新增两个【说明性】字段，数值口径零改动（close/last/chg/pct 与 v1.9.2 完全一致）：
      ref_actual = 该行基准价实际取自哪一笔分时的时刻，如 "10-16 10:23"
      gap_min    = 该笔时刻与本档位标称节点相差的分钟数，如 67
    背景：稀疏品种（美豆粕 / 伦锡 / 伦铅 / 天然气…）在档位节点附近没有成交，
    实际取的是更早的最后一笔，而页面「起始时间」列显示的是标称节点 ——
    看起来精确、实际模糊，拿它去分钟图上反查会对不上。这两个字段供前端如实显示。
  - 继承（v1.8 续接）、换月修正行过渡继承（v1.9.1）时一并继承这两个字段；
    换月修正行置空（修正值来自"昨结算"，不对应任何一笔分时）。
  - 文件末尾新增一行统计打印，便于日志里直接看到偏移情况。

v1.9.2 更新（2026-10-16）：
  - 新增「10:15 档预轮等待」：GitHub 定时任务实测稳定延迟 26~36 分钟执行，
    原 10:17 轮实际要 10:4x 才跑，赶不上 10:30 前参考。为此在 fetch.yml 新增
    北京 09:50 / 09:55 两条预触发 cron（把排队延迟吃进触发点）。
    本脚本配套：若本轮执行时间落在 09:46:05 ~ 10:16:05 之间（即预轮提前落地），
    等待到 10:16:05 再继续 —— 否则 10:15 的基准价尚未产出，会取到错误参考价。
    （仅在上述窗口生效，不影响其它任何轮次。）

v1.9.1 更新（2026-10-16）：
  - 换月修正的起始时间标注由「昨结」改为「昨结 换月」（提醒更醒目，用户要求）。
  - 新增「换月修正行过渡期兜底继承」：某行上轮被换月修正（note 含"换月"）后，
    在下一轮取到新值之前，若遇取不到价且 ref 匹配失败，沿用其修正值（连 ref 一并沿用），
    不再跌回"缺"（覆盖场景：修正当天的手动 Run、或任何中间轮次）。

v1.9 更新（2026-10-16）：
  - 新增「换月检测」：主连换月时，若参考时点落在换月前（参考价=老合约），
    而行情已切到新合约，页面涨跌幅会失真（例：10-16 美燃油 老合约 4.834
    vs 新合约 4.596，显示假跌 -4.9%，实际约 -1.3%）。
    双条件同时满足才修正（防误伤正常大波动日）：
      ① 参考价与快照"昨结算"（当前合约）偏离 > 2%；
      ② 参考价不在最近 2 根日K的 [min(low), max(high)] 区间内（±0.5% 容差）。
    修正动作：参考价 := 昨结；起始时间列标注「昨结」；note 记「换月」。
    （美铜日K为美分口径，检测时按 SINA_CENT_TO_DOLLAR 统一换算。）

v1.8 更新（2026-10-16）：
  - 新增「取不到价时的续接」：某品种本轮取不到参考价（close 仍为空）时，
    从上一版 data.json 继承【同一参考时点（ref 相同）】的旧值，不再把上一轮
    已取到的好数据覆盖成空。解决场景：轮次跑在"分时时段切换"之后
    （CME 纽约盘 06:00 切换、ICE/CBOT/LME 08:00 切换，旧时段数据被顶掉），
    如 05:50 轮常被 GitHub 排队延迟到 06:05+，导致 WTI/黄金/白银/铜/燃油/天然气
    集体丢参考价。美股三指数接口失败时按名称整体沿用上一版（避免清空）。
  - 新增 --us-only 轻量模式：只重取美股三行（3 个请求、约 10 秒），
    供清晨 07:45 轮"美股日线定格"用（新浪美股日K更新晚于 05:30 判据，
    05:35/05:50 轮拿不到新日线，靠白天轮次补太晚）。其他行与 generated_at 不动；
    美股行无变化时不写文件、不产生提交。

v1.7 更新（2026-10-15）：
  - 新增白天两档参考时点（配套国内日盘作息）：10:15 档（10:15-11:30，含 10:15 休息段；
    10:30 开盘后不切换、连续对比到 11:30）与 11:30 档（11:30-15:00，含午休段）。
    仅交易日生效，非交易日回落 night。
  - data.json 新增 title 字段（各档页面标题），前端优先使用（旧前端自动回落原逻辑）。
  - 原油双档合并条件由「day 模式」放宽为「非 night 模式」（白天两档同样显示单行）；
    夜盘双行时名称不再带「(23:00)/(02:30)」组标记（区分由"起始时间"列呈现）。
  - 美原糖「起始时间」标签修正放宽到白天两档（mode != night 时均显示"最近时段收盘 01:00"，
    与 v1.5 的 day 档口径一致）；马棕等其他品种维持名义档位时点显示。

v1.6 更新（2026-10-15）：
  - rows 每行新增 code 字段（新浪 hf_ 代码，如 "hf_GC"），供网页端直连腾讯行情
    （qt.gtimg.cn）拉取实时最新价时做品种匹配。腾讯行情与新浪同数据体系、
    字段协议一致（实测同一秒数值一致），且响应带 CORS 头、无 Referer 防盗链，
    浏览器可直接获取；新浪官方接口有防盗链，网页端无法直连。

v1.5 更新（2026-10-15）：
  - 美原糖（时段 15:30 → 次日 01:00）参考价标签修正：day 模式（16:50/20:50 轮，
    时段进行中）下参考 = 前一（时段）01:00 收盘价，标签同步显示该收盘时刻
    （如 "10-15 01:00"，跨周末由日K日期推算、自动正确），不再误标"今日 15:00"。
  - 9:00/12:50 轮（时段已收）：参考 = 前一晚 23:00、最新价 = 01:00 收盘价（冻结），维持不变。
  - 日K读取函数升级为返回 (日期, 收盘价)：`sina_dailyk_closed_bar()`。

v1.4 更新（2026-10-15）：
  - 移除"东财 vs 新浪"两源差异比对（※ 标记逻辑）：两源合约口径本就不同，
    在东财偶发放行时会产生误导性 ※（天然气/豆粉曾差 5%~18%）。现东财仅作兜底。
  - 新增日橡胶（RSS3）夜盘 16:00 开盘后的兜底：用日K"今天"那根（当日日盘收盘价）。
  - 修复原糖日K 兜底取值：排除"今天"那根（含进行中的夜盘），改取"昨天"收盘。

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
# v1.13: 品种改名对照（旧名 → 新名）。**只用于继承上一版 data.json 时兼容旧名**，
#   保证改名后的第一轮照样能继承到值，不会出现一次"缺"。
NAME_ALIAS_MAP = {
    '美黄豆粉': '美豆粕',
    '美黄豆油': '美豆油',
    '美国棉花': '美棉花',
    '美国天然气': '美天然气',
}

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
    ('美天然气',      'M23',   '102.NG00Y',  'hf_NG'),
    ('美大豆',       'M23',   '103.ZS00Y',  'hf_S'),
    ('美豆粕',       'M23',   '103.ZM00Y',  'hf_SM'),
    ('美豆油',       'M23',   '103.ZL00Y',  'hf_BO'),
    ('美原糖',       'M23',   '108.SB00Y',  'hf_RS'),
    ('美棉花',       'M23',   '108.CT00Y',  'hf_CT'),
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

def sina_dailyk_closed_bar(symbol, now, exclude_today=False):
    """v1.5: 新浪日K中"已收盘"的最后一根 → (日期str, 收盘价)；无则 (None, None)。
    exclude_today=False: 取日期 <= 北京今天的最后一根（如日橡胶：夜盘归次日，"今天"那根=当日日盘已收）；
    exclude_today=True:  取日期 <  北京今天的最后一根（如原糖："今天"那根含进行中的夜盘，不可用）。"""
    u = ('https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20d=/'
         f'GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={symbol}')
    txt = http_get(u, SINA_HEADERS)
    m = re.search(r'\((\[.*\])\)', txt, re.S)
    if not m:
        return None, None
    try:
        arr = json.loads(m.group(1))
    except Exception:
        return None, None
    if not isinstance(arr, list):
        return None, None
    today = now.date()
    for k in reversed(arr):
        try:
            d = datetime.strptime(k['date'], '%Y-%m-%d').date()
        except (ValueError, KeyError, TypeError):
            continue
        if exclude_today and d >= today:
            continue
        if (not exclude_today) and d > today:
            continue
        try:
            return k['date'], float(k['close'])
        except (ValueError, KeyError, TypeError):
            return None, None
    return None, None

def sina_dailyk_highlow_range(symbol, n=2):
    """v1.9: 取最近 n 根日K的 [min(low), max(high)]，供换月检测的区间校验用。
    失败返回 None（调用方跳过检测，不影响主流程）。"""
    u = ('https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20d=/'
         f'GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={symbol}')
    try:
        txt = http_get(u, SINA_HEADERS)
        m = re.search(r'\((\[.*\])\)', txt, re.S)
        if not m:
            return None
        arr = json.loads(m.group(1))
    except Exception:
        return None
    if not isinstance(arr, list) or len(arr) < n:
        return None
    lows, highs = [], []
    for k in arr[-n:]:
        try:
            lows.append(float(k['low']))
            highs.append(float(k['high']))
        except (ValueError, KeyError, TypeError):
            continue
    if not lows:
        return None
    return min(lows), max(highs)

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

def us_ref_date(ref, today):
    """v1.9: 解析美股行 ref（如 '10-15美'）为 date，按"最近原则"归属年份（跨年安全）。
    解析失败返回 None。用于"防回退"比较：本轮算出的日线不该比上一版更旧。"""
    m = re.match(r'^(\d{2})-(\d{2})美$', ref or '')
    if not m:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    try:
        d = today.replace(month=mm, day=dd)
        if d > today + timedelta(days=7):
            d = d.replace(year=today.year - 1)
        return d
    except ValueError:
        return None

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
    """档位判定（v1.7 新增白天两档）：
       day   = 15:00-23:00（参考今日 15:00）
       m1015 = 10:15-11:30（参考今日 10:15；10:30 开盘后不切换，连续对比到 11:30）
       m1130 = 11:30-15:00（参考今日 11:30，午休段起）
       night = 其余（夜盘分组参考）
       白天两档仅在交易日生效，非交易日回落 night。"""
    today = now.date().isoformat()
    t = now.hour * 60 + now.minute
    is_trade = (today in trade_days) if trade_days else (now.weekday() < 5)
    if is_trade:
        if 15 * 60 <= t < 23 * 60:
            return 'day'
        if 10 * 60 + 15 <= t < 11 * 60 + 30:
            return 'm1015'
        if 11 * 60 + 30 <= t < 15 * 60:
            return 'm1130'
    return 'night'

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
    v1.10: 返回值增加第三项 = 该笔的 datetime（取价笔时刻），供"实际取价笔"字段使用。
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
        return None, 'missing', None
    if (ref_dt - best[0]) > timedelta(hours=max_gap_hours):
        if allow_stale:
            return best[1], 'ok', best[0]          # v1.10: 一并返回取价笔时刻
        feed_live = bars and (now or now_cn()) - bars[-1][0] <= timedelta(hours=8)
        if not feed_live:
            return None, 'stale', None
    return best[1], 'ok', best[0]                   # v1.10: 一并返回取价笔时刻

# ---------------- 主流程 ----------------
def main():
    t0 = time.time()
    now = now_cn()
    print(f'当前北京时间: {now:%Y-%m-%d %H:%M:%S}')

    # v1.9.2: 10:15 档预轮等待 —— 配套 fetch.yml 的 09:50 / 09:55 预触发轮。
    # 预轮因调度波动可能提前落地（如 09:5x 就执行），此时 10:15 基准价还没产出；
    # 等待到 10:16:05 再继续，保证取价时点正确。窗口 09:46:05~10:16:05，只影响预轮。
    t_1016 = now.replace(hour=10, minute=16, second=5, microsecond=0)
    if timedelta(0) < (t_1016 - now) <= timedelta(minutes=30):
        print(f'预轮等待: 本轮于 {now:%H:%M:%S} 提前执行，等待至 10:16:05 再取 10:15 基准价')
        time.sleep((t_1016 - now).total_seconds())
        now = now_cn()
        print(f'等待结束，现在: {now:%Y-%m-%d %H:%M:%S}')

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
    elif mode in ('m1015', 'm1130'):
        # v1.7: 白天两档 —— 全组统一参考时点（与 15:00 档同构）
        hh, mm = {'m1015': (10, 15), 'm1130': (11, 30)}[mode]
        dc = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        for g in GROUPS:
            ref_map[g] = (dc, 'day')
        ref_map['IDX'] = (dc, 'day')
        ref_desc = f'参考: 今日 {hh:02d}:{mm:02d}'
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

    # v1.8: 读上一版 data.json（Actions 里 = 上一轮提交的版本），供"取不到价时续接"用。
    # 普通品种按 name+ref 精确匹配；铁矿等特判分支会在行组装时提前用到 prev_by_key。
    prev_rows = []
    prev_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')
    try:
        with open(prev_path, encoding='utf-8') as f:
            prev_rows = (json.load(f) or {}).get('rows') or []
        print(f'续接: 读到上一版 data.json, {len(prev_rows)} 行')
    except Exception:
        prev_rows = []
        print('续接: 无上一版 data.json（首次运行）')
    prev_by_key = {}
    prev_by_name = {}
    prev_special = {}   # v1.9.1: 换月修正行（note 含"换月"），供过渡期兜底继承
    for _r in prev_rows:
        if _r.get('close') is None:
            continue
        if _r.get('ref'):
            prev_by_key[(_r.get('name'), _r.get('ref'))] = _r
            # v1.13: 上一版里的"旧名 + 同 ref"行，也注册到新名下 → 改名后第一轮照样能继承
            _nn = NAME_ALIAS_MAP.get(_r.get('name'))
            if _nn:
                prev_by_key.setdefault((_nn, _r.get('ref')), _r)
        prev_by_name.setdefault(_r.get('name'), _r)
        _nn2 = NAME_ALIAS_MAP.get(_r.get('name'))
        if _nn2:
            prev_by_name.setdefault(_nn2, _r)
        if '换月' in (_r.get('note') or ''):
            prev_special.setdefault(_r.get('name'), _r)

    # 组装行
    rows = []
    for name, group, secid, sina_code in VARIETIES:
        if '原油' in name and mode != 'night' and name.endswith('(02:30)'):
            continue   # 单行档（15:00 / 10:15 / 11:30）：原油只显示一行
        if '原油' in name:
            # 名称不带组标记；两行时的区分（23:00 / 02:30）由「起始时间」列呈现
            name = name.split('(')[0]
        ref_dt, _ = ref_map.get('IDX' if secid in INDEX_SECIDS else group, (None, None))
        ref_show = ref_dt
        ref_text = None   # v1.2: 特判品种直接给出 ref 文本（美股指数等）
        sym = (sina_code[3:] if sina_code.startswith('hf_') else sina_code) if sina_code else None
        bars_ml = ml_by_sym.get(sym, []) if sym else []

        last, flag = None, False
        hit_dt = None   # v1.10: 本行基准价实际取自哪一笔（datetime）；不适用/取不到时 None
        # v1.4: 新浪快照优先（与参考价同源）；东财仅作兜底、不再做两源差异比对
        #（两源的连续/主力合约口径本就不同，比对会产生误导性的 ※ 标记）
        if sina_code and sina_code in sina_map:
            last = sina_map[sina_code]['last']
        if last is None and secid and secid.split('.')[-1] in em_map:
            last = em_map[secid.split('.')[-1]]['last']
        if last is None and bars_ml:
            last = bars_ml[-1][1]   # 两个快照源都缺时，用新浪分时末根

        close, note = None, ''
        if ref_dt is None:
            note = '缺'
        elif name == '伦敦银现货':
            # v1.1: 新浪当日分时优先（新鲜），5 日线兜底（可跨日）
            if bars_ml:
                try:
                    close, st, hit_dt = ref_price_from_bars(bars_ml, ref_dt, max_gap_hours=26,
                                                    now=now, allow_stale=True)
                except Exception:
                    close = None
            if close is None:
                try:
                    bars5 = sina_5day_minline('XAG')
                    close, st, hit_dt = ref_price_from_bars(bars5, ref_dt, now=now)
                except Exception:
                    close = None
            if close is None:
                note = '缺'
        elif name == '美原糖':
            # v1.13（用户口径）：所有品种统一以"国内 15:00 收盘"为基准价。
            #   原糖自身时段 15:30 → 次日 01:00，所以 15:00 那一刻它【没有成交】。
            #   day 档（15:00 基准）：取"15:00 之后的第一笔"（≈它今天开盘的价），
            #     这样时间跨度与其他品种基本一致，而不是退到 14 小时前（今晨 01:00 的收盘价）。
            #   m1015 / m1130 / night 档：15:00 之后的价还没产生（或基准本就是 23:00），
            #     保持"取 ≤ 节点最后一笔"的通用逻辑。
            #   分时表取不到时（如次日表已滚动）交给 v1.8 继承机制按同 ref 顶住，不降级、不显示缺。
            if mode == 'day' and bars_ml:
                for _dt, _c in bars_ml:
                    if _dt >= ref_dt:
                        close, hit_dt = _c, _dt
                        break
            if close is None and bars_ml:
                try:
                    close, st, hit_dt = ref_price_from_bars(bars_ml, ref_dt, max_gap_hours=26,
                                                    now=now, allow_stale=True)
                except Exception:
                    close = None
            if close is None and secid:
                try:
                    close, st, hit_dt = ref_price_from_bars(bars_map.get(secid, []), ref_dt, now=now)
                    if st != 'ok':
                        close = None
                except Exception:
                    close = None
            if close is None:
                note = '缺'   # 下一轮/上一版按同 ref 继承

        elif name == '日橡胶':
            # v1.11: 日盘 14:50 收盘。day 档（15:00 基准）改用"今天日K那根的收盘价"：
            #   该品种成交极稀疏，分时表在收盘前常已无成交（实测最后一笔只到 14:11），
            #   而日K"今天"那根的 close 就是 14:50 的收盘价，且夜盘 16:00 开盘后也不再变。
            #   （用户实测：新浪行情页显示的是 14:50 的数据，即收盘价。）
            if mode == 'day':
                try:
                    _rd, _rc = sina_dailyk_closed_bar('RSS3', now, exclude_today=False)
                    if _rc is not None and _rd == now.date().isoformat():
                        close = _rc
                        ref_text = f'{now:%m-%d} 14:50'          # 语义即"日盘 14:50 收盘"
                        hit_dt = now.replace(hour=14, minute=50, second=0, microsecond=0)
                except Exception:
                    close = None
            if close is None and bars_ml:
                try:
                    close, st, hit_dt = ref_price_from_bars(bars_ml, ref_dt, max_gap_hours=26,
                                                    now=now, allow_stale=True)
                except Exception:
                    close = None
            if close is None:
                try:
                    _d, close = sina_dailyk_closed_bar('RSS3', now, exclude_today=False)
                except Exception:
                    close = None
            if close is None and secid:
                try:
                    close, st, hit_dt = ref_price_from_bars(bars_map.get(secid, []), ref_dt, now=now)
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
                    close, st, hit_dt = ref_price_from_bars(bars, ref_dt, max_gap_hours=10, now=now)
                except Exception:
                    close = None
            # v1.8: 日K兜底会把口径降级为"时段起点"（如 20:00），优先继承上一版
            # 同参考时点（如 10-15 23:00）的旧值，保持口径一致
            if close is None and ref_dt is not None:
                _p = prev_by_key.get((name, f'{ref_dt:%m-%d %H:%M}'))
                if _p is not None:
                    close = _p['close']
                    note = '继'
            if close is None and ref_dt is not None:
                try:
                    close, ref_show = fef_ref_from_dailyk(ref_dt)
                    hit_dt = ref_show   # v1.10: 该值取自日K的时段起点
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
                        close, st, hit_dt = ref_price_from_bars(bars_ml, ref_dt, max_gap_hours=26,
                                                        now=now, allow_stale=True)
                    except Exception:
                        close = None
                if close is None:
                    try:
                        close, st, hit_dt = ref_price_from_bars(bars_map.get(secid, []), ref_dt, now=now)
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
        # v1.10: 记录"实际取价笔时刻"与"页面显示的起始时刻和它的差"（纯说明用途，不参与任何计算）
        _ref_actual = f'{hit_dt:%m-%d %H:%M}' if hit_dt is not None else None
        # 偏差基准 = 本行「起始时间」列最终显示的那个时刻（优先 ref_text 修正值，其次档位节点 ref_show）
        _nominal = ref_show if ref_text is None else None
        if ref_text is not None and hit_dt is not None:
            _m = re.match(r'^(\d{2})-(\d{2}) (\d{2}):(\d{2})$', ref_text)
            if _m:
                try:
                    _cand = hit_dt.replace(month=int(_m.group(1)), day=int(_m.group(2)),
                                           hour=int(_m.group(3)), minute=int(_m.group(4)),
                                           second=0, microsecond=0)
                    if (_cand - hit_dt).days > 180:
                        _cand = _cand.replace(year=_cand.year - 1)
                    elif (hit_dt - _cand).days > 180:
                        _cand = _cand.replace(year=_cand.year + 1)
                    _nominal = _cand
                except ValueError:
                    _nominal = None
        _gap_min = None
        if hit_dt is not None and _nominal is not None:
            _gap_min = int(round((_nominal - hit_dt).total_seconds() / 60.0))
        rows.append({
            'name': name, 'close': close, 'last': last, 'chg': chg, 'pct': pct,
            'flag': flag, 'note': note, 'code': sina_code,
            'ref': ref_text if ref_text is not None else (f'{ref_show:%m-%d %H:%M}' if ref_show else None),
            'ref_actual': _ref_actual,   # v1.10: 实际取价笔时刻，如 "10-16 10:23"
            'gap_min': _gap_min,         # v1.10: 与「起始时间」列显示时刻的分钟差，如 67
        })

    # ---------------- v1.8：取不到价的续接（后处理） ----------------
    # 场景：轮次跑在"分时时段切换"之后（CME 纽约盘 06:00 起新时段、ICE/CBOT/LME 08:00 起），
    # 旧时段的参考点（23:00 / 01:00 / 02:30 等）已不在"当日分时"里；若东财 K 线也被限流，
    # close 会取空 —— 此时从上一版 data.json 继承同一参考时点（name+ref 完全一致）的旧值，
    # 避免把上一轮已取到的好数据覆盖成空。
    # 美股三指数：接口临时失败（不足 2 根日线）时按名称整体沿用上一版，避免行被清空。
    us_index_names = {'标准普尔', '道琼工业', '纳斯达克'}
    inherit_n = 0
    for row in rows:
        if row['close'] is not None:
            continue
        p = None
        if row.get('ref'):
            p = prev_by_key.get((row['name'], row['ref']))
        if p is None and row['name'] in us_index_names:
            p = prev_by_name.get(row['name'])
            if p is not None and not row.get('ref'):
                row['ref'] = p.get('ref')   # 美股行整体沿用（含参考日期标签）
        # v1.9.1: 换月修正行的过渡期兜底 —— 本轮取不到价且 ref 匹配失败时，
        # 沿用其修正值（连 ref 一并沿用，保持「昨结 换月」口径标注），不再跌回"缺"
        if p is None and row['name'] in prev_special:
            p = prev_special[row['name']]
            if p is not None:
                row['ref'] = p.get('ref')
        if p is None:
            continue
        row['close'] = p['close']
        row['ref_actual'] = p.get('ref_actual')   # v1.10: 说明字段一并继承，保持口径一致
        row['gap_min'] = p.get('gap_min')
        if row['last'] is None:
            row['last'] = p.get('last')
        if row.get('note') == '缺':
            row['note'] = '继'
        if row['close'] is not None and row['last'] is not None and row['close'] > 0:
            row['chg'] = row['last'] - row['close']
            row['pct'] = row['chg'] / row['close'] * 100
        inherit_n += 1
    if inherit_n:
        print(f'续接: {inherit_n} 行继承上一版数据')

    # ---------------- v1.9：美股防回退 ----------------
    # 数据源偶尔会撤回"最近一根日线"（如 2026-10-16 新浪 .INX 短暂撤下 10-15 那根，
    # 5736→5735 根），导致页面倒退回前一天。市场数据只向前：
    # 若本轮算出的最新日线比上一版 data.json 的更旧，则保留上一版整行。
    rollback_keep = 0
    for row in rows:
        if row['name'] not in us_index_names:
            continue
        p = prev_by_name.get(row['name'])
        if not p or p.get('close') is None:
            continue
        cur_d = us_ref_date(row.get('ref'), now.date())
        old_d = us_ref_date(p.get('ref'), now.date())
        if cur_d and old_d and cur_d < old_d:
            row['close'], row['last'] = p['close'], p.get('last')
            row['ref'], row['chg'], row['pct'] = p.get('ref'), p.get('chg'), p.get('pct')
            row['ref_actual'], row['gap_min'] = p.get('ref_actual'), p.get('gap_min')
            row['note'] = '防退'
            rollback_keep += 1
            print(f"防回退: {row['name']} 本轮源数据({cur_d})落后于上一版({p.get('ref')})，保留上一版")
    if rollback_keep:
        print(f'美股防回退: {rollback_keep} 行保留上一版')

    # ---------------- v1.9：换月检测（参考价失真自动修正） ----------------
    # 主连换月时，若"参考时点"落在换月前（参考价=老合约价），而行情已切到新合约，
    # 页面涨跌幅会失真（例：2026-10-16 美燃油 老合约 4.834 vs 新合约 4.596，
    # 显示假跌 -4.9%，实际约 -1.3%）。双条件同时满足才修正（防误伤正常大波动日）：
    #   ① 参考价与快照"昨结算"（当前合约）偏离 > 2%；
    #   ② 参考价不在最近 2 根日K的 [min(low), max(high)] 区间内（±0.5% 容差）。
    # 修正：参考价 := 昨结；ref := '昨结'（页面"起始时间"列显示该标注）；note := '换月'。
    month_fix = 0
    for row in rows:
        code = row.get('code')
        if not code or row.get('close') is None or code not in sina_map:
            continue
        ps = sina_map[code].get('prev_settle')
        if not ps or ps <= 0:
            continue
        close = row['close']
        if abs(close - ps) / ps <= 0.02:
            continue                                     # 条件①未命中
        sym = code[3:] if code.startswith('hf_') else code
        rng = sina_dailyk_highlow_range(sym, 2)
        if not rng:
            continue                                     # 取不到日K → 不冒险，跳过
        lo, hi = rng
        if code in SINA_CENT_TO_DOLLAR:                  # 口径统一（美铜日K为美分）
            lo, hi = lo / 100.0, hi / 100.0
        if lo * 0.995 <= close <= hi * 1.005:
            continue                                     # 条件②未命中（在正常区间内）
        row['close'] = ps
        row['ref'] = '昨结 换月'
        row['note'] = '换月'
        row['ref_actual'] = None   # v1.10: "昨结算"不对应任何一笔分时，说明字段置空
        row['gap_min'] = None
        if row['last'] is not None:
            row['chg'] = row['last'] - ps
            row['pct'] = row['chg'] / ps * 100
        month_fix += 1
        print(f"换月修正: {row['name']} 参考价 {close} -> 昨结 {ps}")
    if month_fix:
        print(f'换月检测: {month_fix} 行已修正')
    else:
        print('换月检测: 未发现疑似换月失真')

    em_ok = em_snap_ok and kline_fail < 3
    mode_title = {'day': '对比15:00涨跌统计（日间）',
                  'm1015': '对比10:15涨跌统计',
                  'm1130': '对比11:30涨跌统计'}.get(mode, '隔夜涨跌统计')
    data = {
        'generated_at': f'{now:%Y-%m-%d %H:%M}',
        'mode': mode,
        'title': mode_title,
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
    # v1.10: 顺带把"实际取价笔"的偏移情况打到日志里，方便一眼看出稀疏品种
    _gaps = [(r['name'], r['gap_min']) for r in rows if r.get('gap_min') is not None]
    if _gaps:
        _off = [(n, g) for n, g in _gaps if abs(g) >= 3]
        _msg = f'实际取价笔: {len(_gaps)} 行有记录'
        if _off:
            _msg += f', 其中偏离标称节点 >=3 分钟 {len(_off)} 行: ' + \
                    ', '.join(f'{n}{g:+d}分' for n, g in sorted(_off, key=lambda x: -abs(x[1]))[:8])
        print(_msg)

    ok_n = sum(1 for r in rows if r['pct'] is not None)
    print(f'完成: {ok_n}/{len(rows)} 个品种有涨跌幅, 耗时 {time.time() - t0:.0f} 秒')
    print(f'已写入 {out}')

def main_us_only():
    """v1.8：--us-only 轻量模式 —— 只重取美股三行（标普/道指/纳指）。
    用途：清晨 07:45 轮补最新已收盘日线（新浪美股日K更新晚于 05:30 判据）。
    其他行、generated_at 均保持不动；美股行无变化时不写文件（git 不产生提交）。
    日线「已收盘」判据与主流程一致（日线日期次日北京 05:30 之后）。"""
    t0 = time.time()
    now = now_cn()
    print(f'us-only 模式 · 当前北京时间: {now:%Y-%m-%d %H:%M:%S}')
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')
    try:
        with open(out, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'读取 data.json 失败({type(e).__name__})，退出')
        return
    idx_secid = {name: sid for name, group, sid, sina_code in VARIETIES if sid in US_INDEX_MAP}
    changed = 0
    for row in data.get('rows', []):
        secid = idx_secid.get(row.get('name'))
        if secid is None:
            continue
        try:
            bars_us = us_index_daily_bars(US_INDEX_MAP[secid], now, 2)
        except Exception as e:
            bars_us = []
            print(f"{row['name']}: 日K接口失败({type(e).__name__})")
        if len(bars_us) < 2:
            print(f"{row['name']}: 已收盘日线不足 2 根，跳过")
            continue
        (d_prev, c_prev), (d_last, c_last) = bars_us
        new_ref = f'{d_last[5:]}美'
        # v1.9: 防回退 —— 本轮日线若比 data.json 现有的更旧（源数据撤回抖动），跳过不动
        cur_d = us_ref_date(new_ref, now.date())
        old_d = us_ref_date(row.get('ref'), now.date())
        if cur_d and old_d and cur_d < old_d:
            print(f"{row['name']}: 日线回退保护（本轮 {new_ref} 落后于现有 {row.get('ref')}），跳过")
            continue
        if (row.get('close') != c_prev or row.get('last') != c_last
                or row.get('ref') != new_ref):
            row['close'], row['last'] = c_prev, c_last
            row['ref'] = new_ref
            row['chg'] = c_last - c_prev
            row['pct'] = row['chg'] / c_prev * 100 if c_prev else None
            row['flag'] = False
            row['note'] = ''
            changed += 1
            print(f"{row['name']}: -> {new_ref} 收盘={c_prev} 最新={c_last}")
        else:
            print(f"{row['name']}: 无变化（{new_ref}）")
    if changed:
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f'us-only 完成: {changed} 行更新, 已写入 {out}, 耗时 {time.time() - t0:.0f} 秒')
    else:
        print('us-only 完成: 无变化，不写文件')

if __name__ == '__main__':
    if '--us-only' in sys.argv:
        main_us_only()
    else:
        main()
