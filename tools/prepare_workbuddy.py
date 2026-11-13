#!/usr/bin/env python3
"""Prepare a fresh local WorkBuddy diagnostic project; never install globally."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import struct
import sys
import tempfile
import uuid
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def png(variant: int) -> bytes:
    """Procedural, non-private vision fixtures; no descriptive text in pixels."""
    width, height = 512, 384
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            color = (24, 28, 37)
            if variant == 0:
                for cx in (120, 256, 392):
                    if 70 <= y <= 290 and abs(x - cx) <= (y - 70) * 0.24:
                        color = (244, 127, 38)
            else:
                for cx, cy in ((140, 110), (372, 110), (140, 275), (372, 275)):
                    if (x-cx)**2 + (y-cy)**2 < 64**2:
                        color = (54, 187, 224)
            row.extend(color)
        rows.append(bytes(row))
    def chunk(tag, content):
        return struct.pack('>I', len(content)) + tag + content + struct.pack('>I', zlib.crc32(tag+content) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def prepare(destination: Path, *, app: Path = Path('/Applications/WorkBuddy.app')):
    if sys.version_info < (3, 11):
        raise ValueError('diagnostic launcher requires Python 3.11 or later')
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination exists; use a new directory to preserve prior evidence')
    destination.parent.mkdir(parents=True, exist_ok=True)
    app_info = plistlib.loads((app/'Contents/Info.plist').read_bytes())
    if app_info.get('CFBundleIdentifier') != 'com.tencent.workbuddy.mac':
        raise ValueError('expected WorkBuddy app bundle')
    executable_name = app_info.get('CFBundleExecutable')
    if not isinstance(executable_name, str) or not executable_name or Path(executable_name).name != executable_name or executable_name in ('.', '..'):
        raise ValueError('invalid declared WorkBuddy executable')
    executable = app/'Contents/MacOS'/executable_name
    if executable.is_symlink() or not executable.is_file() or not executable.resolve().is_relative_to((app/'Contents/MacOS').resolve()):
        raise ValueError('WorkBuddy executable must be a confined regular file')
    app_identity = {'bundle_id': app_info['CFBundleIdentifier'], 'app_version': app_info['CFBundleShortVersionString'],
                    'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
                    'identity_source': 'installed_app_read_only', 'running_instance_verified': False}
    staging = Path(tempfile.mkdtemp(prefix='.bridge-workbuddy-', dir=str(destination.parent)))
    try:
        control = staging/'control'; project = staging/'project'
        (control/'assets').mkdir(parents=True); (project/'.workbuddy').mkdir(parents=True)
        runtime = control/'runtime'/'vfx_pipeline'; runtime.mkdir(parents=True)
        (runtime/'__init__.py').write_text('"""Standalone diagnostic subset; not a full Bridge release."""\n')
        for name in ('workbuddy_project.py', 'workbuddy_mcp.py'):
            source = ROOT/'packages/vfx-pipeline/src/vfx_pipeline'/name
            if source.is_symlink() or not source.is_file():
                raise ValueError('diagnostic implementation missing or symlinked: '+name)
            shutil.copyfile(source, runtime/name)
        shared_runtime = ROOT/'packages/dcc-task-runtime/src/dcc_task_runtime'
        if (shared_runtime.is_symlink() or not shared_runtime.is_dir()
                or any(path.is_symlink() for path in shared_runtime.rglob('*'))):
            raise ValueError('shared diagnostic runtime missing or symlinked')
        shutil.copytree(shared_runtime, control/'runtime/dcc_task_runtime',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', '.DS_Store'))
        assets=[]
        for variant in range(2):
            asset_id='asset_'+uuid.uuid4().hex[:12]
            data=png(variant); name='assets/'+asset_id+'.png'; (control/name).write_bytes(data)
            assets.append({'asset_id':asset_id,'file':name,'sha256':hashlib.sha256(data).hexdigest(),
                           'classification':'controller_generated_synthetic','mime_type':'image/png','width':512,'height':384})
        run_id='workbuddy_'+uuid.uuid4().hex
        _json(control/'run.json', {'schema':'bridge.workbuddy.diagnostic_run/1.0','run_id':run_id,
              'requested_route':'WorkBuddyDesktopRoute','requested_model':'HY3','app':app_identity,'assets':assets,
              'preview_budget_seconds':1200,'boundary_verified':False,'release_acceptance':False})
        launcher = '''from pathlib import Path
import argparse
import json
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'runtime'))
from vfx_pipeline.workbuddy_project import DiagnosticRun
parser=argparse.ArgumentParser()
parser.add_argument('--export',action='store_true')
args=parser.parse_args()
facade=DiagnosticRun(ROOT/'run.json')
if args.export:
    print(json.dumps(facade.export(),ensure_ascii=False,indent=2))
else:
    from vfx_pipeline.workbuddy_mcp import serve
    serve(facade)
'''
        (control/'server.py').write_text(launcher,encoding='utf-8')
        config={'mcpServers':{'bridge-hy3':{'command':sys.executable,'args':['-I',str(destination/'control/server.py')]}}}
        _json(project/'.workbuddy/mcp.json',config)
        # Candidate application policy. It is deliberately NOT an attestation
        # that this WorkBuddy build loaded or enforces the policy.
        policy={'permissions':{'defaultMode':'default','allow':[], 'deny':[
            'Bash','Read','Write','Edit','Glob','Grep','WebFetch','WebSearch','Task','Agent','ComputerUse'
        ]}}
        _json(project/'.workbuddy/settings.json',policy)
        prompt='''请只使用 bridge-hy3 连接器进行本次合成图片通信预检。不要调用终端、读写文件、浏览器、其他连接器或专家，也不要操作 Houdini/Nuke。
先读取连接器 health 和 catalog，再通过连接器读取其中两份 asset 的真实图片。对每张图片独立描述主要颜色、形状、数量与方向，以及不确定之处，再提交 observation。不要从 asset 名称猜测图像。
如果工具只返回文字、图片不可见或连接器不可用，请明确停止并说明，不要写脚本修复或声称看到了图片。
每份观察使用独立稳定 request_id；若网络重试，复用原 ID 和原观察。不要给自己打通过分，也不要声称已经完成 DCC 或模型身份验收。
最后用中文报告两图差异、连接器回执和任何阻塞。'''
        (project/'粘贴给HY3.txt').write_text(prompt+'\n',encoding='utf-8')
        readme=f'''# WorkBuddy + HY3 合成预检包

本包仅验证连接和图片观察，没有 DCC、缓存或授权签发工具；不是发布包。

1. 在 WorkBuddy 新建普通任务，工作目录选择 `{destination/'project'}`。
2. 选择 HY3，保持用户已选择的完全访问权限。
3. 在 MCP 管理页面确认 bridge-hy3 加载自本项目 `.workbuddy/mcp.json`。若未加载，可粘贴同目录的配置。不要覆盖用户级配置。
4. 仅批准 bridge-hy3 的诊断工具，把“粘贴给HY3.txt”的内容粘贴发送。
5. 将该测试任务的回复与工具记录返回给 Codex；本地 connector 回执会自动保存。

Bridge 的操作范围由当前任务合同约束；完全访问权限不等于 Bridge 提供系统级隔离。仅发送已登记、允许传输的合成媒体。

本机回执导出由 Codex 在控制端执行，不需要模型运行命令：
`{sys.executable} -I {destination/'control/server.py'} --export`

本地回执只能证明连接器收到请求；实际 WorkBuddy 会话、HY3 选择、看图正确性和权限边界需另行核对。生成前已存在的应用、配置和工程均不修改。

run_id: {run_id}
'''
        (staging/'操作说明.md').write_text(readme,encoding='utf-8')
        files=[]
        for p in sorted(staging.rglob('*')):
            if p.is_file():files.append({'path':p.relative_to(staging).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        _json(staging/'bundle-manifest.json',{'schema':'bridge.workbuddy.diagnostic_bundle/1.0','run_id':run_id,'files':files,'release_acceptance':False})
        os.rename(staging,destination)
        return {'project':str(destination/'project'),'instructions':str(destination/'操作说明.md'),'run_id':run_id,'mcp_config':str(destination/'project/.workbuddy/mcp.json'),'release_acceptance':False}
    finally:
        if staging.exists():shutil.rmtree(staging)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.output),ensure_ascii=False,indent=2))
