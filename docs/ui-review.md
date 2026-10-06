# UI review

## Readability and accessibility

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| HIGH | src/gdcalc/web/style.css:1 | Several labels were 10–11px with contrast between 2.45:1 and 4.26:1 | Bundled IBM Plex Sans, 12px minimum UI metadata, darker light-surface labels and lighter dark-surface labels | Readability and contrast. Native worksheet type remains unchanged. |
| HIGH | src/gdcalc/web/style.css:25 | Small page controls and close button | 44px minimum control dimensions, visible focus, named remove-file actions | Touch targets and keyboard access. |
| HIGH | src/gdcalc/web/app.js:16 | An invalid override surfaced away from the field | Return to inputs, expand settings, show an inline alert, mark invalid and focus the field | Errors belong beside the input and explain recovery. |

## Structure and surface polish

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | src/gdcalc/web/style.css:140 | File title and tabs consumed separate desktop rows | Shared title/tab row on desktop, stacked layout on narrower screens | Information hierarchy keeps the document dominant. |
| MEDIUM | src/gdcalc/web/app.js:128 | Thumbnail rail consumed mobile reading width | Rail starts collapsed on narrow screens and remains available through Pages | Responsive reading space. |
| LOW | src/gdcalc/web/style.css:105 | Output actions wrapped into uneven rows | Two-column action group | Consistent grouping and alignment. |
| LOW | src/gdcalc/web/index.html:1; src/gdcalc/web/app.js:1 | Arrow-suffixed actions, uppercase comparison labels, decorative status dots and monospace metadata | Sentence case, consistent action names, reduced decoration and one interface family | Content guides the workflow. |

## Interaction polish

| Severity | Location | Before | After | Why |
| --- | --- | --- | --- | --- |
| MEDIUM | src/gdcalc/web/app.js:14 | Busy state was only visual disabled controls | Explicit aria-busy plus existing status announcements | State changes have static and accessible cues. |
| LOW | src/gdcalc/web/style.css:25 | Generic transitions with no press feedback | 150ms cubic-bezier(0.2, 0, 0, 1), 0.96 press scale, static page controls, reduced-motion override | Interruptible feedback with high-frequency restraint. |

## Verification

- Browser: actual report upload, input review, invalid override and recovery, comparison, successful output generation, actual-file page navigation and thumbnails.
- Browser: 360 CSS pixel mobile viewport, no document overflow, thumbnail rail collapsed, close returns to workflow, visible keyboard focus, error focus returns to overrides.
- Browser: desktop screenshot critique, no browser errors during the verified flow.
- Server: six integration tests pass, including local font assets, rejected unlisted/traversal paths and existing conversion/authentication checks.
- Source: exact transition easing, press scale, explicit properties, reduced-motion override, no page-load animation, no runtime font CDN.
- Not verified: 10%-speed playback in a browser Animations panel, physical touch devices, a screen-reader session, OS-level reduced-motion switching and theme switching (the product has no theme switch).
- The additional scripts/recipe files referenced in the pasted skills were absent; no database-match or missing-recipe verification is claimed.

Approve for the inspected scope. Unverified coverage is listed above.
