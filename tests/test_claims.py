from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter
import pytest

from app.api import app, get_store
from app.claims.checks import run_checks
from app.claims.extraction import parse_pdf, normalize_value
from app.claims.models import Correction, ReviewRequest
from app.claims.samples import render_pdf, sample_files, sample_pages
from app.claims.store import Store, RevisionConflict


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / 'reviews.sqlite3'))


@pytest.fixture
def client(store):
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def documents(name='clean'):
    files = sample_files(name)
    return [parse_pdf(role, files[role][0], files[role][1]) if role in files else parse_pdf(role, '', None)
            for role in ('policy', 'claim', 'invoice')]


def modify(role, replace=None, append=None):
    pages = sample_pages('clean')[role]
    if replace:
        pages = [[replace(line) for line in page] for page in pages]
    if append:
        pages[-1].extend(append)
    return parse_pdf(role, role + '.pdf', render_pdf(role, pages))


@pytest.mark.parametrize('name,expected', [
    ('clean', ['consistent'] * 5),
    ('conflicting', ['conflict', 'conflict', 'conflict', 'consistent', 'conflict']),
    ('missing', ['unknown'] * 5),
])
def test_end_to_end_fictional_cases(name, expected):
    docs = documents(name)
    assert [f.status for f in run_checks(docs)] == expected


def test_all_evidence_matches_exact_page_passages():
    for doc in documents():
        assert doc.status == 'ready'
        assert doc.sha256 and len(doc.sha256) == 64
        for field in doc.fields.values():
            assert field.status == 'known'
            assert field.evidence
            for e in field.evidence:
                assert doc.pages[e.page - 1][e.start:e.end] == e.passage
    invoice = documents()[2]
    assert invoice.fields['item_2_line_total'].evidence[0].page == 2
    assert invoice.fields['item_2_line_total'].evidence[0].passage == 'Item 2 line total: EUR 200.00'


@pytest.mark.parametrize('field,raw,expected', [
    ('incident_date', '29.02.2024', '2024-02-29'),
    ('claimed_amount', 'EUR 595,00', '595.00'),
    ('claimed_amount', 'EUR 0.00', '0.00'),
    ('item_1_quantity', '1.5', '1.5'),
])
def test_explicit_supported_formats(field, raw, expected):
    assert normalize_value(field, raw) == expected


@pytest.mark.parametrize('field,raw', [
    ('incident_date', '29.02.2025'), ('incident_date', '06/10/2026'),
    ('claimed_amount', 'EUR 1,234.56'), ('claimed_amount', 'USD 595.00'),
    ('claimed_amount', '595.00'), ('claimed_amount', 'EUR -1.00'),
    ('claimed_amount', 'EUR NaN'), ('item_1_quantity', '0'), ('item_count', '21'),
])
def test_unparseable_values_not_inferred(field, raw):
    with pytest.raises(ValueError):
        normalize_value(field, raw)


def test_conflicting_duplicate_values_are_unknown_with_both_passages():
    policy = modify('policy', append=['Policy ID: OTHER-ID'])
    field = policy.fields['policy_id']
    assert field.status == 'ambiguous' and field.value is None and len(field.evidence) == 2
    docs = documents()
    docs[0] = policy
    assert run_checks(docs)[0].status == 'unknown'


def test_one_invalid_duplicate_does_not_disappear():
    claim = modify('claim', append=['Incident date: pending'])
    assert claim.fields['incident_date'].status == 'unparseable'
    assert len(claim.fields['incident_date'].evidence) == 2


def test_repeated_identical_values_preserve_all_evidence():
    policy = modify('policy', append=['Policy start: 01.01.2026'])
    assert policy.fields['policy_start'].status == 'known'
    assert len(policy.fields['policy_start'].evidence) == 2


@pytest.mark.parametrize('day,status', [('2026-01-01', 'consistent'), ('2026-12-31', 'consistent'), ('2027-01-01', 'conflict')])
def test_period_boundaries_are_inclusive_not_coverage(day, status):
    docs = documents()
    docs[1] = modify('claim', replace=lambda line: line.replace('2026-06-10', day))
    finding = run_checks(docs)[1]
    assert finding.status == status
    assert 'not a coverage decision' in finding.detail


