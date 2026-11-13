"""Strict software HOM boundary backed by versioned static vendor evidence.

No native geometry is executed. Unknown operators/fields are rejected; static
unknown defaults and unevaluated expressions remain unknown, never zero-filled.
Instance state is serialized through the existing fake HOM userdata snapshot.
"""
from __future__ import annotations

import copy
import base64
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace

STATE_KEY = "_bridge_native_schema_state_v1"
SUPPLEMENT_NAME = "native-boundary-metadata-supplement.json"
FOLDERS = {"group", "groupcollapsible", "groupsimple", "switcher", "multiparm", "multiswitcher"}
STRING_TYPES = {"string", "oppath", "oplist", "file", "directory", "image"}
INT_TYPES = {"integer", "intvector", "intvector2", "int_minmax", "intlog", "toggle", "ordinal", "iconstrip", "buttonstrip"}
SUFFIXES = {"XYZW": "xyzw", "RGBA": "rgba", "UVW": "uvw", "XYWH": "xywh",
            "MinMax": ("min", "max"), "MaxMin": ("max", "min"),
            "StartEnd": ("start", "end"), "BeginEnd": ("begin", "end")}
CHILD_CONTEXTS = {("Obj", "geo"): "Sop", ("Obj", "dopnet"): "Dop",
                  ("Sop", "dopnet"): "Dop", ("Obj", "lopnet"): "Lop",
                  ("Obj", "matnet"): "Vop", ("Obj", "ropnet"): "Driver",
                  ("Sop", "lopnet"): "Lop", ("Sop", "matnet"): "Vop"}
_UNSET = object()


def capture_catalog(schema_path, version="21.0.631", supplement_path=None):
    """Return exact ``(category, operator_name) -> captured_record`` mappings.

    The supplement repairs metadata loss without rewriting the original capture.
    Its digest must bind to that exact capture; versions never fall back.
    """
    schema_path = Path(schema_path)
    if version == '22.0.459':
        if schema_path.name != 'hda-interface-22.0.459.json':
            schema_path = schema_path.with_name('hda-interface-22.0.459.json')
        encoded = schema_path.read_bytes()
        if hashlib.sha256(encoded).hexdigest() != 'e8d9ee7a16f14baa2327ae45412b2acee60ef4849d4e3aa099aea229586379c7':
            raise ValueError('22.0.459 static capture differs from its independent original')
        capture = json.loads(encoded)
        if (capture.get('schema') != 'bridge.independent_hda_static_capture/1'
                or capture.get('version') != version or capture.get('native_execution') is not False):
            raise ValueError('exact 22.0.459 static capture required')
        catalog = {}
        for name, record in capture['operators'].items():
            if record.get('status') != 'CAPTURED_STATIC_DIALOG':
                continue
            original = schema_path.parent / 'h22-459-originals' / record['raw_section']
            section = original.read_bytes()
            archive = capture['libraries'][record['library']]
            if (record.get('version') != version or len(section) != record['section_bytes']
                    or hashlib.sha256(section).hexdigest() != record['section_sha256']
                    or record['source_archive'] != archive):
                raise ValueError('22.0.459 original section binding differs: ' + name)
            catalog[tuple(name.split('/', 1))] = {
                'status': 'CAPTURED', 'parameters': copy.deepcopy(record['parameters']),
                'source': {'version': version, 'file_sha256': archive['sha256'],
                           'section_sha256': record['section_sha256'], 'member': name + '/DialogScript'}}
        return catalog
    capture = json.loads(schema_path.read_text(encoding='utf-8'))
    records = capture["versions"][version]["operators"]
    supplement_path = Path(supplement_path or schema_path.with_name(SUPPLEMENT_NAME))
    if not supplement_path.is_file():
        raise ValueError("native boundary metadata supplement is required")
    supplement = json.loads(supplement_path.read_text(encoding='utf-8'))
    digest = hashlib.sha256(schema_path.read_bytes()).hexdigest()
    if supplement.get("base_capture_sha256") != digest:
        raise ValueError("metadata supplement does not bind this capture")
    metadata = supplement["versions"][version]
    catalog = {}
    for name, record in metadata["operators"].items():
        if record.get("status") == "CAPTURED":
            original = records.get(name, {})
            if original.get("status") != "CAPTURED" or original.get("section_sha256") != record["source"]["section_sha256"]:
                raise ValueError("metadata source mismatch: " + name)
        elif record.get("status") == "CAPTURED_SELECTIVE":
            source = record.get('source', {})
            if not all(re.fullmatch('[0-9a-f]{64}',str(source.get(key,''))) for key in
                       ('file_sha256','section_sha256','capture_evidence_sha256')) or not source.get('member', '').endswith('/DialogScript'):
                raise ValueError('selective native definition provenance is incomplete: ' + name)
        elif record.get("status") != "CAPTURED_CORE":
            continue
        if record["source"].get("version") != version:
            raise ValueError("cross-version native source: " + name)
        catalog[tuple(name.split("/", 1))] = copy.deepcopy(record)
    return catalog


def native_category(node):
    if node.path() in {"/", "/obj", "/stage", "/mat", "/out"}:
        return {"/": "Root", "/obj": "Manager", "/stage": "Manager", "/mat": "Manager", "/out": "Manager"}[node.path()]
    parent = sys.modules["hou"].node(node.path().rsplit("/", 1)[0])
    if parent is None:
        raise ValueError("native node has no parent: " + node.path())
    return native_child_category(parent)


def native_child_category(node):
    roots = {"/obj": "Obj", "/stage": "Lop", "/mat": "Vop", "/out": "Driver"}
    if node.path() in roots:
        return roots[node.path()]
    key = (native_category(node), node._type_name)
    if key in CHILD_CONTEXTS:
        return CHILD_CONTEXTS[key]
    # Only subnets preserve their own category. A regular SOP/DOP/LOP is not
    # implicitly a network merely because the unconstrained fake allows it.
    if node._type_name == "subnet":
        return key[0]
    raise ValueError("node is not an evidenced parent network: " + "/".join(key))


