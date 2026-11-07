"""Selectively stage reviewed skills, without changing originals or executing helpers."""
import argparse,hashlib,json,re,shutil
from pathlib import Path,PurePosixPath
TEXT={'.md','.py','.sh','.json','.yaml','.yml','.toml','.txt'}
NAME=re.compile(r'[a-z0-9][a-z0-9_-]*')
def bundle(source,destination,inventory,curated=None):
    source=Path(source);destination=Path(destination)
    for root in (source,destination):
        for component in [root,*root.parents]:
            if component.is_symlink() or (hasattr(component,'is_junction') and component.is_junction()):raise ValueError('linked skill root refused')
    source=source.resolve();destination=destination.resolve()
    if destination==source or destination.is_relative_to(source) or source.is_relative_to(destination):raise ValueError('bundle must be outside original skills')
    if destination.exists():raise ValueError('never overwrite a skill bundle')
    curated=Path(curated) if curated else None
    for root in [Path(source),Path(destination),*([curated] if curated else [])]:
        for component in [root,*root.parents]:
            if component.is_symlink() or (hasattr(component,'is_junction') and component.is_junction()):raise ValueError('linked skill root refused')
    selected=[];seen=set()
    for row in inventory:
        if row['category']!='meenemen':continue
        parts=PurePosixPath(row['id']).parts;name=row['name']
        if not parts or any(not NAME.fullmatch(p) for p in parts) or not NAME.fullmatch(name) or name in seen:raise ValueError('unsafe/duplicate skill identifier')
        origin=source.joinpath(*parts)
        if origin.is_symlink() or not origin.resolve().is_relative_to(source):raise ValueError('unsafe skill source')
        main=origin/'SKILL.md'
        if main.is_symlink() or not main.is_file() or hashlib.sha256(main.read_bytes()).hexdigest()!=row['source_sha256']:raise ValueError('skill source changed since review')
        use=curated/name if curated and (curated/name/'SKILL.md').is_file() else origin
        if use.is_symlink() or (hasattr(use,'is_junction') and use.is_junction()) or (curated and use!=origin and not use.resolve().is_relative_to(curated.resolve())):raise ValueError('curated skill root escape refused')
        files=[]
        for f in sorted(use.rglob('*')):
            rel=f.relative_to(use)
            if f.is_symlink():raise ValueError('skill symlinks refused')
            if not f.is_file() or any(x.startswith('.') or x in {'__pycache__','node_modules'} for x in rel.parts):continue
            if f.suffix.lower() not in TEXT:continue
            if 'windows' in str(rel).lower() or f.suffix.lower() in {'.ps1','.bat','.cmd'}:continue
            files.append((f,rel))
        if not any(str(rel)=='SKILL.md' for _,rel in files):raise ValueError('missing staged skill')
        selected.append((row,use!=origin,files));seen.add(name)
    destination.mkdir(parents=True)
    manifest=[]
    for row,is_curated,files in selected:
        for source_file,rel in files:
            out=destination/row['name']/rel;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source_file,out)
            manifest.append({'skill':row['name'],'path':out.relative_to(destination).as_posix(),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'curated':is_curated})
    (destination/'.bundle-manifest.json').write_text(json.dumps({'files':manifest,'selected_count':len(selected)},indent=2),encoding='utf-8')
    return manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('inventory',type=Path);p.add_argument('destination',type=Path);p.add_argument('--curated',type=Path);a=p.parse_args()
    result=bundle(a.source,a.destination,json.loads(a.inventory.read_text(encoding='utf-8'))['skills'],a.curated)
    print(json.dumps({'files':len(result),'skills':len({x['skill'] for x in result})}))
if __name__=='__main__':main()
