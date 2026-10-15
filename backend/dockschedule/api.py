import csv
import hashlib
import io
import json
import secrets
import shutil
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from .config import config
from .db import Session, get_db
from .models import ACTIVE, FINISHED, Audit, Compound, LoginSession, Receptor, Settings, Task, Upload, User, now, uid
from .schemas import Docking, LibraryOptions, Login, PasswordChange, Prepare, Register, ResourceSettings, UserUpdate
from .security import admin, approved, bootstrap, create_session, current_user, digest, owned, password_hash, verify
from . import library, storage
from .structure import inspect_pdb


@asynccontextmanager
async def lifespan(app):
    bootstrap()
    yield


app = FastAPI(title='DOCKSCHEDULE', lifespan=lifespan)


@app.middleware('http')
async def csrf(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if request.headers.get('x-ds-request') != '1' or (origin and urlparse(origin).netloc != request.headers.get('host')):
            return JSONResponse({'detail': '요청 출처를 확인할 수 없습니다.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)


def user_json(u):
    return dict(id=u.id, username=u.username, name=u.name, student_number=u.student_number,
                role=u.role, status=u.status, cpu_override=u.cpu_override)


def task_json(t, db=None, owner_name=None):
    data = {k: getattr(t, k) for k in ('id', 'owner_id', 'receptor_id', 'kind', 'name', 'status', 'parameters', 'cpu_ids',
                                      'total', 'completed', 'failed', 'cancel_requested', 'error', 'created_at', 'started_at', 'finished_at')}
    if db:
        data['owner_name'] = db.get(User, t.owner_id).name
    elif owner_name is not None:
        data['owner_name'] = owner_name
    return data


def settings(db):
    return db.get(Settings, 1).values


def audit(db, u, action, target='', detail=None):
    db.add(Audit(actor_id=u.id, action=action, target=str(target), detail=detail or {}))


def require_capacity(db, u):
    # Serialize quota checks for concurrent submissions by the same student.
    # PostgreSQL NO KEY UPDATE serializes submissions without blocking audit FKs.
    db.execute(select(User.id).where(User.id == u.id).with_for_update(key_share=True))
    s = settings(db)
    n = db.scalar(select(func.count()).select_from(Task).where(Task.owner_id == u.id, Task.status.in_(['queued', *ACTIVE])))
    if n >= s['max_pending_per_user']:
        raise HTTPException(409, '학생별 대기 및 실행 작업 수 한도에 도달했습니다.')
    storage.check_capacity(s, u.id, db=db)


@app.get('/api/health')
def health(db=Depends(get_db)):
    s = db.get(Settings, 1)
    return dict(status='ok', scheduler_heartbeat=s.heartbeat if s else None,
                scheduler_error=s.scheduler_error if s else None)


_attempts = defaultdict(deque)


def limit_login(key, limit=15):
    now_time = time.monotonic()
    # Bounded in-process limiter; deployment runs one API process.
    if len(_attempts) > 10000:
        for k in list(_attempts):
            if not _attempts[k] or _attempts[k][-1] < now_time-60:
                del _attempts[k]
    q = _attempts[key]
    while q and q[0] < now_time-60:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, '잠시 후 다시 시도하세요.')
    q.append(now_time)


@app.post('/api/auth/register', status_code=201)
def register(body: Register, request: Request, db=Depends(get_db)):
    limit_login('register:' + request.client.host, limit=60)
    if body.username.lower() == 'admin':
        raise HTTPException(409, '사용할 수 없는 ID입니다.')
    u = User(username=body.username, name=body.name, student_number=body.student_number, password_hash=password_hash(body.password))
    db.add(u)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, '이미 사용 중인 ID입니다.')
    return user_json(u)


@app.post('/api/auth/login')
def login(body: Login, request: Request, response: Response, db=Depends(get_db)):
    limit_login(request.client.host + ':' + body.username)
    u = db.scalar(select(User).where(User.username == body.username))
    if u is None or not verify(body.password, u.password_hash):
        raise HTTPException(401, 'ID 또는 비밀번호가 올바르지 않습니다.')
    if u.status in ('rejected', 'suspended'):
        raise HTTPException(403, '승인 거절 또는 정지된 계정입니다.')
    token = create_session(db, u)
    db.commit()
    response.set_cookie('ds_session', token, httponly=True, samesite='strict', secure=config().cookie_secure,
                        max_age=config().session_hours*3600, path='/')
    return user_json(u)


@app.get('/api/auth/me')
def me(u=Depends(current_user)):
    return user_json(u)


@app.post('/api/auth/logout')
def logout(request: Request, response: Response, db=Depends(get_db)):
    db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(request.cookies.get('ds_session', ''))))
    db.commit()
    response.delete_cookie('ds_session', path='/')
    return {'ok': True}


