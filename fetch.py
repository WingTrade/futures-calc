# -*- coding: utf-8 -*-
"""
外盘涨跌统计 · 云端抓取脚本（GitHub Actions 版 v1.16）
======================================================
  - 美股三行「同批对齐」（v2.18，2026-10-20 纳指滞留事故）：
      · 事故：07:45 --us-only 轮与 08:00 完整轮落地时，新浪 .IXIC 的 10-19 日线尚未落库，
        而 .INX / .DJI 已落库 → 表里标普/道指是 10-19 口径，纳指停在 10-16，
        并按 10-15→10-16 两根算出 -2.15%（实际 10-19 是 +1.11%）。
      · 成因：us_index_daily_bars 是单源单次请求，无重试、无备源；既有「防回退」只在
        本轮比上一版更旧时触发，"两新一旧"的同批不同步它管不到。
      · 修复：① 日线取数改多源 —— 新浪 3 次重试（4s / 8s 退避）+ 腾讯美股日K兜底 2 次；
              ② 新增 align_us_index_rows()：三行抓完比对日期，落后行按"本批最新日期"
                 定向重抓（want_last）；仍不齐则三行统一退到共同最新日
                 —— 宁可旧一天，也不让同一张表混两种口径（该行 note='滞后'）；
              ③ 主流程与 --us-only 两条路径都接入，对齐放在「防回退」之后（防止被拉回去）。
      · 腾讯备源实测：.INX / .DJI / .IXIC 收盘与新浪逐位一致
        （10-19：7690.73 / 51966.03 / 26430.89）。
  - 换月检测换引擎：主力合约锚定法（v1.16，用户方案，替代价格区间判据为主通道）：
  - 富时A50 回归（v2.19，2026-10-20）——v1.3 曾因"仅东财有源"移除；实测新浪 hf_CHA50CFD
    快照/MinLine/日K 全通（当时的判断不成立），按双窗口口径重新接入（见 a50_window）。
      · 原理：主连 hf_CL 的行情流就是当前主力合约的行情流，所以枚举候选月份合约
        快照（hf_CL + YYMM，本月起 6 个月窗口——实测美天然气主力跳 NG2701、
        美原糖跳 RS2703，跨多月换月真实存在，窗口窄了会漏），找与主连
        【同价且同刻】（快照 date+time 完全相同、价差 <=0.3%）者 = 当前主力合约。
      · 持久化：每轮把 {sym: 'CL2612'} 写进 data.json 顶层 contracts；
        下一轮比对，锚变了 = 换月（首轮回无锚只建锚，不动作）。
      · 修正两级：① 优先"穿越换月"——拉【新合约】自己的当日分时表，按原参考时点
        重新取价（新合约换月前也在交易，口径无缝连续，「起始时间」列保持原时点）；
        ② 分时取不到 → 参考价 := 新合约昨结算，起始时间列标「换月」。
        行字段 roll='fix'，页面「起始时间」列显示「换月」二字（不放涨跌幅小标，v2.17 用户要求）；跨轮续接时一并继承。
      · 与旧通道的关系：锚定法覆盖的品种（判得出当前主力）【不再走】v1.9/1.14/1.15
        的价格区间检测——旧判据依赖"当段分时表=同一合约"，换月点落在时段中段时
        该假设破裂（2026-10-17 WTI 事故：23:00 行 97.578 与 02:30 行 101.58 同轮
        相差 3.9%，区间被两个合约共同撑宽，双通道全部漏检）。锚定法判不出的品种
        才由旧通道兜底。
  - 换月检测补第二通道（v1.15，采纳同行评审）：
      · v1.14 只查【最新价】是否跑出当段分时表区间 —— 覆盖"分时表与快照切合约不同步"的瞬间；
        但真实事故（10-16 美燃油）不是这样：两个源**都已切到新合约**，失真的是【起始价】
        —— 它跨过换月线后被"续接继承"钉成了老合约价（close=4.834 / last=4.596 / 昨结 4.654），
        所以每轮都不触发。经复核，该案例属实。
      · 新增通道2 `rollover_suspect_close()`：起始价跑出当段表区间、且明显偏离昨结算。
        双阈值分级：偏离 >= 2.5% → 自动修正（roll='fix'）；1.5%~2.5% → 只记录嫌疑
        （roll='watch'，不动数值，避免把"跨时段继承的正确值"改错）。留痕字段：roll / roll_gap。
      · 新增 ROLLOVER_EXCLUDE：日橡胶 / 新加坡铁矿石 / 伦敦银现货 不参与通道2
        （它们的起始价有专门来源，不是当段分时表）。

  - 换月检测判据重写（v1.14）：
      · 新判据：**最新价是否跑到【当段分时表】的价格区间之外**（±0.5% 容差）。
        同一段分时表必然是同一个合约 → 最新价理应落在它的 [min,max] 内；
        跑出去就说明两个数据源切合约不同步 = 换月。
      · 为什么废掉旧判据：新浪日K在换月点附近【自身数据矛盾】（实测布伦特 10-02 那根
        "低>开"、伦铝 10-09 那根"高<开"），拿它当区间不可靠；而且"最近 2 根"
        会把换月前那根【老合约】包进来、把区间撑宽 → 系统性漏检（回测 2/4 漏检）。
      · 新增手工覆盖表 ROLLOVER_OVERRIDE（自动检测失灵时按品种强制按换月处理）。
      · 修正动作不变：参考价 := 昨结算；起始时间列标「换月」。
      · 保护：分时表点数 < 3、区间幅度 < 0.2%、或表末根距今 > 30 分钟（时段已滚动）时不判。

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

# v1.14: 手工换月覆盖表 {品种名: True} —— 自动检测失灵时，把品种名填进来即可强制按换月处理
#   （基准 := 昨结算，起始时间列标「昨结 换月」）。
ROLLOVER_OVERRIDE = {}

# v1.15: 明确【不参与】"起始价换月检测"的品种 —— 它们的起始价有专门来源，不是当段分时表：
#   日橡胶（day 档取当天日K收盘价）、新加坡铁矿石（可能走日K兜底）、伦敦银现货（可能走 5 日线兜底）。
#   少了这张表，它们会被误判成换月。
ROLLOVER_EXCLUDE = {
    '日橡胶': True,
    '新加坡铁矿石': True,
    '伦敦银现货': True,
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
    # v2.19: 富时A50（SGX，用户要求倒数第4）。组 A50 = 独立双窗口（09:30 前对比昨日 15:00 /
    # 11:30-13:00 对比今日 11:30），窗口外整行隐藏。无东财 secid —— 东财 104.CN00Y 是
    # "期指当月连续"拼接口径，与新浪 hf_CHA50CFD 的主连行情不同源，混用会出假涨跌。
    # 参考价兜底链全部走新浪系（分时 / 日K / 继承）。
    ('富时A50',      'A50',   None,         'hf_CHA50CFD'),
]
GROUP_CLOSE = {'M23': (23, 0), 'M01': (1, 0), 'M0230': (2, 30)}
GROUPS = ['M23', 'M01', 'M0230']
# v2.19: 富时A50 走 A50_GROUP 专属双窗口（a50_window），不进 GROUPS（无固定收盘节点）
INDEX_SECIDS = {'100.SPX', '100.DJIA', '100.NDX'}
# v1.2: 美股指数 → 新浪美股日K symbol（展示"最近一根已收盘日线"的开盘→收盘）
US_INDEX_MAP = {'100.SPX': '.INX', '100.DJIA': '.DJI', '100.NDX': '.IXIC'}
# v2.18: 美股三指数的名称集合 / 名称反查 secid / 腾讯备源符号
US_INDEX_NAMES = {'标准普尔', '道琼工业', '纳斯达克'}
US_INDEX_SECID_BY_NAME = {name: sid for name, group, sid, sina_code in VARIETIES
                          if sid in US_INDEX_MAP}
TX_SYMBOL_BY_SINA = {'.INX': 'usINX', '.DJI': 'usDJI', '.IXIC': 'usIXIC'}

# ---------------- HTTP ----------------
SINA_HEADERS = {'Referer': 'https://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
EM_HEADERS = {'Referer': 'https://quote.eastmoney.com',
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
TX_HEADERS = {'Referer': 'https://gu.qq.com/',
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

def rollover_suspect(bars, last, now, tol=0.005, min_span=0.002, max_age_min=30):
    """v1.14: 换月嫌疑判定 —— 最新价是否跑到【当段分时表】的价格区间之外。

    原理（物理必然）：同一段分时表 = 同一个合约，所以"当前所有成交价"必然落在
    该分时表的 [min, max] 之内。若"最新价"跑出去了，说明参考价所在的数据源与
    最新价所在的数据源切合约不同步 —— 这就是换月。

    为什么不用日K区间（v1.9 的老判据）：
      · 新浪日K在换月点附近【自身数据矛盾】（实测：布伦特 10-02 那根"低>开"，
        伦铝 10-09 那根"高<开"），拿它当区间不可靠；
      · 且"最近 2 根"会把换月前那根【老合约】包进来，区间被撑宽 → 系统性漏检。

    返回 (是否可疑, 说明文字)。"""
    if not bars or last is None or len(bars) < 3:
        return False, ''
    lo = min(p for _dt, p in bars)
    hi = max(p for _dt, p in bars)
    if hi <= 0 or (hi - lo) / hi < min_span:
        return False, ''            # 区间过窄（表刚重置 / 极稀疏）→ 不可靠，不判
    last_dt = bars[-1][0]
    age_min = (now - last_dt).total_seconds() / 60.0
    if age_min > max_age_min:
        return False, ''            # 表本身已经"不新鲜"（如时段已滚动）→ 不是换月，不判
    if lo * (1 - tol) <= last <= hi * (1 + tol):
        return False, ''
    return True, '最新价 %s 落在分时表区间 [%s, %s] 之外' % (last, lo, hi)

def rollover_suspect_close(bars, close, ps, exclude=False,
                           tol=0.005, min_span=0.002, fix_pct=0.025, watch_pct=0.015):
    """v1.15: 【起始价 close】的换月嫌疑判定 —— 覆盖"参考价跨换月线被继承钉住"这一真实机制。

    为什么要补这条（v1.14 的缺口）：
      v1.14 只检查【最新价】是否跑出当段分时表区间，覆盖的是"分时表与快照切合约不同步"的瞬间。
      但真实事故（2026-10-16 美燃油）不是这样：表和新快照**都已经切到新合约**，
      失真的是【起始价】—— 它跨过换月线后被"续接继承"机制钉成了老合约价
      （close=4.834 老合约、last=4.596 新合约、昨结 ps=4.654），于是每轮都不触发。

    close 正常时有三种来源，都不该"既跑出当段表区间、又远离当前合约的昨结算"：
      · 取自当段分时表 → 必在区间内；
      · 特判规则（日胶日K / 铁矿 / 银现货 5 日线）→ 这些品种已在 ROLLOVER_EXCLUDE 里排除；
      · 跨时段继承 → 继承的是【同一合约】的历史价，与昨结算的差就是真实隔夜波动（通常 <1.5%）。
    只有"继承来的老合约价"会同时满足：跑出区间 + 明显远离昨结算。

    双阈值分级（避免把正确的继承值改错）：
      · 偏离 >= 2.5% → 'fix'   自动修正（高置信度，如美燃油案例 3.87%）
      · 偏离 1.5%~2.5% → 'watch' 只记录嫌疑、不动数值（供观察，零风险）
    返回 (级别, 偏离比例, 说明文字)。"""
    if exclude or not bars or close is None or ps is None or ps <= 0 or len(bars) < 3:
        return None, None, ''
    lo = min(p for _dt, p in bars)
    hi = max(p for _dt, p in bars)
    if hi <= 0 or (hi - lo) / hi < min_span:
        return None, None, ''          # 区间过窄 → 不可靠
    if lo * (1 - tol) <= close <= hi * (1 + tol):
        return None, None, ''          # 起始价就在当段区间内 → 正常
    gap = abs(close - ps) / ps
    if gap >= fix_pct:
        return 'fix', gap, '起始价 %s 跑出分时表区间 [%s, %s] 且偏离昨结 %s 达 %.2f%%' % (
            close, lo, hi, ps, gap * 100)
    if gap >= watch_pct:
        return 'watch', gap, '起始价 %s 跑出分时表区间 [%s, %s]、偏离昨结 %.2f%%（只记录不发动作）' % (
            close, lo, hi, gap * 100)
    return None, None, ''

def _snap_gap_min(a, b):
    """v1.16.3: 两个快照时刻相差几分钟（处理跨午夜；解析失败返回 None）。"""
    try:
        da = datetime.strptime(a['date'] + ' ' + a['time'], '%Y-%m-%d %H:%M:%S')
        db = datetime.strptime(b['date'] + ' ' + b['time'], '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None
    gap = abs((da - db).total_seconds())
    return min(gap, 86400 - gap) / 60.0


def sina_active_contracts(sina_map, now):
    """v1.16: 锚定法——枚举候选月份合约快照，找"与主连同价同刻"者 = 当前主力合约。

    原理（物理必然）：主连 hf_XXX 的行情流就是当前主力合约的行情流，
    所以必然存在某个月份合约 hf_XXXYYMM 与主连【同一秒、同一价】。
    判据分级：
      · 强判据：快照时间戳相差 <= 3 秒 且 价差 <= 0.3% → 直接认定；
      · 弱判据：价差 <= 0.2% 的【最小者】（收盘静止期时间戳各自停在不同时刻时用），
        且与主连时间差 <= 2 分钟。
    v1.16.3 修误判（2026-10-19 美黄金 GC2612 被判成 GC2610）：
      · 新增新鲜度闸门——报价时刻落后主连 > 20 分钟的合约是"僵尸报价"
        （GC2610 停在 19:14、主连已 20:24，价差 0.25% 恰好落在弱判据区间），
        价格再接近也不得当主力；
      · 弱判据由"第一个命中者"改为"价差最小者"——原实现先到先得，
        GC2610 排在候选第一位，一旦命中 0.2% 就会抢占锚，后面更接近的
        GC2612 不再替换；
      · 强判据由"秒级完全相同"放宽到 <= 3 秒——新浪各合约快照常差 1 秒，
        原判据在跨秒瞬间失效，正是这次误判的入口。
    判不出的品种不进结果（调用方跳过，走原有价格区间检测兜底）。

    返回 {sym: {'contract': 'CL2612', 'prev_settle': float|None}}。"""
    out = {}
    syms = sorted({c[3:] for c in sina_map if c.startswith('hf_')})
    for sym in syms:
        main_q = sina_map.get('hf_' + sym)
        if not main_q or not main_q.get('last'):
            continue
        y, m = now.year, now.month
        cand_codes = []
        # 本月起 6 个月，跨年进位。窗口要宽：主力不一定是次月——
        # 实测美天然气 2026-10-19 主力已是 NG2701（跳过 2611/2612），
        # 国内外都存在"跨多月换月"，窗口窄了会判不出 = 换月漏检。
        for k in range(6):
            mm = (m - 1 + k) % 12 + 1
            yy = y + (m - 1 + k) // 12
            cand_codes.append(f'hf_{sym}{yy % 100:02d}{mm:02d}')
        try:
            cands = sina_snapshot(cand_codes)
        except Exception:
            continue
        cent = ('hf_' + sym) in SINA_CENT_TO_DOLLAR   # 美铜：候选合约同样是美分，比较前换算
        best_weak = None                 # (gap, code) —— 取价差最小者，而非第一个命中者
        found = None
        for cc in cand_codes:
            q = cands.get(cc)
            if not q or not q.get('last'):
                continue
            qlast = q['last'] / 100.0 if cent else q['last']
            mlast = main_q['last'] / 100.0 if cent else main_q['last']
            gap = abs(qlast - mlast) / mlast if mlast else 1.0
            lag = _snap_gap_min(q, main_q)
            if lag is not None and lag > 20:
                continue                   # 僵尸报价：与主连脱节太久，不参与锚定
            if q.get('date') == main_q.get('date') and gap <= 0.003 \
                    and (lag is None or lag * 60 <= 3):
                found = cc                     # 同价且同刻（容 3 秒）= 铁证
                break
            if gap <= 0.002 and (lag is None or lag <= 2) \
                    and (best_weak is None or gap < best_weak[0]):
                best_weak = (gap, cc)
        if found is None and best_weak:
            found = best_weak[1]
        if found:
            q = cands[found]
            ps = q.get('prev_settle')
            if ps is not None and cent:
                ps /= 100.0
            out[sym] = {'contract': found[3:], 'prev_settle': ps}
        time.sleep(0.2)                        # 温和请求
    return out

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

def _us_bar_closed(dstr, now):
    """v2.18: 该日线是否已收盘 —— 日线日期(美东)的次日北京 05:30 之后（覆盖夏/冬令时收盘差）"""
    try:
        d = datetime.strptime(dstr, '%Y-%m-%d')
    except (ValueError, TypeError):
        return False
    return now >= d + timedelta(days=1, hours=5, minutes=30)

def _us_series_from_sina(symbol, now, limit):
    """v2.18: 新浪美股日K（主源）。带时间戳参数破缓存，返回已收盘日线 [(date, close)] 升序。"""
    u = ('https://stock2.finance.sina.com.cn/usstock/api/jsonp.php/var%20d=/'
         f'US_MinKService.getDailyK?symbol={symbol}&_={int(time.time() * 1000)}')
    txt = http_get(u, SINA_HEADERS, timeout=12)
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
    for k in arr:
        try:
            d, c = k['d'], float(k['c'])
        except (KeyError, ValueError, TypeError):
            continue
        if _us_bar_closed(d, now):
            out.append((d, c))
    out.sort()
    return out[-limit:]

def _us_series_from_tx(symbol, now, limit):
    """v2.18: 腾讯美股日K（备源）。实测三指数收盘与新浪逐位一致。
    数组格式：[日期, 开, 收, 高, 低, 量, ...]（第 3 个字段是收盘）。"""
    u = ('https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get'
         f'?_var=kline_dayqfq&param={symbol},day,,,{max(limit, 12)},qfq'
         f'&_={int(time.time() * 1000)}')
    txt = http_get(u, TX_HEADERS, timeout=8)
    try:
        j = json.loads(txt)
    except Exception:
        m = re.search(r'=\s*(\{.*\})', txt, re.S)
        if not m:
            return []
        try:
            j = json.loads(m.group(1))
        except Exception:
            return []
    node = (j.get('data') or {}).get(symbol) or {}
    arr = node.get('day') or node.get('qfqday') or []
    out = []
    for b in arr:
        try:
            d, c = b[0], float(b[2])
        except (IndexError, ValueError, TypeError):
            continue
        if _us_bar_closed(d, now):
            out.append((d, c))
    out.sort()
    return out[-limit:]

def us_daily_series(symbol, now, limit=8, want_last=None, quiet=False):
    """v2.18: 单个美股指数已收盘日线（升序）。
    主源新浪重试 3 次（4s / 8s 退避），仍拿不到期望日期就切腾讯重试 2 次。
    want_last='YYYY-MM-DD'：期望的最新日线日期；不传则拿到就返回（旧行为）。"""
    best = []
    for i in range(3):
        try:
            s = _us_series_from_sina(symbol, now, limit)
        except Exception as e:
            s = []
            if not quiet:
                print(f'  新浪日K({symbol})第{i + 1}次失败: {type(e).__name__}')
        if s and (not best or s[-1][0] >= best[-1][0]):
            best = s
        if s and (not want_last or s[-1][0] >= want_last):
            return s
        if i < 2:
            time.sleep(4 + 4 * i)
    for i in range(2):
        try:
            t = _us_series_from_tx(TX_SYMBOL_BY_SINA.get(symbol, symbol), now, limit)
        except Exception as e:
            t = []
            if not quiet:
                print(f'  腾讯日K({symbol})第{i + 1}次失败: {type(e).__name__}')
        if t and (not best or t[-1][0] >= best[-1][0]):
            best = t
        if t and (not want_last or t[-1][0] >= want_last):
            if not quiet:
                print(f'  腾讯日K({symbol})接管 -> {t[-1][0]}')
            return t
        if i < 1:
            time.sleep(3)
    if want_last and not quiet:
        print(f'  日线未达期望 {want_last}（{symbol} 手上最新 {best[-1][0] if best else "无"}）')
    return best

def us_index_daily_bars(symbol, now, n=2, want_last=None):
    """v2.18: 取最近 n 根【已收盘】美股指数日线 → [(日期str, 收盘价), ...]（升序，新的在后）。
    多源：新浪为主 + 腾讯兜底；want_last 让调用方指定"至少要拿到哪一天"。"""
    s = us_daily_series(symbol, now, limit=max(n + 6, 8), want_last=want_last)
    return s[-n:] if len(s) >= n else []

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

def align_us_index_rows(rows, now, quiet=False):
    """v2.18: 美股三行「同批对齐」—— 解决"标普/道指已到 10-19、纳指还停在 10-16"。
    事故（2026-10-20 早盘）：07:45 --us-only 轮与 08:00 完整轮跑的时候，新浪 .IXIC
    的 10-19 日线尚未落库（.INX/.DJI 已落库），于是纳指按 10-15→10-16 两根算出 -2.15%
    （实际 10-19 是 +1.11%），表里混了两种口径。既有的「防回退」只在比上一版更旧时
    触发，同批不同步它管不到。
    处理：① 落后行定向重抓（want_last=本批最新日期，新浪重试 + 腾讯兜底）；
         ② 仍不齐 → 三行统一退到共同最新日（宁可旧一天，也不让同一张表混两种口径）。
    返回：被修正的行数。"""
    idx = [(i, r) for i, r in enumerate(rows) if r.get('name') in US_INDEX_NAMES]
    if len(idx) < 2:
        return 0
    dmap = {i: us_ref_date(r.get('ref'), now.date()) for i, r in idx}
    known = [d for d in dmap.values() if d]
    if not known:
        return 0
    max_d = max(known)
    if len(set(known)) == 1:
        return 0
    if not quiet:
        _ds = ', '.join(sorted(d.strftime('%m-%d') for d in known))
        print(f'美股对齐: 本轮日期不齐 [{_ds}]，以 {max_d:%m-%d} 为目标补齐')
    fixed = 0
    for i, r in idx:
        d = dmap[i]
        if d and d >= max_d:
            continue
        secid = US_INDEX_SECID_BY_NAME.get(r['name'])
        if not secid:
            continue
        try:
            bars = us_index_daily_bars(US_INDEX_MAP[secid], now, 2,
                                       want_last=max_d.strftime('%Y-%m-%d'))
        except Exception as e:
            bars = []
            if not quiet:
                print(f"  对齐取数失败({r['name']}): {type(e).__name__}")
        if len(bars) < 2:
            continue
        (d_prev, c_prev), (d_last, c_last) = bars
        nd = us_ref_date(f'{d_last[5:]}美', now.date())
        if nd and nd >= max_d:
            r['close'], r['last'], r['ref'] = c_prev, c_last, f'{d_last[5:]}美'
            r['chg'] = c_last - c_prev
            r['pct'] = r['chg'] / c_prev * 100 if c_prev else None
            r['flag'], r['note'] = False, ''
            dmap[i] = nd
            fixed += 1
            if not quiet:
                print(f"美股对齐: {r['name']} 补齐 -> {r['ref']}（{c_prev} → {c_last}）")
    # ② 仍有落后行（两个源都没这一根）→ 整组退到共同最新日，保证表内口径一致
    known2 = [d for d in dmap.values() if d]
    if len(set(known2)) > 1:
        common = min(known2)
        if not quiet:
            _ds2 = ', '.join(sorted(d.strftime('%m-%d') for d in known2))
            print(f'美股对齐: 仍不齐 [{_ds2}]，统一退到 {common:%m-%d}')
        for i, r in idx:
            if dmap.get(i) == common:
                continue
            secid = US_INDEX_SECID_BY_NAME.get(r['name'])
            if not secid:
                continue
            try:
                series = us_daily_series(US_INDEX_MAP[secid], now, limit=10, quiet=True)
            except Exception:
                series = []
            part = [x for x in series if x[0] <= common.strftime('%Y-%m-%d')][-2:]
            if len(part) < 2:
                continue
            (d_prev, c_prev), (d_last, c_last) = part
            r['close'], r['last'], r['ref'] = c_prev, c_last, f'{d_last[5:]}美'
            r['chg'] = c_last - c_prev
            r['pct'] = r['chg'] / c_prev * 100 if c_prev else None
            r['note'] = '滞后'
            dmap[i] = us_ref_date(r['ref'], now.date())
            fixed += 1
            if not quiet:
                print(f"美股对齐: {r['name']} 退到 {r['ref']}（标「滞后」）")
    return fixed

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

# v2.19: 富时A50 显示窗口 —— 用户看盘点与 A50 自身时段错位，单独两个窗口：
#   窗口1：A股 09:30 开盘前（05:20-09:30）→ 对比【前一交易日 15:00】的价
#   窗口2：11:30-13:00（A股午休，下午开盘前）→ 对比【今日 11:30】的价
#   其余时段不显示该行（无看盘意义，A50 16:35 收盘、17:00 接 T+1 段）。
A50_GROUP = 'A50'
def a50_window(now, trade_days):
    """富时A50 当前窗口 → ('ref15prev' | 'ref1130', ref_dt, label) 或 None（窗口外不显示）。
    ref15prev 的 ref_dt = 前一交易日 15:00（按交易日历回退）；ref1130 = 今日 11:30。
    周末/非交易日两个窗口都不显示（前一交易日的 15:00 对当天开盘参考意义弱，保持简洁）。"""
    today = now.date().isoformat()
    is_trade = (today in trade_days) if trade_days else (now.weekday() < 5)
    if not is_trade:
        return None
    t = now.hour * 60 + now.minute
    # 窗口2：11:30 - 13:00（13:00 A股午盘开盘，之后看盘意义弱化 → 隐藏）
    if 11 * 60 + 30 <= t < 13 * 60:
        return 'ref1130', now.replace(hour=11, minute=30, second=0, microsecond=0), '11:30'
    # 窗口1：05:20（夜盘段临近尾声）- 09:30（A股开盘）
    if 5 * 60 + 20 <= t < 9 * 60 + 30:
        # 前一交易日 15:00：今天往前找最近一个交易日
        cand = now.replace(hour=15, minute=0, second=0, microsecond=0)
        cand -= timedelta(days=1)
        for _ in range(20):
            ok = (cand.date().isoformat() in trade_days) if trade_days else (cand.weekday() < 5)
            if ok:
                return 'ref15prev', cand, '15:00'
            cand -= timedelta(days=1)
    return None

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

    # v1.9.2 → v1.16.1: 节点等待泛化到全部档位 —— 配套 fetch.yml 的"提前 30 分钟
    # 预触发"策略（GitHub 定时排队延迟实测 26~36 分钟，预触发把延迟吃进触发点）。
    # 预轮若提前落地，此时基准价还没产出；等待到"节点+1 分 05 秒"再继续取价。
    # 各档目标：10:15→10:16:05 / 11:30→11:31:05 / 15:00→15:01:05 /
    #           23:00→23:01:05 / 01:00→01:01:05 / 02:30→02:31:05
    for _hh, _mm in ((10, 16), (11, 31), (15, 1), (23, 1), (1, 1), (2, 31)):
        _t = now.replace(hour=_hh, minute=_mm, second=5, microsecond=0)
        if timedelta(0) < (_t - now) <= timedelta(minutes=32):
            print(f'预轮等待: 本轮于 {now:%H:%M:%S} 提前执行，等待至 {_hh:02d}:{_mm:02d}:05 再取价')
            time.sleep((_t - now).total_seconds())
            now = now_cn()
            print(f'等待结束，现在: {now:%Y-%m-%d %H:%M:%S}')
            break

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

    # v2.19: 富时A50 独立双窗口（与商品档位无关）：
    #   09:30 前对比【前一交易日 15:00】；11:30-13:00 对比【今日 11:30】；其余窗口=None（整行隐藏）。
    a50_win = a50_window(now, trade_days)
    if a50_win:
        print(f"A50窗口: {a50_win[0]} ref={a50_win[1]:%m-%d %H:%M}（{a50_win[2]}）")
    else:
        print('A50窗口: 外（本行隐藏）')

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

    # v1.16: 主力合约锚定 —— 枚举候选月份合约，找与主连"同价同刻"者。
    # 结果每轮写入 data.json 顶层 contracts，下一轮比对：变了 = 换月。
    try:
        contracts_now = sina_active_contracts(sina_map, now)
    except Exception as e:
        print(f'主力锚定失败({type(e).__name__})')
        contracts_now = {}
    if contracts_now:
        print('主力锚定:', {s: i['contract'] for s, i in contracts_now.items()})

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
    # v1.16: 同时读顶层 contracts（上一轮的主力合约锚），供换月判定。
    prev_rows = []
    prev_contracts = {}
    prev_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')
    try:
        with open(prev_path, encoding='utf-8') as f:
            _prev_data = json.load(f) or {}
        prev_rows = _prev_data.get('rows') or []
        prev_contracts = _prev_data.get('contracts') or {}
        print(f'续接: 读到上一版 data.json, {len(prev_rows)} 行, 合约锚 {len(prev_contracts)} 个')
    except Exception:
        prev_rows, prev_contracts = [], {}
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

    # v1.16: 换月集合 = {sym: (旧合约, 新合约)}，本轮锚 vs 上一轮锚。
    # 锚定判不出的品种不进集合（走旧价格区间通道兜底）；首轮回无锚可比对，自然为空。
    rollover_syms = {}
    for _sym, _info in contracts_now.items():
        _pc = prev_contracts.get(_sym)
        if _pc and _pc != _info['contract']:
            rollover_syms[_sym] = (_pc, _info['contract'])
    if rollover_syms:
        print(f'换月判定(锚定法): {rollover_syms}')

    # 组装行
    rows = []
    for name, group, secid, sina_code in VARIETIES:
        if '原油' in name and mode != 'night' and name.endswith('(02:30)'):
            continue   # 单行档（15:00 / 10:15 / 11:30）：原油只显示一行
        if '原油' in name:
            # 名称不带组标记；两行时的区分（23:00 / 02:30）由「起始时间」列呈现
            name = name.split('(')[0]
        # v2.19: 富时A50 —— 独立双窗口，窗口外整行跳过（不产生任何行数据）
        if group == A50_GROUP:
            if not a50_win:
                continue
            a50_kind, a50_ref_dt, a50_label = a50_win
            ref_dt, ref_show = a50_ref_dt, a50_ref_dt
        else:
            a50_kind = None
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
        elif name == '富时A50':
            # v2.19: A50 双窗口取价（SGX T+1 时段：17:00-05:15 夜段 + 09:00-16:35 日段）。
            #   MinLine 的表 = "当前交易时段"（09:00 新日段开盘时滚动），每天只有一张：
            #   窗口2（11:30-13:00）今日 11:30 的笔就在当前表里 → 直接按节点取；
            #   窗口1（09:30 前）"前一交易日 15:00"在上一张已滚动的表里 → 当前表取不到，
            #   兜底链：MinLine(≤15:00 最后一笔, 覆盖"表尚未滚动"的清晨轮次)
            #         → 日K前一交易日那根 close（16:35 收盘口径，时间跨度略长但方向正确）
            #         → v1.8 继承（同 ref 沿用上一轮云端值）。
            if bars_ml:
                try:
                    close, st, hit_dt = ref_price_from_bars(bars_ml, ref_dt, max_gap_hours=40,
                                                            now=now, allow_stale=True)
                except Exception:
                    close = None
            if close is None and a50_kind == 'ref15prev':
                # 日K兜底：前一交易日那根 close = 16:35 收盘。仅窗口1用（有总比缺好）；
                # ref_text 标注真实口径（15:00笔取不到时显示 16:35 收盘），不冒充 15:00。
                try:
                    _d, _c = sina_dailyk_closed_bar('CHA50CFD', now, exclude_today=True)
                    if _c is not None and _d == ref_dt.date().isoformat():
                        close = _c
                        ref_text = f'{ref_dt:%m-%d} 16:35收'
                        hit_dt = ref_dt.replace(hour=16, minute=35)
                except Exception:
                    close = None
            if close is None:
                note = '缺'   # v1.8 继承机制按同 ref 顶住
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
    us_index_names = US_INDEX_NAMES   # v2.18: 提升为模块级常量
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
        if p.get('roll') == 'fix':
            # v1.16: 换月修正行的继承要连"换月"身份一起继承 ——
            # 否则下一轮页面小标消失，且 close 仍是修正口径却没了说明
            row['roll'] = 'fix'
            row['note'] = '换月'
        elif row.get('note') == '缺':
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

    # ---------------- v2.18：美股三行同批对齐 ----------------
    # 放在防回退之后：对齐可能有意把某行退到共同日期，不能再被防回退拉回去。
    align_us_index_rows(rows, now)

    # ---------------- v1.16：换月修正（锚定法，优先于旧价格区间检测） ----------------
    # 判据：本轮主力合约锚 != 上一轮锚（用户方案：CL0 等价的具体合约变了 = 换月）。
    # 处理（两步，优先"穿越换月"而不是简单打补丁）：
    #   ① 拉【新合约】自己的当日分时表，按本行参考时点重新取价
    #      —— 新合约在换月前也在交易，能拿到"那个时点的新合约真实价"，
    #      涨跌口径无缝连续，「起始时间」列保持原时点不变；
    #   ② 分时取不到（远月流动性差等）→ 退化为：参考价 := 新合约昨结算，
    #      「起始时间」列标「换月」。
    # 锚定法覆盖的品种不再走 v1.9/v1.14/v1.15 的旧价格区间检测（避免旧判据误伤）。
    roll16_fix = 0
    bars_by_contract = {}   # 新合约分时表缓存：contract -> [(dt, price)]
    for row in rows:
        code = row.get('code')
        if not code or not code.startswith('hf_'):
            continue
        sym = code[3:]
        if sym not in rollover_syms:
            continue
        old_c, new_c = rollover_syms[sym]
        ref_dt = None
        _m = re.match(r'^(\d{2})-(\d{2}) (\d{2}):(\d{2})$', row.get('ref') or '')
        if _m:
            try:
                ref_dt = now.replace(month=int(_m.group(1)), day=int(_m.group(2)),
                                     hour=int(_m.group(3)), minute=int(_m.group(4)),
                                     second=0, microsecond=0)
                if (ref_dt - now).days > 180:
                    ref_dt = ref_dt.replace(year=ref_dt.year - 1)
                elif (now - ref_dt).days > 180:
                    ref_dt = ref_dt.replace(year=ref_dt.year + 1)
            except ValueError:
                ref_dt = None
        new_close, new_hit = None, None
        if ref_dt is not None:
            if new_c not in bars_by_contract:
                try:
                    bars_by_contract[new_c] = sina_minline_today(new_c)
                except Exception:
                    bars_by_contract[new_c] = []
            _bc = bars_by_contract[new_c]
            if _bc:
                try:
                    new_close, _st, new_hit = ref_price_from_bars(
                        _bc, ref_dt, max_gap_hours=26, now=now, allow_stale=True)
                except Exception:
                    new_close = None
        if new_close is not None:
            # ① 穿越成功：参考价 = 新合约在原时点的真实价，ref 文本保持原时点
            row['close'] = new_close
            row['note'] = '换月'
            row['roll'] = 'fix'
            row['ref_actual'] = f'{new_hit:%m-%d %H:%M}' if new_hit else None
            row['gap_min'] = (int(round((ref_dt - new_hit).total_seconds() / 60.0))
                              if new_hit and ref_dt else None)
        else:
            # ② 退化：参考价 := 新合约昨结算（优先合约快照的昨结，其次主连快照昨结）
            ps = (contracts_now.get(sym) or {}).get('prev_settle') \
                or (sina_map.get(code) or {}).get('prev_settle')
            if not ps or ps <= 0:
                print(f'换月修正跳过(无昨结): {row["name"]}')
                continue
            row['close'] = ps
            row['ref'] = '换月'
            row['note'] = '换月'
            row['roll'] = 'fix'
            row['ref_actual'] = None
            row['gap_min'] = None
        if row['last'] is not None and row['close'] > 0:
            row['chg'] = row['last'] - row['close']
            row['pct'] = row['chg'] / row['close'] * 100
        roll16_fix += 1
        print(f"换月修正(锚定法): {row['name']} {old_c}→{new_c}，参考价 -> {row['close']}")
    if roll16_fix:
        print(f'换月修正(锚定法): {roll16_fix} 行')

    # v1.16.2: 换月去重 —— 原油这类同品种分两档（23:00 / 02:30）的品种，
    # 换月修正后两行都退化为「同一个新合约昨结 + 同一个最新价」，数字完全重复，
    # 页面上并排显示两条毫无意义（用户要求只留一条）。
    # 判定严格：同 code + 都 roll='fix' + close/last/chg 全等才去重；
    # 正常轮次两档参考时点不同、价格不同，绝不会触发。
    _seen_dup = {}
    _dedup_rows = []
    for row in rows:
        if row.get('roll') == 'fix' and row.get('code'):
            _k = (row['code'], row.get('close'), row.get('last'), row.get('chg'))
            if _k in _seen_dup:
                print(f"换月去重: {row['name']}（{row.get('ref')}）与上一条数值全等，去掉重复行")
                continue
            _seen_dup[_k] = True
        _dedup_rows.append(row)
    rows = _dedup_rows

    # ---------------- v1.9：换月检测（参考价失真自动修正） ----------------
    # 主连换月时，若"参考时点"落在换月前（参考价=老合约价），而行情已切到新合约，
    # 页面涨跌幅会失真（例：2026-10-16 美燃油 老合约 4.834 vs 新合约 4.596，
    # 显示假跌 -4.9%，实际约 -1.3%）。v1.14 起判据已重写（见 rollover_suspect）：
    #   ① 参考价与快照"昨结算"（当前合约）偏离 > 2%；
    #   ② 参考价不在最近 2 根日K的 [min(low), max(high)] 区间内（±0.5% 容差）。
    # 修正：参考价 := 昨结；ref := '昨结'（页面"起始时间"列显示该标注）；note := '换月'。
    # v2.19: 富时A50 不参与旧通道（它的"参考价"是双窗口口径，不来自当段分时表的连续价，
    # 偏离昨结是常态 —— 例：窗口1 的基准是昨日 15:00/16:35，与昨结 16:35 收盘本就不同）。
    # A50 换月完全依赖锚定法（hf_CHA50CFD 实测能锚到具体月份合约）。
    month_fix = 0
    month_watch = 0
    for row in rows:
        code = row.get('code')
        if not code or row.get('close') is None:
            continue
        sym = code[3:] if code.startswith('hf_') else code
        # v1.16: 锚定法已覆盖的品种（判得出当前主力合约）不再走旧价格区间检测 ——
        # 旧判据依赖"分时表=同一合约"假设，换月点在时段中段时会系统性失效；
        # 锚定法说没换月就是没换月，不让旧通道的结论盖过它。
        if sym in contracts_now:
            continue
        if row['name'] == '富时A50':
            continue   # v2.19: 双窗口口径不适用旧通道，换月全靠锚定法
        if '换月' in (row.get('note') or ''):
            continue   # 本轮已被锚定法修正过
        bars_row = ml_by_sym.get(sym) or []
        ps = (sina_map.get(code) or {}).get('prev_settle')

        # 通道1（v1.14）：最新价跑出当段分时表区间 → 两源切合约不同步
        suspect, why = rollover_suspect(bars_row, row.get('last'), now)
        level = 'fix' if suspect else None

        # 通道2（v1.15）：起始价跑出区间 + 明显偏离昨结 → 跨换月线被继承钉住
        if level != 'fix':
            lv2, gap2, why2 = rollover_suspect_close(
                bars_row, row.get('close'), ps,
                exclude=bool(ROLLOVER_EXCLUDE.get(row['name'])))
            if lv2:
                level, why = lv2, why2
                row['roll_gap'] = round(gap2 * 100, 2)

        # 手工覆盖
        if not level and row['name'] in ROLLOVER_OVERRIDE:
            level, why = 'fix', '手工覆盖表指定'

        if level == 'watch':
            row['roll'] = 'watch'      # 只留痕，不动数值（零风险观察档）
            month_watch += 1
            print('换月观察: %s（%s）' % (row['name'], why))
            continue
        if level != 'fix':
            continue
        if not ps or ps <= 0:
            continue
        close = row['close']
        row['close'] = ps
        row['ref'] = '换月'   # v1.15.1: 用户要求——「起始时间」列只显示"换月"两个字
        row['note'] = '换月'
        row['ref_actual'] = None   # v1.10: "昨结算"不对应任何一笔分时，说明字段置空
        row['gap_min'] = None
        row['roll'] = 'fix'
        if row['last'] is not None:
            row['chg'] = row['last'] - ps
            row['pct'] = row['chg'] / ps * 100
        month_fix += 1
        print(f"换月修正: {row['name']} 参考价 {close} -> 昨结 {ps}（{why}）")
    if month_fix or month_watch:
        print(f'换月检测: {month_fix} 行已修正, {month_watch} 行只记录')
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
        # v2.16.1: 前端版本号 —— 页面拿它和自己内置的 UI_VER 比对，
        # 不一致就自动重载（解决"页面常驻打开时旧 JS 永远不更新"的问题）
        'ui': '2.19',
        'em_ok': em_ok,
        'sina_ok': sina_ok,
        'kline_fail': kline_fail,
        # v1.16: 主力合约锚（{sym: 'CL2612'}）。本轮判不出的品种沿用上一轮锚，
        # 保证"跨轮比对"不断链；页面顺带展示当前主力合约。
        'contracts': {**prev_contracts,
                      **{s: i['contract'] for s, i in contracts_now.items()}},
        'rows': rows,
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
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
    # v2.18: 同批对齐 —— 某一指数日线慢一拍时定向补齐（新浪重试 + 腾讯兜底），
    # 补齐后三行日期一致，避免表里混两种口径
    changed += align_us_index_rows(data.get('rows', []), now)
    if changed:
        with open(out, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(f'us-only 完成: {changed} 行更新, 已写入 {out}, 耗时 {time.time() - t0:.0f} 秒')
    else:
        print('us-only 完成: 无变化，不写文件')

if __name__ == '__main__':
    if '--us-only' in sys.argv:
        main_us_only()
    else:
        main()
