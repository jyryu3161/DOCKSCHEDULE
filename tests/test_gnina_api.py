import csv
import io
import json
import zipfile
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from dockschedule.api import require_capacity
from dockschedule.db import transaction
from dockschedule.gnina_rank import consensus_order
from dockschedule.models import Compound, CompoundAnalysis, GninaScore, InteractionHit, Receptor, Settings, Task, User
from dockschedule.security import password_hash
from test_gnina_jobs import old_job, screen, set_top

# vina, cnn_score, cnn_affinity, cnn_vs, gnina_vina per compound (row 1..4 succeeded); row 5 failed; row 6 no record.
SET = {1: (-9.0, .50, 6.0, 3.0, -8.0), 2: (-8.0, .90, 7.0, 6.3, -7.5), 3: (-8.0, .70, 7.0, 4.9, -7.0), 4: (-7.0, .95, 8.0, 7.6, -9.0)}
AFFINITIES = [-9, -8, -8, -7, -6, -5]


def seeded(status='completed', cids=None):
    sid, ids = screen([(a, 'succeeded') for a in AFFINITIES], status=status)
    job = old_job(sid)
    with transaction() as db:
        for row, (vina, cs, ca, cv, gv) in SET.items():
            db.add(GninaScore(compound_id=ids[row-1], task_id=sid, job_id=job, status='succeeded', cnn_score=cs, cnn_affinity=ca,
                              cnn_vs=cv, gnina_vina=gv, details={'gnina_version': 'gnina v1.3', 'binary_sha256': 'b'*64}))
        db.add(GninaScore(compound_id=ids[4], task_id=sid, job_id=job, status='failed', error='boom'))
    return sid, ids, job


def expected_rows(w):
    rows = [dict(id=i, row_number=i, vina=SET[i][0], cnn_affinity=SET[i][2]) for i in SET]
    return consensus_order(rows, w)


def rows(client, sid, query=''):
    r = client.get(f'/api/jobs/{sid}/results?{query}')
    assert r.status_code == 200, r.text
    return r.json()


def other_student(client):
    with transaction() as db:
        db.add(User(username='other', name='other', student_number='2', password_hash=password_hash('OtherPass123!'), status='approved'))
    r = client.post('/api/auth/login', json={'username': 'other', 'password': 'OtherPass123!'})
    assert r.status_code == 200


# --- results: sorting, ranks, filters -----------------------------------------------

@pytest.mark.parametrize('w', [0, 0.25, 0.5, 1])
def test_consensus_sort_matches_rank_helper_with_ties_and_non_members_last(admin_client, w):
    sid, ids, _ = seeded()
    data = rows(admin_client, sid, f'sort=consensus&w={w}')
    assert [r['row_number'] for r in data['rows']] == [o['row_number'] for o in expected_rows(w)] + [5, 6]
    assert data['total'] == 6
    for r, o in zip(data['rows'], expected_rows(w)):
        assert r['gnina']['rank']['consensus'] == o['rank']['consensus']
        assert r['gnina']['rank']['vina'] == o['rank']['vina'] and r['gnina']['rank']['cnn_affinity'] == o['rank']['cnn_affinity']


def test_default_weight_is_half_and_rows_two_three_tie_by_row_number(admin_client):
    sid, _, _ = seeded()
    assert [r['row_number'] for r in rows(admin_client, sid, 'sort=consensus')['rows']] == [r['row_number'] for r in rows(admin_client, sid, 'sort=consensus&w=0.5')['rows']]
    order = [r['row_number'] for r in rows(admin_client, sid, 'sort=consensus&w=0.5')['rows']]
    assert order.index(2) < order.index(3)


def test_metric_sorts_and_average_ranks(admin_client):
    sid, _, _ = seeded()
    assert [r['row_number'] for r in rows(admin_client, sid, 'sort=cnn_score')['rows']] == [4, 2, 3, 1, 5, 6]
    assert [r['row_number'] for r in rows(admin_client, sid, 'sort=cnn_vs')['rows']] == [4, 2, 3, 1, 5, 6]
    data = rows(admin_client, sid, 'sort=cnn_affinity')
    assert [r['row_number'] for r in data['rows']] == [4, 2, 3, 1, 5, 6]
    by_row = {r['row_number']: r['gnina']['rank'] for r in data['rows'] if r['gnina']}
    assert by_row[2]['cnn_affinity'] == by_row[3]['cnn_affinity'] == 2.5  # tie shares average rank
    assert by_row[2]['vina'] == by_row[3]['vina'] == 2.5
    assert by_row[4]['cnn_score'] == 1 and by_row[1]['cnn_score'] == 4