@app.post('/api/auth/password')
def change_password(body: PasswordChange, u=Depends(current_user), db=Depends(get_db)):
    u = db.get(User, u.id)
    if not verify(body.old_password, u.password_hash):
        raise HTTPException(400, '현재 비밀번호가 올바르지 않습니다.')
    u.password_hash = password_hash(body.new_password)
    db.execute(delete(LoginSession).where(LoginSession.user_id == u.id))
    db.commit()
    return {'ok': True}


@app.get('/api/admin/users')
def users(u=Depends(admin), db=Depends(get_db)):
    return [user_json(x) for x in db.scalars(select(User).order_by(User.created_at.desc()))]


@app.patch('/api/admin/users/{user_id}')
def edit_user(user_id: int, body: UserUpdate, u=Depends(admin), db=Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, '사용자를 찾을 수 없습니다.')
    if target.role == 'admin' and body.status and body.status != 'approved':
        raise HTTPException(400, '관리자 계정은 정지할 수 없습니다.')
    if body.cpu_override and body.cpu_override > settings(db)['cpu_budget']:
        raise ValueError('학생 CPU 수는 전체 CPU 한도를 넘을 수 없습니다.')
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(target, key, value)
    if target.status in ('suspended', 'rejected'):
        db.execute(delete(LoginSession).where(LoginSession.user_id == target.id))
        db.execute(update(Task).where(Task.owner_id == target.id, Task.status.in_(['queued', *ACTIVE])).values(cancel_requested=True))
    audit(db, u, 'update_user', target.id, body.model_dump(exclude_unset=True))
    db.commit()
    return user_json(target)


@app.post('/api/admin/users/{user_id}/reset-password')
def reset_password(user_id: int, u=Depends(admin), db=Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404)
    temporary = secrets.token_urlsafe(12)
    target.password_hash = password_hash(temporary)
    db.execute(delete(LoginSession).where(LoginSession.user_id == target.id))
    audit(db, u, 'reset_password', target.id)
    db.commit()
    return {'temporary_password': temporary}


@app.get('/api/settings')
def get_settings(u=Depends(approved), db=Depends(get_db)):
    s = db.get(Settings, 1)
    active = list(db.scalars(select(Task).where(Task.status.in_(ACTIVE))))
    return dict(values=s.values, available_cpu_count=len(s.available_cpus), heartbeat=s.heartbeat,
                scheduler_error=s.scheduler_error, allocated_cpus=sum(len(t.cpu_ids) for t in active),
                active_students=len(active), queued=db.scalar(select(func.count()).select_from(Task).where(Task.status == 'queued')))


@app.put('/api/admin/settings')
def put_settings(body: ResourceSettings, u=Depends(admin), db=Depends(get_db)):
    s = db.get(Settings, 1)
    if body.default_cpus > body.cpu_budget or (s.available_cpus and body.cpu_budget > len(s.available_cpus)):
        raise ValueError('CPU 설정이 서버 또는 전체 한도를 초과합니다.')
    oversized = db.scalar(select(User).where(User.cpu_override > body.cpu_budget).limit(1))
    if oversized:
        raise ValueError(f'{oversized.name}님의 CPU 개별 설정을 먼저 전체 한도 이하로 줄이세요.')
    s.values = body.model_dump()
    audit(db, u, 'settings', detail=s.values)
    db.commit()
    return get_settings(u, db)


