import json
from pathlib import Path
import shutil
import subprocess
import unittest

from research_projection import build_research
from test_r06_projection import NOW, r06_plan


@unittest.skipUnless(shutil.which("node"), "Node.js is required for dashboard rendering checks")
class ResearchDashboardTests(unittest.TestCase):
    def render_check(self, script):
        module = (Path(__file__).resolve().parents[1] / "src/research-dashboard.js").as_uri()
        source = (
            "import assert from 'node:assert/strict';\n"
            "import {renderResearch, parameterMarkup, bindResearch} from "
            + json.dumps(module) + ";\n" + script
        )
        result = subprocess.run(["node", "--input-type=module"], input=source, encoding="utf-8",
                                capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_r06_budget_states_and_p0_are_rendered_in_existing_layout(self):
        self.render_check("""
const count = (planned) => ({planned,solved:0,solver_finished:1,archived:0,accepted:0,remaining:planned,running:0,failed:0});
const research = {
  available:true, revision:'r0.6', totals:count(396),
  budget:{total_cases:396,zero_cases:26,profile_count:13,radiation_count:10,statistics_intent_cases:214,statistics_eligible_cases:0,manifest_eligible_cases:0},
  statistics_snapshot_status:'not_connected',
  counts:Object.fromEntries(Object.entries({Z:26,T:68,S:150,R:12,HR:28,HP:30,AL:82}).map(([key,n])=>[key,count(n)])),
  diagnostics:{P0:{planned:3,solved:2,archived:2,running:1,failed:0,included_in_formal_plan:false}},
};
const html = renderResearch(research,'zh');
const visible = html.replace(/<[^>]*>/g, ' ').replace(/\\s+/g, ' ').trim();
for (const text of ['计划槽位 396','器件 13','辐照条件 10','统计用途上限 214',
  '统计资格快照待接入','清单资格标记 0','求解结束 · 待收集 1','归档已核验 0','科学验收通过 0',
  'P0 前置诊断','诊断单独记录，不计入正式计划完成数','归档已核验 2']) assert.ok(visible.includes(text),text);
assert.ok(!html.includes('当前统计合格'));
for (const block of ['Z','T','S','R','HR','HP','AL']) assert.ok(html.includes('data-cohort="'+block+'"'),block);
assert.ok(html.includes('value="0"'));
assert.ok(!html.includes('12 个 primary'));
assert.ok(parameterMarkup({Hjc_nm:82},'zh').includes('82 nm'));
""")

    def test_sealed_block_and_parameters_do_not_render_per_case_results(self):
        self.render_check("""
const callbacks = {};
const chip = {dataset:{cohort:'HR'}};
const root = {addEventListener:(event,callback)=>{callbacks[event]=callback;}};
bindResearch(root,()=>{});
callbacks.click({target:{closest:()=>chip}});
const html = renderResearch({
  available:true,revision:'r0.6',
  blocks:[{id:'HR',sealed:true,counts:{planned:28,solved:1,accepted:0,remaining:28}}],
  counts:{HR:{planned:28,solved:1,accepted:0,remaining:28}},
  cases:[{case_id:'r06-hr-hidden-b1',block:'HR',cohort:'HR',state:'solved',profile_id:'private-result'}],
  progress:[{case_id:'r06-hp-hidden-b1',note:'private-holdout-note'}],
  profiles:[{id:'H0',sealed:true,parameters:{NA_relative:987654321}}],
  radiations:[{id:'C2',sealed:true,parameters:{energy_MeV:123456789}}],
},'zh',{live_items:[{id:'ANON-1',kind:'sealed',case_id:'r06-hr-live-only',label:'private-run-progress',stage_label:'private-stage'}]});
assert.ok(html.includes('封存中，仅显示区块汇总'));
assert.ok(html.includes('封存留出任务'));
for (const secret of ['private-result','r06-hr-hidden','private-holdout-note','r06-hr-live-only',
  'private-run-progress','private-stage','987654321','123456789','case-manifest']) assert.ok(!html.includes(secret),secret);
""")

    def test_r05_layout_and_english_still_render(self):
        self.render_check("""
const research = {available:true,revision:'r0.5',counts:{
  core:{planned:384,archived:1,solved:1,accepted:0,remaining:384,pairs:192},
  reserve:{planned:48,archived:0,solved:0,accepted:0,remaining:48,pairs:24},
  control:{planned:12,archived:0,solved:0,accepted:0,remaining:12,pairs:6},
},cases:[],conditions:[],profiles:[]};
const html = renderResearch(research,'en');
for (const text of ['data-cohort="core"','data-cohort="reserve"','data-cohort="control"','384','192','r0.5','Archive verified']) assert.ok(html.includes(text),text);
assert.ok(!html.includes('data-cohort="HR"'));
assert.ok(!html.includes('396'));
""")

    def test_actual_r06_projection_renders_through_javascript(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(r06_plan()), encoding="utf-8")
            payload = build_research(path, {}, {}, [], now=NOW)
        self.render_check("const payload = " + json.dumps(payload) + ";\n"
                          "const html = renderResearch(payload,'zh');\n"
                          "assert.ok(html.includes('完整计划 · 396'));\n"
                          "assert.ok(html.includes('338'));\n"
                          "assert.ok(!html.includes('r06-hr-case'));\n"
                          "assert.ok(!html.includes('r06-hp-case'));\n")


if __name__ == "__main__":
    unittest.main()
