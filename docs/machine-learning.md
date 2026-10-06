# Machine learning

gdcalc ships two small models implemented in the package itself. They run offline, need no extra dependencies or downloads, and only advise: they never change inputs, case selections, worksheets or results.

## Case classifier

GROUP case names drive the default selection: names starting with `STR` are strength cases. Other conventions (`Strength I`, `ULS-1`, `Str1`, `Extreme Event II`, project-specific names) stop at "Case classification unavailable".

`gdcalc learn REPORT` and **Suggest cases** in the Inputs step classify each final-summary case as `strength`, `service`, `extreme`, `fatigue` or `other`.

- **Model:** multinomial naive Bayes over character 2-4 grams and whole words of the normalized name, with Laplace smoothing.
- **Training data:** a seed corpus of AASHTO LRFD limit-state names and common abbreviations, plus the engineer's own history. Every completed conversion's audit records the final-summary case names (`case_names`, new in this version; older audits only list the selected cases) and which were selected; selected names are learned as strength and unselected names as not strength, weighted 3× over the seed. The browser learns from its output directory; the CLI from `--history DIR`.
- **Abstention:** a case below 80% posterior probability is reported as `unknown` and listed in `unresolved_case_ids`.
- **Explanation:** each case lists its confidence and the name fragments that most favored the predicted class.
- **Safety:** only `strength` cases are recommended, and the recommended set is checked with the same `select` rules as a manual selection. A set the template cannot use, for example one containing tension, is returned with `selection_issue` and cannot be applied in the browser. Extreme-event cases are classified but never recommended; include them deliberately when the design requires them.

## Load outliers

`inspect` (CLI, SDK and browser) returns `anomalies`: cases whose peak magnitude for a load component is an outlier among the report's cases.

- **Method:** Iglewicz-Hoaglin modified z-score, `0.6745 (x - median) / MAD`, on log10 peak magnitudes, flagged at |z| >= 3.5. Robust statistics keep a single bad case from hiding itself. The MAD is floored at 0.1 decades, so in tightly clustered reports only departures of roughly 3× or more are flagged; ordinary case-to-case scatter is not. Requires at least five cases with nonzero values for that component.
- **Unit signatures:** departures within about 20% of 12× or 1/12× on moments, or 1000× / 1/1000× on any component, are labeled as possible kip-ft/kip-in or lb/kip mix-ups.
- An outlier is a prompt to check the GROUP input, not an error: extreme-event and construction cases are often legitimately different.

## Governing cases

`inspect` also returns `governing`: for each envelope component, the selected case that produces the peak, the runner-up case and the lead ratio. The browser shows it under each value and notes leads of 1.5× or more.