@app.post('/api/uploads', status_code=201)
def upload(kind: str = Query(pattern='^(pdb|library)$'), file: UploadFile = File(), u=Depends(approved), db=Depends(get_db)):
    identifier = uid()
    folder = storage.root()/str(u.id)/'uploads'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/identifier
    size, h = 0, hashlib.sha256()
    storage.check_capacity(settings(db), u.id, db=db)
    try:
        with path.open('wb') as f:
            while chunk := file.file.read(1024*1024):
                size += len(chunk)
                if size > config().max_upload_mb*1024**2:
                    raise HTTPException(413, '업로드 파일 크기 한도를 초과했습니다.')
                h.update(chunk)
                f.write(chunk)
        structure = inspect_pdb(path.read_text()) if kind == 'pdb' else None
        # Serialize final upload accounting so simultaneous uploads see committed sizes.
        limits = db.scalar(select(Settings).where(Settings.id == 1).with_for_update())
        storage.check_capacity(limits.values, u.id, size, db=db)
        record = Upload(id=identifier, owner_id=u.id, kind=kind, filename=(file.filename or 'file')[:250], path=str(path), size=size, sha256=h.hexdigest())
        db.add(record)
        db.commit()
        return dict(id=identifier, filename=record.filename, size=size, structure=structure)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@app.get('/api/uploads/{upload_id}/structure')
def input_structure(upload_id: str, model: int | None = None, u=Depends(approved), db=Depends(get_db)):
    item = owned(db.get(Upload, upload_id), u)
    if item.kind != 'pdb':
        raise ValueError('PDB 파일이 아닙니다.')
    return inspect_pdb(Path(item.path).read_text(), model)


@app.post('/api/uploads/{upload_id}/preview')
def preview(upload_id: str, body: LibraryOptions, u=Depends(approved), db=Depends(get_db)):
    item = owned(db.get(Upload, upload_id), u)
    if item.kind != 'library':
        raise ValueError('Library 파일이 아닙니다.')
    try:
        return library.preview(Path(item.path), body.delimiter, body.encoding, body.header)
    except (UnicodeError, csv.Error) as e:
        raise ValueError('인코딩 또는 구분자를 확인하세요: ' + str(e))


@app.post('/api/receptors', status_code=201)
def prepare(body: Prepare, u=Depends(approved), db=Depends(get_db)):
    require_capacity(db, u)
    file = owned(db.get(Upload, body.upload_id), u)
    if file.kind != 'pdb':
        raise ValueError('PDB 파일을 선택하세요.')
    info = inspect_pdb(Path(file.path).read_text(), body.model)
    if not body.chains or not set(body.chains) <= set(info['chains']):
        raise ValueError('올바른 단백질 chain을 선택하세요.')
    allowed = {r['key'] for r in info['residues'] if r['category'] != 'protein' and r['chain'] in body.chains}
    if not set(body.keep_heterogens) <= allowed:
        raise ValueError('유지할 구성 성분을 확인하세요.')
    receptor = Receptor(owner_id=u.id, upload_id=file.id, name=body.name, options=body.model_dump())
    db.add(receptor)
    db.flush()
    task = Task(owner_id=u.id, receptor_id=receptor.id, kind='prepare', name=body.name, parameters=body.model_dump())
    db.add(task)
    db.commit()
    return {'receptor_id': receptor.id, 'task_id': task.id}


@app.get('/api/receptors')
def receptors(u=Depends(approved), db=Depends(get_db)):
    query = select(Receptor).order_by(Receptor.created_at.desc())
    if u.role != 'admin':
        query = query.where(Receptor.owner_id == u.id)
    return [dict(id=r.id, name=r.name, status=r.status, owner_id=r.owner_id) for r in db.scalars(query)]


