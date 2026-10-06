# Machine learning

mcdxkit ships a case-name classifier and a set of review flags, both implemented in the package itself with the standard library. They run offline, need no extra dependencies or downloads, and only advise: they never change inputs, case selections, worksheets or results.

## Case classifier

GROUP case names drive the default selection: names starting with `STR` are strength cases. Other conventions (`Strength I`, `ULS-1`, `Str1`, `Extreme Event II`, project-specific names) stop at "Case classification unavailable".

`mcdxkit learn REPORT` and **Suggest cases** in the Inputs step classify each final-summary case as `strength`, `service`, `extreme`, `fatigue` or `other`.

- **Model:** multinomial naive Bayes over character 2-4 grams and whole words of the normalized name, with Laplace smoothing.
- **Training data:** a seed corpus of AASHTO LRFD limit-state names and common abbreviations, plus the engineer's own history. Every completed conversion's audit records the final-summary case names (`case_names`, new in this version; older audits only list the selected cases) and which were selected; selected names are learned as strength and unselected names as not strength, weighted 3× over the seed. The browser learns from its output directory; the CLI from `--history DIR`.
- **Abstention:** a case below 80% posterior probability is reported as `unknown` and listed in `unresolved_case_ids`.
- **Explanation:** each case lists its confidence and the name fragments that most favored the predicted class.
- **Safety:** only `strength` cases are recommended, and the recommended set is checked with the same `select` rules as a manual selection. A set the template cannot use, for example one containing tension, is returned with `selection_issue` and cannot be applied in the browser. Extreme-event cases are classified but never recommended; include them deliberately when the design requires them.

## Review flags

**Advisory only, never applied without your click.** Review flags, case-name suggestions and dominance hints never change inputs, case selection, worksheets or results. The only way a suggestion changes anything is the explicit **Use cases …** button. Tests check that the `.mcdx`, `.cpd` and `.html` bytes and the audit (apart from `review_flags`) are identical with the review on and off.

`inspect` (CLI, SDK and browser), `convert`, batch audits and `mcdxkit learn` return `review_flags` from `mcdxkit.review`. They replace the earlier magnitude-based `anomalies`, which a planted-error validation found misleading (below). The browser shows them on the Inputs and Changes steps as "Review: …" items. A flag means "check the GROUP input for this case"; it is never a pass or fail, and no flag is not a verification.

```json
"review_flags": {
  "advisory": true, "method": "rules+robust-ratio-z+gross-magnitude", "version": 2, "load_source": "effects",
  "checks": ["service_exceeds_strength", "effects_below_top", "duplicate_case", "ratio_outlier", "gross_magnitude"],
  "skipped": [],
  "flags": [{"rule": "service_exceeds_strength", "case": 3, "component": "P",
             "detail": "Case 3 SER-IX axial load 304.2 exceeds every STR case (largest 256, case 2). ...",
             "values": {"service": 304.23, "strength_max": 256.03, "strength_case": 2}}],
  "dominance": {"basis": "selected", "note": "Selected cases.", "cases": [2, 4, 5],
                "dominated": [{"case": 4, "dominated_by": [2]}]}
}
```

- A check that cannot run on a report is listed in `skipped` with its reason, for example a report with fewer than three cases or the `reactions` load source; it is not reported as clean.
- If the review itself fails, `review_flags` is `{advisory: true, method, version, error: "review unavailable: …"}` and inspection or conversion continues. Advisory code never fails a conversion.

### Rules

Each rule is a physical or labelling invariant. The only tolerance is 1% for rounding of GROUP's printed values.

| Rule | Flags | Notes |
| --- | --- | --- |
| `service_exceeds_strength` | A service case whose maximum axial load exceeds every strength case | Axial load only: service lateral loads legitimately exceed strength (AASHTO LRFD Table 3.4.1-1 uses 1.2 TU in Service I against 0.5 in Strength), and comparing lateral components false-alarmed on 12% of the harder corpus. Skipped when no strength case has compression. Recognizes `STR`/`SER` prefixes and AASHTO names such as `Strength I` and `Service I` (`group_report.limit_state(name, long_names=True)`). Default case selection is unchanged and still recognizes only the `STR`/`SER` prefixes. |
| `effects_below_top` | The largest magnitude along the pile is below the pile-top reaction for the same quantity | Effects load source only. Pairs (local column → effects column): `LAT. y` 1 → `SHEAR y-DIR` 4, `LAT. z` 2 → `SHEAR z-DIR` 5, `MOM y` 4 → `MOMENT y-DIR` 3, `MOM z` 5 → `MOMENT z-DIR` 2. Compared by magnitude, so it holds whether the effects table uses the same moment sign as the pile-top table (the `tests/test_pipeline.py` fixtures) or the opposite sign (the validation generator); both are tested. GROUP's own conventions are still to be confirmed on real reports. |
| `duplicate_case` | A case whose numeric tables are identical to an earlier case | Usually a copied case. |

### Statistics

