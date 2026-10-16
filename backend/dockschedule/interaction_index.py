"""Durable, compact residue/type index shared by candidate queries and exports.

Only successful analyses can match; pending, failed and zero-contact poses remain
distinct. Chemical analysis stays in the scheduled worker, outside the API.
"""
from sqlalchemy import delete, func, select

from .models import ACTIVE, Compound, CompoundAnalysis, InteractionHit, Task

KINDS = ('hydrogen_bond', 'hydrophobic', 'salt_bridge', 'pi_stacking', 'cation_pi', 'halogen_bond')


def eligible(task_id):
    return select(Compound).where(Compound.task_id == task_id,
        Compound.status.in_(('succeeded', 'partial')), Compound.affinity.is_not(None))


def active_analysis(db, task_id):
    return db.scalar(select(Task).where(Task.source_task_id == task_id,
        (Task.status.in_(('queued', *ACTIVE))) | Task.worker_pid.is_not(None)))


def invalidate(db, compound_ids):
    db.execute(delete(CompoundAnalysis).where(CompoundAnalysis.compound_id.in_(compound_ids)))


def summarize(report):
    groups = {}
    for row in report['interactions']:
        key = row['residue']['key'], row['kind']
        if key not in groups:
            groups[key] = dict(residue_key=key[0], kind=key[1],
                residue={k: v for k, v in row['residue'].items() if k != 'atom_indices'},
                count=0, distance=row['distance'])
        groups[key]['count'] += 1
        groups[key]['distance'] = min(groups[key]['distance'], row['distance'])
    return list(groups.values())


def hit_query(task_id, filters):
    return select(InteractionHit).where(InteractionHit.task_id == task_id,
        InteractionHit.residue_key.in_(filters['residues']), InteractionHit.kind.in_(filters['kinds']))


def candidate_query(task_id, filters):
    matches = hit_query(task_id, filters).with_only_columns(InteractionHit.compound_id).group_by(InteractionHit.compound_id)
    if filters['match'] == 'all':
        matches = matches.having(func.count(func.distinct(InteractionHit.residue_key)) == len(filters['residues']))
    return eligible(task_id).join(CompoundAnalysis, CompoundAnalysis.compound_id == Compound.id).where(
        CompoundAnalysis.status == 'succeeded', Compound.id.in_(matches))


def text_filters(query, search, status):
    if search:
        query = query.where(Compound.cid.contains(search, autoescape=True))
    if status:
        query = query.where(Compound.status == status)
    return query


def matching_hits(db, task_id, ids, filters):
    groups = {i: [] for i in ids}
    for hit in db.scalars(hit_query(task_id, filters).where(InteractionHit.compound_id.in_(ids)).order_by(
            InteractionHit.residue_key, InteractionHit.kind)):
        groups[hit.compound_id].append(dict(residue=hit.residue, kind=hit.kind, count=hit.count, distance=hit.distance))
    return groups