@app.get('/api/receptors/{receptor_id}')
def receptor(receptor_id: str, u=Depends(approved), db=Depends(get_db)):
    r = owned(db.get(Receptor, receptor_id), u)
    return dict(id=r.id, name=r.name, status=r.status, options=r.options, structure=r.structure, report=r.report)


@app.get('/api/receptors/{receptor_id}/file/{format}')
def receptor_file(receptor_id: str, format: str, u=Depends(approved), db=Depends(get_db)):
    r = owned(db.get(Receptor, receptor_id), u)
    if format == 'original':
        path = Path(db.get(Upload, r.upload_id).path)
    elif format in ('pdb', 'pdbqt', 'json') and r.status == 'ready':
        path = storage.receptor_dir(r.owner_id, r.id)/('preparation.json' if format == 'json' else 'receptor.'+format)
    else:
        raise HTTPException(404)
    return FileResponse(storage.inside(path), filename=f'receptor.{format if format != "original" else "pdb"}')


@app.post('/api/jobs', status_code=201)
def submit(body: Docking, u=Depends(approved), db=Depends(get_db)):
    require_capacity(db, u)
    r = owned(db.get(Receptor, body.receptor_id), u)
    f = owned(db.get(Upload, body.library_id), u)
    if r.status != 'ready' or f.kind != 'library':
        raise ValueError('전처리 완료된 단백질과 library 파일을 선택하세요.')
    s = settings(db)
    if body.conformers > s['max_conformers'] or body.exhaustiveness > s['max_exhaustiveness']:
        raise ValueError('관리자가 지정한 계산 옵션 한도를 초과했습니다.')
    if not set(body.selected_residues) <= {x['key'] for x in r.structure['residues']}:
        raise ValueError('선택한 잔기가 전처리 구조에 없습니다.')
    params = body.model_dump()
    params.update(timeout=s['compound_timeout'], max_retries=s['max_retries'], library_sha256=f.sha256)
    task = Task(owner_id=u.id, receptor_id=r.id, library_id=f.id, kind='screen', name=body.name, parameters=params)
    db.add(task)
    db.flush()
    batch, count, failed = [], 0, 0
    try:
        for row in library.compounds(Path(f.path), body.library.model_dump(), s['max_compounds']):
            count += 1
            failed += row['status'] == 'failed'
            batch.append(dict(task_id=task.id, **row))
            if len(batch) >= 1000:
                db.execute(insert(Compound), batch)
                batch.clear()
        if batch:
            db.execute(insert(Compound), batch)
    except (UnicodeError, csv.Error) as e:
        raise ValueError('Library 형식을 확인하세요: ' + str(e))
    task.total, task.failed = count, failed
    audit(db, u, 'submit', task.id)
    db.commit()
    return task_json(task)


@app.get('/api/jobs/summary')
def job_summary(u=Depends(approved), db=Depends(get_db)):
    q = select(Task.status, func.count()).group_by(Task.status)
    if u.role != 'admin':
        q = q.where(Task.owner_id == u.id)
    counts = dict(db.execute(q).all())
    return dict(total=sum(counts.values()), running=sum(counts.get(k, 0) for k in ACTIVE),
                done=sum(counts.get(k, 0) for k in ('completed', 'partial')), counts=counts)


@app.get('/api/jobs')
def jobs(limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0),
         search: str = '', state: str = 'all', include_total: bool = False,
         u=Depends(approved), db=Depends(get_db)):
    q = select(Task)
    if u.role != 'admin':
        q = q.where(Task.owner_id == u.id)
    if search:
        q = q.where(Task.name.ilike('%'+search.replace('!', '!!').replace('%', '!%').replace('_', '!_')+'%', escape='!'))
    if state == 'running':
        q = q.where(Task.status.in_(['queued', *ACTIVE]))
    elif state == 'done':
        q = q.where(Task.status.in_(FINISHED))
    total = db.scalar(select(func.count()).select_from(q.subquery())) if include_total else None
    page = q.add_columns(User.name).join(User, User.id == Task.owner_id)
    rows = [task_json(t, owner_name=name) for t, name in db.execute(page.order_by(Task.created_at.desc(), Task.id).offset(offset).limit(limit))]
    return dict(rows=rows, total=total, limit=limit, offset=offset) if include_total else rows


