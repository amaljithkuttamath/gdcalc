# AI assistant

gdcalc includes an optional Claude assistant for two engineering review tasks. It is off by default, advisory only, and never changes inputs, case selections, worksheets or calculated results.

| Task | Where | What it does |
| --- | --- | --- |
| Case classification | **Inputs** step → *Suggest cases with AI*; `gdcalc assist cases report.gp11t` | Classifies each final-summary case as strength, service, other or unknown with a reason, and recommends strength cases. Useful when case names do not follow the `STR`/`SER` convention and `selection_required` blocks the default selection. |
| Results review | **Outputs** → *AI review*; `gdcalc assist review out.mcdx` | Reads the audit and the CalcpadCE result page and reports what governs, failed or marginal checks, suspicious inputs or provenance, and what to verify next, with the evidence for each finding. |

Separately, and without any model, `inspect` now reports the **governing case** for every envelope component, the runner-up case and the lead ratio between them. The Inputs step shows it under each load value and flags a component when one case leads the next by 1.5× or more.

## Guarantees

- Suggestions are validated: only cases the assistant itself classified as strength can be recommended, unknown case IDs are dropped (`ignored_case_ids`), and the recommended set is checked by the same `select` rules as a manual selection. A set the template cannot use (for example tension in a compression template) is shown with `selection_issue` and cannot be applied.
- Nothing is applied automatically. The engineer selects *Use cases …* or passes `--cases` explicitly.
- A refused, truncated or failed request is an explicit error, never an empty or partial suggestion.
- Report text and case names are untrusted data; the prompts tell the model to ignore instructions inside them.
- Reviews are labeled advisory in the browser, terminal and Markdown output. They are not an engineering check, Prime verification or approval.

## Data sent to Anthropic

Only when a user asks for a suggestion or review:

- Case classification: case IDs, case names and min/max of the five local load components per case. The raw report is not sent.
- Results review: the audit metadata (source filename, selected cases and their extrema, envelope, governing cases, overrides, pile counts, notes, engine revision) and the plain text of the CalcpadCE result page. The `.mcdx` package is not sent, but the result page shows the template's inherited inputs, equations and labels as calculated, so treat the template's values as shared.

Do not enable the assistant where project data may not leave your network.

## Setup

```bash
python -m pip install "gdcalc[ai]"
export ANTHROPIC_API_KEY=...        # or an `ant auth login` profile
gdcalc serve --ai                   # or GDCALC_AI=1
gdcalc assist cases report.gp11t
gdcalc assist review outputs/design.mcdx --output outputs/design.ai-review.md
```

`GDCALC_AI_MODEL` overrides the model (default `claude-opus-5-5`). Requests use structured outputs; on Claude Opus 5.5, Opus 5, Sonnet 5.5 and Fable 5.1 they also use Anthropic's server-side refusal fallback, and the output names the model that actually answered. `serve --ai` refuses to start without the `anthropic` package; the published container image does not include it. The browser server allows one assistant request at a time and 200 per session; assistant calls do not hold the conversion lock.
