#!/usr/bin/env python3
"""Build a fail-closed software readiness matrix from executed evidence.

This tool records evidence; it does not certify native behavior or manufacture
an independent review. Missing evidence is a failed preparation gate.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from readiness_evidence import (DOMAINS, REQUIRED, build_id, digest,
                                 inspect_row_execution_artifacts,
                                 validate_contract, validate_contract_rows,
                                 domain_stage_errors, _DOMAIN_COMMAND_STAGES,
                                 _diagnostic_marked, PackageEvidenceResolver, _evidence_file,
                                 inspect_prepared_case)
ROOT = Path(__file__).resolve().parents[1]


def _collect_operation_ids(value):
    """Return operation IDs that are actually present in nested receipts."""
    found = set()
    if isinstance(value, dict):
        operation_id = value.get('operation_id')
        if isinstance(operation_id, str) and operation_id:
            found.add(operation_id)
        for child in value.values():
            found.update(_collect_operation_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_operation_ids(child))
    return found


def _collect_stages(value):
    found = set()
    if isinstance(value, dict):
        stage = value.get('stage')
        if isinstance(stage, str) and stage:
            found.add(stage)
        for child in value.values():
            found.update(_collect_stages(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_collect_stages(child))
    return found


def _domain_execution_binding(domain, domain_pack, root=ROOT, *, resolver=None):
    cases = [case for case in domain.get('cases', [])
             if isinstance(case, dict) and case.get('domain_pack') == domain_pack]
    expected = {f'{domain_pack}__{scenario}' for scenario in
                ('build_inspect', 'causal_candidate', 'approval_recovery')}
    errors = []
    observed_ids = set()
    observed_operations = set()
    observed_stages = set()
    prepared_cases = []
    for case in cases:
        case_id = case.get('case_id')
        if isinstance(case_id, str) and case_id:
            observed_ids.add(case_id)
        else:
            errors.append('domain case has no concrete case_id')
        if case.get('status') != 'PASS':
            errors.append(f'{case_id}: status is not PASS')
        if case.get('case_execution') == 'prepared_production_controller':
            adapted = inspect_prepared_case(case, root, resolver=resolver)
            prepared_cases.append(dict(adapted, case_id=case_id))
            observed_stages.update(adapted['stages'])
            observed_operations.update(adapted['operation_ids'])
            errors.extend(adapted['errors'])
            errors.extend(f'{case_id}: missing proof: {proof}' for proof in adapted['missing_proofs'])
            continue
        if case.get('case_execution') != 'production_domain_dispatch':
            errors.append(f'{case_id}: production dispatch receipt missing')
        stages = case.get('stage_receipts')
        if not isinstance(stages, list) or not stages:
            errors.append(f'{case_id}: stage receipts missing')
        else:
            case_stages = {
                _DOMAIN_COMMAND_STAGES[receipt['command']] for receipt in stages
                if isinstance(receipt, dict) and receipt.get('command') in _DOMAIN_COMMAND_STAGES
                and isinstance(receipt.get('result'), dict) and not _diagnostic_marked(receipt)
            }
            observed_stages.update(case_stages)
            if not case_stages:
                errors.append(f'{case_id}: stage receipts do not identify executed stages')
        operations = _collect_operation_ids(case)
        if not operations:
            errors.append(f'{case_id}: operation_id missing from stage receipts')
        observed_operations.update(operations)
    if observed_ids != expected:
        errors.append(f'{domain_pack}: expected three distinct scenario case IDs')
    errors.extend(domain_stage_errors('DOMAIN-' + domain_pack, observed_stages))
    binding = {
        'passed': not errors,
        'errors': errors,
        'case_ids': sorted(observed_ids),
        'stages': sorted(observed_stages),
        'build_id': domain.get('build_id'),
        'operation_ids': sorted(observed_operations),
    }
    if prepared_cases:
        binding['prepared_cases'] = prepared_cases
    return binding


def _composite_execution_binding(domain):
    composites = [item for item in domain.get('composites', []) if isinstance(item, dict)]
    errors = []
    case_ids = []
    operation_ids = set()
    stages = set()
    for composite in composites:
        case_id = composite.get('case_id')
        if isinstance(case_id, str) and case_id:
            case_ids.append(case_id)
        else:
            errors.append('composite case has no concrete case_id')
        execution = composite.get('execution')
        if composite.get('status') != 'PASS' or not isinstance(execution, dict):
            errors.append(f'{case_id}: executed composite chain is not PASS')
            continue
        if execution.get('formal_operation') is not True:
            errors.append(f'{case_id}: formal composite operation receipt missing')
        execution_stages = _collect_stages(execution)
        stages.update(execution_stages)
        if not execution_stages:
            errors.append(f'{case_id}: composite execution stage is missing')
        operations = _collect_operation_ids(composite)
        if not operations:
            errors.append(f'{case_id}: operation_id missing from composite receipts')
        operation_ids.update(operations)
    if len(composites) != 2 or len(set(case_ids)) != 2:
        errors.append('two distinct composite case IDs required')
    return {
        'passed': not errors,
        'errors': errors,
        'case_ids': sorted(case_ids),
        'stages': sorted(stages),
        'build_id': domain.get('build_id'),
        'operation_ids': sorted(operation_ids),
    }


def _row_binding_matches(row, observed, kind):
    binding = row.get('execution_binding')
    if not isinstance(binding, dict):
        return [row.get('id', '<row>') + ': execution_binding is missing']
    errors = []
    if kind == 'domain_scenarios':
        errors.extend(domain_stage_errors(row.get('id'), observed.get('stages', [])))
    if binding.get('kind') != kind:
        errors.append(row.get('id', '<row>') + ': execution_binding kind mismatch')
    if binding.get('build_id') != observed.get('build_id'):
        errors.append(row.get('id', '<row>') + ': execution_binding build_id mismatch')
    for key in ('case_ids', 'stages', 'operation_ids'):
        declared = binding.get(key)
        actual = observed.get(key, [])
        if (not isinstance(declared, list)
                or any(not isinstance(item, str) or not item for item in declared)
                or len(declared) != len(set(declared))
                or not isinstance(actual, list)
                or set(declared) != set(actual)):
            errors.append(row.get('id', '<row>') + f': execution_binding {key} do not match receipts')
    if kind == 'unit_test':
        expected_tests = sorted(set(
            list(row.get('positive_tests') or []) + list(row.get('negative_tests') or [])))
        if binding.get('test_ids') != expected_tests:
            errors.append(row.get('id', '<row>') + ': execution_binding test IDs do not match mapped tests')
        if binding.get('evidence_ref') != row.get('evidence_ref'):
            errors.append(row.get('id', '<row>') + ': execution_binding evidence_ref mismatch')
    return errors


def _unit_execution_binding(row, root, *, resolver=None):
    """Derive a unit-row binding from persisted receipts, never row text."""
    observed = inspect_row_execution_artifacts(
        row, root, build_id(root, resolver=resolver), check_files=True, resolver=resolver)
    return {
        'passed': not observed['errors'],
        'errors': list(observed['errors']),
        'case_ids': list(observed['case_ids']),
        'stages': list(observed['stages']),
        'build_id': build_id(root, resolver=resolver),
        'operation_ids': list(observed['operation_ids']),
    }


def check_review(audit, root, *, resolver=None):
    errors = []
    if audit.get('schema') != 'bridge.readiness.independent_review/1':
        errors.append('independent reviewer report required; automated source checks are not review')
    if not audit.get('reviewer') or audit.get('reviewer') in audit.get('implementers', []) or not audit.get('implementers'):
        errors.append('reviewer and implementer identities must be distinct and recorded')
    if audit.get('build_id') != build_id(root, resolver=resolver): errors.append('review build mismatch')
    if set(audit.get('reviewed_contracts', [])) != set(REQUIRED): errors.append('independent review does not cover all contracts')
    if audit.get('open_findings') != [] or audit.get('passed') is not True: errors.append('independent review is not closed')
    try:
        report = _evidence_file(root if resolver is not None else None, audit['report']['path'],
                                audit['report']['sha256'], resolver)
        if digest(report) != audit['report']['sha256'] or report.stat().st_size == 0:
            errors.append('independent review report is empty or changed')
    except (OSError, KeyError, TypeError, ValueError): errors.append('independent review report is missing')
    return errors


def assess(contract, domain, media, lifecycle, audit, root=ROOT, *, resolver=None):
    errors = validate_contract(contract, root, resolver=resolver) + check_review(audit, root, resolver=resolver)
    cases = domain.get('cases', [])
    scenarios = {'build_inspect', 'causal_candidate', 'approval_recovery'}
    expected = {(d, s) for d in DOMAINS for s in scenarios}
    actual = {(c.get('domain_pack'), c.get('scenario')) for c in cases if isinstance(c, dict)}
    if len(cases) != 48 or actual != expected or any(c.get('status') != 'PASS' for c in cases):
        errors.append('48 distinct passing domain/scenario executions required')
    composites = domain.get('composites', [])
    composite_binding = _composite_execution_binding(domain)
    if not composite_binding['passed']:
        errors.append('two distinct executed composite chains required')
    if media.get('passed') is not True:
        errors.append('media execution evidence missing or failed')
    artifacts = lifecycle.get('artifacts', [])
    if lifecycle.get('passed') is not True or len(artifacts) != 3 or {a.get('skill') for a in artifacts} != {'houdini-bridge','nuke-bridge','vfx-visual-twin'} or any(a.get('passed') is not True for a in artifacts):
        errors.append('three verified installed Skill lifecycles required')
    for label, payload in [('domain',domain),('media',media),('lifecycle',lifecycle)]:
        if payload.get('build_id') != build_id(root, resolver=resolver): errors.append(label + ': build binding missing or stale')
    rows = []
    source_rows = {r.get('id'):r for r in contract.get('rows', []) if isinstance(r, dict)}
    contract_errors = validate_contract(contract, root, resolver=resolver)
    row_errors = validate_contract_rows(contract, root, resolver=resolver)
    row_prefixes = tuple(identifier + ':' for identifier in REQUIRED)
    global_contract_errors = [error for error in contract_errors
                              if not error.startswith(row_prefixes)]
    for identifier in REQUIRED:
        row = dict(source_rows.get(identifier, {}), id=identifier)
        observed = None
        binding_kind = None
        if identifier.startswith('DOMAIN-'):
            domain_pack = identifier[len('DOMAIN-'):]
            observed = _domain_execution_binding(domain, domain_pack, root, resolver=resolver)
            binding_kind = 'domain_scenarios'
        elif identifier == 'P3-COMPOSITES':
            observed = composite_binding
            binding_kind = 'composite_dataflow'
        else:
            observed = _unit_execution_binding(row, root, resolver=resolver)
            binding_kind = 'unit_test'
        local_errors = list(row_errors.get(identifier, []))
        if observed is not None:
            local_errors.extend(observed['errors'])
            local_errors.extend(_row_binding_matches(row, observed, binding_kind))
        ready = not global_contract_errors and not local_errors
        row['evidence_validation_errors'] = local_errors
        if observed is not None:
            row['observed_execution_binding'] = observed
        row['software_gate_passed'] = ready
        row['status'] = 'PASS' if ready else 'UNVERIFIED'
        rows.append(row)
    failed_rows = [row['id'] for row in rows if row.get('status') != 'PASS']
    if failed_rows:
        errors.append('all 54 required rows need independent row-local execution evidence: ' +
                      ','.join(failed_rows))
    return {'schema':'bridge.full_readiness.contract_matrix/2.0', 'build_id':build_id(root, resolver=resolver),
            'row_count':len(rows),'rows':rows,'errors':errors,
            'software_preparation_status':'PASS' if not errors else 'NOT_READY',
            'real_host_acceptance_status':'UNVERIFIED_NOT_RUN_BY_CONTRACT',
            'visual_acceptance_status':'UNVERIFIED_NOT_RUN_BY_CONTRACT'}


def main():
    parser = argparse.ArgumentParser()
    for arg in ('contract-evidence', 'domain-cases', 'media', 'skill-lifecycle', 'audit'):
        parser.add_argument('--' + arg, type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--package-root', type=Path)
    parser.add_argument('--package-manifest-sha256')
    parser.add_argument('--package-source-relative-root', default='source/bridge-skills')
    args = parser.parse_args()
    resolver = None
    if bool(args.package_root) != bool(args.package_manifest_sha256):
        parser.error('--package-root and --package-manifest-sha256 must be supplied together')
    if args.package_root is not None:
        try:
            resolver = PackageEvidenceResolver(args.package_root,
                manifest_sha256=args.package_manifest_sha256,
                source_relative_root=args.package_source_relative_root)
        except (OSError, ValueError, TypeError) as exc:
            parser.error('package verification rejected: ' + str(exc))
        sys.path.insert(0, str(resolver.source_root / 'packages/dcc-task-runtime/src'))
    inputs = {}
    errors = []
    for key in ('contract_evidence','domain_cases','media','skill_lifecycle','audit'):
        try:
            input_path = getattr(args,key)
            if resolver is not None:
                input_path = resolver.package_input(input_path)
            value = json.loads(input_path.read_text())
            if not isinstance(value, dict): raise ValueError('must be object')
            inputs[key] = value
        except (OSError,ValueError) as exc:
            inputs[key] = {}; errors.append(key + ': ' + str(exc))
    matrix = assess(inputs['contract_evidence'],inputs['domain_cases'],inputs['media'],inputs['skill_lifecycle'],inputs['audit'],
                    root=resolver.source_root if resolver is not None else ROOT, resolver=resolver)
    if errors:
        matrix['errors'].extend(errors); matrix['software_preparation_status'] = 'NOT_READY'
    output = args.output_dir; output.mkdir(parents=True, exist_ok=True)
    (output/'acceptance_matrix.json').write_text(json.dumps(matrix, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'status':matrix['software_preparation_status'], 'errors':matrix['errors']}, ensure_ascii=False))
    return 0 if matrix['software_preparation_status']=='PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
