import csv
from itertools import islice
from pathlib import Path

ENCODINGS = {'utf-8-sig', 'cp949', 'utf-16', 'latin-1'}


def read_rows(path: Path, delimiter=',', encoding='utf-8-sig', header=True):
    if delimiter == '\\t':
        delimiter = '\t'
    if len(delimiter) != 1 or delimiter in '\r\n"':
        raise ValueError('구분자는 줄바꿈과 따옴표를 제외한 한 글자여야 합니다.')
    if encoding not in ENCODINGS:
        raise ValueError('지원하지 않는 인코딩입니다.')
    with path.open(encoding=encoding, newline='') as f:
        reader = csv.reader(f, delimiter=delimiter, strict=True)
        first = next(reader, None)
        if first is None:
            raise ValueError('파일이 비어 있습니다.')
        width = len(first)
        columns = first if header else [f'column_{i+1}' for i in range(width)]
        if not all(x.strip() for x in columns) or len(set(columns)) != len(columns):
            raise ValueError('컬럼 이름은 비어 있거나 중복될 수 없습니다.')
        yield columns
        if not header:
            yield 1, first
        for n, row in enumerate(reader, 2 if header else 2):
            if not row:
                continue
            if len(row) != width:
                raise ValueError(f'{n}행: 컬럼 수가 {width}개가 아닙니다. 구분자와 인용부호를 확인하세요.')
            yield n, row


def preview(path, delimiter=',', encoding='utf-8-sig', header=True):
    rows = read_rows(path, delimiter, encoding, header)
    columns = next(rows)
    values = list(islice(rows, 21))
    return dict(columns=columns, rows=[dict(row_number=n, values=v) for n, v in values[:20]],
                has_more=len(values) > 20)


def compounds(path, options, limit):
    rows = read_rows(path, options['delimiter'], options['encoding'], options['header'])
    cols = next(rows)
    try:
        ci, si = cols.index(options['cid_column']), cols.index(options['smiles_column'])
    except ValueError as e:
        raise ValueError('CID와 SMILES 컬럼을 선택하세요.') from e
    if ci == si:
        raise ValueError('CID와 SMILES는 서로 다른 컬럼이어야 합니다.')
    count = 0
    for n, row in rows:
        count += 1
        if count > limit:
            raise ValueError(f'최대 {limit:,}개 화합물까지 제출할 수 있습니다.')
        cid, smiles = row[ci].strip(), row[si].strip()
        if len(cid) > 500 or len(smiles) > 10000:
            raise ValueError(f'{n}행의 CID 또는 SMILES가 너무 깁니다.')
        error = 'CID 또는 SMILES가 비어 있습니다.' if not cid or not smiles else None
        yield dict(row_number=n, cid=cid, smiles=smiles, status='failed' if error else 'pending', error=error)
    if count == 0:
        raise ValueError('화합물 데이터가 없습니다.')
