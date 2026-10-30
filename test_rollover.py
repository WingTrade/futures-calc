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
        mock_get.return_value = (
            'var hq_str_hf_HG="652.456,,,,,,20:00:00,660.25,,12345,,,2026-10-30,";\n'
            'var hq_str_hf_HG2612="652.456,,,,,,20:00:00,660.25,,12345,,,2026-10-30,";'
        )
        snap = fetch.sina_snapshot(['hf_HG', 'hf_HG2612'])
        for code in ('hf_HG', 'hf_HG2612'):
            with self.subTest(code=code):
                self.assertAlmostEqual(snap[code]['last'], 6.52456)
                self.assertAlmostEqual(snap[code]['prev_settle'], 6.6025)
                self.assertEqual(snap[code]['volume'], 12345.0)


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


if __name__ == '__main__':
    unittest.main()
