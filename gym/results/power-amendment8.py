import sys, math
sys.path.insert(0, "gym")
import stats
from stats import detectable, ALPHA_FW, DELTA
far = dict(task_var=0.04006384613634231, a=0.0063643627947589975, b=0.03533754386920581)
close = dict(task_var=0.004424712405879669, a=0.019607568107258652, b=0.0063643627947589975)
kw = dict(sims=200, n_boot=500)
for name, vc, margin, ka, kb in (("H1 superiority", far, 0.0, 5, 5),
                                 ("H3(ii) NI", close, DELTA, 5, 5),
                                 ("H4 NI (frontier 2 runs, seed var = router's)", {**close, "a": close["b"], "b": close["a"]}, DELTA, 5, 2),
                                 ("H4 NI (frontier 1 run)", {**close, "a": close["b"], "b": close["a"]}, DELTA, 5, 1)):
    for alpha in (ALPHA_FW, ALPHA_FW / 5):
        g = detectable(46, math.sqrt(vc["task_var"]), vc["a"], vc["b"], ka, kb, margin, alpha, **kw)
        print(f"| {name} | 46 | {ka}/{kb} | alpha {alpha} | {'none in grid' if g is None else f'{g:+.3f}'} |", flush=True)