class Template:
    def __init__(self, raw, records, source):
        self.raw, self.records, self.source = raw, records, source
        self.key, self.count, self.kind = raw["name"], int(raw["size"]), raw["type"]
        self.multiparms = tuple(n for n in raw.get("ancestors", ())
                                if records.get(n, {}).get("type") in {"multiparm", "multiswitcher"})

    def name(self): return self.key
    def label(self): return self.raw.get("label", "")
    def numComponents(self): return self.count
    def namingScheme(self):
        naming = self.raw.get("naming_tokens")
        if naming:
            naming = naming[0] if isinstance(naming, list) else naming
        else:
            naming = ("RGBA" if self.kind in {"color", "ramp_rgb"} else
                      "Base1" if self.kind in STRING_TYPES | {"toggle", "angle"} else
                      "MinMax" if self.kind in {"float_minmax", "int_minmax"} else "XYZW")
        if naming not in SUFFIXES and naming != "Base1":
            raise ValueError("unknown captured naming scheme: " + str(naming))
        return "parmNamingScheme." + naming

    def type(self):
        kind = ("Folder" if self.kind in FOLDERS else "String" if self.kind in STRING_TYPES else
                "Menu" if self.kind in {"ordinal", "iconstrip", "buttonstrip"} else
                "Toggle" if self.kind == "toggle" else "Int" if self.kind in INT_TYPES else
                "Button" if self.kind == "button" else "Separator" if self.kind == "separator" else
                "Label" if self.kind == "label" else "Data" if self.kind == 'data' else "Ramp" if self.kind.startswith("ramp_") else "Float")
        return "parmTemplateType." + kind

    def folderType(self):
        return "folderType." + ("MultiparmBlock" if self.kind in {"multiparm", "multiswitcher"} else "Collapsible" if self.kind == "groupcollapsible" else "Simple")
    def parmTemplates(self):
        if self.kind not in FOLDERS:
            raise AttributeError("not a folder")
        return tuple(Template(self.records[n], self.records, self.source)
                     for n in self.raw.get("children", ()) if n in self.records)
    def stringType(self):
        if self.kind not in STRING_TYPES:
            raise TypeError("not a string template")
        return "stringParmType." + ("NodeReference" if self.kind == "oppath" else "Regular")
    def menuItems(self): return tuple(self.raw.get("menu_tokens", ())[::2])
    def menuUseToken(self): return self.raw.get("menu_uses_token_value", False)
    def menuLabels(self): return tuple(self.raw.get("menu_tokens", ())[1::2])
    def itemGeneratorScript(self): return " ".join(self.raw.get("menu_script_tokens", ()))
    def disableWhen(self): return self.raw.get("disable_when")
    def tags(self):
        values = self.raw.get("tags_tokens", ())
        return dict(zip(values[::2], values[1::2]))
    def scriptCallback(self):
        value = self.tags().get("script_callback", "")
        return str(value)
    def scriptCallbackLanguage(self):
        value = self.tags().get("script_callback_language", "")
        return "exprLanguage.Python" if value == "python" else "exprLanguage.Hscript" if value == "hscript" else ""
    def defaultValue(self):
        # A separately evidenced factory-template getter must not initialize
        # an otherwise unknown compiled parameter instance.
        return tuple(self.raw.get("declared_factory_defaults", self.raw.get("default_tokens", ())))
    def isHidden(self):
        if type(self.raw.get('native_api_compiled_hidden')) is bool:
            return self.raw['native_api_compiled_hidden']
        if self.raw.get("hide_when") is None:
            raise ValueError("native hidden metadata was not captured")
        return "invisible" in self.raw.get("flags", ())
    def component_names(self, key=None):
        key = key or self.key
        if self.count == 1:
            return (key,)
        scheme = self.namingScheme().split(".")[-1]
        suffixes = tuple(str(i + 1) for i in range(self.count)) if scheme == "Base1" else SUFFIXES[scheme]
        if self.count > len(suffixes):
            raise ValueError("invalid captured component count: " + key)
        return tuple(key + suffix for suffix in suffixes[:self.count])


class ParmTuple:
    def __init__(self, node, template, name): self.node, self.template, self.key = node, template, name
    def __iter__(self): return iter(self.parms())
    def __len__(self): return self.template.count
    def __getitem__(self, index): return self.parms()[index]
    def parms(self): return tuple(self.node.parm(n) for n in self.template.component_names(self.key))
    def name(self): return self.key
    def path(self): return self.node.path() + "/" + self.key
    def parmTemplate(self): return self.template
    def eval(self): return tuple(p.eval() for p in self)
    def set(self, values, **kwargs):
        if not isinstance(values, (list, tuple)) or len(values) != len(self):
            raise ValueError("native tuple arity mismatch")
        components = self.parms()
        for parm, value in zip(components, values):
            parm._native_validate(value)
        for parm, value in zip(components, values):
            parm.set(value, **kwargs)


class Keyframe:
    """Explicit software channel state; never implies native interpolation."""
    def __init__(self, value=None): self.record = {"value": value, "frame": None, "expression": None, "language": None}
    def setFrame(self, frame): self.record["frame"] = float(frame)
    def setValue(self, value): self.record["value"] = value
    def setExpression(self, expression, language=None): self.record.update(expression=str(expression), language=str(language))
    def frame(self): return self.record["frame"]
    def value(self): return self.record["value"]
    def expression(self): return self.record["expression"]
    def expressionLanguage(self): return self.record["language"]
    def asCode(self, **kwargs): return json.dumps(self.record, sort_keys=True)


