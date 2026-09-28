def reconcile_attempt(record,observation):
    result=dict(record)
    if not observation.get('reachable',True):
        result['connection']='unknown';return result
    if observation.get('identity_alive'):return result
    if observation.get('exit_code')==0 and observation.get('success'):result['status']='completed'
    elif observation.get('stop_requested'):result['status']='stopped'
    else:result['status']='failed'
    return result
