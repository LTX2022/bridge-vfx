"""Approved S01/S02 programs; pure validation and deterministic goal sampling.

Native endpoints: installed H21.0.631/H22.0.429 popsteerseek goal vector/3,
popforce amp float/1. No simulation or successful host observations are created.
"""
from __future__ import annotations
from .native_459_basis import PREPARATION_VERSIONS
import copy
import hashlib
import json
import math

SCHEMA = 'bridge.swarm-basis/1'
CHANNEL_SCHEMA = 'bridge.swarm-goal-channels/1'
NOISE_FIELDS = {'swirlsize':1, 'swirlscale':3, 'pulselength':1, 'rough':1,
                'atten':1, 'turb':1, 'offset':4}
VERSIONS = ('21.0.631', '22.0.429')
# Both same-build public bindgeo string defaults and their internal consumers.
GEOMETRY_NAME = 'Geometry'

class SwarmControlError(ValueError):
    def __init__(self,code,detail):
        self.code=code
        super().__init__(code+': '+detail)

def fail(code,detail): raise SwarmControlError(code,detail)
def number(x):
    try:return type(x) in (float,int) and math.isfinite(x)
    except OverflowError:return False
def vector(x,n): return isinstance(x,(list,tuple)) and len(x)==n and all(number(v) for v in x)
def digest(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def near(a,b):
    if number(a) and number(b): return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-11)
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
        return len(a)==len(b) and all(near(x,y) for x,y in zip(a,b))
    return type(a) is type(b) and a==b

def validate_input(value):
    """The caller supplies task context; defaults never stand in for missing basis."""
    if not isinstance(value,dict) or set(value)!={'schema','space','goal_base','seed','time_origin','time_range','noise_context'}:
        fail('SWARM_FROZEN_BASIS_REQUIRED','explicit complete swarm_basis required')
    if value['schema']!=SCHEMA or value['space']!='simulation_geometry' or not vector(value['goal_base'],3):
        fail('SWARM_FROZEN_BASIS_REQUIRED','goal must be in actual simulation Geometry P space')
    if type(value['seed']) is not int or not 0<=value['seed']<=2147483647:
        fail('SWARM_FROZEN_BASIS_REQUIRED','stable task seed must be a bounded integer')
    if not number(value['time_origin']) or not vector(value['time_range'],2):
        fail('SWARM_FROZEN_BASIS_REQUIRED','finite scene seconds required')
    lo,hi=value['time_range']; origin=value['time_origin']
    if not lo<hi or not all(number(t-origin) and abs(t-origin)<=1e6 for t in (lo,hi)) or hi-lo>120:
        fail('SWARM_TIME_BUDGET_REQUIRED','bounded scene-time interval <=120 seconds required')
    noise=value['noise_context']
    if not isinstance(noise,dict) or set(noise)!=set(NOISE_FIELDS):
        fail('SWARM_NOISE_CONTEXT_REQUIRED','exact native noise baseline required; no seed alias')
    for n,size in NOISE_FIELDS.items():
        if not (number(noise[n]) if size==1 else vector(noise[n],size)):
            fail('SWARM_NOISE_CONTEXT_REQUIRED',n)
    if (noise['swirlsize']<=0 or noise['pulselength']<=0 or any(v<=0 for v in noise['swirlscale'])
            or type(noise['turb']) is not int or not 0<=noise['turb']<=32 or not 0<=noise['rough']<=1 or not 0<=noise['atten']<=1):
        fail('SWARM_NOISE_CONTEXT_REQUIRED','invalid or unbounded noise baseline')
    return copy.deepcopy(value)