@app.get('/api/jobs/{task_id}')
def job(task_id: str, u=Depends(approved), db=Depends(get_db)):
    return task_json(owned(db.get(Task, task_id), u), db)


@app.post('/api/jobs/{task_id}/cancel')
def cancel(task_id: str, u=Depends(approved), db=Depends(get_db)):
    t = owned(db.get(Task, task_id), u)
    if t.status not in FINISHED:
        t.cancel_requested = True
        audit(db, u, 'cancel', t.id)
        db.commit()
    return task_json(t)


@app.post('/api/jobs/{task_id}/retry')
def retry(task_id: str, u=Depends(approved), db=Depends(get_db)):
    owned(db.get(Task, task_id), u)
    # Match account suspension's lock order: user first, then task.
    require_capacity(db, u)
    t = owned(db.get(Task, task_id, with_for_update=True, populate_existing=True), u)
    if t.status not in ('partial', 'failed', 'cancelled') or t.cpu_ids or t.worker_pid is not None:
        raise HTTPException(409, '실행 종료와 자원 반환 후 재시도할 수 있습니다.')
    t.status, t.cancel_requested, t.error, t.finished_at = 'queued', False, None, None
    t.run_id = None
    if t.kind == 'screen':
        db.execute(update(Compound).where(Compound.task_id == t.id, Compound.status.in_(['failed', 'running', 'partial']),
                                          Compound.cid != '', Compound.smiles != '').values(
            status='pending', attempts=0, error=None, affinity=None, normalized_smiles=None, details={}, elapsed=None))
        t.failed = db.scalar(select(func.count()).select_from(Compound).where(Compound.task_id == t.id, Compound.status == 'failed'))
        t.completed = db.scalar(select(func.count()).select_from(Compound).where(Compound.task_id == t.id, Compound.status == 'succeeded'))
    else:
        db.get(Receptor, t.receptor_id).status = 'queued'
    audit(db, u, 'retry', t.id)
    db.commit()
    return task_json(t)


def compound_json(c):
    return {k: getattr(c, k) for k in ('id', 'row_number', 'cid', 'smiles', 'normalized_smiles', 'status', 'affinity', 'error', 'elapsed', 'details')}


@app.get('/api/jobs/{task_id}/results')
def results(task_id: str, page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=200),
            search: str = '', status: str = '', sort: str = 'affinity', u=Depends(approved), db=Depends(get_db)):
    owned(db.get(Task, task_id), u)
    q = select(Compound).where(Compound.task_id == task_id)
    if search:
        q = q.where(Compound.cid.contains(search, autoescape=True))
    if status:
        q = q.where(Compound.status == status)
    count = db.scalar(select(func.count()).select_from(q.subquery()))
    q = q.order_by(Compound.affinity.asc().nulls_last(), Compound.row_number) if sort == 'affinity' else q.order_by(Compound.row_number)
    return dict(total=count, page=page, rows=[compound_json(c) for c in db.scalars(q.offset((page-1)*page_size).limit(page_size))])


@app.get('/api/jobs/{task_id}/compounds/{compound_id}/{format}')
def pose(task_id: str, compound_id: int, format: str, u=Depends(approved), db=Depends(get_db)):
    t = owned(db.get(Task, task_id), u)
    c = db.get(Compound, compound_id)
    if c is None or c.task_id != t.id or c.status not in ('succeeded', 'partial') or format not in ('sdf', 'pdbqt'):
        raise HTTPException(404)
    return FileResponse(storage.compound_dir(t.owner_id, t.id, c.id)/('best.'+format), filename=f'row-{c.row_number}.{format}')


