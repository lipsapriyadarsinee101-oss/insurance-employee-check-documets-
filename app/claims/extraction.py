"""Labelled text-PDF parser. Evidence offsets refer to pypdf extracted page text."""
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import re

from pypdf import PdfReader
from app.claims.models import Document, Evidence, ExtractedField

MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 10
MAX_TEXT = 100_000
SCHEMA = {
    'policy': {'policy_id': 'Policy ID', 'policy_start': 'Policy start', 'policy_end': 'Policy end',
               'policyholder': 'Policyholder', 'property_address': 'Property address'},
    'claim': {'policy_id': 'Policy ID', 'claim_id': 'Claim ID', 'incident_date': 'Incident date',
              'reported_date': 'Reported date', 'claimed_amount': 'Claimed amount',
              'claimant': 'Claimant', 'property_address': 'Property address', 'description': 'Damage description'},
    'invoice': {'policy_id': 'Policy ID', 'invoice_id': 'Invoice ID', 'invoice_date': 'Invoice date',
                'supplier': 'Supplier', 'item_count': 'Item count', 'subtotal': 'Subtotal',
                'tax': 'Tax', 'invoice_total': 'Invoice total'},
}
DATE_FIELDS = {'policy_start', 'policy_end', 'incident_date', 'reported_date', 'invoice_date'}
MONEY_FIELDS = {'claimed_amount', 'subtotal', 'tax', 'invoice_total'}


def normalize_value(field: str, raw: str) -> str:
    value = raw.strip()
    if not value or value.lower() in {'unknown', 'n/a', 'not provided', 'pending'}:
        raise ValueError('No usable value')
    if field in DATE_FIELDS:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return date.fromisoformat(value).isoformat()
        if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value):
            return datetime.strptime(value, '%d.%m.%Y').date().isoformat()
        raise ValueError('Use YYYY-MM-DD or DD.MM.YYYY')
    if field in MONEY_FIELDS or field.endswith(('_unit_price', '_line_total')):
        match = re.fullmatch(r'EUR\s+([0-9]{1,8}[.,][0-9]{2})', value, re.I)
        if not match:
            raise ValueError('Use EUR 1234.56, with no thousands separator')
        return f"{Decimal(match[1].replace(',', '.')):.2f}"
    if field == 'item_count':
        if not re.fullmatch(r'[1-9]|1[0-9]|20', value):
            raise ValueError('Item count must be 1-20')
        return str(int(value))
    if field.endswith('_quantity'):
        if not re.fullmatch(r'[0-9]{1,5}(?:[.,][0-9]{1,3})?', value):
            raise ValueError('Invalid quantity')
        result = Decimal(value.replace(',', '.'))
        if result <= 0:
            raise ValueError('Quantity must be positive')
        return str(result)
    if field.endswith('_id') and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{1,79}', value):
        raise ValueError('Invalid identifier')
    if len(value) > 500:
        raise ValueError('Value too long')
    return value


def field_labels(role: str, pages: list[str]) -> dict[str, str]:
    labels = dict(SCHEMA[role])
    if role == 'invoice':
        # Include all declared/discovered item indexes, even if another item is missing.
        indexes = set()
        for page in pages:
            indexes.update(int(n) for n in re.findall(r'^Item ([0-9]{1,2}) ', page, re.M | re.I) if 1 <= int(n) <= 20)
            for count in re.findall(r'^Item count:\s*([0-9]{1,2})\s*$', page, re.M | re.I):
                if 1 <= int(count) <= 20:
                    indexes.update(range(1, int(count) + 1))
        for index in sorted(indexes):
            for suffix in ('quantity', 'unit_price', 'line_total'):
                labels[f'item_{index}_{suffix}'] = f"Item {index} {suffix.replace('_', ' ')}"
    return labels


def extract_fields(role: str, pages: list[str]) -> dict[str, ExtractedField]:
    fields = {}
    for key, label in field_labels(role, pages).items():
        evidence, values = [], []
        invalid = False
        for page_no, text in enumerate(pages, 1):
            for match in re.finditer(r'^' + re.escape(label) + r':[ \t]*([^\r\n]*)', text, re.M | re.I):
                evidence.append(Evidence(page=page_no, passage=match[0], start=match.start(), end=match.end()))
                try:
                    values.append(normalize_value(key, match[1]))
                except ValueError:
                    invalid = True
        status = 'missing' if not evidence else 'unparseable' if invalid else 'ambiguous' if len(set(values)) > 1 else 'known'
        fields[key] = ExtractedField(value=values[0] if status == 'known' else None, status=status, evidence=evidence)
    return fields


def parse_pdf(role: str, filename: str, data: bytes | None) -> Document:
    if data is None:
        return Document(role=role, filename='', status='missing', issues=['Document not supplied'], fields=extract_fields(role, []))
    doc = Document(role=role, filename=filename[:200], sha256=sha256(data).hexdigest(), status='invalid')
    if len(data) > MAX_BYTES:
        doc.issues = ['PDF exceeds 5 MiB limit']
    elif not data.startswith(b'%PDF-'):
        doc.issues = ['Not a PDF']
    else:
        try:
            reader = PdfReader(BytesIO(data), strict=False)
            if reader.is_encrypted:
                doc.status, doc.issues = 'unsupported', ['Encrypted PDFs are unsupported']
            elif not 1 <= len(reader.pages) <= MAX_PAGES:
                doc.status, doc.issues = 'unsupported', ['PDF must have 1-10 pages']
            else:
                for page in reader.pages:
                    text = page.extract_text() or ''
                    if sum(map(len, doc.pages)) + len(text) > MAX_TEXT:
                        raise ValueError('Text limit exceeded')
                    doc.pages.append(text)
                empty = [str(i) for i, text in enumerate(doc.pages, 1) if not text.strip()]
                if empty:
                    doc.status = 'partial' if len(empty) < len(doc.pages) else 'unsupported'
                    doc.issues = ['No extractable text on page(s) ' + ', '.join(empty) + '; scans require manual review; no OCR is performed']
                else:
                    doc.status = 'ready'
                if role == 'invoice':
                    indexes = re.findall(r'^Item (.+?) (?:quantity|unit price|line total):', '\n'.join(doc.pages), re.M | re.I)
                    if any(not re.fullmatch(r'[1-9]|1[0-9]|20', index) for index in indexes):
                        doc.status = 'unsupported'
                        doc.issues.append('Invoice item indexes must be integers 1-20')
                types = re.findall(r'^Document type:[ \t]*([^\r\n]*)', '\n'.join(doc.pages), re.M | re.I)
                if not types or any(t.strip().lower() != role for t in types):
                    doc.status = 'unsupported'
                    doc.issues.append(f'Expected Document type: {role.title()}; wrong or unrecognised template')
        except Exception:
            doc.status, doc.issues = 'invalid', ['PDF could not be parsed within supported limits']
            doc.pages = []
    doc.fields = extract_fields(role, doc.pages)
    return doc
