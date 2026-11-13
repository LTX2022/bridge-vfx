"""Swarm HOM collectors/writer using the existing add-on transaction helpers.

This module owns no feedback state machine, lease, persistence or operation receipt.
"""
from __future__ import annotations
import copy
import json
from . import native_swarm_controls as program

BASIS_KEY='bridge_swarm_basis_v1'
CHANNEL_KEY='bridge_swarm_goal_channels_v1'

class Host:
    def __init__(self,host):
        import hou
        self.h=host;self.hou=hou
    def call(self,name,*args,**kwargs): return self.h[name](*args,**kwargs)
    def error(self,code,message): raise self.h['BridgeCommandError'](code,message)
    def build_preflight(self,roles,pack):
        """Read only, including the no-plan/no-candidate rebuild path."""
        solver=self.hou.node(roles.get('solver',''))
        if solver is not None:
            wires=[c for c in solver.inputConnections() if c.inputIndex()==1]
            if wires:
                expected=self.hou.node(roles.get('noise_force',''))
                if (len(wires)!=1 or expected is None or wires[0].inputNode()!=expected
                        or wires[0].outputIndex()!=0):
                    self.error('SWARM_PRESOLVE_CONFLICT','refusing to replace an existing PreSolve branch')
                self.call('_fx_planned_owned_root',roles,pack)
        self.geometry_bindings(roles,allow_missing_nodes=True)

    def geometry_bindings(self,roles,allow_missing_nodes=False):
        """Observe actual same-build public string fields before evaluation."""
        result={}
        for role in ('seek','noise_force'):
            node=self.hou.node(roles.get(role,''))
            if node is None and allow_missing_nodes:continue
            try:
                if node is None:raise ValueError('required node is absent')
                actual=self.call('_fx_planned_observation',node,'bindgeo',observe_value=False)
                if (actual['type']!='string' or actual['size']!=1 or actual['driven']
                        or any(actual[k] for k in ('locked','disabled','hidden'))):
                    raise ValueError('bindgeo must be an undriven available string/1')
                parm=node.parm('bindgeo')
                driver=self.call('_component_driver_identity',parm)
                keys=[self.call('_keyframe_identity',key) for key in parm.keyframes()]
                raw=parm.unexpandedString();value=parm.eval()
                if (driver['expression'] is not None or driver['reference_path'] is not None or keys
                        or raw!=program.GEOMETRY_NAME or value!=program.GEOMETRY_NAME):
                    raise ValueError('bindgeo differs from literal Geometry or carries a driver')
                result[role]={'origin':'runtime_hom','path':parm.path(),'type':'string','size':1,
                    'value':value,'unexpanded':raw,**driver,'keyframe_identities':keys}
            except Exception as exc:
                self.error('SWARM_GEOMETRY_BINDING_CHANGED',role+'/bindgeo: '+str(exc))
        return result

    def binding(self,roles,pack):
        root=self.call('_fx_planned_owned_root',roles,pack)
        lease=self.call('_root_lease_check',root,scope='sop',renew=False)
        identity=self.call('_host_identity')
        if (identity.get('task_id')!=lease['task_id'] or not identity.get('launch_nonce')
                or not identity.get('pid') or identity.get('version')!=self.hou.applicationVersionString()):
            self.error('SWARM_OWNED_CHANNEL_REQUIRED','authenticated current task host required')
        return {'task_id':lease['task_id'],'task_root':root,'seek_path':roles['seek'],
                'noise_path':roles['noise_force'],'native_version':self.hou.applicationVersionString()}
    def noise(self,roles):
        node=self.hou.node(roles['noise_force']);result={}
        if node.inputConnections():
            self.error('SWARM_NOISE_SCOPE_DRIFT','independent noise must not reexecute the source chain')
        for name,size in program.NOISE_FIELDS.items():
            actual=self.call('_fx_planned_observation',node,name)
            if (actual['type']!=('integer' if name=='turb' else 'float') or actual['size']!=size
                    or actual['driven'] or actual['locked'] or actual['disabled'] or actual['hidden']):
                self.error('SWARM_NOISE_CONTEXT_REQUIRED','actual undriven noise context required: '+name)
            result[name]=list(actual['value']) if size>1 else actual['value']
        return result
    def time_context(self,roles):
        actual=self.call('_fx_planned_observation',self.hou.node(roles['solver']),'timescale')
        if actual['type']!='float' or actual['size']!=1 or actual['driven']:
            self.error('SWARM_TIME_CONTEXT_REQUIRED','actual undriven solver time scale required')
        return self.hou.fps(),actual['value']
    def initialize(self,params,roles,pack,fresh_roles):
        geometry=self.geometry_bindings(roles)
        supplied=self.call('_fx_configuration',params).get('swarm_basis')
        seek=self.hou.node(roles['seek']);raw=seek.userData(BASIS_KEY)
        if supplied is None:
            if raw: return self.basis(roles,pack)
            return {'status':'blocked','code':'SWARM_FROZEN_BASIS_REQUIRED'}
        data=program.validate_input(supplied)
        if raw:
            actual=self.basis(roles,pack)
            if actual['basis']['input']!=data:self.error('SWARM_BASIS_DRIFT','rebuild cannot replace the frozen basis')
            return actual
        if not {'seek','noise_force'}<=set(fresh_roles):
            self.error('SWARM_FROZEN_BASIS_REQUIRED','initial basis registration requires fresh owned roles')
        actual=self.call('_fx_planned_observation',seek,'goal')
        if actual['driven'] or actual['type']!='float' or actual['size']!=3 or not program.near(actual['value'],data['goal_base']):
            self.error('SWARM_BASIS_DRIFT','provided baseline must match actual undriven goal')
        if self.noise(roles)!=data['noise_context']:
            self.error('SWARM_NOISE_CONTEXT_CHANGED','provided noise baseline must match actual public parameters')
        fps,scale=self.time_context(roles)
        frozen={'schema':program.SCHEMA,'native_version':self.hou.applicationVersionString(),
                'binding':self.binding(roles,pack),'input':data,'fps':fps,'solver_timescale':scale,
                'geometry_name':program.GEOMETRY_NAME,'geometry_bindings':geometry}
        frozen['content_sha256']=program.digest(frozen)
        seek.setUserData(BASIS_KEY,json.dumps(frozen,sort_keys=True))
        result=self.basis(roles,pack);program.basis({('seek','@swarm_basis'):result},self.hou.applicationVersionString())
        return result
    def basis(self,roles,pack):
        seek=self.hou.node(roles['seek']);raw=seek.userData(BASIS_KEY)
        if raw is None:self.error('SWARM_FROZEN_BASIS_REQUIRED','explicit frozen task basis is missing')
        fps,scale=self.time_context(roles)
        result={'origin':'runtime_hom','task_owned':True,'binding':self.binding(roles,pack),
                'basis':json.loads(raw),'fps':fps,'solver_timescale':scale,'noise_context':self.noise(roles),
                'geometry_bindings':self.geometry_bindings(roles)}
        try:program.basis({('seek','@swarm_basis'):result},self.hou.applicationVersionString())
        except program.SwarmControlError as exc:self.error(exc.code,str(exc))
        return result
    def channels(self,roles,pack):
        node=self.hou.node(roles['seek']);target=self.call('_resolve_parm_target',node,['goal'])
        actual=self.call('_fx_planned_observation',node,'goal')
        if actual['type']!='float' or actual['size']!=3 or any(actual[n] for n in ('locked','disabled','hidden')):
            self.error('SWARM_OWNED_CHANNEL_REQUIRED','writable actual goal vector/3 required')
        raw=node.userData(CHANNEL_KEY);reg=json.loads(raw) if raw else None
        result={'origin':'runtime_hom','binding':self.binding(roles,pack),'time':self.hou.time(),
                'value':list(target.eval()),'registration':reg,'channels':[],'samples':[]}
        for p in target._components():
            keys=list(p.keyframes());normalized=[]
            for key in keys:
                normalized.append({'time':key.time(),'value':key.value(),'expression':key.expression(),
                    'language':str(key.expressionLanguage()).rsplit('.',1)[-1]})
            result['channels'].append({**self.call('_component_driver_identity',p),'keys':normalized,
                'identities':[self.call('_keyframe_identity',k) for k in keys],
                'pre':str(p.keyframeExtrapolation(True)).rsplit('.',1)[-1].lower(),
                'post':str(p.keyframeExtrapolation(False)).rsplit('.',1)[-1].lower()})
        if reg is not None:
            basis=self.basis(roles,pack)
            frozen=program.basis({('seek','@swarm_basis'):basis},self.hou.applicationVersionString())
            keys=program.schedule(frozen,reg.get('radius'))
            times=[k['time'] for k in keys]+[(a['time']+b['time'])/2 for a,b in zip(keys,keys[1:])]
            frame=self.hou.frame()
            try:
                for t in times:
                    result['samples'].append({'time':t,'value':[p.evalAtTime(t) for p in target._components()]})
            finally:
                if self.hou.frame()!=frame:self.hou.setFrame(frame)
        return result
    def prepare(self,item):
        item['snapshot']=self.call('_snapshot_parm_state',item['parm'],capture_extrapolation=True)
        item['swarm_snapshot']={'registration':item['node'].userData(CHANNEL_KEY)}
    def restore(self,item):
        value=item['swarm_snapshot']['registration'];node=item['node']
        if value is None:node.destroyUserData(CHANNEL_KEY)
        else:node.setUserData(CHANNEL_KEY,value)
        if node.userData(CHANNEL_KEY)!=value or (CHANNEL_KEY in node.userDataDict())!=(value is not None):
            self.error('PARAMETER_RESTORE_MISMATCH','Swarm channel registration restoration differs')
    def write(self,item,roles,pack):
        w=item['native_write']
        observations=self.call('_fx_planned_observations',{'target_noise':w['public_value']},roles,pack,[w])
        self.call('_fx_planned_module',pack)[0].validate_control_write_plan([w],observations)
        components=item['parm']._components();keys=program.schedule(w['swarm_basis'],w['public_value'])
        for axis,parm in enumerate(components):
            parm.deleteAllKeyframes()
            if w['public_value']==0:
                parm.set(w['swarm_basis']['input']['goal_base'][axis],follow_parm_reference=False)
            else:
                native=[]
                for sample in keys:
                    key=self.hou.Keyframe();key.setTime(sample['time']);key.setValue(sample['value'][axis])
                    key.setExpression('linear()',self.hou.exprLanguage.Hscript);native.append(key)
                parm.setKeyframes(native)
            for before in (True,False):parm.setKeyframeExtrapolation(before,self.hou.parmExtrapolate.Constant)
        reg={'schema':program.CHANNEL_SCHEMA,'basis_sha256':w['swarm_basis']['content_sha256'],
             'binding':w['swarm_basis']['binding'],'radius':w['public_value'],
             'keyframe_identities':[[self.call('_keyframe_identity',k) for k in p.keyframes()] for p in components]}
        reg['content_sha256']=program.digest(reg)
        item['node'].setUserData(CHANNEL_KEY,json.dumps(reg,sort_keys=True))
        observations=self.call('_fx_planned_observations',{'target_noise':w['public_value']},roles,pack,[w])
        self.call('_fx_planned_module',pack)[0].validate_applied_readback([w],observations)
        return {'parameter':'goal','parameter_path':item['parm'].path(),'requested':w['public_value'],
            'after':w['public_value'],'readback_verified':True,
            'native_channel_readback':observations['seek','@swarm_channels']}
    def readback(self,roles,pack,normalized):
        changes={n:v for n,v in normalized.items() if n in ('target_noise','noise_strength')}
        obs=self.call('_fx_planned_observations',changes,roles,pack)
        actual=self.call('_fx_planned_domain_readback','swarm_flocking_v1',changes,roles,pack)
        result={'frame':self.hou.frame(),'time':self.hou.time(),'native_execution_claim':False,
                'basis':obs.get(('seek','@swarm_basis')),'controls':actual}
        if 'target_noise' in changes:result['goal_channels']=obs['seek','@swarm_channels']
        if 'noise_strength' in changes:
            node=self.hou.node(roles['noise_force']);solver=self.hou.node(roles['solver'])
            if node.inputConnections():self.error('SWARM_NOISE_SCOPE_DRIFT','independent noise must not reexecute the source chain')
            result['noise_force']={'amp':self.call('_fx_planned_observation',node,'amp'),
                'connection':obs.get(('solver','@input/1')),'noise_context':self.noise(roles),
                'solver_gates':{n:self.call('_fx_planned_observation',solver,n) for n in ('externalforce','integratevel','integratepos')},
                'force_integration':'not_run: graph/parameter evidence only; no simulation result asserted'}
        return result
