"""Versioned native plans composed with the shared USD render capability.

This registry supplies data to the existing graph compiler and host transaction.
It neither constructs native nodes nor executes or manages operations.
"""
from __future__ import annotations

import copy
from . import native_pyro_domains as pyro
from . import native_vellum_domains as vellum
from . import native_crowd_hair_domains as crowd_hair
from . import native_render_domains as render
from . import native_flip_rbd_domains as flip_rbd
from . import native_particle_ocean_geometry_domains as particle_ocean_geometry

DOMAIN_IDS = (pyro.SMOKE, pyro.FIRE, vellum.CLOTH, vellum.SOFT_GRAINS,
              crowd_hair.CROWD, crowd_hair.HAIR, flip_rbd.FLIP, flip_rbd.RBD,
              *particle_ocean_geometry.DOMAIN_IDS)


def module_for(domain):
    if domain in (pyro.SMOKE, pyro.FIRE):
        return pyro
    if domain in (vellum.CLOTH, vellum.SOFT_GRAINS):
        return vellum
    if domain in (crowd_hair.CROWD, crowd_hair.HAIR):
        return crowd_hair
    if domain in flip_rbd.DOMAIN_IDS:
        return flip_rbd
    if domain in particle_ocean_geometry.DOMAIN_IDS:
        return particle_ocean_geometry
    raise ValueError('unregistered native domain: ' + str(domain))


def branches(domain):
    return ('softbody', 'grains') if domain == vellum.SOFT_GRAINS else ('cloth',) if domain == vellum.CLOTH else (None,)


def arguments(domain, version, branch=None):
    if domain == vellum.CLOTH:
        branch = 'cloth' if branch is None else branch
    if domain in (vellum.CLOTH, vellum.SOFT_GRAINS):
        # The combined public domain has two different native source contracts.
        # A caller must select one before any scene mutation can occur.
        vellum.control_contract(domain, version, branch)
        return (domain, version, branch)
    if branch is not None:
        raise ValueError('this native domain has no branch selector')
    return (domain, version)


def layout(domain, version, branch=None):
    module = module_for(domain)
    args = arguments(domain, version, branch)
    core = copy.deepcopy(module.node_requirements(*args))
    for node in core:
        parent = node.pop('context_parent_role', None)
        node['parent_role'] = parent or ('geometry_network' if node['category'] == 'sop' else None)
    shared = copy.deepcopy(render.node_requirements(render.LIGHTING, version))
    shared = [node for node in shared if node['role'] != 'source']
    # Pyro volume sampling controls retain their public render_settings role.
    for node in shared:
        if node['role'] == 'settings':
            node['role'] = 'render_settings'
        if node.get('input_role') == 'settings':
            node['input_role'] = 'render_settings'
    wires = copy.deepcopy(module.connection_requirements(*args))
    for wire in render.connection_requirements(render.LIGHTING, version):
        wire = dict(wire)
        for key in ('source_role', 'destination_role'):
            if wire[key] == 'settings':
                wire[key] = 'render_settings'
        wires.append(wire)
    return [shared[0], *core, *shared[1:]], wires


def overlay_host_pack(domain, pack, version, branch=None):
    module = module_for(domain)
    args = arguments(domain, version, branch)
    # Preserve the public controls, metrics, evidence and invalidation contract.
    result = module.overlay_host_pack(domain, pack, version, *args[2:])
    result['nodes'], result['connections'] = layout(domain, version, branch)
    result.update(native_domain_id=domain, native_branch=args[2] if len(args) == 3 else None,
                  shared_render_schema="bridge.native-render-domains/1", native_execution=False)
    return result


def overlay_core_pack_dict(pack, version, branch=None):
    domain = pack['id']
    module = module_for(domain)
    args = arguments(domain, version, branch)
    result = module.overlay_core_pack_dict(pack, version, *args[2:])
    nodes, wires = layout(domain, version, branch)
    result['nodes'] = []
    for node in nodes:
        node = dict(node)
        node['type_candidates'] = node.pop('types')
        node['required_parameter_aliases'] = node.pop('required_parms', [])
        result['nodes'].append(node)
    result.update(connections=wires, native_domain_id=domain, shared_render_schema="bridge.native-render-domains/1",
                  native_branch=args[2] if len(args) == 3 else None)
    return result