def test_invalid_policy_period_is_unknown():
    docs = documents()
    docs[0] = modify('policy', replace=lambda line: line.replace('Policy start: 2026-01-01', 'Policy start: 2027-01-01'))
    assert run_checks(docs)[1].status == 'unknown'


@pytest.mark.parametrize('replacement', [
    ('Item 1 line total: EUR 300.00', 'Item 1 line total: EUR 299.99'),
    ('Subtotal: EUR 500.00', 'Subtotal: EUR 499.00'),
    ('Invoice total: EUR 595.00', 'Invoice total: EUR 594.99'),
])
def test_arithmetic_checks_line_subtotal_and_grand_total(replacement):
    docs = documents()
    docs[2] = modify('invoice', replace=lambda line: line.replace(*replacement))
    assert run_checks(docs)[4].status == 'conflict'


def test_missing_line_or_extra_item_count_never_passes_arithmetic():
    for old, new in [('Item 2 quantity: 4', 'Item 2 quantity: unknown'), ('Item count: 2', 'Item count: 1'), ('Item count: 2', 'Item count: 3')]:
        docs = documents()
        docs[2] = modify('invoice', replace=lambda line: line.replace(old, new))
        assert run_checks(docs)[4].status == 'unknown'


def test_half_up_line_rounding():
    docs = documents()
    docs[2] = modify('invoice', replace=lambda line: line.replace('Item 1 quantity: 2', 'Item 1 quantity: 1.005')
                     .replace('Item 1 unit price: EUR 150.00', 'Item 1 unit price: EUR 1.00')
                     .replace('Item 1 line total: EUR 300.00', 'Item 1 line total: EUR 1.01')
                     .replace('Subtotal: EUR 500.00', 'Subtotal: EUR 201.01')
                     .replace('Invoice total: EUR 595.00', 'Invoice total: EUR 296.01'))
    assert run_checks(docs)[4].status == 'consistent'


def blank_pdf():
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.write(buffer)
    return buffer.getvalue()


def test_scan_without_text_is_explicitly_unsupported():
    doc = parse_pdf('invoice', 'scan.pdf', blank_pdf())
    assert doc.status == 'unsupported'
    assert any('no OCR' in issue for issue in doc.issues)
    docs = documents()
    docs[2] = doc
    assert run_checks(docs)[4].status == 'unknown'


def test_mixed_text_and_empty_pages_are_not_silently_accepted():
    data = sample_files('clean')['invoice'][1]
    writer = PdfWriter()
    writer.append(PdfReader(BytesIO(data)))
    writer.add_blank_page(width=595, height=842)
    buffer = BytesIO()
    writer.write(buffer)
    doc = parse_pdf('invoice', 'mixed.pdf', buffer.getvalue())
    assert doc.status == 'partial'
    docs = documents()
    docs[2] = doc
    assert run_checks(docs)[4].status == 'unknown'


def test_invalid_encrypted_wrong_role_and_too_many_pages():
    assert parse_pdf('policy', 'broken.pdf', b'%PDF-broken').status == 'invalid'
    assert parse_pdf('policy', 'fake.pdf', b'not pdf').status == 'invalid'
    assert parse_pdf('policy', 'wrong-role.pdf', sample_files('clean')['claim'][1]).status == 'unsupported'
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.encrypt('secret')
    buffer = BytesIO()
    writer.write(buffer)
    assert parse_pdf('policy', 'locked.pdf', buffer.getvalue()).status == 'unsupported'
    writer = PdfWriter()
    for _ in range(11):
        writer.add_blank_page(width=595, height=842)
    buffer = BytesIO()
    writer.write(buffer)
    assert parse_pdf('policy', 'long.pdf', buffer.getvalue()).status == 'unsupported'