def test_non_members_ordered_by_affinity_and_paging_crosses_boundary(admin_client):
    sid, _, _ = seeded()
    seen = []
    for page in (1, 2, 3):
        seen += [r['row_number'] for r in rows(admin_client, sid, f'sort=consensus&page_size=2&page={page}')['rows']]
    assert seen == [r['row_number'] for r in rows(admin_client, sid, 'sort=consensus')['rows']]
    assert len(seen) == 6 and seen[-2:] == [5, 6]


def test_existing_sorts_keep_behavior_and_include_gnina_key(admin_client):
    sid, _, _ = seeded()
    assert [r['row_number'] for r in rows(admin_client, sid)['rows']] == [1, 2, 3, 4, 5, 6]
    assert [r['row_number'] for r in rows(admin_client, sid, 'sort=row')['rows']] == [1, 2, 3, 4, 5, 6]


def test_row_payload_shape(admin_client):
    sid, ids, _ = seeded()
    by_row = {r['row_number']: r['gnina'] for r in rows(admin_client, sid)['rows']}
    assert set(by_row[1]) == {'status', 'cnn_score', 'cnn_affinity', 'cnn_vs', 'gnina_vina', 'rank', 'error'}
    assert set(by_row[1]['rank']) == {'vina', 'cnn_affinity', 'cnn_score', 'cnn_vs', 'consensus'}
    assert by_row[1]['status'] == 'succeeded' and by_row[1]['cnn_score'] == .5 and by_row[1]['gnina_vina'] == -8.0
    assert by_row[5]['status'] == 'failed' and by_row[5]['error'] == 'boom' and by_row[5]['cnn_score'] is None
    assert set(by_row[5]['rank'].values()) == {None}
    assert by_row[6] is None


def test_filters_choose_rows_but_never_change_ranks(admin_client):
    sid, _, _ = seeded()
    full = {r['row_number']: r['gnina']['rank'] for r in rows(admin_client, sid, 'sort=consensus')['rows'] if r['gnina'] and r['gnina']['rank']['consensus']}
    only = rows(admin_client, sid, 'sort=consensus&min_cnn_score=0.7')
    assert [r['row_number'] for r in only['rows']] == [r['row_number'] for r in expected_rows(.5) if r['row_number'] in (2, 3, 4)]
    assert only['total'] == 3
    assert all(r['gnina']['rank'] == full[r['row_number']] for r in only['rows'])
    searched = rows(admin_client, sid, 'sort=consensus&search=c4')
    assert [r['row_number'] for r in searched['rows']] == [4] and searched['rows'][0]['gnina']['rank'] == full[4]
    assert rows(admin_client, sid, 'min_cnn_score=0.95')['rows'][0]['gnina']['rank'] == full[4]
    assert rows(admin_client, sid, 'min_cnn_score=0.95')['total'] == 1
    assert rows(admin_client, sid, 'sort=consensus&status=succeeded&min_cnn_score=0')['total'] == 4


@pytest.mark.parametrize('query', ['w=-0.1', 'w=1.5', 'w=nan', 'w=abc', 'min_cnn_score=1.1', 'min_cnn_score=-1'])
def test_out_of_range_parameters_are_422_with_korean_detail(admin_client, query):
    sid, _, _ = seeded()
    for path in (f'/api/jobs/{sid}/results?sort=consensus&{query}', f'/api/jobs/{sid}/scores?{query}'):
        if path.endswith('scores?'+query) and query.startswith('min'):
            continue
        r = admin_client.get(path)
        assert r.status_code == 422, path
        if 'abc' not in query:
            assert any('가' <= ch <= '힣' for ch in str(r.json()['detail']))


# --- screening summary, resume ------------------------------------------------------

def test_screening_summary_fields(admin_client):
    sid, ids, job = seeded()
    set_top(5)
    g = admin_client.get(f'/api/jobs/{sid}').json()['gnina']
    assert g == dict(active=None, status=None, scored=4, failed=1, pending=0, top_n=None, can_resume=True)
    assert g['scored'] == 4 and g['failed'] == 1 and g['pending'] == 0 and g['active'] is None and g['status'] is None
    with transaction() as db:
        t = db.get(Task, job)
        t.status, t.parameters = 'running', {'top_n': 7}
    g = admin_client.get(f'/api/jobs/{sid}').json()['gnina']
    assert g['active'] == job and g['status'] == 'running' and g['top_n'] == 7 and g['can_resume'] is False


