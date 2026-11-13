"""几何常规入口的公开输入指引；保留历史生产内核与接收证明原字节。"""
from __future__ import annotations
from dcc_task_runtime.execution_lock import execution_lock
from .geometry_session import GeometrySession
from .workbuddy_graph_mcp import _schema_error


class EntryGuidanceError(ValueError):
    """只携带由公开目录生成的有限指引，不暴露底层异常原文。"""
    def __init__(self, code, **details):
        super().__init__(code)
        self.public = {'code':code, **details, 'native_dispatch_attempted':False}


def required_assets(preparation, revision):
    """首版与执行准备器登记的全部输入相同；反馈版使用当前正式全图及局部图。"""
    if revision == 0:
        return sorted(preparation['media'])
    if revision >= 1:
        return [f'preview_{revision}', f'local_{revision}']
    return []


def observation_requirements(preparation, state):
    """统一目录和提案预检的素材身份，保留实际送达/观察的原核心检查。"""
    identifiers = required_assets(preparation, state['revision'])
    observed = {identifier:[] for identifier in identifiers}
    for key, item in state['observations'].items():
        asset = state['assets'].get(item['asset_id'])
        if item['asset_id'] in observed and asset and item['file'] == asset['file']:
            observed[item['asset_id']].append(key)
    return {'base_revision':state['revision'], 'required_asset_ids':identifiers,
            'accepted_observation_ids_by_asset':observed,
            'missing_observation_asset_ids':[key for key in identifiers if not observed[key]],
            'instruction':'Use bridge_media with each required asset_id, actually view its image, then bridge_observe with your own description. Include the returned observation IDs in bridge_propose. Result files keys are not media asset IDs.'}


def editable_nodes(state):
    """只公布当前模型已有可编辑节点与合法参数名，不生成任何参数答案。"""
    graph = state.get('current_model_graph') or {}
    allowed = {'h21.sop.geometry_box':['sizex','sizey','sizez','tx','ty','tz'],
               'h21.sop.geometry_transform':['tx','ty','tz','sx','sy','sz']}
    return [{'node_id':node['node_id'],'parameter_names':allowed[node['node_type']]}
            for node in graph.get('nodes',[]) if node['node_type'] in allowed]


def schema_advice(arguments, schema):
    """按工具自带schema返回有限字段位置；不回显未知键名或任意输入值。"""
    if not isinstance(arguments,dict):
        return {'missing_required_fields':list(schema.get('required',[])),
                'diagnostics':[{'field':'$','code':'OBJECT_REQUIRED'}],
                'hint':'Supply a JSON object matching this tool inputSchema.'}
    missing = [key for key in schema.get('required',[]) if key not in arguments]
    diagnostics = [{'field':'$.'+key,'code':'REQUIRED'} for key in missing]
    for key, sub in schema.get('properties',{}).items():
        if key in arguments and _schema_error(arguments[key],sub):
            diagnostics.append({'field':'$.'+key,'code':'SCHEMA_MISMATCH'})
    if set(arguments) - set(schema.get('properties',{})):
        diagnostics.append({'field':'$','code':'UNEXPECTED_FIELDS'})
    return {'missing_required_fields':missing, 'diagnostics':diagnostics[:12],
            'hint':'Read this tool inputSchema. For bridge_propose supply goal, rationale and observation_ids, plus model_graph for the first version or edits [{node_id, parms}] for feedback. Get media and observation IDs from bridge_catalog.'}


def validate_edit_inputs(state, edits):
    """用实际模型公开字段检查编辑结构；纯检查，不生成结果或改写版本。"""
    nodes = editable_nodes(state);by_id = {node['node_id']:node for node in nodes}
    if not isinstance(edits,list) or not edits:
        raise EntryGuidanceError('GEOMETRY_FEEDBACK_EDITS_REQUIRED',editable_nodes=nodes,
            hint='Use edits [{node_id, parms}] with exact node_id values from editable_nodes.')
    for edit in edits:
        if (not isinstance(edit,dict) or set(edit)!={'node_id','parms'} or edit.get('node_id') not in by_id
                or not isinstance(edit.get('parms'),dict) or not edit['parms']
                or set(edit['parms'])-set(by_id[edit['node_id']]['parameter_names'])):
            raise EntryGuidanceError('GEOMETRY_EDIT_NODE_REQUIRED',editable_nodes=nodes,
                hint='Every edit contains only node_id and parms. Use the exact editable_nodes node_id and its parameter_names; values are your own proposal.')


