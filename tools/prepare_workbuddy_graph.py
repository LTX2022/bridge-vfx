#!/usr/bin/env python3
"""Prepare a new construction-only project without changing app permissions."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import shutil
import sys

from prepare_workbuddy import prepare, ROOT, png

SNAPSHOT_TOOLS = ('qualify_native_stack.py', 'nuke_owned_render_worker.py', 'software_graph_worker.py',
                        'verify_controlled_output.py', 'prepare_native_alpha_scene.py',
                        'run_alpha_calibration.py', 'run_controlled_engineering.py',
                        'prepare_controlled_engineering.py', 'prepare_nuke_project.py',
                        'activate_controlled_engineering.py', 'prepare_workbuddy_graph.py',
                        'prepare_workbuddy.py','prepare_official_karma_scope.py',
                        'prepare_official_karma_source.py','compare_official_karma_images.py',
                        'continue_official_karma.py','feedback_official_karma.py','continue_disklight_feedback_nuke.py','recover_disklight_nuke.py','run_hy3_creative.py','run_luna_official_case.py','run_geometry_creative.py','run_rectlight_shape.py')


def snapshot_python_sources():
    paths=[]
    for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
        paths.extend(p for p in (ROOT/'packages'/package/'src').rglob('*.py')
                     if not p.is_symlink() and '__pycache__' not in p.parts)
    paths.extend(p for p in (ROOT/'plugins/houdini').rglob('*.py')
                 if not p.is_symlink() and '__pycache__' not in p.parts)
    paths.append(ROOT/'plugins/nuke/nuke_bridge_addon.py')
    paths.extend(ROOT/'tools'/name for name in SNAPSHOT_TOOLS)
    return sorted(set(paths))


def validate_media_config(config: dict) -> dict:
    """Validate the controller's existing media policy without running tools."""
    if not isinstance(config, dict):
        raise ValueError('controller_media: object required')
    allowed = {'ffmpeg_executable', 'attachment_limits', 'sequence_diagnostics'}
    if set(config) - allowed:
        raise ValueError('controller_media: unknown fields: ' + ', '.join(sorted(set(config) - allowed)))
    executable = config.get('ffmpeg_executable')
    if not isinstance(executable, str) or not executable or not Path(executable).is_absolute():
        raise ValueError('controller_media.ffmpeg_executable: absolute local executable required')
    path = Path(executable)
    if not path.is_file():
        raise ValueError('controller_media.ffmpeg_executable: file missing')
    if not os.access(path, os.X_OK) or (os.name == 'nt' and path.resolve().suffix.lower() not in {'.exe', '.com'}):
        raise ValueError('controller_media.ffmpeg_executable: file is not executable')
    if 'attachment_limits' in config:
        limits = config['attachment_limits']
        keys = {'max_attachments', 'max_attachment_bytes', 'max_total_bytes', 'max_dimension'}
        if not isinstance(limits, dict) or set(limits) - keys:
            raise ValueError('controller_media.attachment_limits: only existing attachment limit fields allowed')
        for key, value in limits.items():
            if type(value) is not int or value <= 0:
                raise ValueError('controller_media.attachment_limits.' + key + ': positive integer required')
    if 'sequence_diagnostics' in config:
        policy = config['sequence_diagnostics']
        keys = {'expected_frames', 'active_frames', 'max_temporal_delta'}
        if not isinstance(policy, dict) or set(policy) - keys:
            raise ValueError('controller_media.sequence_diagnostics: only existing sequence policy fields allowed')
        for key in ('expected_frames', 'active_frames'):
            frames = policy.get(key)
            if (not isinstance(frames, list) or not 1 <= len(frames) <= 12 or
                    any(type(frame) is not int or frame < 0 for frame in frames) or
                    frames != sorted(set(frames))):
                raise ValueError('controller_media.sequence_diagnostics.' + key + ': 1..12 sorted distinct nonnegative integer frames required')
        if not set(policy['active_frames']).issubset(policy['expected_frames']):
            raise ValueError('controller_media.sequence_diagnostics.active_frames: must be a subset of expected_frames')
        if 'max_temporal_delta' in policy:
            delta = policy['max_temporal_delta']
            try:
                valid_delta = type(delta) in (int, float) and math.isfinite(delta) and delta >= 0
            except OverflowError:
                valid_delta = False
            if not valid_delta:
                raise ValueError('controller_media.sequence_diagnostics.max_temporal_delta: finite nonnegative number required')
    return json.loads(json.dumps(config, allow_nan=False))