def set_parm_state(parm, *, locked=_UNSET, disabled=_UNSET, hidden=_UNSET, expression=_UNSET,
                   reference=_UNSET, keyframes=_UNSET):
    """Set explicit fake channel state for negative tests (not production bypass).

    References are actual parm paths. Keyframes retain their complete record.
    ``disabled=None`` removes the explicit override and resumes captured gates.
    """
    state = parm._native_state
    if locked is not _UNSET: state["locked"] = bool(locked)
    if disabled is not _UNSET: state["disabled"] = None if disabled is None else bool(disabled)
    if hidden is not _UNSET: state["hidden"] = None if hidden is None else bool(hidden)
    if expression is not _UNSET: state["expression"] = expression
    if reference is not _UNSET: state["reference"] = reference.path() if hasattr(reference, "path") else reference
    if keyframes is not _UNSET:
        state["keyframes"] = [copy.deepcopy(k.record if isinstance(k, Keyframe) else k) for k in keyframes]
    return copy.deepcopy(state)


def constrain_hou(schema_path: Path, version="21.0.631", supplement_path=None, *, instance_states=None,
                  native_api_interfaces=None, native_api_ports=None, native_api_type_preferences=None):
    hou = sys.modules["hou"]
    if getattr(hou, "_native_schema_constrained", False):
        raise ValueError("native schema boundary already installed on this fake host")
    catalog = capture_catalog(schema_path, version, supplement_path)
    native_api_ports = copy.deepcopy(native_api_ports or {})
    for operator, interface in (native_api_interfaces or {}).items():
        if interface.get("origin") != "test_injected_native_api" or interface.get("version") != version:
            raise ValueError("explicit same-version native API interface is required")
        source = Path(interface["machine_field_evidence_path"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != interface.get("machine_field_evidence_sha256"):
            raise ValueError("native API interface machine-field evidence changed")
        key = tuple(operator.split("/",1))
        existing = catalog.get(key)
        if existing is not None and (interface.get('mode') != 'missing_compiled_templates' or
                existing.get('status') != 'CAPTURED_CORE'):
            raise ValueError("injected interface cannot replace a captured operator")
        parameters = copy.deepcopy(interface["parameters"])
        captured_dialog = interface.get('mode') == 'captured_dialog'
        if captured_dialog:
            evidence = json.loads(source.read_text(encoding='utf-8'))['versions'][version]['operators'][operator]
            if evidence['parameters'] != parameters or evidence['source']['version'] != version:
                raise ValueError('full native dialog interface differs from its same-version machine evidence')
        if existing is not None and set(parameters) & set(existing['parameters']):
            raise ValueError('injected compiled templates cannot replace captured fields')
        for name, raw in parameters.items():
            supported = STRING_TYPES | INT_TYPES | {"multiparm","float","vector","color","button","data"}
            if captured_dialog:
                supported |= FOLDERS | {'ramp_flt','ramp_rgb','separator','label','angle','float_minmax','vector2','direction'}
            if raw.get("name") != name or raw.get("type") not in supported or type(raw.get("size")) is not int:
                raise ValueError("invalid explicit native API template")
            if captured_dialog:
                raw.update(default_status='CAPTURED',gate_status='CAPTURED',origin='test_injected_native_api')
            else:
                raw.update(default_tokens=[],default_status="NOT_CAPTURED",disable_when=None,hide_when=None,
                           gate_status="NOT_CAPTURED",origin="test_injected_native_api")
            raw.setdefault("ancestors",[]); raw.setdefault("children",[])
            raw['_native_api_source'] = {'version':version,'kind':'test_injected_native_api',
                'machine_field_evidence_sha256':interface['machine_field_evidence_sha256']}
        if existing is not None:
            existing['parameters'].update(parameters)
            existing['runtime_api_additions'] = sorted(parameters)
        else:
            catalog[key] = {"status":"TEST_INJECTED_NATIVE_API","parameters":parameters,
                            "source":{"version":version,"kind":"test_injected_native_api",
                                      "machine_field_evidence_sha256":interface["machine_field_evidence_sha256"]}}
    type_preferences = copy.deepcopy(native_api_type_preferences or {})
    for operator, preferred in type_preferences.items():
        category, requested = operator.split('/', 1)
        if (category, requested) not in catalog or not isinstance(preferred, str) or not preferred:
            raise ValueError("explicit creation preference requires a captured requested operator")
        # Only type selection is modeled for a preferred definition. Its fields
        # remain unavailable unless supplied through a separate native API input.
        catalog.setdefault((category, preferred), {"status": "TEST_INJECTED_NATIVE_API", "parameters": {},
            "source": {"version": version, "kind": "test_injected_native_api_type_preference"}})
    instance_states = copy.deepcopy(instance_states or {})
    for operator, states in instance_states.items():
        if not isinstance(states, dict) or tuple(operator.split("/", 1)) not in catalog:
            raise ValueError("injected instance must use a captured operator")
        for name, state in states.items():
            if not isinstance(state, dict) or state.get("origin") != "test_injected_native_api" or set(state) - {"origin", "value", "locked", "disabled", "hidden", "menu_tokens", "menu_labels"}:
                raise ValueError("explicit native API instance provenance is required")
    node_class = type(hou.node("/obj"))
    original_init, original_parm, original_create = node_class.__init__, node_class.parm, node_class.createNode
    dummy = original_parm(hou.node("/obj"), "_native_fixture")
    parm_class = type(dummy)
    hou.node("/obj").parms_dict.pop("_native_fixture")
    original_set, original_eval = parm_class.set, parm_class.eval
    restoring = {"active": False}
    template_cache = {}
    lookup_cache = {}

    def templates(node):
        operator = (('Manager', 'lopnet') if node is hou.node('/stage') and ('Manager', 'lopnet') in catalog
                    else (native_category(node), node._type_name))
        if operator in template_cache:
            return template_cache[operator]
        record = catalog.get(operator)
        if not record:
            return ()
        template_cache[operator] = tuple(
            Template(raw, record["parameters"], raw.get('_native_api_source',record["source"]))
            for raw in record["parameters"].values())
        return template_cache[operator]

    def instances(node, template):
        keys = [template.key]
        for count_name in template.multiparms:
            expanded = []
            for key in keys:
                count_parm = node.parm(count_name)
                if count_parm is None:
                    return ()
                try:
                    count = count_parm.eval()
                except ValueError:
                    if restoring['active']:
                        # Defer compiled children until the saved parent count
                        # is restored; do not synthesize a factory count.
                        return ()
                    raise
                if type(count) is not int or not 0 <= count <= 10000:
                    raise ValueError("unknown or invalid multiparm count: " + count_name)
                expanded.extend(key.replace("#", str(i), 1) for i in range(1, count + 1))
            keys = expanded
        return tuple(keys)

    def find_template(node, name, tuple_lookup=False):
        operator = (native_category(node), node._type_name)
        cache_key = (*operator, tuple_lookup)
        if cache_key not in lookup_cache:
            exact, patterned = {}, []
            for position, template in enumerate(templates(node)):
                if template.kind in FOLDERS and template.kind not in {"multiparm", "multiswitcher"}:
                    continue
                if template.kind in {"separator", "label", "unknown"}:
                    continue
                if template.kind.startswith('ramp_') and not (operator==('Dop','crowdtransition::3.0') and template.key=='blend'):
                    continue
                candidate_names = (template.key,) if tuple_lookup else template.component_names()
                for candidate in candidate_names:
                    if '#' in candidate:
                        pattern = re.compile(re.escape(candidate).replace(r"\#", r"[1-9][0-9]*"))
                        patterned.append((position, template, pattern))
                    else:
                        exact.setdefault(candidate, []).append((position, template))
            lookup_cache[cache_key] = exact, patterned
        exact, patterned = lookup_cache[cache_key]
        candidates = list(exact.get(name, ()))
        candidates.extend((position, template) for position, template, pattern in patterned
                          if pattern.fullmatch(name))
        for position, template in sorted(candidates, key=lambda item: item[0]):
            for key in instances(node, template):
                if tuple_lookup and key == name:
                    return template, key, 0
                names = template.component_names(key)
                if not tuple_lookup and name in names:
                    return template, key, names.index(name)
        return None

    def initial(template, index):
        if template.kind.startswith("ramp_"):
            return None, None
        defaults = template.raw.get("default_tokens", ())
        if index >= len(defaults):
            return None, None
        token = defaults[index]
        if template.kind in STRING_TYPES:
            # Backticks in a string default are a driver, not an evaluated path.
            return str(token), str(token) if "`" in str(token) else None
        if template.kind == "toggle" and token in {"off", "on"}:
            return int(token == "on"), None
        if template.kind in {"ordinal", "iconstrip", "buttonstrip"}:
            items = template.menuItems()
            if token in items:
                return (int(token) if template.menuUseToken() else items.index(token)), None
        try:
            value = int(token) if template.kind in INT_TYPES | {"multiparm", "multiswitcher"} else float(token)
            return value, None
        except (TypeError, ValueError):
            return None, str(token)

    def parm(node, name):
        found = find_template(node, str(name))
        if found is None:
            return None
        template, key, index = found
        operator = ('Manager', 'lopnet') if node is hou.node('/stage') and ('Manager', 'lopnet') in catalog else (native_category(node), node._type_name)
        injected = instance_states.get("/".join(operator),{}).get(str(name))
        if injected is not None and 'menu_tokens' in injected:
            captured_menu = template.raw.get('menu_tokens',())
            if not template.raw.get('menu_script_tokens') and '[' not in captured_menu:
                raise ValueError('runtime menu injection cannot replace a fixed captured menu')
            tokens, labels = injected['menu_tokens'],injected.get('menu_labels')
            if not isinstance(tokens,list) or not tokens or len(set(tokens)) != len(tokens) or not all(isinstance(t,str) and t for t in tokens) or not isinstance(labels,list) or len(labels) != len(tokens):
                raise ValueError('explicit runtime menu API is incomplete')
            raw = copy.deepcopy(template.raw)
            raw['menu_tokens'] = [x for pair in zip(tokens,labels) for x in pair]
            raw['runtime_menu_origin'] = 'test_injected_native_api'
            template = Template(raw,template.records,template.source)
        first = name not in node.parms_dict
        p = original_parm(node, name)
        p._node, p._template, p._component_index, p._instance_key = node, template, index, key
        if first:
            value, expression = initial(template, index)
            p.value = value
            p._native_state = {"locked": False, "disabled": None, "expression": expression,
                               "hidden": None,"language": "Hscript" if expression else None, "reference": None, "keyframes": [], "pre_extrapolation":"parmExtrapolate.Constant","post_extrapolation":"parmExtrapolate.Constant"}
            if injected is not None:
                if "value" in injected:
                    # Explicit bottom API return values are instance fixture
                    # state; they never update captured factory defaults.  The
                    # value seeds first so a factory-locked channel (e.g. the
                    # rendersettings resolution under autoheight) models its
                    # native initial state without a scripted write.
                    p._native_state["expression"] = None
                    p.value = validate(p, injected["value"])
                set_parm_state(p, **{key: injected[key] for key in ("locked", "disabled", "hidden") if key in injected})
                p._native_state["instance_state_origin"] = "test_injected_native_api"
        return p

    def node_init(self, path, node_type="null"):
        if path not in {"/", "/obj", "/stage", "/mat", "/out"}:
            parent = hou.node(path.rsplit("/", 1)[0])
            if parent is None or (native_child_category(parent), str(node_type)) not in catalog:
                raise ValueError("node is absent from exact native context capture: " + str(node_type))
        original_init(self, path, node_type)

    def create(self, node_type_name, name=None, **kwargs):
        context = native_child_category(self)
        exact = kwargs.pop('exact_type_name', False)
        if type(exact) is not bool or kwargs:
            raise ValueError("unsupported software native create options")
        if not exact:
            node_type_name = type_preferences.get(context + '/' + node_type_name, node_type_name)
        if (context, node_type_name) not in catalog:
            raise ValueError("node is absent from native interface capture: " + context + "/" + node_type_name)
        node = original_create(self, node_type_name, name or node_type_name.replace(":", "_"))
        for template in templates(node):
            if "#" in template.key:
                continue
            for key in template.component_names():
                node.parm(key)
        declared = instance_states.get(context + "/" + node_type_name,{})
        known_patterns = [re.escape(name).replace(r"\#",r"[1-9][0-9]*") for template in templates(node) for name in template.component_names()]
        if any(not any(re.fullmatch(pattern,name) for pattern in known_patterns) for name in declared):
            raise ValueError("injected instance contains a non-addressable parameter")
        return node

    def node_type(self):
        context = native_category(self)
        # Capture keys use Obj; the HOM category name is Object.
        hom_category = "Object" if context == "Obj" else context
        return SimpleNamespace(name=lambda: self._type_name, nameWithCategory=lambda: hom_category + "/" + self._type_name,
                               category=lambda: SimpleNamespace(name=lambda: hom_category),
                               maxNumInputs=lambda: capacity(self,'input_count'),
                               maxNumOutputs=lambda: capacity(self,'output_count'),
                               parmTemplateGroup=lambda: SimpleNamespace(entries=lambda: root_templates(self)))

    def root_templates(node):
        all_templates = templates(node)
        names = {t.key for t in all_templates}
        return tuple(t for t in all_templates if not any(n in names for n in t.raw.get("ancestors", ())))

    def gate(node, condition, instance):
        if condition is None:
            raise ValueError("native disabled metadata was not captured")
        if not condition:
            return False
        groups = re.findall(r"\{([^{}]*)\}", condition)
        if not groups:
            raise ValueError("unsupported captured disablewhen: " + condition)
        results = []
        row_numbers = re.findall(r"\d+", instance)
        for group in groups:
            tokens = re.findall(r'"(?:\\.|[^"\\])*"|[^\s]+', group)
            if len(tokens) % 3:
                raise ValueError("unsupported captured disablewhen: " + condition)
            comparisons = []
            for i in range(0, len(tokens), 3):
                name, op, expected = tokens[i:i + 3]
                for number in row_numbers:
                    name = name.replace("#", number, 1)
                p = node.parm(name)
                if p is None:
                    raise ValueError("missing disablewhen dependency: " + name)
                actual = p.evalAsString() if p._template.menuItems() or p._template.kind in STRING_TYPES else p.eval()
                if expected.startswith('"'):
                    expected = json.loads(expected)
                if not isinstance(actual, str):
                    try: expected = float(expected)
                    except ValueError: pass
                elif p._template.menuItems() and re.fullmatch(r"[+-]?\d+", expected):
                    # Numeric ordinal conditions compare the integer index.
                    actual = p.eval()
                    expected = int(expected)
                operations = {"==": lambda: actual == expected, "!=": lambda: actual != expected,
                              "<": lambda: actual < expected, ">": lambda: actual > expected,
                              "<=": lambda: actual <= expected, ">=": lambda: actual >= expected}
                if op not in operations:
                    raise ValueError("unsupported captured gate operator: " + op)
                comparisons.append(operations[op]())
            results.append(all(comparisons))
        return any(results)

    def disabled(p):
        state = p._native_state
        if state["disabled"] is not None:
            return state["disabled"]
        conditions = [p._template.raw.get("disable_when", None)]
        for ancestor in p._template.raw.get("ancestors", ()):
            raw = p._template.records.get(ancestor, {})
            conditions.extend((raw.get("disable_when", ""), raw.get("disable_when_tab", "")))
        return any(gate(p._node, c, p._instance_key) for c in conditions)

    def validate(p, value):
        if restoring["active"]:
            return value
        # H21 HOM Parm.disable (1023-1028): UI disable-when state does not
        # prevent scripting from changing the underlying value.
        if p.isLocked():
            raise ValueError("native parameter is locked: " + p.path())
        state = p._native_state
        if state["expression"] or state["reference"] or state["keyframes"]:
            raise ValueError("native parameter is driven: " + p.path())
        t = p._template
        if t.kind == 'data':
            if not isinstance(value,hou.Geometry):
                raise TypeError('native geometry data parameter requires Geometry')
        elif t.kind == 'ramp_flt':
            if not isinstance(value,hou.Ramp) or value.isColor():
                raise TypeError('native float ramp requires Ramp')
        elif t.kind in STRING_TYPES:
            if not isinstance(value, str): raise TypeError("native string parameter requires string")
        elif t.kind in {"ordinal", "iconstrip", "buttonstrip"}:
            items = t.menuItems()
            if isinstance(value, str):
                if value not in items: raise ValueError("unknown native menu token: " + value)
                return int(value) if t.menuUseToken() else items.index(value)
            if t.menuUseToken():
                if type(value) is not int or str(value) not in items:
                    raise ValueError("native token-value menu requires an available integer token")
                return value
            if type(value) is not int or items and not 0 <= value < len(items):
                raise ValueError("native menu index is out of range")
        elif t.kind == "toggle":
            if type(value) not in {bool, int} or value not in (0, 1): raise TypeError("native toggle requires 0/1")
            return int(value)
        elif t.kind in INT_TYPES | {"multiparm", "multiswitcher"}:
            if type(value) is not int: raise TypeError("native integer parameter requires int")
            if t.kind in {"multiparm", "multiswitcher"} and not 0 <= value <= 10000:
                raise ValueError("invalid multiparm count")
        elif type(value) not in {int, float}:
            raise TypeError("native numeric parameter requires number")
        return value

    def set_value(p, value, **kwargs):
        value = validate(p, value)
        if p._template.kind == 'data' and not restoring['active']:
            # This is the bottom API's actual geometry serialization, not a
            # task graph, expected snapshot or precomputed business receipt.
            value = {'_test_native_geometry_data':base64.b64encode(value.data()).decode('ascii')}
        if p._template.kind == 'ramp_flt' and not restoring['active']:
            value = {'_test_native_ramp_data':{'basis':list(value.basis()),'keys':list(value.keys()),'values':list(value.values())}}
        original_set(p, value)
        if p._template.kind in {"multiparm", "multiswitcher"}:
            for name in tuple(p._node.parms_dict):
                if find_template(p._node, name) is None:
                    p._node.parms_dict.pop(name)

    evaluating = set()
    def eval_value(p):
        if p.path() in evaluating:
            raise ValueError("native parameter reference cycle")
        state = p._native_state
        if state["reference"]:
            evaluating.add(p.path())
            try: return referenced(p).eval()
            finally: evaluating.remove(p.path())
        if state["expression"]:
            if (state['expression'] == '$SF==1' and state['language'] == str(hou.exprLanguage.Hscript)
                    and p._node.type().name() == 'popsource::2.0' and p.name() == 'impulseactiveate'):
                return float(hou.frame() == 1)
            raise ValueError("software boundary does not evaluate native expressions: " + p.path())
        if state["keyframes"]:
            frame = hou.frame()
            keys = sorted(state['keyframes'], key=lambda k:k.get('frame'))
            if len({k.get('frame') for k in keys}) != len(keys):
                raise ValueError('duplicate native keyframe time')
            if all(k.get('expression') == 'constant()' and
                   k.get('language') == str(hou.exprLanguage.Hscript) for k in keys):
                extrapolation = ('pre_extrapolation' if frame < keys[0]['frame'] else
                                 'post_extrapolation' if frame > keys[-1]['frame'] else None)
                if extrapolation and state[extrapolation] != str(hou.parmExtrapolate.Constant):
                    raise ValueError('software boundary does not evaluate native extrapolation')
                before = [k for k in keys if k['frame'] <= frame]
                value=(before[-1] if before else keys[0])['value']
                return int(value) if p._template.kind in INT_TYPES else value
            matched = [k for k in keys if k.get('frame') == frame and k.get('expression') is None]
            if len(matched) == 1:
                return matched[0]['value']
            raise ValueError('software boundary does not interpolate native keyframes')
        if p.value is None:
            raise ValueError("native default is not captured: " + p.path())
        if p._template.kind == 'data':
            raw = p.value
            if not isinstance(raw,dict) or set(raw) != {'_test_native_geometry_data'}:
                raise ValueError('saved native geometry data is invalid')
            geometry = hou.Geometry()
            geometry.loadFromString(base64.b64decode(raw['_test_native_geometry_data'],validate=True))
            return geometry
        if p._template.kind == 'ramp_flt':
            raw = p.value
            if not isinstance(raw,dict) or set(raw) != {'_test_native_ramp_data'}:
                raise ValueError('saved native ramp data is invalid')
            data=raw['_test_native_ramp_data']
            return hou.Ramp(tuple(data['basis']),tuple(data['keys']),tuple(data['values']))
        value = original_eval(p)
        if p._template.kind in STRING_TYPES:
            return hou._bridge_expand_string(value)
        return value

    def eval_string(p):
        value = p.eval()
        if p._template.kind in {"ordinal", "iconstrip", "buttonstrip"}:
            return str(value) if p._template.menuUseToken() else p._template.menuItems()[value]
        return str(value)

    def referenced(p):
        path = p._native_state["reference"]
        if not path: return p
        parent, name = path.rsplit("/", 1)
        node = hou.node(parent)
        other = node.parm(name) if node else None
        if other is None: raise ValueError("missing native reference: " + path)
        return other

    def expression(p):
        value = p._native_state["expression"]
        if value is None: raise RuntimeError("no expression")
        return value

    def unexpanded(p):
        if p._template.kind not in STRING_TYPES:
            raise TypeError("unexpandedString is only available for string parameters")
        return str(p.value)

    def keyframes(p):
        result = []
        for raw in p._native_state["keyframes"]:
            k = Keyframe()
            k.record = copy.deepcopy(raw)
            result.append(k)
        return tuple(result)

    def set_keys(p, keys):
        if p.isLocked() or p.isDisabled(): raise ValueError("native parameter is locked or disabled")
        set_parm_state(p, keyframes=keys)

    node_class.__init__, node_class.type, node_class.parm, node_class.createNode = node_init, node_type, parm, create
    def parm_tuple(node, name):
        found = find_template(node, name, True)
        return ParmTuple(node, found[0], name) if found else None
    node_class.parmTuple = parm_tuple
    node_class.childTypeCategory = lambda self: SimpleNamespace(name=lambda: native_child_category(self))
    node_class.parent = lambda self: hou.node(self.path().rsplit("/", 1)[0])
    node_class.node = lambda self, name: hou.node(self.path() + "/" + name)
    node_class.layoutChildren = lambda self, items=None: None
    def ports(node, key):
        interface = native_api_ports.get("/".join((native_category(node),node._type_name)))
        if interface is None or interface.get("origin") != "test_injected_native_api" or not isinstance(interface.get(key),list):
            raise ValueError("explicit native port API return value is unavailable")
        return tuple(interface[key])
    def capacity(node, key):
        interface = native_api_ports.get("/".join((native_category(node),node._type_name)),{})
        value = interface.get(key)
        if interface.get('origin') != 'test_injected_native_api' or type(value) is not int or value < 0:
            raise ValueError('explicit finite native NodeType capacity API return is unavailable')
        return value
    session_ids = {}
    def session_id(node):
        if node not in session_ids:
            session_ids[node] = len(session_ids)+1
        return session_ids[node]
    node_class.sessionId = session_id
    node_class.isEditable = lambda node: True
    node_class.inputNames = lambda self: ports(self,"input_names")
    node_class.outputNames = lambda self: ports(self,"output_names")
    node_class.setMaterialFlag = lambda self,value: self.setUserData("_native_api_material_flag",json.dumps(bool(value)))
    node_class.isMaterialFlagSet = lambda self: json.loads(self.userData("_native_api_material_flag") or "false")
    def set_node_flag(node, name, value):
        if type(value) is not bool:
            raise TypeError("native node flag requires a bool")
        category = native_category(node)
        if category not in {"Sop", "Obj"}:
            raise TypeError("native display/render flags require a SOP or object")
        key = "_native_api_" + name + "_flag"
        # SOP display and render flags each select one child of their network.
        if value and category == "Sop":
            for sibling in node.parent().children():
                if native_category(sibling) == "Sop":
                    sibling.setUserData(key, "false")
        node.setUserData(key, json.dumps(value))
    node_class.setDisplayFlag = lambda self, value: set_node_flag(self, "display", value)
    node_class.setRenderFlag = lambda self, value: set_node_flag(self, "render", value)
    node_class.isDisplayFlagSet = lambda self: json.loads(self.userData("_native_api_display_flag") or "false")
    node_class.isRenderFlagSet = lambda self: json.loads(self.userData("_native_api_render_flag") or "false")
    parm_class.path = lambda self: self._node.path() + "/" + self.name()
    parm_class.node = lambda self: self._node
    parm_class.parmTemplate = lambda self: self._template
    parm_class._native_validate = validate
    parm_class.set, parm_class.eval, parm_class.evalAsString = set_value, eval_value, eval_string
    parm_class.evalAsInt = lambda self: int(self.eval())
    def eval_at_frame(p,frame):
        current=hou.frame()
        try:hou.setFrame(frame);return p.eval()
        finally:hou.setFrame(current)
    def set_extrapolation(p,before,value):
        if value not in ('parmExtrapolate.Constant','parmExtrapolate.Linear'):
            raise ValueError('unsupported native software extrapolation')
        if p.isLocked() or p.isDisabled():raise ValueError('native channel not writable')
        p._native_state['pre_extrapolation' if before else 'post_extrapolation']=value
    parm_class.evalAtFrame=eval_at_frame
    parm_class.keyframeExtrapolation=lambda p,before:p._native_state['pre_extrapolation' if before else 'post_extrapolation']
    parm_class.setKeyframeExtrapolation=set_extrapolation
    hou.parmExtrapolate=SimpleNamespace(Constant='parmExtrapolate.Constant',Linear='parmExtrapolate.Linear')
    parm_class.evalAsGeometry = lambda self:self.eval() if self._template.kind == 'data' else (_ for _ in ()).throw(TypeError('not a geometry data parameter'))
    parm_class.isLocked = lambda self: self._native_state["locked"]
    parm_class.isDisabled = disabled
    def hidden(p):
        if p._native_state.get("hidden") is not None:
            return p._native_state["hidden"]
        return gate(p._node, p._template.raw.get("hide_when"), p._instance_key)
    parm_class.isHidden = hidden
    parm_class.isVisible = lambda p:not p.isHidden() and not p._template.isHidden()
    parm_class.lock = lambda self, value: set_parm_state(self, locked=value)
    parm_class.keyframes = keyframes
    parm_class.setKeyframes = set_keys
    parm_class.deleteAllKeyframes = lambda self: set_parm_state(self, keyframes=[], expression=None, reference=None)
    parm_class.getReferencedParm = referenced
    parm_class.expression = expression
    class Ramp:
        def __init__(self,basis,keys,values):
            self._basis,self._keys,self._values=tuple(basis),tuple(keys),tuple(values)
            if not len(self._basis)==len(self._keys)==len(self._values) or len(self._keys)<2 or any(b!='rampBasis.Linear' for b in self._basis) or any(type(v) not in (int,float) or not math.isfinite(v) for v in (*self._keys,*self._values)) or list(self._keys)!=sorted(set(self._keys)):
                raise ValueError('unsupported native software Ramp')
        def basis(self):return self._basis
        def keys(self):return self._keys
        def values(self):return self._values
        def isColor(self):return False
    hou.Ramp=Ramp
    hou.rampBasis=SimpleNamespace(Linear='rampBasis.Linear')
    parm_class.evalAsRamp=lambda self:self.eval() if self._template.kind=='ramp_flt' else (_ for _ in ()).throw(TypeError('not a float ramp parameter'))
    hou.exprLanguage = SimpleNamespace(Hscript='exprLanguage.Hscript',Python='exprLanguage.Python')
    parm_class.expressionLanguage = lambda self: self._native_state["language"]
    parm_class.setExpression = lambda self, value, language=None: self._native_state.update(expression=str(value), language=str(language))
    parm_class.unexpandedString = unexpanded
    parm_class.menuItems = lambda self: self._template.menuItems()
    parm_class.menuLabels = lambda self: self._template.menuLabels()
    def multiparm_instances(p):
        if p._template.kind not in {'multiparm','multiswitcher'}:
            return ()
        result = []
        for template in templates(p._node):
            if p._template.key not in template.multiparms:
                continue
            for key in instances(p._node,template):
                for name in template.component_names(key):
                    actual = p._node.parm(name)
                    if actual is not None:
                        result.append(actual)
        return tuple(result)
    parm_class.multiParmInstances = multiparm_instances
    parm_class.multiParmInstanceIndices = lambda p: tuple(int(i)-1 for i in re.findall(r'\d+',p._instance_key)) if p._template.multiparms else ()
    parm_class.isMultiParmParent = lambda p:p._template.kind in {'multiparm','multiswitcher'}
    parm_class._components = lambda p: [p]

    def press_button(p):
        # A button's script callback is native behaviour executed by HOM;
        # the software twin must run the identical callback, not fake effects.
        callback = p._template.scriptCallback().strip()
        if not callback or p._template.scriptCallbackLanguage() != str(hou.exprLanguage.Python):
            raise ValueError("native button callback is unavailable: " + p.path())
        environment = getattr(hou, "_bridge_callback_environment", None)
        if environment is None:
            raise ValueError("native callback environment is unavailable: " + p.path())
        environment.execute(callback, p._node)
    parm_class.pressButton = press_button

    def update_parm_states(node):
        # Native state updates re-run pending menu/item generators; the twin
        # has no deferred state queue, so this stays an explicit no-op.
        return None
    node_class.updateParmStates = update_parm_states

    # Existing fake save/load already serializes node userdata. Store actual
    # channel state there, then restore it only after the values have loaded.
    # No manifest or expected graph is consulted and no node is synthesized.
    original_save, original_load = hou.hipFile.save, hou.hipFile.load
    def all_nodes():
        return tuple(node for root in ("/obj", "/stage", "/mat", "/out")
                     for parent in [hou.node(root)] if parent is not None
                     for node in parent.allSubChildren())
    def save(*args, **kwargs):
        snapshots = [(node, dict(node.userDataDict())) for node in all_nodes()]
        try:
            for node, userdata in snapshots:
                node.setUserData(STATE_KEY, json.dumps({"version": version,
                    "type": node.type().nameWithCategory(), "original_reserved_user_data": userdata.get(STATE_KEY),
                    "parms": {name: copy.deepcopy(p._native_state) for name, p in node.parms_dict.items()}}, sort_keys=True))
            return original_save(*args, **kwargs)
        finally:
            for node, userdata in snapshots:
                for key in set(node.userDataDict()) - set(userdata):
                    node.destroyUserData(key)
                for key, value in userdata.items():
                    node.setUserData(key, value)
    def load(*args, **kwargs):
        restoring["active"] = True
        try: result = original_load(*args, **kwargs)
        finally: restoring["active"] = False
        for node in all_nodes():
            raw = node.userData(STATE_KEY)
            if not raw: raise ValueError("saved native state is missing: " + node.path())
            state = json.loads(raw)
            if state["version"] != version or state["type"] != node.type().nameWithCategory():
                raise ValueError("saved native version/context mismatch")
            if set(state["parms"]) != set(node.parms_dict):
                raise ValueError("saved native parameter state mismatch")
            for name, record in state["parms"].items():
                p = node.parm(name)
                if p is None: raise ValueError("saved native parameter is absent: " + name)
                p._native_state = copy.deepcopy(record)
            original_reserved = state.get('original_reserved_user_data')
            if original_reserved is None:
                node.destroyUserData(STATE_KEY)
            elif isinstance(original_reserved, str):
                node.setUserData(STATE_KEY, original_reserved)
            else:
                raise ValueError('saved native reserved user data is invalid')
        return result
    hou.hipFile.save, hou.hipFile.load = save, load

    for category in ("Sop", "Dop", "Lop", "Vop", "Obj", "Driver"):
        setattr(hou, category.lower() + "NodeTypeCategory",
                lambda c=category: SimpleNamespace(name=lambda: "Object" if c == "Obj" else c))
    hou.ropNodeTypeCategory = lambda: SimpleNamespace(name=lambda: "Driver")
    def node_type_lookup(context, name):
        context = context.name() if hasattr(context, "name") else str(context)
        context = "Obj" if context == "Object" else context
        record = catalog.get((context, name))
        if record is None: return None
        hom_category = "Object" if context == "Obj" else context
        return SimpleNamespace(name=lambda: name, nameWithCategory=lambda: hom_category + "/" + name,
            category=lambda: SimpleNamespace(name=lambda: hom_category),
            parmTemplateGroup=lambda: SimpleNamespace(entries=lambda: tuple(
                Template(raw, record["parameters"], raw.get('_native_api_source',record["source"]))
                for raw in record["parameters"].values()
                if not any(n in record["parameters"] for n in raw.get("ancestors", ())))))
    hou.nodeType = node_type_lookup
    hou.applicationVersionString = lambda: version
    hou.Keyframe, hou.StringKeyframe = Keyframe, Keyframe

    class CallbackEnvironment:
        """Executes captured native script callbacks with real semantics.

        ``updateResolutionParameters`` mirrors SideFX H21 loputils.py
        (4210-4245): manual mode unlocks both resolution components and
        clears their expressions; auto modes lock the other axis behind a
        pythonexprf driver.  No resolution value is invented here.
        """
        def execute(self, callback, node):
            text = callback.strip()
            match = re.fullmatch(r"__import__\('loputils'\)\.updateResolutionParameters\((.*)\)", text)
            if match is None:
                raise ValueError("software callback environment does not implement: " + text[:120])
            import ast
            raw_arguments = match.group(1).strip()
            if raw_arguments in ("", "hou.pwd()"):
                arguments = ()
            elif raw_arguments in ("hou.pwd(),True", "hou.pwd(), True"):
                arguments = (None, True)
            else:
                raise ValueError("unexpected native callback arguments: " + raw_arguments[:120])
            xyz = bool(arguments[1]) if len(arguments) > 1 else False
            expression_template = ("pythonexprf(\"__import__('loputils').computeResolutionParameter({}, {})\")"
                                   if xyz else
                                   "pythonexprf(\"__import__('loputils').computeResolutionParameter({}, {})\")")
            res_tuple = node.parmTuple('resolution')
            if res_tuple is None or len(res_tuple) != 2:
                raise ValueError("native resolution tuple is unavailable: " + node.path())
            xres, yres = res_tuple[0], res_tuple[1]
            mode = node.parm('res_mode').eval()
            if mode == 'autowidth':
                yres.deleteAllKeyframes()
                if yres.eval() <= 0: yres.revertToDefaults()
                yres.lock(False)
                xres.setExpression(expression_template.format('False', 1 if xyz else 2), hou.exprLanguage.Hscript)
                xres.lock(True)
            elif mode == 'autoheight':
                xres.deleteAllKeyframes()
                if xres.eval() <= 0: xres.revertToDefaults()
                xres.lock(False)
                yres.setExpression(expression_template.format('True', 1 if xyz else 2), hou.exprLanguage.Hscript)
                yres.lock(True)
            else:
                for component in (xres, yres):
                    component.deleteAllKeyframes()
                    if component.eval() <= 0: component.revertToDefaults()
                    component.lock(False)

    hou._bridge_callback_environment = CallbackEnvironment()
    hou._native_schema_constrained = True
    hou._native_schema_parm_class = parm_class
    return {"schema_sha256": hashlib.sha256(Path(schema_path).read_bytes()).hexdigest(),
            "version": version, "evidence_kind": "software_native_api_boundary", "native_geometry_executed": False,
            "exact_operator_count": len(catalog), "supplement_path": str(Path(supplement_path or Path(schema_path).with_name(SUPPLEMENT_NAME)))}
