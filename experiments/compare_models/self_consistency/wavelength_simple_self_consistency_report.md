# Wavelength Simple Self-Consistency (5 runs)

- Config: `experiments/compare_models/experiment_configs/wavelength_normalization_100.yaml`
- Runs: `wavelength_simple_100_run1..run5` (100 cases each)
- Fleiss’ kappa: **0.929**
- Perfect agreement: **89/100** cases
- Parse errors: **0** across all runs

## Disagreement cases (11)
Per case: prompt text, per-run outputs `(type, unit, values)`, and a quick hypothesis on why runs diverged.

### Case 16 — Lyα
- Prompt: `Lyα`
- Outputs:
  - run1: (discrete, angstrom, 1215.67)
  - run2: (discrete, angstrom, 1215.67)
  - run3: (discrete, angstrom, 1215.67)
  - run4: (discrete, angstrom, 1215.67)
  - run5: (discrete, angstrom, 1216.0)
- Likely cause: rounding variance on the canonical Lyα wavelength.

### Case 17 — EUV multi-line list
- Prompt: `EUV 131 Å ... 94, 131, 193, 171, 211, 335 Å`
- Outputs:
  - run1: (discrete, angstrom, 94.0, 131.0, 131.0, 171.0, 193.0, 211.0, 335.0)
  - run2: (discrete, angstrom, 94.0, 131.0, 171.0, 193.0, 211.0, 335.0)
  - run3: (discrete, angstrom, 94.0, 131.0, 171.0, 193.0, 211.0, 335.0)
  - run4: (discrete, angstrom, 94.0, 131.0, 131.0, 171.0, 193.0, 211.0, 335.0)
  - run5: (discrete, angstrom, 94.0, 131.0, 171.0, 193.0, 211.0, 335.0)
- Likely cause: occasional duplication of a listed value (131) in the text output.

### Case 62 — “1.4–3.7 mHz”
- Prompt: `p-mode frequency domain emphasized: between 1.4 and 3.7 mHz`
- Outputs:
  - run1: (range, Hz, 0.001, 0.004)
  - run2: (not_applicable, N/A, [])
  - run3: (range, Hz, 0.001, 0.004)
  - run4: (not_applicable, N/A, [])
  - run5: (range, Hz, 0.001, 0.004)
- Likely cause: borderline frequency phrasing—some runs convert mHz to Hz range, others bail out.

### Cases 63 & 64 — “ν < 2.2 mHz; below 2 mHz”
- Prompt: `Low-frequency emphasis: ν < 2.2 mHz; better computed/observed agreement below 2 mHz`
- Outputs:
  - run1: (discrete, MHz, 2.2, 2.0)
  - run2: (not_applicable, N/A, [])
  - run3: (not_applicable, N/A, [])
  - run4: (discrete, Hz, 0.002, 0.002)
  - run5: (not_applicable, N/A, [])
- Likely cause: inequality phrasing and unit hopping (mHz rendered as MHz or Hz) leading to drop/convert variance.

### Case 65 — “1.4–3.7 mHz (again)”
- Prompt: `p-mode frequency domain where cross-instrument consistency is established: 1.4–3.7 mHz`
- Outputs:
  - run1: (range, Hz, 0.001, 0.004)
  - run2: (not_applicable, N/A, [])
  - run3: (not_applicable, N/A, [])
  - run4: (not_applicable, N/A, [])
  - run5: (not_applicable, N/A, [])
- Likely cause: same frequency range as Case 62; run1 converts, others drop as not_applicable.

### Case 68 — Fe XIV/Fe XIII lines
- Prompt: `Fe XIV 334.2 Å, Fe XIII 348.2 Å ... 353.8 Å`
- Outputs:
  - run1: (discrete, angstrom, 334.2, 348.2, 353.8)
  - run2: (discrete, angstrom, 334.2, 348.2, 353.8)
  - run3: (discrete, angstrom, 334.2, 348.2, 353.8)
  - run4: (discrete, angstrom, 334.2, 348.2, 353.8)
  - run5: (discrete, angstrom, 334.2, 348.2, 334.2, 353.8)
- Likely cause: duplication of 334.2 in one run when parsing multiple comma-separated lines.

### Case 85 — “Soft X-ray imaging (SXT partial-frame)”
- Prompt: `Soft X-ray imaging (SXT partial-frame)`
- Outputs:
  - run1: (range, nm, 0.1, 10.0)
  - run2: (not_applicable, N/A, [])
  - run3: (not_applicable, N/A, [])
  - run4: (not_applicable, N/A, [])
  - run5: (not_applicable, N/A, [])
- Likely cause: ambiguity of “Soft X-ray” without explicit numeric range.

### Case 93 — “X-ray spectroscopy; 1/3 keV bins …”
- Prompt: `X-ray spectroscopy; 1/3 keV bins <25 keV; analysis of high-energy tail >10 keV`
- Outputs:
  - run1: (discrete, keV, 0.333, 10.0, 25.0)
  - run2: (None, None, [])
  - run3: (discrete, keV, 0.333, 25.0, 10.0)
  - run4: (discrete, keV, 0.333, 10.0, 25.0)
  - run5: (discrete, keV, 0.333, 10.0, 25.0)
- Likely cause: one run failed to emit structured text; ordering of discrete energies varies but is equivalent.

### Case 98 — “Soft X-ray”
- Prompt: `Soft X-ray`
- Outputs:
  - run1: (range, angstrom, 1.0, 100.0)
  - run2: (range, angstrom, 1.0, 100.0)
  - run3: (range, keV, 0.1, 10.0)
  - run4: (range, nm, 0.1, 10.0)
  - run5: (range, nm, 0.1, 10.0)
- Likely cause: band-name interpretation mapped to different canonical ranges/units (Å vs keV vs nm).

### Case 99 — “Soft X-ray” (duplicate case)
- Prompt: `Soft X-ray`
- Outputs:
  - run1: (range, nm, 0.12, 12.0)
  - run2: (range, nm, 0.1, 10.0)
  - run3: (range, nm, 0.1, 10.0)
  - run4: (range, nm, 0.124, 12.4)
  - run5: (range, nm, 0.1, 10.0)
- Likely cause: variability in mapping “Soft X-ray” to numeric range (different canonical bounds/rounding).

## Quick takeaways
- Most disagreement stems from ambiguous band names (“Soft X-ray”) and frequency inequality phrasing in mHz.
- Numeric disagreements are small (rounding or duplicate entries) and isolated to a few cases.
- No parse failures; all variance is in model outputs, not the parser.