def test_saved_corrections_preserve_original_and_survive_restart(store):
    case = store.create('Fictional conflict', sample_files('conflicting'), True)
    correction = Correction(role='claim', field='claimed_amount', value='EUR 595.00', reason='Reviewer transcription correction')
    request = ReviewRequest(expected_revision=0, reviewer='Test Reviewer', status='needs_information', notes='Policy ID still needs review.', corrections=[correction])
    updated = store.save_review(case.id, request)
    assert updated.revision == 1
    assert updated.documents[1].fields['claimed_amount'].value == '650.00'
    assert updated.findings[2].status == 'consistent' and updated.findings[2].uses_reviewer_input
    restarted = Store(store.path)
    assert restarted.get(case.id) == updated
    assert restarted.history(case.id)[0].notes == request.notes
    assert restarted.document_bytes(case.id, 'claim') == sample_files('conflicting')['claim'][1]
    # Removing the override restores the source value; both history records remain.
    restored = restarted.save_review(case.id, ReviewRequest(expected_revision=1, reviewer='Second Reviewer'))
    assert restored.findings[2].status == 'conflict'
    assert len(restarted.history(case.id)) == 2


def test_stale_save_rejected_without_losing_history(store):
    case = store.create('Clean', sample_files('clean'))
    request = ReviewRequest(expected_revision=0, reviewer='Reviewer')
    store.save_review(case.id, request)
    with pytest.raises(RevisionConflict):
        store.save_review(case.id, request)
    assert len(store.history(case.id)) == 1


def test_null_correction_marks_unknown_and_bad_edits_do_not_save(store):
    case = store.create('Clean', sample_files('clean'))
    correction = Correction(role='claim', field='incident_date', value=None, reason='Date needs verification')
    updated = store.save_review(case.id, ReviewRequest(expected_revision=0, reviewer='Reviewer', corrections=[correction]))
    assert updated.findings[1].status == 'unknown'
    for changes in [[correction, correction], [Correction(role='claim', field='invented', value='anything', reason='Reason')],
                    [Correction(role='claim', field='claimed_amount', value='EUR NaN', reason='Reason')]]:
        with pytest.raises(ValueError):
            store.save_review(case.id, ReviewRequest(expected_revision=1, reviewer='Reviewer', corrections=changes))
    assert store.get(case.id).revision == 1


def test_missing_document_cannot_be_fabricated_by_correction(store):
    case = store.create('Missing', sample_files('missing'))
    with pytest.raises(ValueError):
        store.save_review(case.id, ReviewRequest(expected_revision=0, reviewer='Reviewer', corrections=[
            Correction(role='invoice', field='invoice_total', value='EUR 595.00', reason='Unsupported assertion')]))


def test_api_upload_download_review_and_history(client):
    files = {role: (filename, data, 'application/pdf') for role, (filename, data) in sample_files('clean').items()}
    response = client.post('/v1/claims/cases', files=files, data={'title': 'Uploaded fictional case'})
    assert response.status_code == 201
    case = response.json()
    assert not case['fictional']  # Uploads are never silently claimed fictional.
    case_id = case['id']
    assert len(case['findings']) == 5
    assert client.get(f'/v1/claims/cases/{case_id}/documents/invoice').content == files['invoice'][1]
    payload = {'expected_revision': 0, 'reviewer': 'Reviewer', 'notes': 'Checked original PDFs.', 'status': 'review_recorded', 'corrections': []}
    assert client.post(f'/v1/claims/cases/{case_id}/reviews', json=payload).status_code == 200
    assert client.post(f'/v1/claims/cases/{case_id}/reviews', json=payload).status_code == 409
    assert len(client.get(f'/v1/claims/cases/{case_id}/history').json()) == 1
    assert client.get('/v1/claims/cases').json()[0]['revision'] == 1
    payload['status'] = 'approved'
    assert client.post(f'/v1/claims/cases/{case_id}/reviews', json=payload).status_code == 422


def test_api_missing_unsupported_limits_and_not_found(client):
    assert client.post('/v1/claims/cases').status_code == 422
    assert client.get('/v1/claims/cases/not-found').status_code == 404
    assert client.post('/v1/claims/samples/not-found').status_code == 404
    response = client.post('/v1/claims/cases', files={'claim': ('bad.pdf', b'%PDF-broken', 'application/pdf')})
    assert response.status_code == 201
    assert all(f['status'] == 'unknown' for f in response.json()['findings'])
    assert client.post('/v1/claims/cases', files={'claim': ('large.pdf', b'0' * (5 * 1024 * 1024 + 1), 'application/pdf')}).status_code == 413
    case = client.post('/v1/claims/samples/missing').json()
    assert case['fictional']
    assert client.get(f"/v1/claims/cases/{case['id']}/documents/invoice").status_code == 404