def score_rows(task_id, separator=','):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=separator)
    exported_at = now().isoformat()+'Z'
    writer.writerow(['row_number', 'CID', 'SMILES', 'normalized_SMILES', 'status', 'affinity_kcal_mol', 'error', 'elapsed_seconds', 'exported_at_utc'])
    yield '\ufeff'+buffer.getvalue()
    last = 0
    while True:
        with Session() as db:
            rows = list(db.scalars(select(Compound).where(Compound.task_id == task_id, Compound.id > last).order_by(Compound.id).limit(1000)))
        if not rows:
            break
        buffer.seek(0)
        buffer.truncate(0)
        for c in rows:
            # Prevent spreadsheet formula execution in student-supplied text.
            safe = lambda s: "'"+s if isinstance(s, str) and s.startswith(('=', '+', '-', '@', '\t', '\r')) else s
            writer.writerow([c.row_number, safe(c.cid), safe(c.smiles), safe(c.normalized_smiles), c.status, c.affinity, safe(c.error), c.elapsed, exported_at])
        yield buffer.getvalue()
        last = rows[-1].id


@app.get('/api/jobs/{task_id}/scores')
def scores(task_id: str, format: str = 'csv', u=Depends(approved), db=Depends(get_db)):
    owned(db.get(Task, task_id), u)
    if format not in ('csv', 'tsv'):
        raise ValueError('CSV 또는 TSV를 선택하세요.')
    return StreamingResponse(score_rows(task_id, '\t' if format == 'tsv' else ','), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': f'attachment; filename="scores-{task_id}.{format}"'})


@app.get('/api/jobs/{task_id}/archive')
def archive(task_id: str, u=Depends(approved), db=Depends(get_db)):
    import zipstream
    t = owned(db.get(Task, task_id), u)
    r = db.get(Receptor, t.receptor_id)
    z = zipstream.ZipStream(compress_type=zipstream.ZIP_DEFLATED)
    z.add((x.encode('utf-8') for x in score_rows(t.id)), 'scores.csv')
    z.add(json.dumps(dict(job=task_json(t), exported_at=now().isoformat(), preparation=r.report), default=str, ensure_ascii=False), 'manifest.json')
    for path in storage.receptor_dir(r.owner_id, r.id).glob('*'):
        if path.is_file():
            z.add_path(path, 'receptor/'+path.name)
    def stream():
        # Stream each artifact immediately: do not queue 40,000 file descriptors.
        yield from z.all_files()
        last = 0
        while True:
            with Session() as query_db:
                rows = list(query_db.scalars(select(Compound).where(Compound.task_id == t.id, Compound.id > last, Compound.status.in_(['succeeded', 'partial'])).order_by(Compound.id).limit(500)))
            if not rows:
                break
            for c in rows:
                for fmt in ('sdf', 'pdbqt'):
                    path = storage.compound_dir(t.owner_id, t.id, c.id)/('best.'+fmt)
                    if path.exists():
                        z.add_path(path, f'poses/row-{c.row_number}.{fmt}')
                yield from z.all_files()
            last = rows[-1].id
        yield from z.finalize()
    return StreamingResponse(stream(), media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="docking-{t.id}.zip"'})


@app.get('/api/admin/storage')
def storage_info(u=Depends(admin), db=Depends(get_db)):
    return dict(**storage.usage(), users=[dict(**user_json(x), **storage.usage(x.id)) for x in db.scalars(select(User))])


@app.delete('/api/jobs/{task_id}')
def delete_job(task_id: str, u=Depends(approved), db=Depends(get_db)):
    t = owned(db.get(Task, task_id, with_for_update=True), u)
    if t.status not in FINISHED or t.cpu_ids or t.worker_pid is not None or t.kind != 'screen':
        raise HTTPException(409, '종료된 screening 작업만 삭제할 수 있습니다.')
    shutil.rmtree(storage.task_dir(t.owner_id, t.id), ignore_errors=True)
    audit(db, u, 'delete_job', t.id)
    db.delete(t)
    db.commit()
    return {'ok': True}
