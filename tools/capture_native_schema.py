#!/usr/bin/env python3
"""Capture interface metadata from installed HDA INDX sections, without execution."""
from __future__ import annotations
import argparse,hashlib,json,re,struct
from datetime import datetime, timezone
from pathlib import Path
import platform
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
import native_install_paths as native_paths
if getattr(native_paths, '__file__', None) is None or Path(native_paths.__file__).resolve() != (TOOLS/'native_install_paths.py').resolve():
    raise ValueError('locator source does not match reviewed file')
SUPPORTED_BUILDS = native_paths.SUPPORTED_BUILDS
DEFAULT_BUILDS = native_paths.DEFAULT_BUILDS
resource_directory = native_paths.resource_directory


def index_sections(data):
    if data[:4]!=b'INDX' or len(data)<16:raise ValueError('not an INDX archive')
    count=struct.unpack_from('>I',data,12)[0]
    if count>100000:raise ValueError('unbounded INDX entry count')
    pos=16;entries={}
    for _ in range(count):
        if pos+4>len(data):raise ValueError('truncated INDX name length')
        size=struct.unpack_from('>I',data,pos)[0];pos+=4
        if size>4096 or pos+size+12>len(data):raise ValueError('invalid INDX name')
        name=data[pos:pos+size].decode();pos+=size
        offset,length,_=struct.unpack_from('>III',data,pos);pos+=12
        if name in entries:raise ValueError('duplicate INDX member')
        entries[name]=(offset,length)
    for name,(offset,length) in entries.items():
        if pos+offset+length>len(data):raise ValueError('out-of-bounds INDX member')
    return {name:data[pos+offset:pos+offset+length] for name,(offset,length) in entries.items()}


def dialog_parameters(data):
    """Keep direct fields, valueless flags, and the actual folder/multiparm tree.

    The former token-pair parser consumed the field after ``nolabel`` or
    ``joinnext`` as its value, dropping defaults and disabled conditions.
    Parse directives per line; nested blocks are balanced independently.
    Dynamic scripts are retained as evidence and are never executed.
    """
    text = data.decode('utf-8')
    text = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}\n]|[^\s{}]+', text)
    containers = {'parm', 'group', 'groupcollapsible', 'groupsimple',
                  'multiparm', 'multiswitcher', 'switcher'}
    flags = {'nolabel', 'joinnext', 'invisible', 'export', 'logarithmic',
             'noncook', 'retain', 'noresize', 'horiz', 'vertical', 'baseparm',
             'tabbreak', 'invisibletab', 'unquoted'}
    out = {}

    def block(start):
        level, pos = 1, start
        while pos < len(tokens) and level:
            level += (tokens[pos] == '{') - (tokens[pos] == '}')
            pos += 1
        if level:
            raise ValueError('unbalanced DialogScript block')
        return pos - 1

    def parse(begin, end, ancestors):
        fields, children, pos = {}, [], begin
        while pos < end:
            key = tokens[pos]
            pos += 1
            if key == '\n':
                continue
            if key in flags:
                fields[key] = True
                continue
            if pos >= end:
                break
            if key == 'menu' and tokens[pos] == 'usetokenvalue':
                fields['menu_modifiers'] = ['usetokenvalue']
                pos += 1
                while pos < end and tokens[pos] == '\n':
                    pos += 1
                if pos >= end or tokens[pos] != '{':
                    raise ValueError('token-value menu has no balanced item block')
            if tokens[pos] == '{':
                close = block(pos + 1)
                if key in containers:
                    children.append((key, pos + 1, close))
                else:
                    value = [_unquote(t) for t in tokens[pos + 1:close] if t != '\n']
                    if key in fields:
                        previous = fields[key]
                        fields[key] = previous + value if isinstance(previous, list) else [previous] + value
                    else:
                        fields[key] = value
                pos = close + 1
            else:
                # Scalar directives have one value; unknown root directives
                # (inputlabel/bindhandle) may have many. Never consume the
                # next line's parm/group keyword as their trailing value.
                if tokens[pos] != '\n':
                    fields[key] = _unquote(tokens[pos])
                while pos < end and tokens[pos] != '\n':
                    pos += 1
        # Root/group directives are traversed, but never borrowed by children.
        name = fields.get('name')
        for kind, first, last in children:
            child_fields, grand = parse(first, last, ancestors + ([name] if name else []))
            child_name = child_fields.get('name')
            if not child_name:
                continue
            raw_type = child_fields.get('type', kind if kind != 'parm' else 'unknown')
            values = child_fields.get('default', [])
            if not isinstance(values, list):
                values = [values]
            record = {
                'name': child_name, 'type': raw_type,
                'size': int(child_fields.get('size', '1')),
                'label': child_fields.get('label', ''),
                'default_tokens': values,
                'menu_tokens': child_fields.get('menu', []),
                'menu_modifiers': child_fields.get('menu_modifiers', []),
                'menu_uses_token_value': 'usetokenvalue' in child_fields.get('menu_modifiers', []),
                'range_tokens': child_fields.get('range', []),
                'disable_when': child_fields.get('disablewhen', ''),
                'hide_when': child_fields.get('hidewhen', ''),
                'disable_when_tab': child_fields.get('disablewhentab', ''),
                'naming_tokens': child_fields.get('naming', child_fields.get('namingScheme', '')),
                'tags_tokens': child_fields.get('parmtag', []),
                'menu_script_tokens': child_fields.get('menureplace', child_fields.get('menuscript', [])),
                'container_kind': kind,
                'children': grand,
                'ancestors': ancestors + ([name] if name else []),
                'flags': [key for key in flags if child_fields.get(key) is True],
                'raw_fields': child_fields,
            }
            if child_name in out:
                raise ValueError('duplicate DialogScript parameter: ' + child_name)
            out[child_name] = record
        return fields, [next((_unquote(tokens[i + 1]) for i in range(first, last - 1)
                             if tokens[i] == 'name'), '')
                        for _, first, last in children]

    # Ignore leading blank lines; comments were removed before tokenization.
    begin = next((i for i, token in enumerate(tokens) if token != '\n'), len(tokens))
    if begin < len(tokens) and tokens[begin] == '{':
        parse(begin + 1, block(begin + 1), [])
    else:
        parse(begin, len(tokens), [])
    return out


