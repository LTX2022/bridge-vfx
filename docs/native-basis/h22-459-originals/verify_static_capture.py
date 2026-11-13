#!/usr/bin/env python3
"""Verify read-only 22.0.459 static evidence; never import/execute a DCC API."""
from pathlib import Path
from zipfile import ZipFile
import base64,gzip,hashlib,json,sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import capture_native_schema as capture

def sha(data):return hashlib.sha256(data).hexdigest()
def original(record):
 data=Path(record.get('path') or record.get('source')).read_bytes()
 assert len(data)==record['bytes'] and sha(data)==record['sha256']
 return data

def normalized_flags(value):
 if isinstance(value,dict):return {k:sorted(v) if k=='flags' and isinstance(v,list) else normalized_flags(v) for k,v in value.items()}
 if isinstance(value,list):return [normalized_flags(v) for v in value]
 return value

def main():
 h=json.loads((HERE/'hda-interface-459.json').read_text());assert h['version']=='22.0.459' and h['native_execution'] is False
 archives={name:capture.index_sections(original(r)) for name,r in h['libraries'].items()}
 count=0
 for name,r in h['operators'].items():
  if r['status']!='CAPTURED_STATIC_DIALOG':continue
  raw=capture.index_sections(archives[r['library']][name])['DialogScript']
  assert sha(raw)==r['section_sha256'] and len(raw)==r['section_bytes'] and raw==(HERE/r['raw_section']).read_bytes()
  assert normalized_flags(capture.dialog_parameters(raw))==normalized_flags(r['parameters']) and capture.dialog_interface(raw)==r['interface'];count+=1
 s=json.loads((HERE/'supporting-sources-459.json').read_text())
 for r in s['files']:
  if r.get('status')=='MISSING':continue
  assert original(r)==(HERE/r['raw_copy']).read_bytes()
 for r in s['documents']:
  if r['status']!='CAPTURED_STATIC_DOCUMENT':continue
  original(r['archive_source'])
  with ZipFile(r['archive_source']['path']) as z:raw=z.read(r['member'])
  assert sha(raw)==r['sha256'] and len(raw)==r['bytes'] and raw==(HERE/r['raw_copy']).read_bytes()
 consumer=s['crowd_transition_consumer'];sections=capture.index_sections(archives[consumer['library']][consumer['operator']]);compressed=sections['Contents.gz'];assert sha(compressed)==consumer['compressed_sha256'];data=gzip.decompress(compressed);assert sha(data)==consumer['decoded_sha256'] and data[:4]==b'\xd6\xf5\x01\x00'
 pos=4;members={}
 while pos<len(data):
  assert data[pos:pos+6]==b'070707' and pos+76<=len(data)
  head=data[pos:pos+76];ns=int(head[59:65],8);size=int(head[65:76],8);assert 1<=ns<=4096 and size<=16*1024*1024 and pos+76+ns+size<=len(data)
  rawname=data[pos+76:pos+76+ns];assert rawname[-1:]==b'\0';name=rawname[:-1].decode('utf8');assert name not in members;start=pos+76+ns;members[name]=data[start:start+size];pos=start+size
  if name=='TRAILER!!!':break
 assert pos==len(data) and len(members)==consumer['record_count'];raw=members[consumer['member']];assert sha(raw)==consumer['sha256'] and len(raw)==consumer['bytes'] and raw==(HERE/consumer['raw_copy']).read_bytes()
 for r in json.loads((HERE/'extra-native-sources-459.json').read_text())['files']:assert original(r)==(HERE/r['raw_copy']).read_bytes()
 ui=json.loads((HERE/'compiled-ui-originals-459.json').read_text())
 for r in ui['files']:assert original(r)==base64.b64decode(r['base64'],validate=True)
 print(json.dumps(dict(scope='installed original bytes and static parsers only',version='22.0.459',native_execution=False,dialog_count=count,compiled_ui_records=len(ui['files']),consumer_cpio_records=len(members),declarative_flag_order='compared as an unordered flag set; menus and all raw bytes retain exact order',passed=True),indent=2))
if __name__=='__main__':main()