- **`ratio_outlier`:** per case, log10 of the lever arms `|Mz|/|Vy|` and `|My|/|Vz|` at the pile top and, for the effects source, the along-pile/top ratios for Mz, My, Vy and Vz. A consistent model keeps these near-constant across cases, while one wrong cell moves them. Each ratio is scored with the Iglewicz-Hoaglin modified z-score `0.6745 (x - median) / MAD` across the report's cases, and the case's largest |z| is flagged above 4.64. The MAD is floored at 0.02 decades (about 5%); in the study this floor made the threshold portable between corpora (3.8 and 4.6), where a 0.001 floor moved it from 4.4 to 16.9. A ratio is undefined when its denominator is below 1% of the report's median for that quantity. Needs 3 defined values per ratio; with fewer, the score cannot exceed 0.67.
- **`gross_magnitude`:** maximum axial load (`P`) and the pile-top lateral resultant `hypot(|Vy|, |Vz|)` (`V`) more than 0.95 decades (about 9×) from the report's median, worded "possible unit slip". Values below 1% of the median, such as a gravity case's 0.02 kip shear beside 15 kip wind cases, are not compared, so a 1/1000 slip downwards is not detected. Needs at least 3 cases.
- **No kip-ft hint.** The earlier kip-ft/kip-in (12×) hint was dropped on purpose: it was wrong for all 17 of 17 moment-unit slips it flagged, because a cap-moment unit slip changes the axial spread across piles rather than making pile moments 12× larger. The lb/kip hint was right for only 57 of 143, so the wording is now only "possible unit slip".

4.64 is the 95th percentile of the per-report maximum ratio score, and 0.95 the 97.5th percentile of the magnitude score, on 300 clean reports of the harder synthetic corpus. Both should be recalibrated on real clean reports, for example with the study's `check_my_reports.py`.

### Case dominance

`dominance` lists strength cases that can never govern: another considered case is at least as large in every envelope component (P, Vy, Vz, My, Mz). In the harder corpus 51% of strength cases were dominated (median 6 strength cases per report). The browser greys them in the case list and names them under the governing cases. They stay selected; it is a hint about where to look, not a selection.

`basis` is `selected` when a case selection is in use (inspect with a resolved selection, and every conversion audit). When no selection is resolved, inspect uses `fallback_non_extreme`: all cases except names starting with `ext`, `extreme`, `eq` or `seis`. This fallback applies only to the dominance hint. It is labelled as a fallback in the API, audit and UI, and is never used as, or shown as, a case selection; `select` still fails explicitly with "Case classification unavailable". In the study, this basis overshot the true strength envelope by a median of 0% (90th percentile 71%), against 24% (400%) for all cases.

### Evidence

Planted-error validation on synthetic GROUP-format reports from a simplified pile-group model. "Harmful" means the error changes the default STR envelope by more than 5%; reports mcdxkit already refuses are excluded. Each corpus has 400 clean reports and 150 reports for each of 8 planted errors (factor typo, cap-moment unit slip, lateral force in lb, y/z axis swap, STR labelled SER, dropped load, one-cell ×10 or ÷10 edit, effects copied from another case).

Round 2 used a harder corpus: thermal load with AASHTO factors, 0.9D minimum strength cases, extreme-event cases, random combination subsets, four naming styles, batter piles, soil and stiffness scatter and 4-significant-figure output. Study results (harmful recall at the false-alarm rate on clean reports):

| Detector | Round 1 corpus | Harder corpus |
| --- | --- | --- |
| Previous `anomalies` (magnitude MAD, z ≥ 3.5) | 46% at 10.5% | 52% at 22.5% |
| Rules + ratio z | 54% at 5.0% | 55% at 4.8% |
| Rules + ratio z + gross magnitude | 64% at 5.0% | **58% at 3.5%** |
| LOF on 400 past reports (not shipped) | 68% at 7.2% | 51% at 5.8% |

The 58% at 3.5% row used a ratio threshold of 5.63 (2.5% calibration) together with the 0.95 magnitude threshold. Re-running the shipped `mcdxkit.review` (ratio threshold 4.64, negligible-value floor) on the same corpora gave:

| Shipped configuration | Round 1 corpus | Harder corpus |
| --- | --- | --- |
| Ratio threshold 4.64 (shipped) | 61% at 4.8% | 60% at 7.0% |
| Ratio threshold 5.63 (for comparison) | 61% at 4.8% | 57% at 3.5% |

On the harder corpus the shipped configuration catches: lateral force in lb 100%, one-cell edit 100%, copied effects 100%, STR labelled SER 63%, dropped load 19%, axis swap 12%, factor typo 10%.

### Limits

- The generators are simplified models, not GROUP. The number that matters next is the false-positive rate on real clean reports.
- A sign flip that keeps each minimum at or below its maximum leaves every magnitude, and so the envelope, unchanged; no check can see it. A flip that inverts the extrema is already refused by the parser.
- Dropped loads, axis swaps and factor typos are input-definition errors that output-only checks mostly cannot recover (no detector at about 6% false alarms got past 31% on any of them). Checking GROUP's input echo against the code's factor table would; that needs a real report to learn the echo format.
- History models (LOF), sibling-case statistics and a numeric case picker were evaluated and are deliberately not built. When case names are opaque, only the engineer can select the cases.
- The statistics compare cases within one report. Reports with fewer than three cases get only the rules.

## Governing cases

`inspect` also returns `governing`: for each envelope component, the selected case that produces the peak, the runner-up case and the lead ratio. The browser shows it under each value and notes leads of 1.5× or more.
