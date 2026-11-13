#!/usr/bin/env python3
"""Build a local history-storage gateway around an unchanged Bridge consumer."""
from pathlib import Path
import argparse, hashlib, json, shutil

LAUNCHER = '''from pathlib import Path
import argparse,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'gateway-manifest.json').read_text())
for item in manifest['files']:
 p=ROOT/item['path']
 if any(q.is_symlink() for q in (p,*p.parents)) or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
  raise ValueError('HISTORY_GATEWAY_PACKAGE_CHANGED')
binding=json.loads((ROOT/'archive-binding.json').read_text())
if hashlib.sha256(Path(binding['store'],'catalog.json').read_bytes()).hexdigest()!=binding['catalog_sha256']:
 raise ValueError('HISTORY_GATEWAY_CATALOG_CHANGED')
sys.path.insert(0,str(ROOT/'scripts'))
from history_archive import Store,gateway
parser=argparse.ArgumentParser();parser.add_argument('action',choices=['serve']);parser.add_argument('--projects');parser.add_argument('--history-archive-gateway',action='store_true')
args=parser.parse_args()
gateway(Store(binding['store']),registry=args.projects)
'''


def build(output, store, source_plugin, version='0.4.26'):
    output=Path(output).absolute();store=Path(store).absolute();source_plugin=Path(source_plugin).absolute()
    if output.exists():raise ValueError('HISTORY_GATEWAY_OUTPUT_EXISTS')
    from history_archive import Store
    Store(store).verify_archive()
    marketplace=output/'marketplace';plugin=marketplace/'plugins/bridge-vfx';(plugin/'scripts').mkdir(parents=True)
    shutil.copy2(Path(__file__).with_name('history_archive.py'),plugin/'scripts/history_archive.py')
    (plugin/'scripts/bridge_mcp.py').write_text(LAUNCHER)
    for directory in ('skills','docs'):
        shutil.copytree(source_plugin/directory,plugin/directory)
    meta=json.loads((source_plugin/'plugin.json').read_text());meta['version']=version
    meta['description']='Local archive storage gateway delegating to the pinned, unchanged Bridge consumer.'
    (plugin/'plugin.json').write_text(json.dumps(meta,indent=2)+'\n')
    (plugin/'mcp.json').write_text(json.dumps({'mcpServers':{'bridge-graph':{'command':'python3.11','args':['-I','-B','./scripts/bridge_mcp.py','serve','--history-archive-gateway']}}},indent=2)+'\n')
    (plugin/'archive-binding.json').write_text(json.dumps({'store':str(store),'catalog_sha256':hashlib.sha256((store/'catalog.json').read_bytes()).hexdigest()},indent=2)+'\n')
    rows=[{'path':str(p.relative_to(plugin)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(plugin.rglob('*')) if p.is_file()]
    (plugin/'gateway-manifest.json').write_text(json.dumps({'files':rows},indent=2)+'\n')
    catalog=marketplace/'.agents/plugins';catalog.mkdir(parents=True)
    name='bridge-local-v'+version.replace('.','')+'-archive'
    (catalog/'marketplace.json').write_text(json.dumps({'name':name,'interface':{'displayName':'Bridge History Archive Gateway'},'plugins':[{'name':'bridge-vfx','source':{'source':'local','path':'./plugins/bridge-vfx'},'policy':{'installation':'AVAILABLE','authentication':'ON_INSTALL'},'category':'Productivity'}]},indent=2)+'\n')
    return {'marketplace':str(marketplace),'plugin':str(plugin),'plugin_id':'bridge-vfx@'+name,'version':version,'files':len(rows)+1}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output');p.add_argument('--store',required=True);p.add_argument('--source-plugin',required=True)
    a=p.parse_args();print(json.dumps(build(a.output,a.store,a.source_plugin)))
