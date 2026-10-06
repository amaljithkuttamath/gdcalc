# Machine learning

gdcalc ships a case-name classifier and a set of review flags, both implemented in the package itself with the standard library. They run offline, need no extra dependencies or downloads, and only advise: they never change inputs, case selections, worksheets or results.

## Case classifier

GROUP case names drive the default selection: names starting with `STR` are strength cases. Other conventions (`Strength I`, `ULS-1`, `Str1`, `Extreme Event II`, project-specific names) stop at "Case classification unavailable".

`gdcalc learn REPORT` and **Suggest cases** in the Inputs step classify each final-summary case as `strength`, `service`, `extreme`, `fatigue` or `other`.

- **Model:** multinomial naive Bayes over character 2-4 grams and whole words of the normalized name, with Laplace smoothing.
- **Training data:** a seed corpus of AASHTO LRFD limit-state names and common abbreviations, plus the engineer's own history. Every completed conversion's audit records the final-summary case names (`case_names`, new in this version; older audits only list the selected cases) and which were selected; selected names are learned as strength and unselected names as not strength, weighted 3× over the seed. The browser learns from its output directory; the CLI from `--history DIR`.
- **Abstention:** a case below 80% posterior probability is reported as `unknown` and listed in `unresolved_case_ids`.
- **Explanation:** each case lists its confidence and the name fragments that most favored the predicted class.
- **Safety:** only `strength` cases are recommended, and the recommended set is checked with the same `select` rules as a manual selection. A set the template cannot use, for example one containing tension, is returned with `selection_issue` and cannot be applied in the browser. Extreme-event cases are classified but never recommended; include them deliberately when the design requires them.

## Review flags

`inspect` (CLI, SDK and browser), `convert`, batch audits and `gdcalc learn` return `review_flags` from `gdcalc.review`. They replace the earlier magnitude-based `anomalies`, which a planted-error validation found misleading (below). The browser shows them on the Inputs and Changes steps as "Review: …" items. A flag means "check the GROUP input for this case"; it is never a pass or fail, and no flag is not a verification.

```json
"review_flags": {
  "advisory": true, "method": "rules+robust-ratio-z", "version": 1, "load_source": "effects",
  "checks": ["service_exceeds_strength", "effects_below_top", "duplicate_case", "ratio_outlier", "unit_slip"],
  "skipped": [],
  "flags": [{"rule": "service_exceeds_strength", "case": 3, "component": "P",
             "detail": "Case 3 SER-IX P 304.2 exceeds every STR case (largest 256, case 2). ...",
             "values": {"service": 304.23, "strength_max": 256.03, "strength_case": 2}}]
}
```

A check that cannot run on a report is listed in `skipped` with its reason, for example a report with fewer than six cases or the `reactions` load source; it is not reported as clean.

### Rules

Each rule is a physical or labelling invariant. The only tolerance is 1% for rounding of GROUP's printed values.

| Rule | Flags | Notes |
| --- | --- | --- |
| `service_exceeds_strength` | A `SER` case whose envelope peak in a component (P, Vy, Vz, My, Mz, on the chosen load source) exceeds every `STR` case | Needs both `STR` and `SER` case names (the same prefixes as default selection). Catches strength cases labelled service, which the name-only classifier cannot see. |
| `effects_below_top` | The largest magnitude along the pile is below the pile-top reaction for the same quantity | Effects load source only. Pairs: local `LAT. y` ↔ effects `SHEAR y-DIR`, `LAT. z` ↔ `SHEAR z-DIR`, `MOM y` ↔ `MOMENT y-DIR`, `MOM z` ↔ `MOMENT z-DIR`. Compared by magnitude, so it holds whether the effects table uses the same moment sign as the pile-top table (the `tests/test_pipeline.py` fixtures) or the opposite sign (the validation generator); both are tested. GROUP's own conventions are still to be confirmed on real reports. |
| `duplicate_case` | A case whose numeric tables are identical to an earlier case | Usually a copied case. |

### Statistics

- **`ratio_outlier`:** per case, log10 of the lever arms `|Mz|/|Vy|` and `|My|/|Vz|` at the pile top and, for the effects source, the along-pile/top ratios for Mz, My, Vy and Vz. A consistent model keeps these near-constant across cases, while one wrong cell moves them. Each ratio is scored with the Iglewicz-Hoaglin modified z-score `0.6745 (x - median) / MAD` across the report's cases and the case's largest |z| is flagged above 4.35. The MAD is floored at 0.001 decades so rounding cannot inflate scores. A ratio is undefined when its denominator is below 1% of the report's median for that quantity. Needs at least 6 cases (the smallest report in the validation set) and 3 defined values per ratio.
- **`unit_slip`:** a component peak at least 10^2.5 (about 316×) from the report's median peak, worded "possible unit slip (lb vs kip)". It needs at least 6 cases. The earlier kip-ft/kip-in (12×) hint is gone: it was wrong for all 17 moment-unit slips it flagged, because a cap-moment unit slip changes the axial spread across piles rather than making pile moments 12× larger.

The threshold 4.35 is the 95th percentile of the per-report maximum score on 300 clean synthetic reports, so about 5% of clean reports receive a `ratio_outlier` flag. It should be recalibrated on real clean reports.

### Evidence

Planted-error validation on synthetic GROUP-format reports from a simplified pile-group model (rigid cap, leading-row lateral share, Winkler head and span moments, AASHTO-like STR/SER combinations with wind directions). Test set: 400 clean reports and 150 reports for each of 8 planted errors. "Harmful" means the error changes the default STR envelope by more than 5% (258 reports); reports gdcalc already refuses are excluded.

| Detector | False-positive rate (clean reports) | Recall, harmful errors | Precision at 10% error prevalence |
| --- | --- | --- | --- |
| Previous `anomalies` (magnitude MAD, z ≥ 3.5) | 10.5% | 46% | 33% |
| Rules only | 0% | 31% | 100% |
| Rules + ratio z (this release) | 4.8% | 70% | 62% |

Harmful recall by error type for rules + ratio z (previous `anomalies` in brackets): factor typo 15% (69%), lateral force in lb 97% (95%), axis swap 0% (3%), STR labelled SER 100% (12%), dropped load 23% (5%), one-cell ×10 or ÷10 edit 91% (39%), effects copied from another case 100% (32%). The previous detector flagged 42 of 400 clean reports, every time on shear or moment components that legitimately vary by more than 3× between gravity-only and wind or braking cases. Re-running the shipped `gdcalc.review` on the same corpus gave 4.75% false positives and 70.5% harmful recall, with `unit_slip` added and no `unit_slip` flags on clean reports.

### Limits

- The generator is a simplified model, not GROUP, and obeys the invariants the rules check, so the rules' 0% false-positive rate is partly by construction. The number that matters next is the false-positive rate on real clean reports.
- A sign flip that keeps each minimum at or below its maximum leaves every magnitude, and so the envelope, unchanged; no check can see it. A flip that inverts the extrema is already refused by the parser.
- Axis swaps, factor typos and dropped loads are mostly not caught. History-based models (LOF) reached 86% harmful recall in the study but need a corpus of earlier reports and are not shipped.
- The statistics compare cases within one report. Reports with fewer than six cases get only the rules.

## Governing cases

`inspect` also returns `governing`: for each envelope component, the selected case that produces the peak, the runner-up case and the lead ratio. The browser shows it under each value and notes leads of 1.5× or more.