def test_summary_can_resume_false_without_targets_or_when_not_finished(admin_client):
    sid, ids, _ = seeded()
    set_top(0)
    assert admin_client.get(f'/api/jobs/{sid}').json()['gnina']['can_resume'] is False
    set_top(1)  # top-1 is row 1 which already succeeded
    assert admin_client.get(f'/api/jobs/{sid}').json()['gnina']['can_resume'] is False
    set_top(5)
    assert admin_client.get(f'/api/jobs/{sid}').json()['gnina']['can_resume'] is True
    with transaction() as db:
        db.get(Task, sid).status = 'running'
    assert admin_client.get(f'/api/jobs/{sid}').json()['gnina']['can_resume'] is False


def test_resume_creates_task_and_audits(admin_client):
    sid, ids, _ = seeded()
    set_top(5)
    r = admin_client.post(f'/api/jobs/{sid}/gnina')
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['kind'] == 'gnina' and body['source_task_id'] == sid and body['status'] == 'queued'
    assert body['parameters'] == dict(top_n=5, auto=False)
    with transaction() as db:
        assert db.scalar(select(GninaScore.status).where(GninaScore.compound_id == ids[4])) == 'pending'
        assert db.scalar(select(GninaScore.job_id).where(GninaScore.compound_id == ids[4])) == body['id']
        assert db.scalar(select(GninaScore.status).where(GninaScore.compound_id == ids[0])) == 'succeeded'
    g = admin_client.get(f'/api/jobs/{sid}').json()['gnina']
    assert g['active'] == body['id'] and g['can_resume'] is False and g['top_n'] == 5
    admin_client.post('/api/auth/login', json={'username': 'admin', 'password': 'TestAdmin123!'})
    assert admin_client.post(f'/api/jobs/{sid}/gnina').status_code == 409  # active task


def test_resume_conflicts(admin_client):
    sid, ids, job = seeded()
    set_top(0)
    assert admin_client.post(f'/api/jobs/{sid}/gnina').status_code == 409
    set_top(1)  # nothing left to compute
    r = admin_client.post(f'/api/jobs/{sid}/gnina')
    assert r.status_code == 409 and 'GNINA' in r.json()['detail']
    set_top(5)
    with transaction() as db:
        db.get(Task, sid).status = 'running'
    assert admin_client.post(f'/api/jobs/{sid}/gnina').status_code == 409
    with transaction() as db:
        db.get(Task, sid).status = 'failed'
    assert admin_client.post(f'/api/jobs/{sid}/gnina').status_code == 409
    assert admin_client.post(f'/api/jobs/{job}/gnina').status_code == 409  # not a screening
    with transaction() as db:
        assert db.scalar(select(Task.id).where(Task.kind == 'gnina', Task.id != job)) is None


def test_resume_requires_csrf_header_and_ownership(admin_client):
    sid, _, _ = seeded()
    set_top(5)
    assert admin_client.post(f'/api/jobs/{sid}/gnina', headers={'X-DS-Request': ''}).status_code == 403
    other_student(admin_client)
    assert admin_client.post(f'/api/jobs/{sid}/gnina').status_code == 404
    with transaction() as db:
        assert db.scalar(select(Task.id).where(Task.kind == 'gnina', Task.parameters['auto'].as_boolean() == False)) is None  # noqa: E712


def test_other_student_gets_404_everywhere(admin_client):
    sid, _, job = seeded()
    other_student(admin_client)
    for method, path in [('get', f'/jobs/{sid}'), ('get', f'/jobs/{sid}/results?sort=consensus'), ('get', f'/jobs/{sid}/scores?w=0.3'),
                         ('get', f'/jobs/{sid}/archive'), ('get', f'/jobs/{sid}/interaction-candidates.csv?interaction=true&residue=A:ALA:1:&kind=hydrogen_bond'),
                         ('post', f'/jobs/{sid}/gnina'), ('post', f'/jobs/{job}/retry'), ('post', f'/jobs/{sid}/retry')]:
        assert getattr(admin_client, method)('/api'+path).status_code == 404, path


