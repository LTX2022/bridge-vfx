#!/usr/bin/env python3
"""有界RectLight任务父驱动；准备及执行同受600秒墙钟限制，未知不重派。"""
from pathlib import Path
import argparse,json,os,signal,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
for name in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):sys.path.insert(0,str(ROOT/'packages'/name/'src'))

def _write_error(directory,error,cleanup=None,cleanup_errors=None):
 """保留最早失败；父驱动只补实际停止结果，不让子进程的未知值挡住收尾。"""
 from houdini_bridge.official_karma_observation import write_new
 from dcc_task_runtime.platform_support import atomic_write
 path=directory/'error.json'
 value=json.loads(path.read_text()) if path.exists() else {'code':type(error).__name__,'message':str(error),'native_success_claimed':False}
 if cleanup is not None:
  value['cleanup_confirmed']=cleanup;value['cleanup_errors']=list(cleanup_errors or [])
 value['native_success_claimed']=False
 if path.exists():atomic_write(path,(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n').encode(),owned_root=directory)
 else:write_new(path,value)

def _stop_control_group(child,*,group=True):
 """只终止本驱动持有的未回收子进程；两异常路径均完成TERM/KILL和wait。"""
 if child is None:return True
 if child.poll() is not None:return True
 def send(sig):
  try:
   if group:os.killpg(child.pid,sig)
   elif sig==signal.SIGTERM:child.terminate()
   else:child.kill()
  except ProcessLookupError:pass
 send(signal.SIGTERM)
 try:child.wait(timeout=15)
 except subprocess.TimeoutExpired:
  send(signal.SIGKILL);child.wait(timeout=10)
 return child.poll() is not None

def _stop_job_native(job_path):
 """只停止本job签票和精确派生NR；不靠空集合声称未知启动已停止。"""
 import hashlib
 from dcc_task_runtime.native_scope import NativeScope,_accounting_lock
 from dcc_task_runtime.owned_process import OwnedProcessHandle
 from houdini_bridge.official_karma_observation import checked_bytes
 job=json.loads(job_path.read_text());prep=json.loads(checked_bytes(job['preparation']));native=NativeScope(prep['scope']);directory=job_path.parent
 nr='nrend-'+hashlib.sha256((job['operation_id']+'_nuke').encode()).hexdigest()[:16]
 nr_directory=native.root/'state/nuke_renders'/(nr+'.supervisor')
 known=True
 def selected(ticket):
  nonlocal known
  path=Path(ticket['directory']);identity=ticket.get('identity') or {}
  is_nr=path==nr_directory or identity.get('operation_id')==nr or identity.get('task_id')==nr
  if ticket.get('role')=='nuke-render' or is_nr:
   if not is_nr:return False
   valid=(path==nr_directory and ticket.get('role')=='nuke-render'
          and identity.get('operation_id')==nr and identity.get('task_id')==nr)
   if not valid:known=False
   return valid
  return path.is_relative_to(directory)
 # 原始签名票决定是否需要finish；snapshot的只读停止调和不替代持久记账。
 with _accounting_lock(native.state_path):tickets=native._read()['tickets']
 by_id={ticket['id']:ticket for ticket in tickets};targets={}
 for ticket in tickets:
  if not selected(ticket) or ticket.get('stopped_at') is not None:continue
  target=by_id.get(ticket.get('parent')) if ticket.get('parent') is not None else ticket
  if target is None or not selected(target):known=False;continue
  targets[target['id']]=target
 for ticket in targets.values():
  try:
   handle=OwnedProcessHandle(ticket['directory'],ticket['identity']);handle.terminate()
   try:handle.wait(timeout=15)
   except subprocess.TimeoutExpired:handle.kill();handle.wait(timeout=10)
   native.finish(ticket)
  except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired):known=False
 after=native.snapshot()['tickets']
 remaining=[ticket for ticket in after if selected(ticket)]
 return known and all(ticket.get('stopped_at') is not None for ticket in remaining)

def _cleanup_failure(job_path,child,*,group=True):
 """清理失败独立留证，不能盖掉触发本次收尾的原异常。"""
 problems=[]
 try:control=_stop_control_group(child,group=group)
 except BaseException as error:control=False;problems.append('control:'+type(error).__name__+':'+str(error))
 try:native=_stop_job_native(job_path)
 except BaseException as error:native=False;problems.append('native:'+type(error).__name__+':'+str(error))
 return control and native,problems

def main():
 parser=argparse.ArgumentParser();parser.add_argument('command',choices=('run-job','prepare-and-execute','execute-job'));parser.add_argument('--job',required=True);args=parser.parse_args();job_path=Path(args.job);directory=job_path.parent
 if args.command=='run-job':
  # 父进程不先做准备；所有可能耗时的验源/prepare_graph/封view均在此受控子组内。
  command=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'prepare-and-execute','--job',str(job_path)]
  child=subprocess.Popen(command,cwd=directory,start_new_session=True)
  try:
   code=child.wait(timeout=600)
   if code:raise RuntimeError('RECT_SHAPE_EXECUTION_FAILED_READ_ORIGINAL_LOG')
  except BaseException as error:
   cleaned,problems=_cleanup_failure(job_path,child)
   try:_write_error(directory,error,cleaned,problems)
   except BaseException as record_error:print('RECT_SHAPE_ERROR_RECORD_FAILED:'+type(record_error).__name__,file=sys.stderr)
   raise
  return
 # 只有受父驱动监管的子进程才加载准备/执行模块；角色120秒限制仍独立生效。
 from vfx_pipeline.rectlight_shape_execution import execution_job,execute_job
 child=None
 try:
  if args.command=='execute-job':execute_job(job_path);return
  active,prepared=execution_job(job_path);job=json.loads(active.read_text());prep=json.loads(Path(job['preparation']['path']).read_text())
  command=[prep['supervisor_python'],'-I','-B',str(Path(prepared['control'])/'snapshot/tools/run_rectlight_shape.py'),'execute-job','--job',str(active)]
  child=subprocess.Popen(command,cwd=directory)
  code=child.wait()
  if code:raise RuntimeError('RECT_SHAPE_EXECUTION_FAILED_READ_ORIGINAL_LOG')
 except BaseException as error:
  cleaned,problems=_cleanup_failure(job_path,child,group=False)
  try:_write_error(directory,error,cleaned,problems)
  except BaseException as record_error:print('RECT_SHAPE_ERROR_RECORD_FAILED:'+type(record_error).__name__,file=sys.stderr)
  raise
if __name__=='__main__':main()