def _unquote(token):
    if token.startswith('"'):
        try:
            return json.loads(token)
        except ValueError:
            return token[1:-1]
    return token


def _record_tokens(text):
    return [_unquote(token) for token in re.findall(r'"(?:\\.|[^"\\])*"|[{}]|[^\s{}]+', text)]


def dialog_interface(data):
    """Parse DialogScript node I/O declarations and normalize label indices.

    Houdini DialogScript inputlabel/outputlabel declarations are numbered from
    one; HOM connection APIs use zero-based indices. A label is interface
    evidence only: it does not establish complete arity or port semantics.
    """
    text = data.decode('utf-8')
    records = {'input_labels': [], 'output_labels': [], 'inputs': [], 'outputs': [], 'signatures': []}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r'^\s*(inputlabel|outputlabel|input|output|signature)\s+(.+?)\s*$', line)
        if not match:
            index += 1
            continue
        directive, body = match.groups()
        if directive in ('inputlabel', 'outputlabel'):
            tokens = _record_tokens(body)
            if len(tokens) >= 2:
                try:
                    label_index = int(tokens[0])
                except ValueError:
                    index += 1
                    continue
                label = ' '.join(tokens[1:])
                label_record = {
                    'dialogscript_index': label_index,
                    'api_index': label_index - 1 if label_index >= 1 else None,
                    'label': label,
                    'index_normalization': 'one_based_dialogscript_to_zero_based_hom',
                    'status': 'NORMALIZED' if label_index >= 1 else 'INVALID_NONPOSITIVE_LABEL_INDEX',
                }
                records['input_labels' if directive == 'inputlabel' else 'output_labels'].append(label_record)
            index += 1
            continue

        accumulated = [body]
        token_list = _record_tokens(body)
        depth = token_list.count('{') - token_list.count('}')
        while depth > 0 and index + 1 < len(lines):
            index += 1
            accumulated.append(lines[index])
            token_list = _record_tokens('\n'.join(accumulated))
            depth = token_list.count('{') - token_list.count('}')
        tokens = _record_tokens('\n'.join(accumulated))
        if directive in ('input', 'output'):
            if len(tokens) >= 2:
                records['inputs' if directive == 'input' else 'outputs'].append({
                    'declared_type': tokens[0],
                    'name': tokens[1],
                    'label': tokens[2] if len(tokens) > 2 else None,
                    'tokens': tokens,
                    'evidence': 'DialogScript',
                })
        else:
            type_block = []
            if '{' in tokens and '}' in tokens:
                begin = tokens.index('{')
                end = len(tokens) - 1 - tokens[::-1].index('}')
                type_block = tokens[begin + 1:end]
            records['signatures'].append({
                'label': tokens[0] if tokens else None,
                'name': tokens[1] if len(tokens) > 1 else None,
                'type_tokens': type_block,
                'tokens': tokens,
                'evidence': 'DialogScript',
            })
        index += 1
    records['port_signature'] = {
        'input_label_count': len(records['input_labels']),
        'output_label_count': len(records['output_labels']),
        'declared_input_count': len(records['inputs']),
        'declared_output_count': len(records['outputs']),
        'signature_count': len(records['signatures']),
        'full_node_port_arity': None,
        'semantics_status': 'LABELS_AND_DIALOGSCRIPT_DECLARATIONS_ONLY',
        'missing_semantics': 'DialogScript labels/declarations do not prove the complete HOM node input/output signature or connection semantics.',
    }
    return records


