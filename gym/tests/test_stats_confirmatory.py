"""Confirmatory statistics of protocol Amendment 1 (docs/eval-protocol.md): known-answer tests, no model calls."""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import stats  # noqa: E402


def test_t_distribution_known_values():
    assert math.isclose(stats.t_cdf(2.0, 10), 0.963306, abs_tol=1e-5)
    assert math.isclose(stats.t_cdf(-2.0, 10), 1 - 0.963306, abs_tol=1e-5)
    assert math.isclose(stats.t_ppf(0.975, 10), 2.228139, abs_tol=1e-4)
    assert math.isclose(stats.t_ppf(0.975, 1000), 1.962339, abs_tol=1e-3)


def test_one_sided_superiority_and_noninferiority():
    d = [0.1] * 10 + [0.0] * 10                      # mean 0.05, sd 0.0513
    sup = stats.one_sided_test(d, 0.0)
    se = statistics_sd(d) / math.sqrt(20)
    assert math.isclose(sup["p_t"], 1 - stats.t_cdf(0.05 / se, 19), rel_tol=1e-9)
    assert sup["reject"] and sup["p"] == max(sup["p_boot"], sup["p_t"])
    assert sup["lb_t"] < 0.05 and sup["lb"] == min(sup["lb_boot"], sup["lb_t"])
    ni = stats.one_sided_test(d, 0.05)
    assert ni["reject"] and ni["p_t"] < sup["p_t"]
    worse = stats.one_sided_test([x - 0.11 for x in d], 0.05)  # mean -0.06 < -delta
    assert not worse["reject"] and worse["p"] > 0.5


def test_bootstrap_p_floor_and_inversion():
    d = [0.2, 0.3, 0.25, 0.1, 0.15] * 4
    r = stats.one_sided_test(d, 0.0, n_boot=999)
    assert r["p_boot"] == 1 / 1000                    # (0 + 1) / (B + 1)
    # p <= alpha exactly when the (1 - alpha) lower bound clears -margin (percentile inversion)
    r2 = stats.one_sided_test([0.02, -0.01, 0.03, -0.02, 0.01] * 6, 0.0, n_boot=2000)
    assert (r2["p_boot"] <= 0.025) == (r2["lb_boot"] > 0)


