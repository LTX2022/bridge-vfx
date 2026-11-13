"""Explicit software-only sample header/VM region bytes; image files and ps/lsof stay real.

Load addresses and mapping extents are a software model, not native VM evidence.
No expected executable, host binding, scene or receipt is an input to the model.
"""
from datetime import datetime, timezone
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

ADDRESS='0x100000000'


def _executable(path):
    with Path(path).open('rb') as stream:
        header=stream.read(16)
    # The copied framework Python used by this finite fixture is thin Mach-O.
    if header[:4] not in (b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xfe\xed\xfa\xce'):
        return False
    order='<' if header[:1] in (b'\xcf',b'\xce') else '>'
    return len(header)==16 and struct.unpack(order+'I',header[12:16])[0]==2


def _facts(original,pid,deadline):
    text=original(['/bin/ps','-p',str(pid),'-o','pid=,ppid=,lstart=,stat='],deadline).decode('utf-8')
    match=re.fullmatch(r'\s*(\d+)\s+(\d+)\s+([A-Z][a-z]{2} [A-Z][a-z]{2}\s+\d{1,2} \d{2}:\d{2}:\d{2} \d{4})\s+([A-Za-z+<>=-]+)\s*',text)
    if not match or int(match[1])!=pid or match[4][0] in 'ZX':raise ValueError('SOFTWARE_IMAGE_PID_INVALID')
    parent=int(match[2]);birth=datetime.strptime(match[3],'%a %b %d %H:%M:%S %Y').replace(tzinfo=timezone.utc)
    raw=original(['/usr/sbin/lsof','-nP','-a','-p',str(pid),'-d','txt','-F','pRfDint0'],deadline)
    records=[]
    if not raw.endswith(b'\n'):raise ValueError('SOFTWARE_IMAGE_LSOF_INVALID')
    for line in raw.split(b'\n')[:-1]:
        fields=line.split(b'\0')
        if fields[-1]!=b'' or not all(fields[:-1]):raise ValueError('SOFTWARE_IMAGE_LSOF_INVALID')
        record={}
        for field in fields[:-1]:
            key=chr(field[0])
            if key in record:raise ValueError('SOFTWARE_IMAGE_LSOF_AMBIGUOUS')
            record[key]=field[1:].decode('utf-8')
        records.append(record)
    if not records or records[0]!={'p':str(pid),'R':str(parent)}:raise ValueError('SOFTWARE_IMAGE_PID_INVALID')
    paths=[]
    for record in records[1:]:
        if set(record)!={'f','t','D','i','n'} or record['f']!='txt' or record['t']!='REG':raise ValueError('SOFTWARE_IMAGE_LSOF_INVALID')
        path=Path(record['n'])
        if not path.is_absolute() or path.is_symlink():raise ValueError('SOFTWARE_IMAGE_PATH_INVALID')
        if _executable(path):paths.append(str(path))
    if len(paths)!=1:raise ValueError('SOFTWARE_IMAGE_MAIN_AMBIGUOUS')
    return parent,birth,paths[0]


def tool_boundary(original,log):
    def call(argv,deadline):
        if not argv or argv[0] not in ('/usr/bin/sample','/usr/bin/vmmap'):
            return original(argv,deadline)
        header=argv[0]=='/usr/bin/sample'
        legacy='-summary' in argv
        pid_text=argv[1] if header and len(argv)>1 else argv[4] if legacy and len(argv)>4 else argv[3] if len(argv)>3 else ''
        if not re.fullmatch(r'[1-9]\d*',pid_text):raise ValueError('SOFTWARE_IMAGE_PID_INVALID')
        pid=int(pid_text)
        expected=(['/usr/bin/sample',str(pid),'1','1000','-file','/dev/stdout'] if header else
            ['/usr/bin/vmmap','-w','-interleaved','-summary',str(pid)] if legacy else
            ['/usr/bin/vmmap','-w','-interleaved',str(pid),ADDRESS])
        if argv!=expected:raise ValueError('SOFTWARE_IMAGE_TOOL_ARGV_INVALID')
        parent,birth,path=_facts(original,pid,deadline)
        log({'event':'modeled-tool','argv':argv,'observed_pid':pid,'observed_parent':parent,
            'observed_image':path,'observed_birth':birth.isoformat(),'address_model':ADDRESS})
        if header or legacy:
            return (f'Process: software [{pid}]\nParent Process: software [{parent}]\nLoad Address: {ADDRESS}\n'
                f'Launch Time: {birth.strftime("%Y-%m-%d %H:%M:%S")}.000 +0000\nTarget Type: live task\n').encode()
        return f'---> __TEXT 100000000-100004000 [ 16K 0K 0K 0K] r-x/r-x SM=COW {path}\n'.encode()
    return call


def _bootstrap_source(source,log,process_source_sha256,supervisor_python):
    digest=hashlib.sha256(source.encode()).hexdigest()
    return ("import hashlib\n_software_model_source="+repr(source)+"\n"
        +"assert hashlib.sha256(_software_model_source.encode()).hexdigest()=="+repr(digest)+"\n"
        +"_software_model_namespace={'__name__':'explicit_software_image_tools'}\n"
        +"exec(compile(_software_model_source,'<frozen-software-image-tools>','exec'),_software_model_namespace)\n"
        +"_software_model_namespace['install']("+repr(str(log))+",_software_model_source,"+repr(process_source_sha256)+","+repr(supervisor_python)+")\n")


def bootstrap(adapter,log):
    process=Path(__file__).resolve().parents[2]/'packages/dcc-task-runtime/src/dcc_task_runtime/process_image.py'
    return _bootstrap_source(Path(adapter).read_text(),log,hashlib.sha256(process.read_bytes()).hexdigest(),str(Path(sys.executable).resolve()))


def install(log_path,frozen_source,process_source_sha256,supervisor_python):
    """Execute only source bytes embedded in the registered API test boundaries."""
    log_path=Path(log_path)
    digest=hashlib.sha256(frozen_source.encode()).hexdigest()
    def log(value):
        value.update(pid=os.getpid(),evidence_source='software_test',adapter_sha256=digest)
        fd=os.open(log_path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        try:os.write(fd,(json.dumps(value,sort_keys=True)+'\n').encode())
        finally:os.close(fd)
    def patch(module):
        source=Path(module.__file__).resolve()
        if (not str(source).endswith('/packages/dcc-task-runtime/src/dcc_task_runtime/process_image.py')
                or hashlib.sha256(source.read_bytes()).hexdigest()!=process_source_sha256):
            raise ValueError('SOFTWARE_IMAGE_MODULE_SOURCE_MISMATCH')
        if not getattr(module,'_explicit_software_image_tool_boundary',False):
            module._run_tool=tool_boundary(module._run_tool,log)
            module._explicit_software_image_tool_boundary=True
            log({'event':'module-installed','module':module.__name__,'source':module.__file__,
                'source_sha256':hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()})
    class Loader(importlib.abc.Loader):
        def __init__(self,original):self.original=original
        def create_module(self,spec):return self.original.create_module(spec)
        def exec_module(self,module):self.original.exec_module(module);patch(module)
    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if not fullname.endswith('.process_image'):return None
            spec=importlib.machinery.PathFinder.find_spec(fullname,path)
            if spec and spec.loader:spec.loader=Loader(spec.loader)
            return spec
    sys.meta_path.insert(0,Finder())
    for name,module in tuple(sys.modules.items()):
        if name.endswith('.process_image') and module is not None:patch(module)
    original_popen=subprocess.Popen
    def popen(command,*args,**kwargs):
        supervisor=(isinstance(command,list) and len(command)==5 and command[0]==supervisor_python
            and command[1]=='-B' and Path(command[2]).name=='owned_process.py' and command[3]=='--supervise')
        controller=(isinstance(command,list) and len(command)==7 and command[0]==supervisor_python
            and command[1:3]==['-I','-B'] and command[3]==str(log_path.parent/'activated/project/control/server.py')
            and command[4:]==['--backend','production','--software-processes'])
        if supervisor or controller:
            index=2 if supervisor else 3;script=Path(command[index])
            log({'event':'supervisor-bootstrap' if supervisor else 'controller-bootstrap','original_argv':command,
                'source_sha256':hashlib.sha256(script.read_bytes()).hexdigest()})
            code=_bootstrap_source(frozen_source,log_path,process_source_sha256,supervisor_python)+"import runpy,sys\nsys.argv=sys.argv[1:]\nrunpy.run_path(sys.argv[0],run_name='__main__')\n"
            command=[*command[:index],'-c',code,*command[index:]]
        return original_popen(command,*args,**kwargs)
    subprocess.Popen=popen
    log({'event':'installed','modeled_facts':['entire sample identity header bytes','ps-second birth with modeled .000 fraction','Load Address','__TEXT mapping extent'],'supervisor_injection':'explicit test Popen bootstrap, original supervisor source and child command retained','native_image_observation':'NOT_RUN'})