def capture(root, *, layout="macos", versions=DEFAULT_BUILDS):
    native_paths.require_local_module(native_paths, TOOLS/'native_install_paths.py')
    library_types = {
        'OPlibSop.hda': ('Sop/particlefluidsurface::2.0','Sop/pyrosource','Sop/volumerasterizeattributes','Sop/attribadjustfloat','Sop/attribadjustvector','Sop/oceanspectrum','Sop/oceanevaluate::2.0','Sop/oceanfoam','Sop/pyrosolver','Sop/flipsolver','Sop/flipsource','Sop/flipcontainer','Sop/flipcollide',
            'Sop/vellumconstraints','Sop/vellumconstraints_grain','Sop/vellumsolver','Sop/rbdmaterialfracture','Sop/rbdconfigure','Sop/rbdbulletsolver','Sop/crowdsource','Sop/crowdsource::3.0'),
        'OPlibPopDop.hda': ('Dop/popsource::2.0','Dop/popsolver::2.0','Dop/popforce','Dop/popdrag','Dop/popflock','Dop/popsteerseek'),
        'OPlibDop.hda': ('Dop/crowdsolver::3.0','Dop/crowdobject','Dop/crowdstate'),
        'OPlibLop.hda': ('Lop/camera','Lop/domelight','Lop/domelight::3.0','Lop/light','Lop/karmarendersettings','Lop/karmarenderproducts::2.0','Lop/renderproduct','Lop/rendersettings','Lop/rendervar'),
        'MaterialX.hda': ('Vop/mtlxstandard_surface','Vop/mtlxsurfacematerial','Vop/mtlxnormalmap','Vop/mtlxdisplacement'),
    }
    result={'schema':'bridge.installed_hda_interface/2.0','evidence_kind':'static_vendor_definition','native_execution':False,
        'capture_metadata':{'captured_at_utc':datetime.now(timezone.utc).isoformat(),'platform':platform.platform(),
            'python_version':platform.python_version(),'tool_path':str(Path(__file__).resolve()),
            'tool_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'install_root':str(root),'install_layout':layout,'requested_builds':list(versions),
            'locator_sha256':hashlib.sha256((TOOLS/'native_install_paths.py').read_bytes()).hexdigest(),
            'locator_path':str(Path(native_paths.__file__).resolve()),
            'scope':'read-only parsing of installed otls/*.hda sections; no Houdini process or native operation was executed'},'versions':{}}
    for version in versions:
        directory=resource_directory(root,version,layout=layout)/'otls'
        record={'archives':{},'operators':{}}
        for library, types in library_types.items():
            file=directory/library
            if not file.is_file():
                record['archives'][library]={'path':str(file),'status':'MISSING'}
                for name in types:
                    record['operators'][name]={'status':'ARCHIVE_MISSING','library':library}
                continue
            data=file.read_bytes();entries=index_sections(data)
            record['archives'][library]={'path':str(file),'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            for name in types:
                if name not in entries:
                    record['operators'][name]={'status':'ABSENT_FROM_THIS_LIBRARY','library':library};continue
                sections=index_sections(entries[name]);dialog=sections.get('DialogScript')
                if dialog is None:
                    record['operators'][name]={'status':'NO_DIALOG_SECTION','library':library};continue
                interface = dialog_interface(dialog)
                record['operators'][name]={'status':'CAPTURED','library':library,'section_sha256':hashlib.sha256(dialog).hexdigest(),
                    'parameters':dialog_parameters(dialog),**interface}
        result['versions'][version]=record
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--install-root',type=Path,default=Path('/Applications/Houdini'))
    parser.add_argument('--install-layout',choices=('macos','windows'),default='macos')
    parser.add_argument('--build',choices=SUPPORTED_BUILDS,action='append')
    a=parser.parse_args()
    native_paths.validate_output_path(a.output)
    result=capture(a.install_root,layout=a.install_layout,versions=tuple(a.build or DEFAULT_BUILDS))
    native_paths.write_new_output(a.output,result)
if __name__=='__main__':main()