def _prepare_software(destination: Path) -> dict:
    """Software-profile project prep: same layout, no WorkBuddy bundle check.

    Used ONLY for controller-selected software runs (C3): synthetic images and
    the same control/project layout the formal generator produces.
    """
    import uuid
    control = destination / 'control'
    (control / 'inbox').mkdir(parents=True, exist_ok=False)
    (control / 'assets').mkdir(parents=True, exist_ok=True)
    assets = []
    for variant in range(2):
        asset_id = 'asset_' + uuid.uuid4().hex[:12]
        data = png(variant)
        name = 'assets/' + asset_id + '.png'
        (control / name).write_bytes(data)
        assets.append({'asset_id': asset_id, 'file': name, 'sha256': hashlib.sha256(data).hexdigest(),
                       'classification': 'controller_generated_synthetic', 'mime_type': 'image/png',
                       'width': 512, 'height': 384})
    run_id = 'workbuddy_' + uuid.uuid4().hex
    (control / 'run.json').write_text(json.dumps({
        'schema': 'bridge.workbuddy.diagnostic_run/1.0', 'run_id': run_id,
        'requested_route': 'WorkBuddyDesktopRoute', 'requested_model': 'HY3',
        'session_id': 'controller-' + run_id, 'session_scope': 'controller_run_not_provider_session',
        'assets': assets, 'preview_budget_seconds': 1200, 'boundary_verified': False,
        'release_acceptance': False}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'project').mkdir(parents=True, exist_ok=True)
    return {'control': control, 'project': destination / 'project', 'run_id': run_id}


def prepare_graph(destination: Path, *, app: "Path | None" = Path('/Applications/WorkBuddy.app'), scheduler_root: Path | None = None,
                  execution_profile: bool = False, simulation_profile: bool = False,
                  render_profile: bool = False,
                  production_host_config: dict | None = None,
                  production_nuke_config: dict | None = None,
                  media_config: dict | None = None,
                  construction_input_manifest=None, application='pipeline', official_case_derivation=None):
    if application not in ('pipeline','nuke'):
        raise ValueError('application must be pipeline or nuke')
    if official_case_derivation is not None:
        if application!='pipeline' or type(official_case_derivation) is not dict:
            raise ValueError('official_case_derivation requires a pipeline contract')
        official_case_derivation=json.loads(json.dumps(official_case_derivation,allow_nan=False))
    scene_configuration = None
    if construction_input_manifest is not None:
        from vfx_pipeline.graph_construction_inputs import freeze_construction_inputs, render_scene_configuration
        construction_input_manifest = freeze_construction_inputs(construction_input_manifest, verify_files=True)
        scene_configuration = render_scene_configuration(construction_input_manifest)
    if media_config is not None:
        media_config = validate_media_config(media_config)
    destination = destination.expanduser().absolute()
    scheduler_root = (scheduler_root or ROOT / '.bridge-state' / 'graph-scheduler').expanduser().resolve()
    for name in ('graph_jobs.py','graph_job_worker.py','graph_job_evidence.py','graph_scheduler.py','task_graph.py','workbuddy_graph_mcp.py','graph_handoff.py','workbuddy_assembly.py','artifact_registry.py'):
        if not (ROOT/'packages/vfx-pipeline/src/vfx_pipeline'/name).is_file():
            raise ValueError('graph implementation is not complete: '+name)
    created_plugin = None
    if production_host_config is not None and production_host_config.get('geometry_feedback_authority'):
        from houdini_bridge.official_karma_observation import checked_bytes
        from vfx_pipeline.geometry_feedback import resolve_execution_plugin
        created_plugin=resolve_execution_plugin(production_host_config['native_scope'],destination/'control',
            production_host_config.get('alpha_calibration'),authority=production_host_config['geometry_feedback_authority'])
    if production_host_config is not None and production_host_config.get('task_creation_origin'):
        # 仅新创建任务带此控制标签；旧调用不增加来源读取或改变配置。
        from vfx_pipeline.task_creation import resolve_execution_plugin
        from houdini_bridge.official_karma_observation import checked_bytes
        created_plugin = resolve_execution_plugin(production_host_config['native_scope'], destination/'control',
            production_host_config.get('alpha_calibration'), origin=production_host_config['task_creation_origin'])
        production_host_config = dict(production_host_config)
        production_host_config.pop('task_creation_origin')
    result = prepare(destination, app=app) if app is not None else _prepare_software(destination)
    control = destination/'control'
    if app is not None:
        (control/'inbox').mkdir()
    # These are new files owned by this generator; no user settings are edited.
    settings = destination/'project/.workbuddy/settings.json'
    if settings.exists():
        settings.unlink()
    snapshot = control/'snapshot'
    for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
        source = ROOT/'packages'/package/'src'
        for path in source.rglob('*.py'):
            if path.is_symlink() or '__pycache__' in path.parts:
                continue
            target = snapshot/'packages'/package/'src'/path.relative_to(source)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    addon = snapshot/'plugins/houdini/_impl/houdini_bridge_addon.py'
    addon.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(ROOT/'plugins/houdini', snapshot/'plugins/houdini', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pyo'))
    if created_plugin is not None:
        # 只覆盖本次新snapshot；原cache/插件/校准不复制密钥、不改签名，也不重跑alpha。
        addon.write_bytes(checked_bytes(created_plugin))
    nuke_addon = snapshot/'plugins/nuke/nuke_bridge_addon.py'
    nuke_addon.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'plugins/nuke/nuke_bridge_addon.py',nuke_addon)
    for worker_name in SNAPSHOT_TOOLS:
        worker = snapshot/'tools'/worker_name
        worker.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'tools'/worker_name, worker)
    baseline = Path('docs/official-baselines/karma/frozen-scene-v2.json')
    (snapshot/baseline).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT/baseline, snapshot/baseline)
    for helper in ('bridge_core_contract.py','durable_lock.py'):
        helper_path = ROOT/'plugins/houdini/_impl'/helper
        if helper_path.is_file():
            shutil.copyfile(helper_path, snapshot/'plugins/houdini/_impl'/helper)
    manifest = json.loads((control/'run.json').read_text(encoding='utf-8'))
    if simulation_profile and not execution_profile:
        raise ValueError('simulation_profile requires execution_profile')
    if render_profile and not execution_profile:
        raise ValueError('render_profile requires execution_profile')
    manifest.update({'construction_authorized':True,'permission_mode':'full_access_user_selected',
        'execution_authorized':bool(execution_profile),
        'session_id':'controller-'+str(manifest['run_id']),
        'session_scope':'controller_run_not_provider_session',
        'trial_budget_seconds':120,'simulation_authorized':bool(simulation_profile),
        'cache_authorized':False,'render_authorized':bool(render_profile),
        'application':application,
        'domain_pack':'nuke_composite_v1' if application == 'nuke' else 'pyro_smoke_v1'})
    if production_host_config is not None:
        manifest['production_host'] = dict(production_host_config)
    if production_nuke_config is not None:
        manifest['production_nuke'] = dict(production_nuke_config)
    if media_config is not None:
        manifest['controller_media'] = dict(media_config)
    if construction_input_manifest is not None:
        manifest['construction_input_manifest'] = construction_input_manifest
    if scene_configuration is not None and scene_configuration.get('profile') == 'official_karma_disklight_v1':
        manifest['domain_pack'] = 'lighting_camera_render_v1'
    if official_case_derivation is not None:
        manifest.update(domain_pack='lighting_camera_render_v1',official_case_derivation=official_case_derivation)
    (control/'run.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (control/'run.json').chmod(0o600)
    launcher = '''from pathlib import Path
import sys,json,argparse,hashlib
sys.dont_write_bytecode=True
import os as _os
from contextlib import nullcontext
sys.stdout.reconfigure(encoding='utf-8',errors='strict',newline='\\n')
sys.stdin.reconfigure(encoding='utf-8',errors='strict')
ROOT=Path(__file__).resolve().parent
SNAPSHOT=ROOT/'snapshot'
for item in json.loads((ROOT/'snapshot-manifest.json').read_text(encoding='utf-8'))['files']:
    path=SNAPSHOT/item['path']
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
        raise SystemExit('Construction runtime changed; controller rebuild required')
for package in ('dcc-task-runtime','houdini-bridge','nuke-bridge','vfx-pipeline'):
    sys.path.insert(0,str(SNAPSHOT/'packages'/package/'src'))
from vfx_pipeline.workbuddy_graph_mcp import GraphMCP
from vfx_pipeline.workbuddy_mcp import serve
from vfx_pipeline.workbuddy_assembly import prepared_graph_facade,SoftwareGraphResources
from vfx_pipeline.graph_handoff import response_contract,handoff_response,handoff_export
parser=argparse.ArgumentParser()
parser.add_argument('--backend',choices=('diagnostic','production','software'),default='diagnostic')
mode=parser.add_mutually_exclusive_group()
mode.add_argument('--export',action='store_true')
mode.add_argument('--handoff-contract',action='store_true')
mode.add_argument('--handoff-response',metavar='FILENAME')
parser.add_argument('--software-processes',action='store_true',help='controller-only software process boundary; never used by default')
parser.add_argument('--official-bindings',metavar='PATH')
parser.add_argument('--official-bindings-bytes',type=int)
parser.add_argument('--official-bindings-sha256')
parser.add_argument('--request-id');parser.add_argument('--actor')
parser.add_argument('--expected-bytes',type=int);parser.add_argument('--expected-sha256')
parser.add_argument('--confirm-complete',action='store_true')
args=parser.parse_args()
facade=None
try:
    backend='diagnostic' if args.export or args.handoff_contract or args.handoff_response else args.backend
    resources=SoftwareGraphResources(environment={
        'HOUDINI_BRIDGE_STATE_DIR':str(ROOT/'software-state/houdini'),
        'BRIDGE_SKILLS_STATE_ROOT':str(ROOT/'software-state/installation'),
        'BRIDGE_SKILLS_SCHEDULER_ROOT':str(Path(__SCHEDULER_ROOT__))}) if backend=='software' else None
    manifest_path=ROOT/'run.json'
    official_options=(args.official_bindings,args.official_bindings_bytes,args.official_bindings_sha256)
    if any(v is not None for v in official_options):
        if not all(v is not None for v in official_options) or backend!='production' or args.software_processes:
            raise ValueError('OFFICIAL_DERIVED_INPUT_PRODUCTION_BINDING_REQUIRED')
        from houdini_bridge.official_karma_inputs import resolve_manifest
        manifest_path=resolve_manifest(manifest_path,{'path':args.official_bindings,
            'bytes':args.official_bindings_bytes,'sha256':args.official_bindings_sha256})
    elif 'official_case_derivation' in json.loads(manifest_path.read_text(encoding='utf-8')):
        raise ValueError('OFFICIAL_DERIVED_INPUT_BINDING_REQUIRED')
    with resources if resources is not None else nullcontext():
        with prepared_graph_facade(manifest_path,repo_root=SNAPSHOT,
                scheduler_root=Path(__SCHEDULER_ROOT__),backend=backend,
                allow_software_processes=args.software_processes,software_resources=resources) as facade:
            if args.handoff_contract:
                result=response_contract(facade)
            elif args.handoff_response:
                result=handoff_response(facade,filename=args.handoff_response,request_id=args.request_id,actor=args.actor,
                    expected_bytes=args.expected_bytes,expected_sha256=args.expected_sha256,confirm_complete=args.confirm_complete)
                output=ROOT/('handoff-result-'+args.request_id+'.json')
                if output.is_symlink(): raise ValueError('handoff result cannot be a symlink')
                output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                result={**result,'result_file':str(output)}
            elif args.export:
                result=handoff_export(facade)
            else:
                serve(facade,adapter_class=GraphMCP)
                result=None
            if result is not None:
                print(json.dumps(result,ensure_ascii=False,indent=2))
except BaseException as exc:
    retained=backend=='software' and (getattr(exc,'resource_cleanup',None) or {}).get('retained') is True
    if not isinstance(exc,Exception) and not retained:
        raise
    try:
        print(json.dumps({'status':'error','error_type':type(exc).__name__,'message':str(exc),
            'close_summary':getattr(exc,'close_summary',None),'cleanup_issue':getattr(exc,'cleanup_issue',None),
            'cleanup_error_type':type(exc.cleanup_error).__name__ if hasattr(exc,'cleanup_error') else None,
            'resource_cleanup':getattr(exc,'resource_cleanup',None),
            'provider_identity_verified':False,'real_workbuddy_acceptance':False,
            'dcc_dispatched':False if facade is None or facade.jobs_service is None else None},ensure_ascii=False))
        if retained:
            sys.stdout.flush()
            sys.stderr.flush()
    finally:
        if retained:
            _os._exit(2)
    raise SystemExit(2)
'''.replace('__SCHEDULER_ROOT__', repr(str(scheduler_root)))
    (control/'server.py').write_text(launcher, encoding='utf-8')
    config={'mcpServers':{'bridge-hy3-graph':{'command':sys.executable,'args':['-I',str(control/'server.py')]}}}
    mcp_dir=destination/'project/.workbuddy'
    mcp_dir.mkdir(parents=True,exist_ok=True)
    (mcp_dir/'mcp.json').write_text(json.dumps(config,indent=2)+'\n', encoding='utf-8')
    prompt='''仅使用 bridge-hy3-graph 进行本轮自主建图。保持 HY3 与完全访问权限，不修改权限或沙箱。不得使用内置文件/终端、其他连接器、专家或子代理去直接修改宿主与测试程序。
先读取 health、catalog 和两张真实图片，分别提交你自己的观察。然后读取 graph_catalog，选择更适合现有目录表达的一张参考，说明准备保留的形状特征与无法表达的部分。
目标：建立一个可编辑的烟尘发射源基础网络，包含几何源和源属性准备，用目录内公开参数体现你选择的参考特征。本轮只验证建图与 HIP 保存重开，不运行仿真、缓存、渲染，不声称已经做出爆炸效果。
请自主提出节点、合法连接和输出，调用 graph_propose；成功后用返回的 graph_id 调用 graph_trial，再通过 graph_status 查询原 operation_id。每种提交使用独立稳定 request_id，重试必须沿用原 ID 和原内容。
若编译失败，根据诊断修正，最多两次；若执行状态未知或需核对，立即停止，不换 ID 新建作业。作业未完成时适当等待，不密集轮询。最后报告实际网络、参数选择理由、操作回执、保存重开结果与尚存差距。不自行宣布模型或发布验收通过。'''
    prompt += '''
参考分析交接：控制端会用 --handoff-contract 给出本轮 run_id、session_id、observation_record_ids 的模板。
请在两图观察后，按此模板返回一个完整 UTF-8 JSON 回复；analysis 按 reference analysis/1.0 结构填写 components、global_observations、confidence。
components 每项包含 component_id、label、roi、confidence、observations；observations 仅陈述你确实看到的结构/运动及不确定性。
不要添加 verified、授权、路径、回执或供应端身份字段。不要执行交接命令，不要为通过而补造观察。原始回复由用户交给控制端，人工介入会被记录。
这一步没有自动回复采集或真实 HY3 认证；无法生成完整结构时，明确报告阻塞，不声称已交接。'''
    (destination/'project/粘贴给HY3.txt').write_text(prompt+'\n', encoding='utf-8')
    instructions=f'''# WorkBuddy + HY3 自主建图

1. 在 WorkBuddy 新建普通 HY3 任务，选择项目目录 `{destination/'project'}`。
2. 保持用户选定的完全访问权限，不修改沙箱。启用本项目 `bridge-hy3-graph` MCP 配置；保留原诊断连接器的历史记录。
3. 发送“粘贴给HY3.txt”。本轮只使用新连接器。
4. 返回该任务回复及工具调用记录；Codex 核对本地作业和 HIP。

允许新建任务专属 Houdini 子进程、构建目录内网络、保存任务自有 HIP 并重开验证。没有仿真、仿真缓存、渲染或授权签发工具。120 秒试做预算；未知状态不得通过换 ID 重做。

这是开发构建快照，不是全域发布包；完全访问环境不构成隔离证明。真实模型身份与视觉效果分别验收。
'''
    instructions += f'''
## 原始回复的控制端交接（人工，不是自动 transport）

观察完成后，在控制端运行：
`python3 -I "{control/'server.py'}" --handoff-contract`
输出 ready=true 后，将 response_template 交给当前 HY3 会话，请它填写真实观察分析；不是要求模型自行运行控制命令。
把 HY3 的完整原始 JSON 回复以 UTF-8 保存到 `{control/'inbox'}/原始回复.json`，不要改写、提取片段或补全截断回复。
该 envelope 必须且只能包含 schema、route_id、selected_model、run_id、session_id、tool_call_id、observation_record_ids、analysis。
schema 固定为 bridge.workbuddy.reference_analysis_response/1.0；tool_call_id 是稳定的回复标识，不证明供应端实际工具调用。
analysis 需要 components、global_observations、confidence。模板中的空 components 不是合格分析，不要机械照抄。

用控制端自己的文件检查工具取得完整文件的字节数和 SHA256，然后运行（替换尖括号参数）：
`python3 -I "{control/'server.py'}" --handoff-response 原始回复.json --request-id handoff_001 --actor <操作者> --expected-bytes <字节数> --expected-sha256 <SHA256> --confirm-complete`

这些命令是正常控制端入口，不是 MCP 模型工具。相同 request-id 和原始内容可安全重放；解析失败后更正回复需要新的 request-id，原失败证据不会覆盖；已绑定成功的 run 不允许换回复冒充重放，须另建合法 run。
输出自动回收到 control/handoff-result-handoff_001.json；完整汇总使用 `python3 -I "{control/'server.py'}" --export`。
原始字节保存在控制端持久账本，结果含 capture、registration、analysis_submission 及 human_intervention=true。
未观察完、无回复、长度/摘要不匹配、非 UTF-8、截断 JSON、解析失败、错会话或素材会拒绝，不能靠摘要字段解锁。
--confirm-complete 是操作者对“完整复制”的声明，不是可独立验证的供应端 finish_reason；结构完整但语义已删节的回复仍须人工核对。
人工交回不等于自动采集、真实模型执行或 provider 身份认证。route_execution_verified=false、provider_identity_verified=false；不会因此解锁下游 DCC 执行。
未配置 collector 时保持未验证。WorkBuddy 继续使用用户选定的 HY3 与完全访问；这些协作约束不是隔离保证。
'''
    (destination/'操作说明.md').write_text(instructions, encoding='utf-8')
    files=[{'path':p.relative_to(snapshot).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(snapshot.rglob('*')) if p.is_file()]
    (control/'snapshot-manifest.json').write_text(json.dumps({'files':files},indent=2)+'\n', encoding='utf-8')
    files=[{'path':p.relative_to(destination).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(destination.rglob('*')) if p.is_file() and p.name!='bundle-manifest.json']
    (destination/'bundle-manifest.json').write_text(json.dumps({'schema':'bridge.workbuddy.construction_bundle/1.0','run_id':manifest['run_id'],'files':files,'release_acceptance':False},indent=2)+'\n', encoding='utf-8')
    return {**result,'mode':'construction_only','connector':'bridge-hy3-graph'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--media-config', type=Path)
    parser.add_argument('--production-config', type=Path)
    parser.add_argument('--construction-input-manifest', type=Path,
                        help='trusted controller input manifest from an existing JSON file')
    parser.add_argument('--execution-profile', action='store_true')
    parser.add_argument('--simulation-profile', action='store_true')
    parser.add_argument('--render-profile', action='store_true')
    parser.add_argument('--application', choices=('pipeline','nuke'), default='pipeline')
    args = parser.parse_args()
    config = validate_media_config(json.loads(args.media_config.read_text(encoding='utf-8'))) if args.media_config else None
    deployment=json.loads(args.production_config.read_text(encoding='utf-8')) if args.production_config else {}
    construction_inputs = json.loads(args.construction_input_manifest.read_text(encoding='utf-8')) if args.construction_input_manifest else None
    if args.construction_input_manifest and construction_inputs is None:
        raise ValueError('construction_input_manifest: JSON list required')
    print(json.dumps(prepare_graph(args.output, media_config=config,
        construction_input_manifest=construction_inputs,
        production_host_config=deployment.get('houdini'),production_nuke_config=deployment.get('nuke'),
        execution_profile=args.execution_profile,simulation_profile=args.simulation_profile,
        render_profile=args.render_profile,application=args.application),ensure_ascii=False,indent=2,default=str))
