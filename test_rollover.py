# -*- coding: utf-8 -*-
"""换月锚定与前端「切月中」判定的回归测试。

运行：python -m unittest -v test_rollover.py
前端测试需要 Node.js；未安装时只跳过该组，不影响 Python 判定测试。
"""

from datetime import datetime
import shutil
import subprocess
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


if __name__ == '__main__':
    unittest.main()
