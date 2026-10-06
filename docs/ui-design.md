# Worksheet review interface

## Brief

A local engineering conversion tool. Engineers need to inspect their raw report, review selected loads and inherited worksheet assumptions, compare changes, then inspect and download executable files. Keep the worksheet central. The visual direction is minimal enterprise with restrained monochrome depth, informed by the user's CRED reference.

## Tokens

- Ink `#000000`: top-level header.
- Graphite `#22252B`: controls surface.
- Paper `#FFFFFF`: actual worksheet and document controls.
- Canvas `#E4E7EB`: surrounding document area.
- Secondary text `#AEB4BF`: readable text on graphite.
- Focus `#365D9F`: keyboard focus and selection boundaries.

IBM Plex Sans, locally bundled under the SIL Open Font License, is the interface family. Use 12px metadata, 12–14px controls/body, 20px tabular load values and 24px section titles. Native document typography and formatting remain unchanged. Source/XML content alone uses monospace. Labels and prose align left; comparable numeric values align right.

## Layout comparison

A generic dashboard puts summaries ahead of source evidence:

    [ status ][ count ][ metric ]
    [            cards         ]

Use a document review desk instead:

    [ brand                         saved outputs ]
    [ workflow ][ file title / document views     ]
    [ inputs   ][ pages ][ actual worksheet      ]
    [ next step][       ][                       ]

The numbered workflow is a real sequence. The page rail contains actual document thumbnails. On small screens, the document occupies the screen with an explicit return-to-inputs control; controls must remain reachable and touch-sized.

## Review against the brief

The earlier design used monospace metadata everywhere, repeated borders and badges, dot-separated labels, arrow-suffixed actions and undersized text. Those conventions were generic decoration rather than useful engineering information. Remove them. Retain boundaries only where they separate the input workflow from the document or show selected state. Keep the main worksheet as the single dominant element; do not introduce a promotional hero, fake metrics or decorative drawings.

Case selection and implementation details stay behind disclosures. Status text describes completed operations, never engineering approval. Saved Mathcad results remain distinct from fresh Calcpad calculations. Errors explain the next action.

## Interaction and verification

Use 44px touch targets where controls are operated, visible keyboard focus, tabular numbers and at least 4.5:1 text contrast. Buttons use the supplied 0.96 press scale, except static high-frequency page controls. Interactive transitions use `cubic-bezier(0.2, 0, 0, 1)`, at most 150ms, and disable under reduced motion. No page-load animation.

Verify desktop and mobile, input and empty states, keyboard focus, selected/disabled controls, errors, loading feedback, thumbnail navigation and search. The pasted ui-ux-pro-max database scripts and linked better-ui recipes were not supplied or installed; this implementation uses the provided prose rules, not a claimed database match.
