from functools import lru_cache
import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.claims.extraction import MAX_BYTES
from app.claims.models import CaseView, ReviewRequest, ReviewSnapshot, Role
from app.claims.samples import SAMPLE_NAMES, sample_files
from app.claims.store import RevisionConflict, Store

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title='Insurance Claims Review Workbench', version='0.1.0',
              description='Local document consistency review. No automated claim or coverage decisions.')


@lru_cache
def get_store() -> Store:
    return Store(os.getenv('CLAIMS_DB_PATH', str(ROOT / 'local-data' / 'reviews.sqlite3')))


@app.get('/health')
def health():
    return {'status': 'healthy', 'mode': 'deterministic-text-pdf', 'version': '0.1.0'}


@app.get('/v1/claims/samples')
def samples():
    return [{'id': key, 'title': value, 'fictional': True} for key, value in SAMPLE_NAMES.items()]


@app.post('/v1/claims/samples/{name}', response_model=CaseView, status_code=201)
def create_sample(name: str, store: Annotated[Store, Depends(get_store)]):
    if name not in SAMPLE_NAMES:
        raise HTTPException(404, 'Unknown sample')
    return store.create('FICTIONAL - ' + SAMPLE_NAMES[name], sample_files(name), fictional=True)


@app.get('/v1/claims/cases')
def cases(store: Annotated[Store, Depends(get_store)]):
    return store.list_cases()


@app.post('/v1/claims/cases', response_model=CaseView, status_code=201)
async def upload_case(
    store: Annotated[Store, Depends(get_store)],
    title: Annotated[str, Form(min_length=1, max_length=150)] = 'Uploaded property-repair case',
    policy: Annotated[UploadFile | None, File()] = None,
    claim: Annotated[UploadFile | None, File()] = None,
    invoice: Annotated[UploadFile | None, File()] = None,
):
    files = {}
    for role, upload in (('policy', policy), ('claim', claim), ('invoice', invoice)):
        if upload is not None:
            try:
                data = await upload.read(MAX_BYTES + 1)
            finally:
                await upload.close()
            if len(data) > MAX_BYTES:
                raise HTTPException(413, f'{role} exceeds 5 MiB')
            # Original name is metadata, never used as a storage path.
            files[role] = ((upload.filename or role + '.pdf').replace('\\', '/').split('/')[-1], data)
    if not files:
        raise HTTPException(422, 'Upload at least one document; absent roles will be review-needed')
    if not title.strip():
        raise HTTPException(422, 'Case title is required')
    return store.create(title.strip(), files)


@app.get('/v1/claims/cases/{case_id}', response_model=CaseView)
def get_case(case_id: str, store: Annotated[Store, Depends(get_store)]):
    try:
        return store.get(case_id)
    except KeyError:
        raise HTTPException(404, 'Case not found') from None


@app.get('/v1/claims/cases/{case_id}/history', response_model=list[ReviewSnapshot])
def history(case_id: str, store: Annotated[Store, Depends(get_store)]):
    try:
        return store.history(case_id)
    except KeyError:
        raise HTTPException(404, 'Case not found') from None


@app.post('/v1/claims/cases/{case_id}/reviews', response_model=CaseView)
def save_review(case_id: str, request: ReviewRequest, store: Annotated[Store, Depends(get_store)]):
    try:
        return store.save_review(case_id, request)
    except KeyError:
        raise HTTPException(404, 'Case not found') from None
    except RevisionConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@app.get('/v1/claims/cases/{case_id}/documents/{role}')
def download(case_id: str, role: Role, store: Annotated[Store, Depends(get_store)]):
    try:
        data = store.document_bytes(case_id, role)
    except KeyError:
        raise HTTPException(404, 'Document not supplied') from None
    return Response(data, media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{role}.pdf"'})
