"""Bounded data configuration and confirmed writes for a static Karma scene.

No Houdini imports or execution occur here. The trusted host must additionally
verify camera/light look-at orientation, apply Y-up/metre metadata, geometry
topology and material bindings. A write plan alone proves none of these facts.
Job duration, output budget and authorization remain the formal job guard's
responsibility; this configuration does not grant a 120-second execution budget.
JSON duplicate keys must be rejected by the caller before passing decoded data.
"""
from __future__ import annotations

import copy
import math

SCHEMA = "bridge.static-render-scene/1"
PROFILE = "sphere_ground_v1"
SUPPORTED_PROFILES = (PROFILE, "sphere_ground_v2", "official_karma_disklight_v1", "bounded_geometry_rig_v1")
SUPPORTED_VERSIONS = ("21.0.631", "22.0.459")
SOURCE_CONTRACT_SHA256 = "557c53f6fd6765894d82ccd8e467a56caee87be14a73e3debce36458ea8c648e"
MAX_FRAMES = 12
PARAMETER_PLAN_REVISION = 2
LEGACY_PARAMETER_PLAN_REVISION = 1


class NativeRenderSceneError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(code + ": " + detail)


def _invalid(detail):
    raise NativeRenderSceneError("INVALID_STATIC_RENDER_SCENE", detail)


def _bounded_tree(value):
    remaining = 512
    active = set()

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 8:
            _invalid("configuration exceeds its data/depth bound")
        if type(item) in (dict, list):
            identity = id(item)
            if identity in active:
                _invalid("cyclic configuration")
            active.add(identity)
            if type(item) is dict:
                for key, child in item.items():
                    if type(key) is not str or len(key) > 80:
                        _invalid("invalid field name")
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
            active.remove(identity)
        elif type(item) is str:
            if len(item) > 128 or any(ord(char) < 32 for char in item):
                _invalid("invalid text value")
        elif type(item) in (int, float):
            try:
                finite = math.isfinite(item)
            except OverflowError:
                finite = False
            if not finite:
                _invalid("non-finite numeric value")
        elif type(item) is not bool:
            _invalid("only JSON objects, arrays, strings, booleans and finite numbers are allowed")

    visit(value, 0)