class GeometryEntrySession(GeometrySession):
    """只扩展常规入口的可用性；执行、账本、版本和接收仍由原内核负责。"""
    def _feedback(self):
        from .geometry_feedback import FeedbackSession
        return FeedbackSession(self)

    def _extended(self):
        return super()._read()['revision'] == 2 or self._feedback().path.is_file()

    def catalog(self):
        value = self._feedback().catalog() if self._extended() else super().catalog()
        state = self._feedback()._read() if self._extended() else super()._read()
        value['observation_requirements'] = observation_requirements(self.prep,state)
        value['editable_nodes'] = editable_nodes(state)
        if 'goal_contract' in self.prep:
            value['goal_contract'] = dict(self.prep['goal_contract'])
        value['proposal_requirements'] = {
            'required_fields':['project_id','request_id','base_revision','goal','rationale','observation_ids'],
            'model_input':'model_graph' if state['revision']==0 else 'edits',
            'edits_fields':['node_id','parms'],
            'instruction':'Use exact node_id values from editable_nodes, not qualified connection references. Every edit uses parms; keep camera, lighting, material and render rig unchanged.'}
        for asset in value['assets']:
            asset['required_for_current_proposal'] = asset['asset_id'] in value['observation_requirements']['required_asset_ids']
        return value

    def media(self, asset_id):
        if self._extended():
            return self._feedback().media(asset_id)
        if asset_id not in self._read()['assets']:
            raise EntryGuidanceError('GEOMETRY_REGISTERED_MEDIA_REQUIRED',
                valid_asset_ids=sorted(self._read()['assets']),
                hint='Use an asset_id from bridge_catalog.assets or observation_requirements; files.preview is not an asset_id.')
        return super().media(asset_id)

    def observe(self,asset_id,request_id,observation):
        if self._extended():
            return self._feedback().observe(asset_id,request_id,observation)
        return super().observe(asset_id,request_id,observation)

    def execute(self,plan_id,request_id):
        if self._extended() and plan_id in self._feedback()._read()['plans']:
            return self._feedback().execute(plan_id,request_id)
        return super().execute(plan_id,request_id)

    def query(self,operation_id,**kwargs):
        if self._extended() and operation_id in self._feedback()._read()['jobs']:
            return self._feedback().query(operation_id)
        return super().query(operation_id,**kwargs)

    def tasks(self):
        return super().tasks()+(self._feedback().tasks() if self._extended() else [])

    def cancel(self,operation_id):
        if self._extended() and operation_id in self._feedback()._read()['jobs']:
            return self._feedback().cancel(operation_id)
        return super().cancel(operation_id)

    def propose(self,request_id,base_revision,goal,rationale,observation_ids,model_graph=None,edits=None):
        if self._extended() and base_revision>=2:
            return self._feedback().propose(request_id,base_revision,goal,rationale,observation_ids,model_graph,edits)
        # 与原核心同锁；回放和冲突先交原实现，不能因阶段推进改变既有请求语义。
        with execution_lock(self.root,'geometry-session'):
            state = self._read()
            if request_id in state['plans'] or base_revision != state['revision']:
                return super().propose(request_id,base_revision,goal,rationale,observation_ids,model_graph,edits)
            requirements = observation_requirements(self.prep,state)
            observed = set()
            for identifier in observation_ids:
                item = state['observations'].get(identifier)
                asset = state['assets'].get(item['asset_id']) if item else None
                if item and asset and item['file']==asset['file']:
                    observed.add(item['asset_id'])
            missing = [key for key in requirements['required_asset_ids'] if key not in observed]
            if missing:
                raise EntryGuidanceError('GEOMETRY_REQUIRED_VIEWS_MISSING',
                    missing_asset_ids=missing, observation_requirements=requirements,
                    hint='View each missing asset with bridge_media and submit bridge_observe; include all required observation IDs in the proposal.')
            if base_revision == 1:
                validate_edit_inputs(state,edits)
            return super().propose(request_id,base_revision,goal,rationale,observation_ids,model_graph,edits)
