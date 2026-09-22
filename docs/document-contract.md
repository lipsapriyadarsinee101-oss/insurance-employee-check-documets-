# Supported document contract (v1)

The parser supports **labelled English text PDFs**, one document per role, up to 5 MiB and 10 pages each, with at most 100,000 extracted characters per document. A document must contain `Document type: Policy`, `Document type: Claim`, or `Document type: Invoice`, matching its upload role. Matching is case-insensitive; field labels must begin an extracted line and end with a colon. Values must fit on that same extracted line. Multi-column tables, handwriting, arbitrary layouts, image-only pages and encrypted files are not supported.

A page with no extractable text makes a mixed document `partial`; all comparisons depending on it remain unknown. A wholly textless document is `unsupported` with a no-OCR message. An image with a pre-existing text layer can be read, but the application does not validate that layer against the image. Invalid PDFs retain their supplied bytes for local review and have no trusted parsed values. File size limits are not a substitute for an isolated parser or hardened upload service.

## Required labels

Policy:

```text
Document type: Policy
Policy ID: HOME-FIC-2026-001
Policyholder: Alex Example
Property address: 14 Example Lane, Sampletown
Policy start: 2026-01-01
Policy end: 2026-12-31
```

Claim:

```text
Document type: Claim
Policy ID: HOME-FIC-2026-001
Claim ID: CLM-FIC-1001
Claimant: Alex Example
Property address: 14 Example Lane, Sampletown
Incident date: 2026-06-10
Reported date: 2026-06-11
Claimed amount: EUR 595.00
Damage description: Accidental breakage of a kitchen window.
```

Invoice (may span multiple pages):

```text
Document type: Invoice
Policy ID: HOME-FIC-2026-001
Invoice ID: INV-FIC-3001
Supplier: Example Window Repair Ltd
Invoice date: 2026-06-15
Item count: 2
Subtotal: EUR 500.00
Tax: EUR 95.00
Invoice total: EUR 595.00
Item 1 quantity: 2
Item 1 unit price: EUR 150.00
Item 1 line total: EUR 300.00
Item 2 quantity: 4
Item 2 unit price: EUR 50.00
Item 2 line total: EUR 200.00
```

All example names and values are fictional. Optional prose is ignored, not interpreted as instructions. Invoice descriptions may be shown in the page text but are not an arithmetic input.

Dates accept only ISO `YYYY-MM-DD` or unambiguous `DD.MM.YYYY`. Calendar validity is checked. Slash dates are unknown, not guessed. EUR money requires a currency prefix and exactly two decimal places; `EUR 1234.56` and `EUR 1234,56` are accepted. Thousands separators, other currencies, negative amounts and scientific notation are unsupported. Quantities must be positive with at most three decimal places; item count is 1-20. IDs use letters, digits and hyphens, with exact case-sensitive comparisons.

Repeated labels with equivalent normalized values retain all their evidence. Conflicting duplicates become `ambiguous`; any invalid duplicate makes the field `unparseable`. Both cases require review. Omitted labels become `missing`. Empty, pending, unknown and N/A values are unparseable. Original evidence is retained even when parsing fails.

Reviewer corrections must refer to existing recognised fields in a `ready` document, use the same formats, and have a reason. They can resolve a field-level ambiguity or mark a value unknown. They cannot invent a missing document or repair a scanned/partial document; upload a new case with supported documents instead. The correction set in each save replaces the previous set, while history retains every saved version.
