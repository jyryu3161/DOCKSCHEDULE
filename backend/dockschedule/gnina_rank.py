"""Pure rank arithmetic for QuickVina/GNINA consensus. No chemistry imports: the api imports this module."""


def average_ranks(values, descending=False):
    """1 = best; tied values share the average of the positions they span."""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=descending)
    ranks = [0.0]*len(values)
    start = 0
    while start < len(order):
        end = start
        while end+1 < len(order) and values[order[end+1]] == values[order[start]]:
            end += 1
        for i in order[start:end+1]:
            ranks[i] = (start+end)/2+1
        start = end+1
    return ranks


def extra_ranks(rows, keys=('cnn_score', 'cnn_vs')):
    """Descending (higher is better) ranks per row id for the given metrics."""
    out = {r['id']: {} for r in rows}
    for key in keys:
        for r, rank in zip(rows, average_ranks([r[key] for r in rows], descending=True)):
            out[r['id']][key] = rank
    return out


def consensus_order(rows, w):
    """Order rows by w*rank(CNNaffinity) + (1-w)*rank(Vina); lower is better, ties by row_number."""
    if not 0 <= w <= 1:
        raise ValueError('가중치는 0 이상 1 이하여야 합니다.')
    vina = average_ranks([r['vina'] for r in rows])
    cnn = average_ranks([r['cnn_affinity'] for r in rows], descending=True)
    scored = [(w*c+(1-w)*v, r['row_number'], r, v, c) for r, v, c in zip(rows, vina, cnn)]
    scored.sort(key=lambda s: (s[0], s[1]))
    return [dict(id=r['id'], row_number=r['row_number'], consensus_value=value,
                 rank=dict(vina=v, cnn_affinity=c, consensus=n))
            for n, (value, _, r, v, c) in enumerate(scored, 1)]