def basis(observations,version):
    observed=observations.get(('seek','@swarm_basis'),{})
    frozen=observed.get('basis',{})
    if observed.get('origin')!='runtime_hom' or observed.get('task_owned') is not True or version not in (*VERSIONS, *PREPARATION_VERSIONS):
        fail('SWARM_FROZEN_BASIS_REQUIRED','owned host collector required')
    if frozen.get('native_version')!=version or frozen.get('schema')!=SCHEMA:
        fail('SWARM_FROZEN_BASIS_REQUIRED','same-build frozen basis required')
    body={k:v for k,v in frozen.items() if k!='content_sha256'}
    if digest(body)!=frozen.get('content_sha256'):
        fail('SWARM_BASIS_DRIFT','basis hash differs')
    validate_input(frozen.get('input'))
    if not number(frozen.get('fps')) or frozen['fps']<=0 or not number(frozen.get('solver_timescale')) or frozen['solver_timescale']<=0:
        fail('SWARM_TIME_CONTEXT_REQUIRED','actual FPS/solver time scale required')
    if observed.get('fps')!=frozen['fps'] or observed.get('solver_timescale')!=frozen['solver_timescale']:
        fail('SWARM_TIME_CONTEXT_REQUIRED','time context changed')
    if observed.get('noise_context')!=frozen['input']['noise_context']:
        fail('SWARM_NOISE_CONTEXT_CHANGED','frequency, roughness or offset drifted')
    bindings=observed.get('geometry_bindings',{})
    if (frozen.get('geometry_name')!=GEOMETRY_NAME or set(bindings)!={'seek','noise_force'}
            or bindings!=frozen.get('geometry_bindings')):
        fail('SWARM_GEOMETRY_BINDING_CHANGED','actual Geometry bindings differ from the registered baseline')
    for role,fact in bindings.items():
        if (fact.get('origin')!='runtime_hom' or fact.get('type')!='string' or fact.get('size')!=1
                or fact.get('value')!=GEOMETRY_NAME or fact.get('unexpanded')!=GEOMETRY_NAME
                or fact.get('expression') is not None or fact.get('reference_path') is not None
                or fact.get('keyframe_identities')!=[]):
            fail('SWARM_GEOMETRY_BINDING_CHANGED',role+'/bindgeo is not the fixed undriven Geometry target')
    if observed.get('binding')!=frozen.get('binding') or not observed.get('binding',{}).get('task_id'):
        fail('SWARM_BASIS_DRIFT','basis is not bound to this task and node')
    return frozen

def schedule(frozen,radius):
    if not number(radius) or not 0<=radius<=100: fail('INVALID_NATIVE_CONTROL_VALUE','target_noise')
    data=frozen['input'];origin=data['time_origin'];lo,hi=data['time_range']
    first=math.floor(lo-origin);last=math.ceil(hi-origin)
    if last-first>122: fail('SWARM_TIME_BUDGET_REQUIRED','too many shared goal samples')
    result=[]
    for k in range(first,last+1):
        if radius==0:
            point=list(data['goal_base'])
        else:
            u=[]
            for component in range(3):
                b=hashlib.sha256(('bridge.S01/1:%d:%d:%d'%(data['seed'],k,component)).encode()).digest()
                u.append((int.from_bytes(b[:8],'big')>>11)/float(1<<53))
            r=radius*u[0]**(1/3);z=2*u[1]-1;phi=2*math.pi*u[2];plane=math.sqrt(max(0.,1-z*z))
            offset=(r*plane*math.cos(phi),r*plane*math.sin(phi),r*z)
            point=[a+b for a,b in zip(data['goal_base'],offset)]
        if not vector(point,3): fail('SWARM_GOAL_OVERFLOW','goal sample is not finite')
        result.append({'time':origin+k,'value':point})
    return result

def interpolate(keys,time):
    if not number(time): fail('SWARM_TIME_CONTEXT_REQUIRED','nonfinite evaluation time')
    if time<=keys[0]['time']: return keys[0]['value'][:]
    if time>=keys[-1]['time']: return keys[-1]['value'][:]
    for a,b in zip(keys,keys[1:]):
        if a['time']<=time<=b['time']:
            w=(time-a['time'])/(b['time']-a['time'])
            return [x*(1-w)+y*w for x,y in zip(a['value'],b['value'])]
    fail('SWARM_GOAL_READBACK_MISMATCH','missing interpolation interval')

