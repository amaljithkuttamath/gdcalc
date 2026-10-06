# Calculation and compatibility

## Inputs and selection

The adapter accepts ENSOFT GROUP `.gp11t` and text reports in kip and kip-in, using the **last summary only**. By default, axial compression comes from local pile-top reactions; shear and moments come from local pile effects. `--load-source reactions` deliberately uses the top-reaction basis for every component. Strength cases are identified by `STR`; unknown case names require explicit selection. See the [CLI guide](cli.md).

The supported worksheet profile is a fixed-head compression-pile template. Geometry, materials, fixity, downdrag, headers and dates are inherited from the supplied template and need project review. Component envelopes are independent extrema, not concurrent load combinations. This does not import Excel binaries, rerun GROUP or design uplift. No production design template or engineering dataset is bundled. Read the [template contract](../references/template-contract.md).

## What executes

CalcpadCE is required for conversion. The adapter translates scalar real arithmetic, `min`/`max`/`abs`, powers/roots, `in`/`ft`/`kip`/`ksi`, comparisons (including chains), conditionals, early returns and string check messages. Mathcad zero comparisons adopt the other operand's units. Strings have distinct internal symbols and are never silently treated as numeric inputs. Other constructs fail explicitly.

These are limits of mcdxkit's current adapter, not the full CalcpadCE language. CalcpadCE executes the translated formulas; it does not execute `.mcdx` directly. The executable `.cpd` can be opened with CalcpadCE to edit and recalculate independently. The `.html` is a result snapshot.

Native `.mcdx` files retain formulas and dependencies; stale result caches are removed. Open in Mathcad Prime and press **Ctrl+F5** to calculate there. Native opening, rendering and calculation remain unverified until tested in Prime. ZIP/XML validation does not establish native compatibility or engineering adequacy. A successful calculation can contain failing design checks; general code-compliance validation is not implemented. See the proposed [standards register](engineering-standards.md).

## Check results

After calculation, MCDXKit reads check outcomes from the published calculated `.html`; nothing is recalculated. CalcpadCE renders a comparison (`<`, `≤`, `>`, `≥`, `≡`, `≠`, or a chain joined by `and`) as `name = symbolic = substituted = 1` (condition holds) or `= 0` (condition does not hold). Each rendered comparison becomes one entry in the audit's `checks` list:

| Field | Meaning |
| --- | --- |
| `name` | Defined variable, or the preceding label (`Expression`) for an evaluated comparison |
| `expression` / `substituted` | Symbolic and numeric forms as rendered |
| `result`, `passed` | The printed 1/0 and `passed = result == 1` |
| `ratio`, `demand`, `capacity`, `unit` | Demand/capacity, only when both substituted operands are single non-negative numbers with identical unit text and a positive capacity; otherwise `null` |
| `region_id`, `line` | Source Mathcad region and calculated-page line |

For `≤`/`<` the left operand is the demand; for `≥`/`>` the right operand is. No ratio is derived for compound operands (`0.75 · 200 kip`), different units (`in` versus `ft`), chains or equality. `check_summary` records totals, failed check names and the governing (largest) ratio. When the page contains no rendered comparisons the status is `no checks found`; MCDXKit does not infer checks from other values.

Limits: comparisons hidden inside conditionals and string messages such as `OK`/`NG` are not interpreted, and a displayed stored check variable (`check = 1`) is not a separate check. "Pass" means the rendered condition holds; write checks as conditions that must hold. Outputs created before this feature report checks as not recorded. Saved outputs in the browser show the summary only; the full list is in the convert response and the `.audit.json`. Check outcomes are not engineering approval.

Detection depends on how CalcpadCE renders results at the pinned revision (`calcpad.REVISION`): the `eq` span, ` = ` separators, operator glyphs and the final `1`/`0`. A test pins the exact rendered markup from the real engine, so a rendering change after an engine upgrade fails loudly instead of silently reporting no checks. A future translator could emit check metadata directly; that is not implemented.

## Original file and results

The browser reconstructs the original worksheet from saved region coordinates, page settings, headers, formatted text, images and native equations. It includes page thumbnails, navigation, zoom and search. Cached Mathcad values are labeled as saved values. The Results tab shows fresh CalcpadCE results; Changes compares native expressions. Reconstruction is not Prime-native rendering, and the calculated page follows equation order rather than reproducing the original layout.

Completed outputs and private source snapshots persist in the output directory. Saved outputs restores them after a restart; the visible upload queue and temporary previews do not survive refresh. Back up the whole output directory. Local mode keeps files local; hosted mode uploads them to the configured server. The server is a shared trusted workspace, not a multi-tenant service.

The UI bundles IBM Plex Sans under the [SIL Open Font License](../src/mcdxkit/web/fonts/OFL.txt) without font CDN requests. [Calculator attribution](../THIRD_PARTY.md) identifies the pinned CalcpadCE dependency.

## Batch pipeline

The batch engine uses bounded workers, an append-only `batch-manifest.jsonl`, source/template snapshots and per-file failures. Duplicate basenames receive separate job directories. Identity includes source path/content, template content, case selection, load basis, overrides and engine/translator versions. Changed inputs create new outputs; verified resume checks identities, hashes and calculation evidence before skipping work. Corrupted or incomplete outputs are not silently reused.

Use the [batch CLI](cli.md#batch-conversion) or `mcdxkit.batch.convert_batch(inputs, template, output_dir, workers=4, recursive=True, resume=True)`. For distributed scheduling, partition jobs into separate output directories. Two batches must not write to the same output directory. The browser is not a distributed job queue.
