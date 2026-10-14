import pytest

from dockschedule import library


@pytest.mark.parametrize('delimiter', [',', ';', '\t'])
def test_excel_separator_declaration_is_not_a_header_or_compound(tmp_path, delimiter):
    path = tmp_path/'vendor.csv'
    path.write_text('\ufeffsep='+delimiter+'\r\n'+delimiter.join(['SMILES', 'Catalog ID'])+
                    '\r\n'+delimiter.join(['CCO', '001'])+'\r\n', encoding='utf-8')
    preview = library.preview(path, delimiter)
    assert preview['columns'] == ['SMILES', 'Catalog ID']
    assert preview['declared_delimiter'] == delimiter
    assert preview['rows'] == [dict(row_number=3, values=['CCO', '001'])]
    options = dict(delimiter=delimiter, encoding='utf-8-sig', header=True,
                   cid_column='Catalog ID', smiles_column='SMILES')
    compounds = list(library.compounds(path, options, 10))
    assert len(compounds) == 1
    assert compounds[0]['row_number'] == 3
    assert compounds[0]['cid'] == '001' and compounds[0]['smiles'] == 'CCO'


def test_blank_and_duplicate_headers_preserve_all_columns_and_column_mapping(tmp_path):
    path = tmp_path/'index.csv'
    path.write_text(', CID ,SMILES,CID,CID [2],column_1\n0,001,CCO,other,extra,index\n')
    preview = library.preview(path)
    assert preview['columns'] == ['column_1 [2]', 'CID', 'SMILES', 'CID [3]', 'CID [2]', 'column_1']
    assert preview['warnings']
    options = dict(delimiter=',', encoding='utf-8-sig', header=True,
                   cid_column='CID [3]', smiles_column='SMILES')
    row = next(library.compounds(path, options, 10))
    assert row['cid'] == 'other' and row['smiles'] == 'CCO'


def test_separator_declaration_also_works_without_header(tmp_path):
    path = tmp_path/'no-header.csv'
    path.write_text('sep=,\na,CCO\nb,CC\n')
    options = dict(delimiter=',', encoding='utf-8-sig', header=False,
                   cid_column='column_1', smiles_column='column_2')
    rows = list(library.compounds(path, options, 10))
    assert [row['cid'] for row in rows] == ['a', 'b']
    assert [row['row_number'] for row in rows] == [2, 3]


def test_explicit_separator_wins_over_file_hint_and_preview_warns(tmp_path):
    path = tmp_path/'hint.csv'
    path.write_text('sep=;\nCID,SMILES\n001,CCO\n')
    preview = library.preview(path, ',')
    assert preview['columns'] == ['CID', 'SMILES']
    assert preview['warnings'] and preview['declared_delimiter'] == ';'


def test_row_numbers_follow_original_file_after_quoted_multiline_cell(tmp_path):
    path = tmp_path/'multiline.csv'
    path.write_text('sep=,\nCID,SMILES,note\n001,CCO,"first\nsecond"\n002,CC,plain\n')
    options = dict(delimiter=',', encoding='utf-8-sig', header=True,
                   cid_column='CID', smiles_column='SMILES')
    rows = list(library.compounds(path, options, 10))
    assert [row['row_number'] for row in rows] == [3, 5]


def test_upload_preview_and_submission_agree_on_excel_vendor_file(admin_client):
    # Use a ready receptor stub; this checks import/submission, not chemistry.
    from sqlalchemy import select
    from dockschedule.db import transaction
    from dockschedule.models import Compound, Receptor, Upload

    with transaction() as db:
        upload = Upload(owner_id=1, kind='pdb', filename='protein.pdb', path='/unused', size=0, sha256='0'*64)
        db.add(upload)
        db.flush()
        receptor = Receptor(owner_id=1, upload_id=upload.id, name='protein', status='ready', structure={'residues': []})
        db.add(receptor)
        db.flush()
        receptor_id = receptor.id
    response = admin_client.post('/api/uploads?kind=library', files={
        'file': ('vendor.csv', b'sep=,\r\nSMILES,Catalog ID\r\nCCO,001\r\n')})
    assert response.status_code == 201
    upload_id = response.json()['id']
    options = dict(delimiter=',', encoding='utf-8-sig', header=True,
                   cid_column='Catalog ID', smiles_column='SMILES')
    response = admin_client.post(f'/api/uploads/{upload_id}/preview', json=options)
    assert response.status_code == 200 and response.json()['columns'] == ['SMILES', 'Catalog ID']
    response = admin_client.post('/api/jobs', json=dict(name='Excel vendor import', receptor_id=receptor_id,
        library_id=upload_id, library=options, center=[1, 2, 3], size=[20, 20, 20]))
    assert response.status_code == 201 and response.json()['total'] == 1
    with transaction() as db:
        compound = db.scalar(select(Compound).where(Compound.task_id == response.json()['id']))
        assert (compound.row_number, compound.cid, compound.smiles) == (3, '001', 'CCO')
