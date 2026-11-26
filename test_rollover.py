# -*- coding: utf-8 -*-
"""换月锚定与前端「切月中」判定的回归测试。

运行：python -m unittest -v test_rollover.py
前端测试需要 Node.js；未安装时只跳过该组，不影响 Python 判定测试。
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import fetch


NOW = datetime(2026, 10, 30, 20, 30)


def quote(last, prev_settle=790.0, volume=12345.0,
          time='20:00:00', date='2026-10-30'):
    return {
        'last': last,
        'prev_settle': prev_settle,
        'volume': volume,
        'time': time,
        'date': date,
    }


class SnapshotGapTests(unittest.TestCase):
    def test_full_datetime_difference_never_wraps(self):
        main = quote(800, time='20:00:00', date='2026-10-30')
        cases = [
            ('数日前旧报价', quote(800, time='19:59:00', date='2026-10-28'), 2881.0),
            ('近一天前旧报价', quote(800, time='20:01:00', date='2026-10-29'), 1439.0),
            ('跨午夜正向差', quote(800, time='00:01:00', date='2026-10-31'), 241.0),
            ('跨午夜反向差', quote(800, time='23:59:00', date='2026-10-29'), 1201.0),
        ]
        for name, candidate, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(fetch._snap_gap_min(candidate, main), expected)

    def test_invalid_datetime_is_unknown(self):
        main = quote(800)
        self.assertIsNone(fetch._snap_gap_min(quote(800, date=''), main))
        self.assertIsNone(fetch._snap_gap_min(quote(800, time=''), main))


class SnapshotParsingTests(unittest.TestCase):
    @patch('fetch.http_get')
    def test_copper_main_and_month_contract_share_units_and_volume(self, mock_get):
        """v1.24: 美铜改美分/磅口径 —— 新浪快照原值直用，主连与月份合约同尺度且保留成交量指纹。"""
        mock_get.return_value = (
            'var hq_str_hf_HG="652.456,,,,,,20:00:00,660.25,,12345,,,2026-10-30,";\n'
            'var hq_str_hf_HG2612="652.456,,,,,,20:00:00,660.25,,12345,,,2026-10-30,";'
        )
        snap = fetch.sina_snapshot(['hf_HG', 'hf_HG2612'])
        for code in ('hf_HG', 'hf_HG2612'):
            with self.subTest(code=code):
                self.assertAlmostEqual(snap[code]['last'], 652.456)
                self.assertAlmostEqual(snap[code]['prev_settle'], 660.25)
                self.assertEqual(snap[code]['volume'], 12345.0)

    @patch('fetch.http_get')
    def test_bad_last_only_skips_its_own_record(self, mock_get):
        mock_get.return_value = (
            'var hq_str_hf_CL="BAD,,,,,,20:00:00,88,,123,,,2026-10-30,";\n'
            'var hq_str_hf_FEF="89.42,,,,,,20:00:00,89.29,,123,,,2026-10-30,";'
        )
        snap = fetch.sina_snapshot(['hf_CL', 'hf_FEF'])
        self.assertNotIn('hf_CL', snap)
        self.assertEqual(snap['hf_FEF']['last'], 89.42)


class MinlineParsingTests(unittest.TestCase):
    @patch('fetch.http_get')
    def test_legacy_rows_roll_forward_across_midnight(self, mock_get):
        payload = {'result': {'data': {'minLine_1d': [
            ['2026-11-26', 'x', 'x', 'x', '23:59', '89.42'],
            ['00:01', '89.50'],
        ]}}}
        mock_get.return_value = 'var d=(' + json.dumps(payload) + ');'
        bars = fetch.sina_minline_today('FEF')
        self.assertEqual(bars, [
            (datetime(2026, 11, 26, 23, 59), 89.42),
            (datetime(2026, 11, 27, 0, 1), 89.50),
        ])


class RolloverFreshnessTests(unittest.TestCase):
    def test_close_channel_rejects_stale_intraday_table(self):
        bars = [(datetime(2026, 10, 30, 19, i), 98.0 + i) for i in range(3)]
        fresh_now = datetime(2026, 10, 30, 19, 30)
        level, _gap, _why = fetch.rollover_suspect_close(bars, 105, 100, now=fresh_now)
        self.assertEqual(level, 'fix')
        stale_now = fresh_now + timedelta(minutes=3)
        self.assertEqual(fetch.rollover_suspect_close(bars, 105, 100, now=stale_now),
                         (None, None, ''))


class MonthKlineTests(unittest.TestCase):
    @patch('fetch.http_get')
    def test_invalid_and_future_bars_do_not_set_range(self, mock_get):
        arr = [
            {'date': '2026-11-24', 'low': 100, 'high': 110},
            {'date': '2026-11-25', 'low': 120, 'high': 110},
            {'date': '2026-11-27', 'low': 1, 'high': 200},
            {'date': '2026-11-26', 'low': 105, 'high': 115},
        ]
        mock_get.return_value = 'var d=(' + json.dumps(arr) + ');'
        self.assertEqual(fetch.month_kline_range(
            'FEF2701', now=datetime(2026, 11, 26, 21, 17)), (100.0, 115.0))


class AtomicWriteTests(unittest.TestCase):
    def test_failed_write_preserves_previous_json_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'data.json'
            path.write_text('{"old": true}', encoding='utf-8')
            with patch('fetch.json.dump', side_effect=RuntimeError('disk full')):
                with self.assertRaises(RuntimeError):
                    fetch.write_json_atomic(str(path), {'new': True})
            self.assertEqual(path.read_text(encoding='utf-8'), '{"old": true}')
            self.assertEqual([p.name for p in Path(td).iterdir()], ['data.json'])


class EmCentUnitTests(unittest.TestCase):
    """v1.24: 东财美铜是美元/磅，入口必须 ×100 转美分，与新浪同口径。"""

    @patch('fetch.em_get_retry')
    def test_em_snapshot_scales_copper_to_cent(self, mock_get):
        import json as _json
        mock_get.return_value = _json.dumps({'data': {'diff': [
            {'f12': 'HG00Y', 'f2': 6.0135, 'f18': 6.0905},
            {'f12': 'CL00Y', 'f2': 87.5, 'f18': 88.0},     # 非美分品种不得被放大
        ]}})
        snap = fetch.em_snapshot(['101.HG00Y', '101.CL00Y'])
        self.assertAlmostEqual(snap['HG00Y']['last'], 601.35)
        self.assertAlmostEqual(snap['HG00Y']['prev_settle'], 609.05)
        self.assertAlmostEqual(snap['CL00Y']['last'], 87.5)


class ActiveContractTests(unittest.TestCase):
    def identify(self, main, candidates):
        with patch('fetch.sina_snapshot', return_value=candidates), \
                patch('fetch.time.sleep'):
            return fetch.sina_active_contracts({'hf_FEF': main}, NOW)

    def test_strong_candidates_scan_all_and_choose_exact_identity(self):
        """铁矿实录形态：2611 排前且近似，2612 才是字段完全一致的真主力。"""
        main = quote(800.0)
        candidates = {
            'hf_FEF2611': quote(800.8, prev_settle=789.0, volume=100.0),
            'hf_FEF2612': quote(800.0),
        }
        result = self.identify(main, candidates)
        self.assertEqual(result['FEF']['contract'], 'FEF2612')
        self.assertEqual(result['FEF']['prev_settle'], 790.0)
        self.assertNotEqual('FEF2611', result['FEF']['contract'],
                            '旧锚 2611 → 新锚 2612 应能被识别为真实换月')

    def test_weak_candidates_also_choose_best_score(self):
        main = quote(800.0)
        candidates = {
            'hf_FEF2611': quote(800.8, prev_settle=789.0, volume=100.0,
                                time='19:59:00'),
            'hf_FEF2612': quote(800.0, time='19:59:30'),
        }
        result = self.identify(main, candidates)
        self.assertEqual(result['FEF']['contract'], 'FEF2612')

    def test_fcpo_close_snapshot_near_price_is_not_contract_identity(self):
        """2026-11-02 收盘实录：2702 近价，但昨结和成交量都与主连不同。"""
        main = quote(4724.55, prev_settle=4748.0, volume=19444.0,
                     time='17:59:47', date='2026-11-02')
        candidates = {
            'hf_FCPO2701': quote(4648.80, prev_settle=4681.0, volume=91257.0,
                                 time='17:59:59', date='2026-11-02'),
            'hf_FCPO2702': quote(4732.24, prev_settle=4761.0, volume=35386.0,
                                 time='17:59:55', date='2026-11-02'),
            'hf_FCPO2703': quote(4800.72, prev_settle=4826.0, volume=39734.0,
                                 time='17:59:59', date='2026-11-02'),
        }
        self.assertEqual(self.identify(main, candidates), {},
                         '价差 0.163% 不能越过昨结、成交量双冲突单独认锚')

    def test_near_price_without_independent_fingerprint_never_anchors(self):
        main = quote(800.0, prev_settle=790.0, volume=12345.0)
        for name, candidate in [
            ('强判据时间命中', quote(800.8, prev_settle=789.0, volume=100.0)),
            ('弱判据时间命中', quote(800.8, prev_settle=789.0, volume=100.0,
                                   time='19:59:30')),
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.identify(main, {'hf_FEF2612': candidate}), {})

    def test_weak_anchor_accepts_volume_as_independent_fingerprint(self):
        main = quote(800.0, prev_settle=790.0, volume=12345.0)
        candidate = quote(800.8, prev_settle=789.0, volume=12345.0,
                          time='19:59:30')
        result = self.identify(main, {'hf_FEF2612': candidate})
        self.assertEqual(result['FEF']['contract'], 'FEF2612')

    def test_stale_and_unverifiable_candidates_never_anchor(self):
        main = quote(800.0)
        cases = [
            ('数日前僵尸合约', quote(800.0, time='19:59:00', date='2026-10-28')),
            ('近一天前僵尸合约', quote(800.0, time='20:01:00', date='2026-10-29')),
            ('超过二十分钟', quote(800.0, time='19:39:59')),
            ('日期无法解析', quote(800.0, date='')),
        ]
        for name, stale in cases:
            with self.subTest(name=name):
                candidates = {
                    'hf_FEF2611': stale,
                    'hf_FEF2612': quote(810.0),  # 价差过大，不能锚定
                }
                self.assertEqual(self.identify(main, candidates), {})

    def test_fresh_exact_candidate_still_anchors(self):
        result = self.identify(quote(800.0), {'hf_FEF2612': quote(800.0)})
        self.assertEqual(result['FEF']['contract'], 'FEF2612')
        self.assertEqual(result['FEF']['date'], '2026-10-30')

    def test_zero_position_on_both_sides_is_not_identity_evidence(self):
        main = quote(800.0, volume=0)
        candidate = quote(800.0, prev_settle=789.0, volume=0)
        self.assertEqual(self.identify(main, {'hf_FEF2612': candidate}), {})


class KlineRecheckIntegrationTests(unittest.TestCase):
    """完整跑主流程，重放 2026-11-26 铁矿同值误标，而不是只测一个判断助手。"""

    def run_recheck(self, replay_price):
        fixed_now = datetime(2026, 11, 26, 21, 17)
        main_bars = [(fixed_now.replace(hour=15, minute=0), 89.42)]
        replay_bars = [(fixed_now.replace(hour=15, minute=0), replay_price)]
        previous = {
            'contracts': {'FEF': 'FEF2701'},
            'rows': [{'name': '新加坡铁矿石', 'close': 89.42, 'last': 87.725,
                      'ref': '11-26 15:00', 'ref_actual': '11-26 15:00', 'gap_min': 0}],
        }
        with tempfile.TemporaryDirectory() as td:
            fake_file = str(Path(td) / 'fetch.py')
            (Path(td) / 'data.json').write_text(
                json.dumps(previous, ensure_ascii=False), encoding='utf-8')
            def minline(symbol):
                return main_bars if symbol == 'FEF' else replay_bars
            with patch('fetch.__file__', fake_file), \
                    patch('fetch.VARIETIES', [('新加坡铁矿石', 'M23', None, 'hf_FEF')]), \
                    patch('fetch.now_cn', return_value=fixed_now), \
                    patch('fetch.get_night_calendar', return_value=({'2026-11-26'}, {'2026-11-25'})), \
                    patch('fetch.sina_snapshot', return_value={'hf_FEF': quote(
                        87.725, prev_settle=89.29, volume=449123,
                        time='21:17:00', date='2026-11-26')}), \
                    patch('fetch.sina_active_contracts', return_value={'FEF': {
                        'contract': 'FEF2701', 'prev_settle': 89.29, 'date': '2026-11-26'}}), \
                    patch('fetch.em_snapshot', return_value={}), \
                    patch('fetch.sina_minline_today', side_effect=minline), \
                    patch('fetch.month_kline_range', return_value=(87.50, 89.35)), \
                    patch('fetch.time.sleep'):
                fetch.main()
            return json.loads((Path(td) / 'data.json').read_text(encoding='utf-8'))

    def test_same_replayed_price_does_not_invent_rollover(self):
        data = self.run_recheck(89.42)
        row = data['rows'][0]
        self.assertEqual(row['close'], 89.42)
        self.assertNotIn('roll', row)
        self.assertNotIn('roll_src', row)
        self.assertEqual(row['note'], '')
        self.assertEqual(row['ref_contract'], 'FEF2701')

    def test_real_contract_price_difference_still_fixes(self):
        data = self.run_recheck(89.10)
        row = data['rows'][0]
        self.assertEqual(row['close'], 89.10)
        self.assertEqual(row['roll'], 'fix')
        self.assertEqual(row['note'], '换月')


JS_HARNESS = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(process.argv[1], 'utf8');
function extract(startMarker, endMarker) {
  const start = html.indexOf(startMarker);
  const end = html.indexOf(endMarker, start);
  assert(start >= 0 && end > start, '无法提取前端函数: ' + startMarker);
  return html.slice(start, end);
}
vm.runInThisContext(
  'var NAME2CODE = {};\n' +
  extract('function sinaCodeOf(r){', 'function quoteOf(r){') + '\n' +
  extract('function prevFingerprintMark(r){', '/* 最新价来源标记')
);
var ANCHOR_STALE_MS = 600000;
var state = { ap: null, apTs: 0 };
var row = {
  code: 'hf_RS', ref_contract: 'RS2703', ref_prev: 1,
  ref_prev_date: '2026-10-30'
};
function fresh(mainPrev, anchorPrev) {
  state.apTs = Date.now();
  state.ap = {
    hf_RS: { prev: mainPrev, prevDate: '2026-10-30' },
    hf_RS2703: { prev: anchorPrev, prevDate: '2026-10-30' }
  };
}
function noMark(name) {
  assert.strictEqual(prevFingerprintMark(row), null, name);
}

// 缓存先渲染、锚快照尚未返回：旧版会拿 ref_prev 猜，现版必须静默。
noMark('初始化/切回前台首轮渲染不得闪标');
fresh(20, 20);
noMark('同请求主连与锚合约昨结相同，即使 ref_prev 不同也不误报');
state.ap = null;
noMark('中转失败且没有证据时不亮标');
fresh(20, 20);
state.apTs = Date.now() - ANCHOR_STALE_MS;
noMark('证据过期后不亮标');
fresh(20, 20);
delete state.ap.hf_RS2703;
noMark('锚合约空壳/缺失时不亮标');
fresh(20, 20);
state.ap.hf_RS.prevDate = '2026-10-29';
noMark('交易日不同不比较');
fresh(20, 20);
state.ap.hf_RS2703.prevDate = '';
noMark('交易日缺失不比较');
fresh(20.01, 20);
noMark('不超过 0.1% 不打扰');
fresh(21, 20);
const mark = prevFingerprintMark(row);
assert(mark && mark.mark === '切月中', '真实主连/锚合约脱节必须亮标');
assert(mark.markTip.includes('RS2703'), '提示必须指名锚合约');
assert(mark.markTip.includes('5.00%'), '提示必须给出确证差值');
console.log('前端切月中判定：10 个场景通过');
'''


@unittest.skipUnless(shutil.which('node'), '前端回归测试需要 Node.js')
class FrontendFingerprintTests(unittest.TestCase):
    def test_cutover_requires_fresh_same_request_evidence(self):
        from pathlib import Path
        index = Path(__file__).with_name('index.html')
        result = subprocess.run(
            [shutil.which('node'), '-e', JS_HARNESS, str(index)],
            capture_output=True, text=True, encoding='utf-8', timeout=20,
        )
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + '\n' + result.stderr)
        self.assertIn('10 个场景通过', result.stdout)


# v2.27（2026-11-20 马棕油/日橡胶起始价「—」事故）：分时表取点的日期归属。
# 表头日期是「交易日」，而交易日的第一个分钟点发生在【前一晚】（马棕油 21:00、日橡胶 16:00 开盘）。
# 旧实现把表头日期当首点日期 → 整表偏移一天，目标日的点在遍历第一步就 break，取价返回 null。
POINTS_HARNESS = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(process.argv[1], 'utf8');
function extract(startMarker, endMarker) {
  const start = html.indexOf(startMarker);
  const end = html.indexOf(endMarker, start);
  assert(start >= 0 && end > start, '无法提取前端函数: ' + startMarker);
  return html.slice(start, end);
}
vm.runInThisContext(
  'function pad2(n){ return (n<10?"0":"") + n; }\n' +
  extract('function stampDateOf(e){', '/* 取 ≤ 目标') + '\n' +
  extract('function pickPoint(pts, dateKey, targetMin){', '/* ---------- 缓存与状态判定')
);

// ① 马棕油式：表头 11-20（交易日），首笔实际是 11-19 21:00（夜盘）
const fcpo = [
  ["2026-11-20","4333.000","bmd","","21:00","4332.300","251","62003","4331.621","2026-11-19 21:00:00"],
  ["21:01","4345.640","232","62003","4337.487","2026-11-19 21:01:00"],
  ["23:29","4368.200","0","62003","4360.000","2026-11-19 23:29:00"],
  ["10:30","4380.000","0","62003","4380.000","2026-11-20 10:30:00"],
  ["11:30","4305.390","0","62003","4305.390","2026-11-20 11:30:00"],
  ["11:31","4299.020","0","62003","4299.020","2026-11-20 11:31:00"]
];
const pts = buildPoints(fcpo);
assert.strictEqual(pts[0].date, '2026-11-19', '表首笔属于前一晚，必须按行内时间戳定日期');
assert.strictEqual(pts[pts.length - 1].date, '2026-11-20', '当天日盘不得被推成次日');
const hit = pickPoint(pts, '2026-11-20', 690);
assert(hit && hit.min === 690 && hit.price === 4305.39, '11:30 节点必须取到当天那一笔');
const before = pickPoint(pts, '2026-11-20', 689);
assert(before && before.min === 630, '节点之前取 10:30 那笔，不能跨到前一天夜盘');

// ② 日橡胶式：表头 11-20，首笔 11-19 16:00（夜盘更早），同样不得偏移
const rss3 = [
  ["2026-11-20","422.800","tocom","","16:00","423.100","2","2287","423.100","2026-11-19 16:00:00"],
  ["16:01","423.000","1","2287","423.067","2026-11-19 16:01:00"],
  ["09:00","420.000","1","2287","421.000","2026-11-20 09:00:00"],
  ["11:29","423.759","1","2287","423.500","2026-11-20 11:29:00"]
];
const rp = buildPoints(rss3);
const rh = pickPoint(rp, '2026-11-20', 690);
assert(rh && rh.price === 423.759, '日橡胶 11:30 取 11:29 那笔');

// ③ 无行内时间戳的旧格式：仍按"时钟倒退 → 次日"推断，不因新逻辑失效
const legacy = [
  ["2026-11-19","18.040","nybot","","16:30","17.954","1541","0","17.981"],
  ["16:31","18.019","808","0","17.982"],
  ["23:59","17.560","0","0","17.560"],
  ["15:30","17.300","0","0","17.300"]
];
const lp = buildPoints(legacy);
assert.strictEqual(lp[0].date, '2026-11-19');
assert.strictEqual(lp[lp.length - 1].date, '2026-11-20', '时钟倒退仍应推断为次日');
assert.strictEqual(pickPoint(lp, '2026-11-20', 960).price, 17.3);
console.log('分时取点日期归属：3 类场景通过');
'''


@unittest.skipUnless(shutil.which('node'), '前端回归测试需要 Node.js')
class FrontendMinlinePointTests(unittest.TestCase):
    def test_points_use_row_timestamp_not_session_header_date(self):
        from pathlib import Path
        index = Path(__file__).with_name('index.html')
        result = subprocess.run(
            [shutil.which('node'), '-e', POINTS_HARNESS, str(index)],
            capture_output=True, text=True, encoding='utf-8', timeout=20,
        )
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + '\n' + result.stderr)
        self.assertIn('3 类场景通过', result.stdout)


POLLING_HARNESS = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync(process.argv[1], 'utf8');
function extract(startMarker, endMarker) {
  const start = html.indexOf(startMarker);
  const end = html.indexOf(endMarker, start);
  assert(start >= 0 && end > start, '无法提取前端函数: ' + startMarker);
  return html.slice(start, end);
}
vm.runInThisContext(
  extract('async function fetchTextWithTimeout(', 'function loadCache(){') + '\n' +
  extract('function loadCache(){', 'function saveCache(d){') + '\n' +
  extract('async function loadJson(){', '/* ---------- 腾讯行情') + '\n' +
  extract('async function refreshTx(){', '/* ---------- 调度') + '\n' +
  extract('async function mlFetch(', 'async function mlTick(){')
);
var UI_VER = '2.28', FETCH_TIMEOUT_MS = 25, DATA_CACHE_STALE_MS = 7200000;
var CACHE_KEY = 'test', TX_URL = 'https://unused/', ML_STALE_MIN = 5;
var jsonBusy = false, txBusy = false, txFail = 0;
var state = { data:null, tx:{}, sn:{}, snTime:'', snDate:'', txTime:'', txDate:'', txFail:0 };
var sessionStorage = { getItem:function(){ return null; }, setItem:function(){} };
var location = { pathname:'/futures-calc/', href:'' };
var document = { getElementById:function(){ return { textContent:'' }; } };
function saveCache(){}
function render(){}
function setLamp(){}
function collectCodes(){ return ['hf_CL']; }
var stored = null;
var localStorage = { getItem:function(){ return stored; }, setItem:function(){} };
function pad(n){ return String(n).padStart(2, '0'); }
function dataStamp(d){
  return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+' '+
         pad(d.getHours())+':'+pad(d.getMinutes());
}
function hangingFetch(_url, opts){
  return new Promise(function(_resolve, reject){
    opts.signal.addEventListener('abort', function(){ reject(new Error('aborted')); });
  });
}
(async function(){
  fetch = hangingFetch;
  assert.strictEqual(await loadJson(), false);
  assert.strictEqual(jsonBusy, false, 'data.json 超时后必须释放忙碌锁');

  const fresh = { ui:'2.28', generated_at:dataStamp(new Date()), rows:[{name:'x', code:'hf_CL'}] };
  fetch = async function(){ return { ok:true, text:async function(){ return JSON.stringify(fresh); } }; };
  assert.strictEqual(await loadJson(), true, '超时后的下一轮必须能重新进入');
  assert.strictEqual(state.data.generated_at, fresh.generated_at);

  const older = Object.assign({}, fresh, { generated_at:'2020-01-01 00:00' });
  fetch = async function(){ return { ok:true, text:async function(){ return JSON.stringify(older); } }; };
  assert.strictEqual(await loadJson(), false, '迟到的旧响应不得覆盖新基准');
  assert.strictEqual(state.data.generated_at, fresh.generated_at);

  fetch = hangingFetch;
  await refreshTx();
  assert.strictEqual(txBusy, false, '腾讯正文挂起超时后必须释放忙碌锁');

  state.data = null;
  stored = JSON.stringify({ ts:Date.now(), data:older });
  loadCache();
  assert.strictEqual(state.data, null, '缓存写入时间再新，也不能救活 24 小时以上的起始价');

  stored = JSON.stringify({ ts:Date.now(), data:fresh, sn:{hf_CL:{last:1}} });
  loadCache();
  assert(state.data && state.data.generated_at === fresh.generated_at, '新鲜起始价缓存仍可秒开');

  const oldDate = new Date(Date.now() - 3600000);
  jsonpMinline = async function(){ return { data:{result:{data:{minLine_1d:[1]}}} }; };
  buildPoints = function(){ return [{ date:dataStamp(oldDate).slice(0,10),
    min:oldDate.getHours()*60+oldDate.getMinutes(), price:89.42 }]; };
  hhmmOf = function(min){ return pad(Math.floor(min/60))+':'+pad(min%60); };
  const mq = await mlFetch('hf_FEF');
  assert(mq.ageMin >= 59, '分时年龄必须使用完整日期，跨午夜旧价不能变新价');
  assert.strictEqual(mlTag(mq), '分时 '+mq.t);
  mq.ageMin = 4; mq.ts = Date.now() - 120000;
  assert.strictEqual(mlTag(mq), '分时 '+mq.t, '驻留两分钟后年龄不能仍冻结在四分钟');
  console.log('前端轮询与缓存：8 个场景通过');
})().catch(function(e){ console.error(e && e.stack || e); process.exit(1); });
'''


@unittest.skipUnless(shutil.which('node'), '前端回归测试需要 Node.js')
class FrontendPollingTests(unittest.TestCase):
    def test_timeout_cache_regression_and_minline_age(self):
        index = Path(__file__).with_name('index.html')
        result = subprocess.run(
            [shutil.which('node'), '-e', POLLING_HARNESS, str(index)],
            capture_output=True, text=True, encoding='utf-8', timeout=20,
        )
        self.assertEqual(result.returncode, 0,
                         msg=result.stdout + '\n' + result.stderr)
        self.assertIn('8 个场景通过', result.stdout)


if __name__ == '__main__':
    unittest.main()
