"""Software hosts wait for their own authenticated start event before exiting."""

SUPERVISOR_START_SYNC = r'''
def software_wait_for_supervisor_start(role):
    import json, os, time
    from dcc_task_runtime.native_scope import NativeScope
    from dcc_task_runtime.owned_process import read_receipt, WRITER_COLLECTION_SECONDS
    binding = os.environ.get('BRIDGE_NATIVE_SCOPE_BINDING')
    ticket_id = os.environ.get('BRIDGE_NATIVE_SCOPE_TICKET')
    if binding is None and ticket_id is None:
        return
    if not binding or not ticket_id:
        raise ValueError('SOFTWARE_SUPERVISOR_SCOPE_INCOMPLETE')
    scope = NativeScope(json.loads(binding))
    state = scope.snapshot()
    tickets = [ticket for ticket in state['tickets'] if ticket['id'] == ticket_id]
    if len(tickets) != 1:
        raise ValueError('SOFTWARE_SUPERVISOR_TICKET_REQUIRED')
    ticket = tickets[0]
    if ticket['role'] != role:
        return
    if ticket['parent'] is not None or ticket.get('stopped_at') is not None or state['closed_reason']:
        raise ValueError('SOFTWARE_SUPERVISOR_TICKET_NOT_ACTIVE')
    remaining = ticket['admitted_at'] + scope.scope['budget']['per_operation_seconds'] - time.time()
    deadline = time.monotonic() + max(0, min(WRITER_COLLECTION_SECONDS, remaining))
    while time.monotonic() < deadline:
        started = read_receipt(ticket['directory'], 'started', identity=ticket['identity'])
        if started is not None:
            if type(started.get('pid')) is not int or started['pid'] != os.getpid():
                raise ValueError('SOFTWARE_SUPERVISOR_PID_MISMATCH')
            return
        time.sleep(.01)
    raise ValueError('SOFTWARE_SUPERVISOR_START_TIMEOUT')
'''