def _fields(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        _invalid(label + " must contain exactly " + ", ".join(fields))


def _number(value, minimum, maximum, label, *, positive=False):
    if type(value) not in (int, float) or not minimum <= value <= maximum or (positive and value <= 0):
        _invalid(label + " is outside its numeric range")


def _vector(value, minimum, maximum, label, *, size=3):
    if type(value) is not list or len(value) != size:
        _invalid(label + " requires exactly " + str(size) + " components")
    for component in value:
        _number(component, minimum, maximum, label)


def validate_configuration(value, version=None):
    """Return a detached validated JSON configuration, without native side effects.

    The profile permits numeric scene edits within explicit data bounds. Render
    resolution stays at the agreed 128-square baseline; denoise, motion blur and
    simulation stay disabled. A job may request at most twelve distinct positive
    frames, and must still pass the separate formal execution resource guard.
    """
    if isinstance(value,dict) and value.get('schema') == 'bridge.geometry-render-scene/1':
        from .geometry_render_scene import validate_configuration as validate_geometry
        return validate_geometry(value, version)
    if isinstance(value,dict) and value.get('schema') == 'bridge.official-karma-scene/1':
        from .official_karma_scene import validate_configuration as validate_official
        return validate_official(value, version)
    _bounded_tree(value)
    _fields(value, ("schema", "profile", "supported_versions", "scene", "source_contract_sha256"), "configuration")
    if value["schema"] != SCHEMA or value["profile"] not in (PROFILE, "sphere_ground_v2"):
        _invalid("unsupported schema/profile")
    if value["supported_versions"] != list(SUPPORTED_VERSIONS):
        _invalid("supported_versions must match the frozen profile")
    if value["source_contract_sha256"] != SOURCE_CONTRACT_SHA256:
        _invalid("source contract digest mismatch")
    if version is not None and (type(version) is not str or version not in SUPPORTED_VERSIONS):
        raise NativeRenderSceneError("UNSUPPORTED_STATIC_RENDER_SCENE_VERSION", str(version))
    scene = value["scene"]
    _fields(scene, ("units", "up_axis", "sphere", "ground", "material", "camera", "light", "engine", "resolution", "frames", "denoise", "motion_blur", "simulation", "feedback_base_color"), "scene")
    if scene["units"] != "metres" or scene["up_axis"] != "Y" or scene["engine"] != "Karma CPU":
        _invalid("profile requires metres, Y-up and Karma CPU")
    for flag in ("denoise", "motion_blur", "simulation"):
        if scene[flag] is not False:
            _invalid(flag + " must be false")
    resolution = scene["resolution"]
    if type(resolution) is not list or len(resolution) != 2 or any(type(x) is not int for x in resolution) or resolution != [128, 128]:
        _invalid("resolution must be [128, 128] integers")
    frames = scene["frames"]
    if (type(frames) is not list or not 1 <= len(frames) <= MAX_FRAMES
            or any(type(frame) is not int or frame < 1 for frame in frames)
            or len(set(frames)) != len(frames)):
        _invalid("frames require one to twelve distinct positive integers")
    sphere = scene["sphere"]
    _fields(sphere, ("radius", "center"), "sphere")
    _number(sphere["radius"], 0, 1000000, "sphere.radius", positive=True)
    _vector(sphere["center"], -1000000, 1000000, "sphere.center")
    ground = scene["ground"]
    _fields(ground, ("plane", "y"), "ground")
    _number(ground["y"], 0, 0, "ground.y")
    if ground["plane"] != "XZ":
        _invalid("ground plane must be XZ")
    material = scene["material"]
    _fields(material, ("semantic_base_color", "semantic_roughness"), "material")
    _vector(material["semantic_base_color"], 0, 1, "material.semantic_base_color")
    _number(material["semantic_roughness"], 0, 1, "material.semantic_roughness")
    _vector(scene["feedback_base_color"], 0, 1, "feedback_base_color")
    for role in ("camera", "light"):
        node = scene[role]
        fields = ("position", "look_at", "focal_length_mm") if role == "camera" else ("usd_shape", "position", "look_at", "radius")
        _fields(node, fields, role)
        _vector(node["position"], -1000000, 1000000, role + ".position")
        _vector(node["look_at"], -1000000, 1000000, role + ".look_at")
        if node["position"] == node["look_at"]:
            _invalid(role + " position and look_at must differ")
    _number(scene["camera"]["focal_length_mm"], 1, 1000, "camera.focal_length_mm")
    _number(scene["light"]["radius"], 0, 1000000, "light.radius", positive=True)
    if scene["light"]["usd_shape"] != "UsdLuxDiskLight":
        _invalid("light must be UsdLuxDiskLight")
    return copy.deepcopy(value)


def parameter_plan(config, version, *, revision=PARAMETER_PLAN_REVISION):
    """Return only confirmed parameter writes, without paths or native scripts.

    Units/up-axis metadata, geometry merge and material assignment are required
    trusted host bindings, separate from this plan.
    Feedback color is retained as configuration and is not applied at initialize.
    Native parameter templates/menu tokens, writability and readback must still
    be checked on actual owned nodes before the host applies these writes.
    """
    if isinstance(config,dict) and config.get('profile') == 'bounded_geometry_rig_v1':
        from .geometry_render_scene import parameter_plan as geometry_plan
        return geometry_plan(config, version, revision=revision)
    if type(version) is not str or version not in SUPPORTED_VERSIONS:
        raise NativeRenderSceneError("UNSUPPORTED_STATIC_RENDER_SCENE_VERSION", str(version))
    if type(revision) is not int or revision not in {LEGACY_PARAMETER_PLAN_REVISION, PARAMETER_PLAN_REVISION}:
        _invalid("unsupported parameter plan revision")
    if isinstance(config,dict) and config.get("profile") == "official_karma_disklight_v1":
        _invalid("official case requires its sealed native reconstruction plan")
    scene = validate_configuration(config, version)["scene"]

    def write(role, parm, value, kind, phase="value"):
        if kind == "float":
            value = float(value)
        elif kind in {"vector3", "color3"}:
            value = tuple(float(component) for component in value)
        return {"role": role, "parm": parm, "value": value, "native_type": kind, "phase": phase}

    radius = scene["sphere"]["radius"]
    plan = [
        write("source", "rad", (radius, radius, radius), "vector3"),
        write("source", "scale", 1.0, "float"),
        write("source", "t", tuple(scene["sphere"]["center"]), "vector3"),
        write("ground", "orient", "zx", "menu", "gate"),
        write("ground", "t", (0, 0, 0), "vector3"),
        write("ground", "r", (0.0, 0.0, 0.0), "vector3"),
        write("camera", "t", tuple(scene["camera"]["position"]), "vector3"),
        write("camera", "focalLength", scene["camera"]["focal_length_mm"], "float"),
        write("light", "t", tuple(scene["light"]["position"]), "vector3"),
        write("light", "lighttype", "UsdLuxDiskLight", "menu", "gate"),
        write("light", "radius", scene["light"]["radius"], "float"),
        write("settings", "res_mode", "manual", "menu", "gate"),
        write("settings", "resolution", tuple(scene["resolution"]), "intvector2"),
        # The rendersettings LOP force-edits the same RenderSettings prim; its
        # own factory resolution (2048x1080, autoheight) would otherwise
        # override the karma settings values during stage composition.  Its
        # res_mode menu is script-generated and observes empty at runtime, so
        # the write is string-typed (type/gate/readback checks still apply).
        write("settings_binding", "res_mode", "manual", "string", "gate"),
        write("settings_binding", "resolution", tuple(scene["resolution"]), "intvector2"),
        # Native synchronous render requires the foreground toggle; its
        # factory state is off and no later stage enables it.  The writer
        # frame instruments the husk post-frame hook, which must start
        # disabled and empty (factory ships it enabled).
        write("render", "soho_foreground", 1, "toggle", "gate"),
        write("render", "husk_tpostframe", 0, "toggle", "gate"),
        write("settings", "engine", "cpu", "menu", "gate"),
        write("settings", "denoiser", "off", "menu", "gate"),
        write("settings", "enablemblur", 0, "toggle", "gate"),
        write("material", "base_color", tuple(scene["material"]["semantic_base_color"]), "color3"),
        write("material", "specular_roughness", scene["material"]["semantic_roughness"], "float"),
        write("normal_map", "scale", 0.0, "float"),
        write("normal_map", "in", (0.5, 0.5, 1.0), "vector3"),
        write("displacement", "scale", 0.0, "float"),
        write("displacement", "displacement", 0.0, "float"),
    ]
    if config["profile"] == "sphere_ground_v2":
        plan.append(write("settings", "beauty", 1, "toggle", "gate"))
    for role in ("camera", "light"):
        plan.extend([
            write(role, "lookatenable", 1, "toggle", "gate"),
            write(role, "lookatprim", "", "string"),
            write(role, "lookatposition", tuple(scene[role]["look_at"]), "vector3"),
            write(role, "upvecmethod", "yaxis", "menu"),
            write(role, "twist", 0.0, "float"),
        ])
    if revision == LEGACY_PARAMETER_PLAN_REVISION:
        added = {("settings_binding", "res_mode"), ("settings_binding", "resolution"),
                 ("render", "soho_foreground"), ("render", "husk_tpostframe")}
        plan = [write for write in plan if (write["role"], write["parm"]) not in added]
    return plan