def statistics_sd(x):
    m = sum(x) / len(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def test_holm_family_fixed_m_and_untested():
    fam = {r["hypothesis"]: r for r in stats.holm_family({"a": 0.001, "b": 0.02, "c": None}, alpha=0.025)}
    assert fam["a"]["reject"] and math.isclose(fam["a"]["alpha_at_rank"], 0.025 / 3)
    assert not fam["b"]["reject"]                     # 0.02 > 0.025 / 2
    assert fam["c"]["p"] == 1.0 and not fam["c"]["tested"] and not fam["c"]["reject"]
    # dropping the untested hypothesis would have made b pass: the fixed family prevents that
    assert {r["hypothesis"]: r for r in stats.holm_family({"a": 0.001, "b": 0.02})}["b"]["reject"]


def test_step_down_stops_at_first_failure():
    fam = {r["hypothesis"]: r for r in stats.holm_family({"a": 0.02, "b": 0.0001, "c": 0.024}, alpha=0.025)}
    assert fam["b"]["reject"] and not fam["a"]["reject"] and not fam["c"]["reject"]


def test_kappa_known_value_and_report():
    assert math.isclose(stats.cohen_kappa([1, 1, 0, 0], [1, 0, 0, 0]), 0.5)
    assert stats.cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    rep = stats.kappa_report([1, 1, 0, 0] * 10, [1, 0, 0, 0] * 10, n_boot=500)
    assert math.isclose(rep["kappa"], 0.5) and rep["kappa_ci95"][0] < 0.5 < rep["kappa_ci95"][1]
    assert rep["p_human_accepts_given_scorer_pass"] == 0.5 and rep["p_human_rejects_given_scorer_fail"] == 1.0


def test_simple_random_sample_is_order_free_and_unstratified():
    ids = [f"t{i:03d}" for i in range(200)]
    s1 = stats.simple_random_sample(ids, 40, seed=3)
    s2 = stats.simple_random_sample(list(reversed(ids)), 40, seed=3)
    assert s1 == s2 and len(set(s1)) == 40


def test_cluster_bootstrap_is_wider_than_row_mcnemar():
    rows = []
    for c in range(10):            # 3 threads where A wins every discordant row, 7 threads fully concordant
        for j in range(10):
            rows.append((f"th{c}", 1, 0) if c < 3 else (f"th{c}", 1, 1))
    r = stats.cluster_paired_test(rows, n_boot=2000)
    assert r["threads"] == 10 and r["rows"] == 100 and math.isclose(r["d"], 0.30)
    assert r["p_mcnemar_row_one_sided"] < 1e-8         # rows treated as independent
    assert r["p"] > r["p_mcnemar_row_one_sided"]        # clustering is honest about 3 threads


def test_reader_compare_from_preds(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("\n".join(json.dumps({"id": f"r{i}", "cluster": f"th{i // 4}", "em_primary": True}) for i in range(40)))
    b.write_text("\n".join(json.dumps({"id": f"r{i}", "cluster": f"th{i // 4}", "em_primary": i % 2 == 0}) for i in range(40)))
    r = stats.reader_compare(str(a), str(b), n_boot=500)
    assert r["threads"] == 10 and math.isclose(r["d"], 0.5) and r["reject"]


def _cfg(label, rows_per_run, extra=None):
    data = [{f"t{i}": {"task_id": f"t{i}", "category": "c", "pass": int(r >= 1.0), "reward": r, **(extra or {})}
             for i, r in enumerate(run)} for run in rows_per_run]
    return stats.Config(label, [f"{label}-{i}" for i in range(len(rows_per_run))], data)


def test_noninferiority_on_configs_and_fewer_calls():
    a = _cfg("a", [[0.9, 0.95, 1.0, 0.92] * 10] * 3, {"model_calls": 10})
    b = _cfg("b", [[0.91, 0.96, 1.0, 0.93] * 10] * 3, {"model_calls": 20})
    ni = stats.noninferiority(a, b, 0.05)
    assert ni["reject"] and ni["tasks"] == 40 and math.isclose(ni["d"], -0.0075, abs_tol=1e-9)
    sup = stats.noninferiority(a, b, 0.0)
    assert not sup["reject"]
    fw = stats.fewer(a, b, "model_calls")
    assert fw["reject"] and fw["d"] == -10


def test_strict_missing_tasks():
    data = [{"t0": {"task_id": "t0", "pass": 1, "reward": 1.0}, "t1": {"task_id": "t1", "pass": 1, "reward": 1.0}},
            {"t0": {"task_id": "t0", "pass": 1, "reward": 1.0}}]
    try:
        stats.Config("x", ["r1", "r2"], data, strict=True)
        raise AssertionError("strict must fail")
    except SystemExit:
        pass
    assert stats.Config("x", ["r1", "r2"], data, strict=False).tasks == ["t0"]


def test_plan_untested_hypotheses_stay_in_family():
    plan = json.loads((HERE / "confirmatory_v3.json").read_text())
    out = stats.run_plan(plan)            # no v3 runs exist yet: everything untested, nothing supported
    assert {f["hypothesis"] for f in out["family"]} == {"H1", "H2a", "H2b", "H3", "H4"}
    assert all(not f["tested"] and f["p"] == 1.0 and not f["reject"] for f in out["family"])


def test_plan_on_committed_v2_runs():
    """The same plan machinery, pointed at the committed v2 runs (secondary set): H1 holds, H3(ii) fails."""
    v2 = lambda p: [f"v2-heldout-{p}-s{i}" for i in (1, 2, 3)]
    plan = {"alpha_familywise_one_sided": 0.025, "delta": 0.05,
            "configs": {"baseline": v2("baseline"), "final": v2("final"), "router": v2("final-router")},
            "hypotheses": [
                {"id": "H1", "test": "superiority", "a": "final", "b": "baseline"},
                {"id": "H3i", "test": "fewer", "a": "router", "b": "final", "metric": "model_calls", "co_primary_of": "H3"},
                {"id": "H3ii", "test": "noninferiority", "a": "router", "b": "final", "co_primary_of": "H3"}]}
    out = stats.run_plan(plan, seed=0, gate=False)   # v2 predates the freeze rules: exploratory reuse only
    fam = {f["hypothesis"]: f for f in out["family"]}
    assert fam["H1"]["reject"] and not fam["H3"]["reject"]
    gated = stats.run_plan(plan, seed=0)            # with the run gate, pre-freeze runs never count
    assert all(not f["tested"] for f in gated["family"]) and gated["input_problems"]
    t = {r["id"]: r for r in out["tests"]}
    assert t["H3i"]["reject"] and not t["H3ii"]["reject"]
    assert math.isclose(t["H3ii"]["d"], -0.053, abs_tol=0.002)


def test_power_simulation_monotone():
    lo = stats.simulate_power(40, -0.03, 0.07, 0.0064, 0.0196, 5, 5, 0.05, sims=60, n_boot=300, seed=1)
    hi = stats.simulate_power(40, 0.03, 0.07, 0.0064, 0.0196, 5, 5, 0.05, sims=60, n_boot=300, seed=1)
    assert hi > lo and hi > 0.8
    rp = stats.simulate_reader_power(40, 8, 0.10, 0.2, sims=40, n_boot=300, seed=1)
    assert rp > 0.5


# ------------------------------------------------------------------ Amendment 2: run names and the run gate
import shlex  # noqa: E402
import subprocess  # noqa: E402

import frozen  # noqa: E402

REPO = HERE.parent


def test_launch_commands_write_exactly_the_plan_run_names():
    """Round-2 N3: every config's run names are what its pre-registered launch command writes (dry run)."""
    plan = json.loads((HERE / "confirmatory_v3.json").read_text())
    assert set(plan["launch"]) - {"_note"} == set(plan["configs"])
    for label, cmd in plan["launch"].items():
        if label == "_note":
            continue
        argv = shlex.split(cmd)
        if argv[0].endswith("python"):
            argv = [sys.executable] + argv[1:] + ["--print-run-names"]
            env = None
        else:
            env = {"PATH": "/usr/bin:/bin", "PRINT_RUN_NAMES": "1"}
        out = subprocess.run(argv, cwd=REPO, env=env, capture_output=True, text=True, check=True).stdout.split()
        assert out == plan["configs"][label], (label, out)


def test_check_plan_lists_every_missing_run():
    plan = json.loads((HERE / "confirmatory_v3.json").read_text())
    chk = stats.check_plan(plan, freeze={"commit": None})
    for names in plan["configs"].values():
        for r in names:
            assert any(r in p for p in chk["problems"]), r
    assert any("frontier" in p for p in chk["problems"])
    r = subprocess.run([sys.executable, str(HERE / "stats.py"), "plan", str(HERE / "confirmatory_v3.json"), "--check"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 1 and "v3-heldout-frontier-cc-" in r.stdout


FZ = {"commit": "a" * 40, "artifact_sha256": {"gym/tasks/v3/heldout.jsonl": "f" * 64}}


def _summary(**kw):
    prov = {"commit": "a" * 40, "dirty_frozen_paths": False, "tasks_path": str(REPO / "gym/tasks/v3/heldout.jsonl"),
            "tasks_sha256": "f" * 64}
    prov.update(kw.pop("prov", {}))
    mer = {"tasks_rerun": [], "still_failed": [], "mid_rollout_drops": [], "void": False, "retry_provenance": []}
    mer.update(kw.pop("mer", {}))
    return {"provenance": prov, "model_error_retries": mer, **kw}


def test_run_problems_rules():
    never = lambda a, b: False
    same = lambda a, b: True
    assert frozen.run_problems(_summary(), FZ, never) == []
    assert any("void" in w for w in frozen.run_problems(_summary(mer={"void": True}), FZ, never))
    assert any("still_failed" in w for w in frozen.run_problems(_summary(mer={"still_failed": ["t1"]}), FZ, never))
    assert any("dirty" in w for w in frozen.run_problems(_summary(prov={"dirty_frozen_paths": True}), FZ, never))
    assert any("not recorded" in w for w in frozen.run_problems(_summary(prov={"dirty_frozen_paths": None}), FZ, never))
    off = _summary(prov={"commit": "b" * 40})
    assert any("differs from freeze commit" in w for w in frozen.run_problems(off, FZ, never))
    assert frozen.run_problems(off, FZ, same) == []          # later commit, frozen paths byte-identical
    assert any("sha256" in w for w in frozen.run_problems(_summary(prov={"tasks_sha256": "0" * 64}), FZ, never))
    assert any("no freeze commit" in w for w in frozen.run_problems(_summary(), {"commit": None}, never))
    s = _summary()
    del s["model_error_retries"]
    assert any("rerun record" in w for w in frozen.run_problems(s, FZ, never))
    dirty_retry = _summary(mer={"retry_provenance": [{**_summary()["provenance"], "dirty_frozen_paths": True}]})
    assert any(w.startswith("retry 1:") for w in frozen.run_problems(dirty_retry, FZ, never))
    assert frozen.run_problems(None, FZ, never) == ["no summary.json"]


def _write_run(root, name, rewards, summary):
    d = root / name
    d.mkdir()
    (d / "per_task.jsonl").write_text("".join(
        json.dumps({"task_id": f"t{i}", "category": "c", "pass": int(r >= 1), "reward": r}) + "\n"
        for i, r in enumerate(rewards)))
    (d / "summary.json").write_text(json.dumps(summary))
    return str(d)


def test_run_plan_gate_rejects_one_dirty_run(tmp_path):
    hi, lo = [1.0, 0.9, 1.0, 0.95] * 10, [0.5, 0.6, 0.4, 0.55] * 10
    a = [_write_run(tmp_path, f"a{i}", hi, _summary()) for i in range(3)]
    b = [_write_run(tmp_path, f"b{i}", lo, _summary()) for i in range(3)]
    plan = {"alpha_familywise_one_sided": 0.025, "configs": {"final": a, "baseline": b},
            "hypotheses": [{"id": "H1", "test": "superiority", "a": "final", "b": "baseline"}]}
    ok = stats.run_plan(plan, freeze=FZ, same_frozen=lambda x, y: False)
    assert ok["family"][0]["tested"] and ok["family"][0]["reject"] and not ok["input_problems"]
    Path(b[1], "summary.json").write_text(json.dumps(_summary(prov={"dirty_frozen_paths": True})))
    bad = stats.run_plan(plan, freeze=FZ, same_frozen=lambda x, y: False)
    assert not bad["family"][0]["tested"] and bad["family"][0]["p"] == 1.0
    assert any("dirty" in p for p in bad["input_problems"])
