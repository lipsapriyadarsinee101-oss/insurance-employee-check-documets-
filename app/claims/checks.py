from decimal import Decimal, ROUND_HALF_UP

from app.claims.extraction import SCHEMA, normalize_value
from app.claims.models import Correction, Document, Finding

RULES_VERSION = 'claims-consistency-1.0'


def validate_corrections(documents: list[Document], corrections: list[Correction]) -> None:
    docs = {d.role: d for d in documents}
    seen = set()
    for correction in corrections:
        key = (correction.role, correction.field)
        if key in seen:
            raise ValueError('Duplicate correction')
        seen.add(key)
        doc = docs[correction.role]
        if doc.status != 'ready' or correction.field not in doc.fields:
            raise ValueError('Only recognised fields in readable documents can be corrected; replace unsupported documents in a new case')
        if len(correction.reason.strip()) < 3:
            raise ValueError('A correction reason is required')
        if correction.value is not None:
            normalize_value(correction.field, correction.value)


def effective_values(documents: list[Document], corrections: list[Correction]):
    values = {f'{doc.role}.{key}': field.value if doc.status == 'ready' and field.status == 'known' else None
              for doc in documents for key, field in doc.fields.items()}
    for correction in corrections:
        values[f'{correction.role}.{correction.field}'] = (
            normalize_value(correction.field, correction.value) if correction.value is not None else None)
    return values


def run_checks(documents: list[Document], corrections: list[Correction] | None = None) -> list[Finding]:
    corrections = corrections or []
    validate_corrections(documents, corrections)
    values = effective_values(documents, corrections)
    changed = {f'{c.role}.{c.field}' for c in corrections}
    findings = []

    def add(code, title, status, detail, inputs):
        findings.append(Finding(code=code, title=title, status=status, detail=detail, inputs=inputs,
                                uses_reviewer_input=bool(set(inputs) & changed)))

    refs = ['policy.policy_id', 'claim.policy_id', 'invoice.policy_id']
    ids = [values.get(key) for key in refs]
    known = {value for value in ids if value is not None}
    status = 'conflict' if len(known) > 1 else 'unknown' if None in ids else 'consistent'
    add('policy_ids', 'Policy IDs across documents', status,
        'IDs differ across available documents.' if status == 'conflict' else
        'All three policy IDs are needed.' if status == 'unknown' else 'All three policy IDs match exactly.', refs)

    refs = ['policy.policy_start', 'policy.policy_end', 'claim.incident_date']
    start, end, incident = [values.get(key) for key in refs]
    if None in (start, end, incident):
        status, detail = 'unknown', 'Readable policy dates and incident date are required.'
    elif start > end:
        status, detail = 'unknown', 'Policy start is after policy end; review the date evidence.'
    elif not start <= incident <= end:
        status, detail = 'conflict', f'Incident {incident} is outside {start} to {end} (inclusive). This is not a coverage decision.'
    else:
        status, detail = 'consistent', f'Incident date is within {start} to {end} (inclusive). This is not a coverage decision.'
    add('policy_period', 'Incident date vs stated policy period', status, detail, refs)

    refs = ['claim.claimed_amount', 'invoice.invoice_total']
    amounts = [values.get(key) for key in refs]
    status = 'unknown' if None in amounts else 'consistent' if amounts[0] == amounts[1] else 'conflict'
    add('amount_match', 'Claimed amount vs invoice total', status,
        'Both readable EUR amounts are required.' if status == 'unknown' else
        f'Claimed EUR {amounts[0]}; invoice EUR {amounts[1]}. Exact cent comparison; no deductible or coverage calculation.', refs)

    refs = [f'{role}.{key}' for role, fields in SCHEMA.items() for key in fields]
    missing = [key for key in refs if values.get(key) is None]
    bad_docs = [f'{d.role}: {d.status}' for d in documents if d.status != 'ready']
    # Invoice item detail is required whenever a valid item count is available.
    count = values.get('invoice.item_count')
    if count:
        for index in range(1, int(count) + 1):
            for suffix in ('quantity', 'unit_price', 'line_total'):
                key = f'invoice.item_{index}_{suffix}'
                refs.append(key)
                if values.get(key) is None:
                    missing.append(key)
    add('required_information', 'Required documents and information', 'unknown' if missing or bad_docs else 'consistent',
        'Review needed: ' + '; '.join(bad_docs + missing) if missing or bad_docs else
        'All required template fields are present and parseable; their truth is not verified.', refs)

    refs = ['invoice.item_count', 'invoice.subtotal', 'invoice.tax', 'invoice.invoice_total']
    problems = []
    unavailable = not count
    calculated_subtotal = Decimal('0')
    if count:
        expected = {f'item_{i}_{suffix}' for i in range(1, int(count) + 1)
                    for suffix in ('quantity', 'unit_price', 'line_total')}
        actual = {key for d in documents if d.role == 'invoice' for key in d.fields if key.startswith('item_') and key != 'item_count'}
        if actual - expected:
            unavailable = True
            problems.append('Item count does not account for all extracted item fields.')
        for index in range(1, int(count) + 1):
            item_refs = [f'invoice.item_{index}_{suffix}' for suffix in ('quantity', 'unit_price', 'line_total')]
            refs.extend(item_refs)
            quantity, price, line = [values.get(key) for key in item_refs]
            if None in (quantity, price, line):
                unavailable = True
                continue
            calculated = (Decimal(quantity) * Decimal(price)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            calculated_subtotal += Decimal(line)
            if calculated != Decimal(line):
                problems.append(f'Item {index}: quantity x unit price = EUR {calculated}, stated line total = EUR {line}.')
    subtotal, tax, total = [values.get(key) for key in refs[1:4]]
    if None in (subtotal, tax, total):
        unavailable = True
    elif count:
        if not unavailable and calculated_subtotal != Decimal(subtotal):
            problems.append(f'Sum of stated line totals = EUR {calculated_subtotal:.2f}, subtotal = EUR {subtotal}.')
        if Decimal(subtotal) + Decimal(tax) != Decimal(total):
            problems.append(f'Subtotal + tax = EUR {Decimal(subtotal) + Decimal(tax):.2f}, total = EUR {total}.')
    status = 'unknown' if unavailable else 'conflict' if problems else 'consistent'
    detail = ' '.join(problems)
    if unavailable:
        detail = 'Complete, unambiguous item count, quantities, EUR unit prices, line totals, subtotal, tax and total are required. ' + detail
    elif not problems:
        detail = 'Quantity x unit price, sum of line totals, and subtotal + stated tax agree. EUR cents, ROUND_HALF_UP per line; tax rate is not assessed.'
    add('invoice_arithmetic', 'Invoice arithmetic', status, detail.strip(), refs)
    return findings
