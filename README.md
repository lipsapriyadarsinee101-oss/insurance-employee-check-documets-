# Insurance Claims Review Workbench

An English-language review desk for **fictional property-repair claims**. Compare a policy schedule, claim form and repair invoice, inspect the exact page passages behind extracted values, correct transcription errors, and keep a versioned record of human review.

This is a bounded portfolio project linking insurance operations and BI experience to Python, FastAPI, document extraction, deterministic validation and an auditable review workflow. **It does not decide insurance coverage, detect fraud, or approve/reject claims.** No LLM, API key, paid service or OCR is used.

## Run it locally

Python 3.11+ is required. Get the implementation branch while the PR is a draft:

```bash
git clone -b feat/claims-review-workbench https://github.com/lipsapriyadarsinee101-oss/insurance-employee-check-documets-.git
cd insurance-employee-check-documets-
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install and start the API from the repository root:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

In a second terminal, activate the same environment, then run:

```bash
python -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Open **http://127.0.0.1:8501**. API documentation: **http://127.0.0.1:8000/docs**. No separate database server is needed.

## Try the workflow

1. Choose **clean**, **conflicting** or **missing** in the sidebar and click **Load sample case**. Every sample is clearly marked fictional. Each click creates a new independent case.
2. Inspect the five findings and expand **Documents & exact passages**. Values include original filename, document hash, one-based page number, and an exact passage from extracted page text. Invoice line items are on page 2. Download the original PDFs to compare visually.
3. In **Reviewer corrections & notes**, enable **Override**, enter the corrected value and a reason, then add your name/notes. A blank override marks the field unknown; disabling it restores the extracted value. **Save review and rerun checks** appends a revision and recalculates findings.
4. Open **Review history** to inspect prior corrections, notes and findings. **Open saved case** reloads the case after a browser/API restart. Concurrent stale saves are rejected rather than overwriting another review.
5. Try **Upload PDFs** with one file per role. A missing document may be omitted. The parser expects the labelled text format described in [the document contract](docs/document-contract.md), not arbitrary insurer layouts.

To export the eight fictional sample PDFs for the upload workflow:

```bash
python -m scripts.export_samples
```

The script creates `sample-pdfs/clean/`, `sample-pdfs/conflicting/` and `sample-pdfs/missing/`. They are generated from versioned source, and are also downloadable from sample cases. There are three documents in clean/conflicting cases and two in the missing case.

## The five checks

| Check | Comparison | Unknown / review-needed when |
|---|---|---|
| Policy IDs | Exact equality across policy, claim and invoice | A needed ID/document is missing, ambiguous or unparseable; known conflicting IDs are still flagged |
| Incident vs stated policy period | Incident date within start/end, inclusive | Dates are unavailable or start is after end; this is **not a coverage decision** |
| Claimed vs invoice amount | EUR amounts compared to the cent | Either amount is unavailable or uses an unsupported format/currency |
| Required information | Required documents, dates, IDs, parties, address, damage description and invoice details | Any required input is missing, ambiguous, unsupported or unparseable |
| Invoice arithmetic | Quantity x unit price; sum of line totals; subtotal + stated tax | Any required arithmetic input is absent/invalid, or item count does not account for extracted items |

Arithmetic uses decimal values and `ROUND_HALF_UP` to cents per line. Tax rates, deductibles, exclusions, liability, authenticity, duplicate claims and payable amounts are **not assessed**. A `consistent` finding means no discrepancy was found in the stated inputs, not that a claim is valid.

## Evidence and human input

Extraction status (`known`, `missing`, `ambiguous`, `unparseable`) is separate from a finding (`consistent`, `conflict`, `unknown`). `known` means a label was parsed, not that the statement is true. Duplicate conflicting values retain all passages and are unknown for comparisons. Missing or unreadable evidence never becomes an automatic pass.

Passage offsets refer to `pypdf`'s extracted page text, **not PDF byte offsets or image coordinates**. The application retains original PDF bytes, SHA-256 hashes, extracted text and original values. Reviewer corrections are separate assertions with reasons; findings using them are visibly labelled. They never inherit document provenance as if automatically verified. There is no confidence probability or citation-based grounding score.

## Storage and API

The default database is `local-data/reviews.sqlite3` (gitignored). It stores original PDFs, immutable extraction snapshots, and append-only review revisions. Set `CLAIMS_DB_PATH` in the API process to choose another local SQLite file; set `API_URL` in the UI process for another API address. `.env.example` documents these names; `.env` is not loaded automatically.

This milestone is a **local, unauthenticated, single-workstation demo**. Use fictional/de-identified data. Records are not encrypted, tamper-evident or suitable for production retention requirements. No secrets or customer documents belong in Git. PostgreSQL migrations, authentication/authorization, controlled document storage and retention are later work, not implemented claims.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Process health; no paid provider |
| `GET /v1/claims/samples` | List fictional samples |
| `POST /v1/claims/samples/{name}` | Create a sample case |
| `POST /v1/claims/cases` | Multipart `policy`, `claim`, `invoice`, plus `title`; at least one file |
| `GET /v1/claims/cases` | Most recent 100 cases |
| `GET /v1/claims/cases/{id}` | Original evidence, current findings and latest review |
| `GET /v1/claims/cases/{id}/documents/{role}` | Download original PDF |
| `POST /v1/claims/cases/{id}/reviews` | Save full correction set, reviewer, notes and workflow status |
| `GET /v1/claims/cases/{id}/history` | All saved review revisions |

Review requests include `expected_revision`. The server returns HTTP 409 for a stale save, 422 for an invalid correction, and 404 for an absent case/document. Review workflow statuses are `in_review`, `needs_information`, and `review_recorded`; approval/rejection statuses are deliberately absent. Replacing the document bundle requires a new case in this milestone.

## Validation

```bash
python -m pytest -q
python -m scripts.evaluate --output evaluation-results.json
```

Tests exercise extraction and exact page provenance, invalid/duplicate values, date boundaries, arithmetic and rounding, scanned/partial/encrypted/malformed PDFs, upload limits, corrections, persistence after restart, stale revisions, API contracts, and a Streamlit load/edit/save/reopen workflow. GitHub Actions runs the same offline commands and uploads the scenario report.

The scenario report records expected vs actual findings for three **authored fictional regression cases**, individual failures, versions, source/PDF hashes and elapsed time. It is not a general extraction-accuracy or claim-decision benchmark. See [validation notes](docs/validation.md) for actual results.

## Structure and next milestones

- `app/claims/extraction.py`: bounded labelled-text parser and passage provenance
- `app/claims/checks.py`: five deterministic checks, without claim decisions
- `app/claims/store.py`: SQLite documents and review revisions
- `app/api.py`: typed FastAPI endpoints
- `streamlit_app.py`: English review desk
- `app/claims/samples.py`: fictional PDF fixtures; `scripts/`: sample export and evaluation

Next milestones: a broader labelled document benchmark and more layouts; scanned-PDF/OCR support with confidence and manual verification; authenticated deployment with PostgreSQL and retention controls; and a short demonstration video. None is necessary to run this first milestone. There is no hosted deployment or external outreach in this delivery.