def channel_value(observations,version):
    frozen=basis(observations,version)
    obs=observations.get(('seek','@swarm_channels'),{})
    if obs.get('origin')!='runtime_hom' or obs.get('binding')!=frozen['binding'] or not number(obs.get('time')):
        fail('SWARM_OWNED_CHANNEL_REQUIRED','actual goal channel collector required')
    if not frozen['input']['time_range'][0]<=obs['time']<=frozen['input']['time_range'][1]:
        fail('SWARM_TIME_BUDGET_REQUIRED','current scene time is outside the explicitly frozen interval')
    channels=obs.get('channels',[]);reg=obs.get('registration')
    if len(channels)!=3: fail('SWARM_OWNED_CHANNEL_REQUIRED','goal vector/3 required')
    if reg is None:
        if any(c.get('keys') or c.get('expression') or c.get('reference_path') for c in channels):
            fail('SWARM_FOREIGN_CHANNEL','unregistered goal animation')
        if not near(obs.get('value'),frozen['input']['goal_base']): fail('SWARM_BASIS_DRIFT','undriven goal changed')
        return 0.
    if (reg.get('schema')!=CHANNEL_SCHEMA or reg.get('basis_sha256')!=frozen['content_sha256']
            or reg.get('binding')!=frozen['binding'] or reg.get('content_sha256')!=digest({k:v for k,v in reg.items() if k!='content_sha256'})):
        fail('SWARM_OWNED_CHANNEL_REQUIRED','registration binding/hash differs')
    radius=reg.get('radius');expected=schedule(frozen,radius)
    identities=[]
    for axis,c in enumerate(channels):
        if c.get('reference_path') or c.get('pre')!='constant' or c.get('post')!='constant':
            fail('SWARM_FOREIGN_CHANNEL','reference or extrapolation changed')
        if radius==0:
            if c.get('keys') or c.get('expression'): fail('SWARM_FOREIGN_CHANNEL','zero radius has foreign animation')
        else:
            if c.get('expression') not in (None,'linear()'): fail('SWARM_FOREIGN_CHANNEL','foreign expression')
            keys=c.get('keys',[])
            if len(keys)!=len(expected): fail('SWARM_FOREIGN_CHANNEL','missing or extra keys')
            for key,target in zip(keys,expected):
                if not near(key.get('time'),target['time']) or not near(key.get('value'),target['value'][axis]) or key.get('expression')!='linear()' or key.get('language')!='Hscript':
                    fail('SWARM_FOREIGN_CHANNEL','key content/ordering differs')
        identities.append(c.get('identities'))
    if identities!=reg.get('keyframe_identities'): fail('SWARM_FOREIGN_CHANNEL','complete key identity changed')
    sample_times=[k['time'] for k in expected]+[(a['time']+b['time'])/2 for a,b in zip(expected,expected[1:])]
    samples=obs.get('samples',[])
    if len(samples)!=len(sample_times): fail('SWARM_GOAL_READBACK_MISMATCH','incomplete native time samples')
    for sample,time in zip(samples,sample_times):
        if sample.get('time')!=time or not near(sample.get('value'),interpolate(expected,time)):
            fail('SWARM_GOAL_READBACK_MISMATCH','native sampled goal differs')
    if not near(obs.get('value'),interpolate(expected,obs['time'])):
        fail('SWARM_GOAL_READBACK_MISMATCH','current goal differs')
    return float(radius)

def validate(w,observations,after=False):
    frozen=basis(observations,w['native_version'])
    if frozen!=w['swarm_basis']: fail('SWARM_BASIS_DRIFT','frozen transaction basis changed')
    actual=channel_value(observations,w['native_version'])
    if after and not near(actual,w['public_value']): fail('SWARM_GOAL_READBACK_MISMATCH','applied radius differs')
    if not after and observations[('seek','@swarm_channels')]!=w['swarm_before']:
        fail('SWARM_FOREIGN_CHANNEL','channel changed since preparation')
