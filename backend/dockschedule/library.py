import csv
from itertools import islice
from pathlib import Path

ENCODINGS = {'utf-8-sig', 'cp949', 'utf-16', 'latin-1'}


def column_names(header):
    """Give every physical column a stable, selectable name without losing data."""
    reserved = {name.strip() for name in header if name.strip()}
    used, names = set(), []
    for index, original in enumerate(header, 1):
        base = original.strip() or f'column_{index}'
        name, suffix = base, 2
        while name in used or (name in reserved and (not original.strip() or name != base)):
            name = f'{base} [{suffix}]'
            suffix += 1
        used.add(name)
        names.append(name)
    return names


def read_rows(path: Path, delimiter=',', encoding='utf-8-sig', header=True, metadata=None):
    if delimiter == '\\t':
        delimiter = '\t'
    if len(delimiter) != 1 or delimiter in '\r\n"':
        raise ValueError('구분자는 줄바꿈과 따옴표를 제외한 한 글자여야 합니다.')
    if encoding not in ENCODINGS:
        raise ValueError('지원하지 않는 인코딩입니다.')
    with path.open(encoding=encoding, newline='') as f:
        # Excel/vendor exports may put e.g. "sep=," before the actual header.
        # This declaration is not a CSV record. The user's delimiter still wins.
        first_line = f.readline().rstrip('\r\n')
        declared = first_line[4] if len(first_line) == 5 and first_line[:4].lower() == 'sep=' else None
        offset = 1 if declared is not None else 0
        if not offset:
            f.seek(0)
        warnings = []
        if declared is not None and declared != delimiter:
            label = '탭' if declared == '\t' else repr(declared)
            warnings.append(f'파일의 구분자 안내는 {label}입니다. 현재 선택한 구분자와 다르므로 미리보기를 확인하세요.')
        reader = csv.reader(f, delimiter=delimiter, strict=True)
        first = next(reader, None)
        if first is None:
            raise ValueError('파일이 비어 있습니다.')
        if not first:
            raise ValueError('첫 데이터 행이 비어 있습니다. 헤더와 구분자를 확인하세요.')
        width = len(first)
        columns = column_names(first) if header else [f'column_{i+1}' for i in range(width)]
        if header and columns != first:
            warnings.append('빈 컬럼명·중복 컬럼명·컬럼명 앞뒤 공백을 자동 정리했습니다. CID와 SMILES 컬럼을 확인하세요.')
        if metadata is not None:
            metadata.update(warnings=warnings, declared_delimiter=declared,
                            original_columns=first if header else None)
        yield columns
        if not header:
            yield offset+1, first
        while True:
            n = offset+reader.line_num+1
            row = next(reader, None)
            if row is None:
                break
            if not row:
                continue
            if len(row) != width:
                raise ValueError(f'{n}행: 컬럼 수가 {width}개가 아닙니다. 구분자와 인용부호를 확인하세요.')
            yield n, row


def preview(path, delimiter=',', encoding='utf-8-sig', header=True):
    metadata = {}
    rows = read_rows(path, delimiter, encoding, header, metadata)
    columns = next(rows)
    values = list(islice(rows, 21))
    return dict(columns=columns, rows=[dict(row_number=n, values=v) for n, v in values[:20]],
                has_more=len(values) > 20, **metadata)


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
