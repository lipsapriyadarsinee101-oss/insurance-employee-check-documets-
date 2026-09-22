# Validation of milestone 1

Local validation on 2026-09-22 (Windows, Python 3.12):

- `python -m pytest -q`: **43 passed**, 2 dependency deprecation warnings, 3.89 seconds.
- `python -m scripts.evaluate`: **3/3 authored fictional scenarios matched their expected findings**.
- `python -m compileall -q app scripts streamlit_app.py`: passed.
- `git diff --check`: passed.
- All 8 fictional PDFs (10 pages) were rendered with Poppler and visually inspected for readable text, page numbering and layout. The renderer emitted missing fallback-font messages, but the samples use standard Helvetica and displayed correctly.

The test suite includes a Streamlit AppTest session connected to the FastAPI test client: load a conflicting sample, edit an amount, enter notes, save a review, recalculate findings, and reopen its history. API tests also exercise actual multipart upload and original-document download. SQLite tests reopen the database and test simultaneous stale saves.

The two warnings originate from the installed Starlette/FastAPI test-client dependencies. No paid services or LLM calls were used. Tests did not launch or deploy a hosted application.

## Expected sample outcomes

| Scenario | Policy IDs | Incident period | Amount match | Required information | Invoice arithmetic |
|---|---|---|---|---|---|
| Clean | consistent | consistent | consistent | consistent | consistent |
| Conflicting | conflict | conflict | conflict | consistent | conflict |
| Missing | unknown | unknown | unknown | unknown | unknown |

The clean case uses EUR 595.00 and matching IDs. The conflicting case has a different invoice policy ID, an incident before the stated period, a EUR 650.00 claim against a EUR 595.00 invoice, and an incorrect item line total. The missing case omits the invoice, incident date and damage description.

[Machine-readable local run](evaluation.json) includes source hashes, PDF hashes, dependency versions, elapsed time and individual expected/actual statuses. These are regression fixtures, **not** a held-out benchmark or proof of performance on real insurer documents. Scenario timings include sample PDF generation and extraction; they are diagnostics, not a latency guarantee.

## Explicit remaining limits

- Labelled English text PDFs only; no OCR, handwriting, general table understanding or arbitrary insurance layouts.
- A pre-existing OCR text layer is not checked against the image. Page/passage provenance supports inspection, not factual authenticity.
- No coverage, payable-amount, fraud or claim decision. Dates are compared only to the stated period; tax rates and contractual rules are not assessed.
- Reviewer corrections are assertions, separately labelled and preserved in history; they are not automatically document-verified.
- Local SQLite and unauthenticated loopback services only. No production access controls, encryption, immutable audit ledger, retention service or hosted deployment.
- Broader benchmark, OCR, authenticated deployment/PostgreSQL, and demonstration video remain later milestones.