def test_streamlit_load_correct_save_and_reopen(client, monkeypatch):
    from urllib.parse import urlsplit
    import requests
    from streamlit.testing.v1 import AppTest

    def request(method, url, **kwargs):
        kwargs.pop('timeout', None)
        response = client.request(method, urlsplit(url).path, **kwargs)
        response.ok = response.is_success
        return response
    monkeypatch.setattr(requests, 'request', request)
    monkeypatch.setattr(requests, 'get', lambda url, **kwargs: request('GET', url, **kwargs))
    ui = AppTest.from_file(Path(__file__).resolve().parents[1] / 'streamlit_app.py', default_timeout=20).run()
    assert not ui.exception
    ui.selectbox[0].select('conflicting')
    next(b for b in ui.button if b.label == 'Load sample case').click().run()
    assert not ui.exception
    assert any(m.label == 'Discrepancies' and m.value == '4' for m in ui.metric)
    case_id = ui.session_state['case_id']
    case = client.get('/v1/claims/cases/' + case_id).json()
    fields = [(d['role'], key) for d in case['documents'] for key in d['fields']]
    index = fields.index(('claim', 'claimed_amount'))
    ui.session_state['corrections_' + case_id + '_0'] = {
        'edited_rows': {index: {'Override': True, 'Reviewer value': 'EUR 595.00', 'Reason': 'Checked source manually'}},
        'added_rows': [], 'deleted_rows': []}
    next(w for w in ui.text_input if w.label == 'Reviewer name').set_value('UI Test Reviewer')
    next(w for w in ui.text_area if w.label == 'Reviewer notes').set_value('Policy conflict remains open.')
    next(b for b in ui.button if b.label == 'Save review and rerun checks').click().run()
    assert not ui.exception
    saved = client.get('/v1/claims/cases/' + case_id).json()
    assert saved['revision'] == 1
    assert saved['findings'][2]['status'] == 'consistent'
    assert saved['documents'][1]['fields']['claimed_amount']['value'] == '650.00'
    next(b for b in ui.button if b.label == 'Open saved case').click().run()
    assert not ui.exception
    assert next(w for w in ui.text_area if w.label == 'Reviewer notes').value == 'Policy conflict remains open.'
    assert any('Revision 1' in e.label for e in ui.expander)


def test_unsupported_extra_invoice_items_do_not_disappear():
    for index in ('0', '21', 'A'):
        invoice = modify('invoice', append=[f'Item {index} quantity: 1'])
        assert invoice.status == 'unsupported'
        docs = documents()
        docs[2] = invoice
        assert run_checks(docs)[4].status == 'unknown'


def test_simultaneous_review_saves_have_one_winner(store):
    from concurrent.futures import ThreadPoolExecutor
    case = store.create('Concurrent case', sample_files('clean'))
    request = ReviewRequest(expected_revision=0, reviewer='Reviewer')
    def save():
        try:
            store.save_review(case.id, request)
            return 'saved'
        except RevisionConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: save(), range(2))) == ['conflict', 'saved']
    assert len(store.history(case.id)) == 1


def test_image_only_pdf_reports_no_ocr():
    from PIL import Image
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    image = Image.new('RGB', (200, 200), 'white')
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawImage(ImageReader(image), 0, 0, width=200, height=200)
    pdf.save()
    doc = parse_pdf('policy', 'scan.pdf', buffer.getvalue())
    assert doc.status == 'unsupported'
    assert any('no OCR' in issue for issue in doc.issues)


def test_authored_scenario_evaluation_has_no_provider_calls():
    from scripts.evaluate import evaluate
    report = evaluate()
    assert report['passed'] == report['total'] == 3
    assert report['provider_calls'] == 0
    assert all(not row['failures'] for row in report['results'])
