import os

import requests
import streamlit as st

from app.claims.extraction import MONEY_FIELDS

st.set_page_config(page_title='Claims Review Workbench', page_icon='📋', layout='wide')
st.title('Claims Review Workbench')
st.caption('PROPERTY REPAIR  /  DOCUMENT CONSISTENCY  /  HUMAN REVIEW')
st.info('Review assistance only. The five checks do not determine coverage or approve/reject a claim. Sample cases are entirely fictional.')
API = os.getenv('API_URL', 'http://127.0.0.1:8000').rstrip('/')


def call(method, path, **kwargs):
    response = requests.request(method, API + path, timeout=60, **kwargs)
    if not response.ok:
        try:
            detail = response.json().get('detail', 'Request failed')
        except ValueError:
            detail = response.text[:200]
        raise RuntimeError(f'API {response.status_code}: {detail}')
    return response.json()


def input_value(field, value):
    if value is None:
        return ''
    if field in MONEY_FIELDS or field.endswith(('_unit_price', '_line_total')):
        return 'EUR ' + value
    return value


try:
    with st.sidebar:
        st.header('Case workspace')
        sample = st.selectbox('Fictional sample', ['clean', 'conflicting', 'missing'])
        if st.button('Load sample case', type='primary'):
            loaded = call('POST', '/v1/claims/samples/' + sample)
            st.session_state['case_id'] = loaded['id']
            st.rerun()
        cases = call('GET', '/v1/claims/cases')
        if cases:
            labels = {c['id']: f"{c['title']} · {c['id'][:8]} · revision {c['revision']}" for c in cases}
            selected = st.selectbox('Saved cases', list(labels), format_func=labels.get)
            if st.button('Open saved case'):
                st.session_state['case_id'] = selected
                st.rerun()
        st.caption('Local SQLite storage. No LLM or OCR. Use fictional/de-identified data for this unauthenticated demo.')

    review_tab, upload_tab, history_tab = st.tabs(['Review case', 'Upload PDFs', 'Review history'])
    with upload_tab:
        st.subheader('Start a property-repair review')
        st.write('One labelled text PDF per role. Missing documents may be left blank; the checks will report unknown.')
        st.caption('Up to 5 MiB and 10 pages per file. Use the sample layouts: explicit Document type and field labels. Scans, encrypted PDFs and unsupported layouts require manual review.')
        with st.form('upload'):
            title = st.text_input('Case title', value='Property-repair document review')
            uploads = {role: st.file_uploader(role.title() + ' PDF', type=['pdf'], key='upload_' + role)
                       for role in ('policy', 'claim', 'invoice')}
            submitted = st.form_submit_button('Create case from PDFs')
        if submitted:
            files = {role: (file.name, file.getvalue(), 'application/pdf') for role, file in uploads.items() if file is not None}
            if not files:
                st.warning('Choose at least one PDF.')
            else:
                loaded = call('POST', '/v1/claims/cases', files=files, data={'title': title})
                st.session_state['case_id'] = loaded['id']
                st.rerun()

    case_id = st.session_state.get('case_id')
    if not case_id:
        with review_tab:
            st.subheader('Start with a fictional case')
            st.write('Load the clean sample to trace a value to its page, then try conflicting documents and missing information. Or upload your own supported text PDFs.')
        with history_tab:
            st.write('Select a case to see its saved review history.')
    else:
        case = call('GET', '/v1/claims/cases/' + case_id)
        with review_tab:
            st.subheader(case['title'])
            st.caption(f"Case {case_id} · revision {case['revision']} · {'FICTIONAL SAMPLE' if case['fictional'] else 'USER UPLOAD - not verified as fictional'}")
            counts = {status: sum(f['status'] == status for f in case['findings']) for status in ('conflict', 'unknown', 'consistent')}
            cols = st.columns(3)
            for col, (key, label) in zip(cols, [('conflict', 'Discrepancies'), ('unknown', 'Unknown / review needed'), ('consistent', 'No discrepancy found')]):
                col.metric(label, counts[key])
            st.caption('No discrepancy found means these inputs agree. It is not a statement that the claim is valid.')
            left, right = st.columns([1, 1])
            with left:
                st.subheader('Five checks')
                for finding in case['findings']:
                    label = {'consistent': 'NO DISCREPANCY', 'conflict': 'DISCREPANCY', 'unknown': 'UNKNOWN'}[finding['status']]
                    with st.expander(f"{label} · {finding['title']}", expanded=finding['status'] != 'consistent'):
                        st.write(finding['detail'])
                        st.caption('Inputs: ' + ', '.join(finding['inputs']))
                        if finding['uses_reviewer_input']:
                            st.warning('Uses reviewer corrections; these are not verified against the PDF.')
            with right:
                st.subheader('Documents & exact passages')
                for document in case['documents']:
                    with st.expander(f"{document['role'].title()} · {document['status']}"):
                        for issue in document['issues']:
                            st.warning(issue)
                        if document['sha256']:
                            st.caption(document['filename'] + ' | SHA-256: ' + document['sha256'])
                            response = requests.get(API + f"/v1/claims/cases/{case_id}/documents/{document['role']}", timeout=60)
                            response.raise_for_status()
                            st.download_button('Download original ' + document['role'], response.content,
                                               file_name=document['role'] + '.pdf', mime='application/pdf', key='download_' + document['role'])
                        for field, value in document['fields'].items():
                            st.write(f"**{field}**: {value['value'] if value['value'] is not None else 'Unknown'} ({value['status']})")
                            for evidence in value['evidence']:
                                st.caption(f"Page {evidence['page']} · extracted-text offsets {evidence['start']}–{evidence['end']}")
                                st.code(evidence['passage'], language=None)
                        if document['pages']:
                            page = st.selectbox('Extracted page text', range(1, len(document['pages']) + 1), key='page_' + document['role'])
                            st.text(document['pages'][page - 1])

            st.subheader('Reviewer corrections & notes')
            st.caption('Original values and passages never change. Enable Override to supply a correction or leave its value blank to mark unknown. Disable Override to restore the extracted value. A reason is required per override. Dates: YYYY-MM-DD or DD.MM.YYYY. Money: EUR 1234.56 (no thousands separator).')
            previous = case['review'] or {}
            corrections = {(c['role'], c['field']): c for c in previous.get('corrections', [])}
            rows = []
            for document in case['documents']:
                if document['status'] != 'ready':
                    continue
                for field, extracted in document['fields'].items():
                    prior = corrections.get((document['role'], field))
                    rows.append({'Document': document['role'], 'Field': field,
                                 'Original': input_value(field, extracted['value']), 'Parse status': extracted['status'],
                                 'Override': prior is not None,
                                 'Reviewer value': prior['value'] or '' if prior else input_value(field, extracted['value']),
                                 'Reason': prior['reason'] if prior else ''})
            with st.form('review_' + case_id + '_' + str(case['revision'])):
                edited = st.data_editor(rows, hide_index=True, use_container_width=True,
                    disabled=['Document', 'Field', 'Original', 'Parse status'],
                    column_config={'Override': st.column_config.CheckboxColumn('Override')},
                    key='corrections_' + case_id + '_' + str(case['revision'])) if rows else []
                reviewer = st.text_input('Reviewer name', value=previous.get('reviewer', ''))
                status_options = ['in_review', 'needs_information', 'review_recorded']
                status = st.selectbox('Review workflow status (not a claim decision)', status_options,
                                     index=status_options.index(previous.get('status', 'in_review')))
                notes = st.text_area('Reviewer notes', value=previous.get('notes', ''), height=100)
                save = st.form_submit_button('Save review and rerun checks', type='primary')
            if save:
                changes = [{'role': row['Document'], 'field': row['Field'], 'value': (row.get('Reviewer value') or '').strip() or None,
                            'reason': row.get('Reason') or ''} for row in edited if row['Override']]
                call('POST', f'/v1/claims/cases/{case_id}/reviews', json={
                    'expected_revision': case['revision'], 'reviewer': reviewer, 'notes': notes,
                    'status': status, 'corrections': changes})
                st.session_state['saved_notice'] = 'Review saved. Findings recalculated; original evidence preserved.'
                st.rerun()
            if st.session_state.get('saved_notice'):
                st.success(st.session_state.pop('saved_notice'))
        with history_tab:
            st.subheader('Saved review history')
            history = call('GET', f'/v1/claims/cases/{case_id}/history')
            if not history:
                st.write('No reviewer records yet. Original extraction is revision 0.')
            for item in history:
                with st.expander(f"Revision {item['revision']} · {item['reviewer']} · {item['status']} · {item['created_at']}"):
                    st.write(item['notes'] or 'No notes')
                    st.json({'corrections': item['corrections'], 'findings': item['findings']})
            st.download_button('Download review history JSON', data=__import__('json').dumps(history, indent=2),
                               file_name=f'review-{case_id}.json', mime='application/json')
except (requests.RequestException, RuntimeError) as exc:
    st.error(str(exc))
    st.caption('Start the API with python -m uvicorn app.api:app --host 127.0.0.1 --port 8000. For a stale revision, reload the case before saving again.')
