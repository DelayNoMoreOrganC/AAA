"""Output-page trace validation. Placement is not a claim of document accuracy."""
import os


VERSION = 'source-pages-v1'


def _path(value):
    return os.path.normcase(os.path.realpath(os.path.abspath(value)))


def project_locations(raw, files, sources, total, pagination):
    if raw is None:
        return None  # Historical results did not record per-page destinations.
    if not isinstance(raw,list):
        raise ValueError('SOURCE_PAGE_LOCATIONS_INVALID')
    lookup = {_path(row['path']):(index,row) for index,row in enumerate(sources,1)}
    if len(lookup)!=len(sources):
        raise ValueError('SOURCE_PAGE_LOCATIONS_AMBIGUOUS')
    projected=[]
    for row in raw:
        if not isinstance(row,dict) or not isinstance(row.get('source_path'),str):
            raise ValueError('SOURCE_PAGE_LOCATIONS_INVALID')
        identity=lookup.get(_path(row['source_path']))
        if identity is None:
            raise ValueError('SOURCE_PAGE_LOCATIONS_UNKNOWN_SOURCE')
        index,source=identity
        projected.append({'source_index':index,'file_id':getattr(files[index-1],'id',None),
            'source_filename':source['filename'],'source_sha256':source['processed_sha256'],
            **{key:row.get(key) for key in ('source_page','archive_page','body_page','doc_id','catalog_seq')}})
    validate_locations(projected,sources,total,pagination)
    return projected


def validate_locations(rows,sources,total,pagination):
    if (not isinstance(rows,list) or not isinstance(sources,list) or not sources or
            type(total) is not int or total<1 or not isinstance(pagination,dict)):
        raise ValueError('SOURCE_PAGE_LOCATIONS_INVALID')
    expected=set()
    for index,source in enumerate(sources,1):
        if not isinstance(source,dict) or type(source.get('pages')) is not int or source['pages']<1:
            raise ValueError('SOURCE_PAGE_LOCATIONS_INVALID')
        expected.update((index,page) for page in range(1,source['pages']+1))
    seen=set();destinations=set()
    mode=pagination.get('mode');start=pagination.get('body_start')
    if mode not in ('draft','body','legacy') or type(start) is not int or not 0<=start<total:
        raise ValueError('SOURCE_PAGE_LOCATIONS_PAGINATION')
    for row in rows:
        if not isinstance(row,dict):raise ValueError('SOURCE_PAGE_LOCATIONS_INVALID')
        index,page,destination=(row.get(key) for key in ('source_index','source_page','archive_page'))
        if any(type(n) is not int for n in (index,page,destination)):
            raise ValueError('SOURCE_PAGE_LOCATIONS_INVALID')
        if (index,page) not in expected or (index,page) in seen or destination in destinations or not 1<=destination<=total:
            raise ValueError('SOURCE_PAGE_LOCATIONS_COVERAGE')
        source=sources[index-1]
        if row.get('source_sha256')!=source['processed_sha256'] or row.get('source_filename')!=source['filename']:
            raise ValueError('SOURCE_PAGE_LOCATIONS_SOURCE')
        expected_label=destination-start if mode=='body' and destination>start else None
        if row.get('body_page')!=expected_label or isinstance(row.get('body_page'),bool):
            raise ValueError('SOURCE_PAGE_LOCATIONS_PAGINATION')
        seen.add((index,page));destinations.add(destination)
    if seen!=expected:
        raise ValueError('SOURCE_PAGE_LOCATIONS_COVERAGE')