def test_gnina_tasks_do_not_count_toward_pending_limit(admin_client):
    sid, _, _ = seeded()
    set_top(5)
    with transaction() as db:
        s = db.get(Settings, 1)
        s.values = {**s.values, 'max_pending_per_user': 1}
    assert admin_client.post(f'/api/jobs/{sid}/gnina').status_code == 201  # at the cap of 1 afterwards, if it counted
    with transaction() as db:
        require_capacity(db, db.get(User, 1))  # a queued gnina task alone does not hit the cap
    with transaction() as db:
        screen_id, _ = screen([(-5, 'succeeded')], status='queued')
    with transaction() as db:
        with pytest.raises(HTTPException) as e:
            require_capacity(db, db.get(User, 1))  # a queued screening does
        assert e.value.status_code == 409
    set_top(5)
    done, _ = screen([(-5, 'succeeded')])
    assert admin_client.post(f'/api/jobs/{done}/gnina').status_code == 201  # resume still allowed at the cap


# --- retry ---------------------------------------------------------------------------

def test_retry_of_gnina_task_is_409_pointing_to_resume(admin_client):
    sid, _, job = seeded()
    with transaction() as db:
        db.get(Task, job).status = 'failed'
    r = admin_client.post(f'/api/jobs/{job}/retry')
    assert r.status_code == 409 and 'GNINA 이어서 계산' in r.json()['detail']
    with transaction() as db:
        assert db.get(Task, job).status == 'failed'


def test_docking_retry_deletes_gnina_rows_of_retried_compounds_only(admin_client):
    sid, ids = screen([(-9, 'succeeded'), (-8, 'partial'), (-7, 'failed'), (-6, 'succeeded'), (-5, 'succeeded')], status='partial')
    job = old_job(sid)
    with transaction() as db:
        for i in ids:
            db.add(GninaScore(compound_id=i, task_id=sid, job_id=job, status='succeeded', cnn_score=.5, cnn_affinity=5, cnn_vs=2, gnina_vina=-5))
        other_sid, other_ids = screen([(-5, 'failed')], status='completed')
        db.add(GninaScore(compound_id=other_ids[0], task_id=other_sid, job_id=old_job(other_sid), status='succeeded'))
    r = admin_client.post(f'/api/jobs/{sid}/retry')
    assert r.status_code == 200, r.text
    with transaction() as db:
        left = set(db.scalars(select(GninaScore.compound_id).where(GninaScore.task_id == sid)))
        assert left == {ids[0], ids[3], ids[4]}
        assert db.scalar(select(GninaScore.compound_id).where(GninaScore.task_id == other_sid)) == other_ids[0]
        assert db.scalar(select(func_count())) == 4
        assert {c.status for c in db.scalars(select(Compound).where(Compound.id.in_([ids[1], ids[2]])))} == {'pending'}


def func_count():
    from sqlalchemy import func
    return func.count(GninaScore.compound_id)


def test_docking_retry_still_blocked_while_child_task_active(admin_client):
    sid, ids = screen([(-9, 'failed')], status='partial')
    job = old_job(sid, status='running')
    with transaction() as db:
        db.add(GninaScore(compound_id=ids[0], task_id=sid, job_id=job, status='pending'))
    assert admin_client.post(f'/api/jobs/{sid}/retry').status_code == 409
    with transaction() as db:
        assert db.scalar(select(GninaScore.status)) == 'pending'


# --- exports -------------------------------------------------------------------------

GNINA_HEADER = ['gnina_status', 'gnina_cnn_score', 'gnina_cnn_affinity', 'gnina_cnn_vs', 'gnina_vina', 'gnina_consensus_rank']


def parse(text, delimiter=','):
    assert text.startswith('﻿')
    return list(csv.DictReader(io.StringIO(text.lstrip('﻿')), delimiter=delimiter))


@pytest.mark.parametrize('fmt,delimiter', [('csv', ','), ('tsv', '\t')])
def test_score_export_appends_gnina_columns(admin_client, fmt, delimiter):
    sid, ids, _ = seeded()
    with transaction() as db:
        db.get(Compound, ids[0]).cid = '=cmd()'
    r = admin_client.get(f'/api/jobs/{sid}/scores?format={fmt}&w=1')
    assert r.status_code == 200
    header = next(csv.reader(io.StringIO(r.text.lstrip('﻿')), delimiter=delimiter))
    assert header[-6:] == GNINA_HEADER and header[-7] == 'exported_at_utc'
    by_row = {int(x['row_number']): x for x in parse(r.text, delimiter)}
    order = [o['row_number'] for o in expected_rows(1)]
    assert by_row[1]['CID'] == "'=cmd()"
    for n, row in enumerate(order, 1):
        assert by_row[row]['gnina_consensus_rank'] == str(n) and by_row[row]['gnina_status'] == 'succeeded'
    assert by_row[2]['gnina_cnn_score'] == '0.9' and by_row[2]['gnina_vina'] == '-7.5'
    assert by_row[5]['gnina_status'] == 'failed' and by_row[5]['gnina_consensus_rank'] == '' and by_row[5]['gnina_cnn_score'] == ''
    assert by_row[6]['gnina_status'] == '' and by_row[6]['gnina_consensus_rank'] == ''
    assert admin_client.get(f'/api/jobs/{sid}/scores?w=2').status_code == 422


