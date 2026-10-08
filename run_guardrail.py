"""Run the guardrail test suite at an initial and a tuned similarity threshold."""
import json
import sys

sys.path.insert(0, "src")
from guardrail import score
from guardrail_cases import CASES

THRESHOLDS = (0.60, 0.35, 0.50)   # initial, lenient, selected
SELECTED = 0.50
report = {"cases": len(CASES), "bad": sum(c["expected"] != "OK" for c in CASES), "runs": []}
for th in THRESHOLDS:
    rows, m = score(CASES, th)
    report["runs"].append({"metrics": m, "wrong": [r["id"] for r in rows if not r["correct"]]})
    print(f"threshold={th:.2f}  TP={m['tp']} FP={m['fp']} FN={m['fn']} TN={m['tn']}  "
          f"accuracy={m['accuracy']:.3f} precision={m['precision']:.3f} recall={m['recall']:.3f}  wrong={report['runs'][-1]['wrong']}")
rows, final = score(CASES, SELECTED)
report["selected"] = SELECTED
report["final"] = [{k: r[k] for k in ("id", "kind", "prompt", "response", "expected", "verdict", "issue", "correct", "similarity")} for r in rows]
json.dump(report, open("out/guardrail_results.json", "w"), indent=1)
print()
print(f"{'ID':<4} {'Type':<18} {'Expected':<8} {'Verdict':<7} {'Issue':<19} {'Sim':<5} Result")
for r in rows:
    sim = "-" if r["similarity"] is None else f"{r['similarity']:.2f}"
    print(f"{r['id']:<4} {r['kind']:<18} {r['expected']:<8} {r['verdict']:<7} {r['issue'] or '-':<19} {sim:<5} {'ok' if r['correct'] else 'MISSED' if r['expected'] != 'OK' else 'FALSE ALARM'}")