def test_candidate_export_appends_gnina_columns(admin_client):
    sid, ids, job = seeded()
    key = 'A:ALA:1:'
    with transaction() as db:
        db.get(Receptor, db.get(Task, sid).receptor_id).structure = {'residues': [dict(key=key, category='protein')]}
        it = Task(owner_id=1, receptor_id=db.get(Task, sid).receptor_id, source_task_id=sid, kind='interactions', name='i', status='completed')
        db.add(it)
        db.flush()
        for i in (ids[0], ids[1], ids[5]):
            db.add(CompoundAnalysis(compound_id=i, job_id=it.id, status='succeeded'))
            db.add(InteractionHit(compound_id=i, residue_key=key, kind='hydrogen_bond', task_id=sid,
                                  residue=dict(chain='A', name='ALA', number=1, insertion=''), count=1, distance=2.9))
    q = f'interaction=true&residue={key}&kind=hydrogen_bond'
    r = admin_client.get(f'/api/jobs/{sid}/interaction-candidates.csv?{q}&w=0')
    assert r.status_code == 200
    by_row = {int(x['row_number']): x for x in parse(r.text)}
    assert set(by_row) == {1, 2, 6}
    assert list(next(csv.reader(io.StringIO(r.text.lstrip('﻿')))))[-6:] == GNINA_HEADER
    rank0 = {o['row_number']: o['rank']['consensus'] for o in expected_rows(0)}
    assert by_row[1]['gnina_consensus_rank'] == str(rank0[1]) and by_row[2]['gnina_status'] == 'succeeded'
    assert by_row[6]['gnina_status'] == '' and by_row[6]['gnina_consensus_rank'] == ''
    assert admin_client.get(f'/api/jobs/{sid}/interaction-candidates.csv?{q}&w=-1').status_code == 422


def test_manifest_contains_gnina_info_only_with_records(admin_client):
    sid, _, _ = seeded()
    with transaction() as db:
        db.scalars(select(Task).where(Task.id == db.scalar(select(GninaScore.job_id).limit(1)))).one().parameters = {'top_n': 6}
    r = admin_client.get(f'/api/jobs/{sid}/archive')
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest = json.loads(z.read('manifest.json'))
        assert manifest['gnina'] == dict(version='gnina v1.3', binary_sha256='b'*64, top_n=6, scored=4)
        assert 'gnina_consensus_rank' in z.read('scores.csv').decode()
    plain, _ = screen([(-5, 'succeeded')])
    r = admin_client.get(f'/api/jobs/{plain}/archive')
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert 'gnina' not in json.loads(z.read('manifest.json'))


# --- settings ------------------------------------------------------------------------

def test_gnina_top_n_round_trips_and_missing_key_is_tolerated(admin_client):
    values = admin_client.get('/api/settings').json()['values']
    assert 'gnina_top_n' in values
    r = admin_client.put('/api/admin/settings', json={**values, 'gnina_top_n': 7})
    assert r.status_code == 200 and r.json()['values']['gnina_top_n'] == 7
    assert admin_client.get('/api/settings').json()['values']['gnina_top_n'] == 7
    assert admin_client.put('/api/admin/settings', json={**values, 'gnina_top_n': values['max_compounds']+1}).status_code == 422
    with transaction() as db:
        s = db.get(Settings, 1)
        s.values = {k: v for k, v in s.values.items() if k != 'gnina_top_n'}
    assert admin_client.get('/api/settings').json()['values']['gnina_top_n'] == 1000
    sid, ids, _ = seeded()
    r = admin_client.post(f'/api/jobs/{sid}/gnina')  # default top_n 1000 applies
    assert r.status_code == 201 and r.json()['parameters']['top_n'] == 1000
    assert admin_client.get(f'/api/jobs/{sid}').json()['gnina']['top_n'] == 1000
