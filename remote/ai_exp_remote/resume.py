"""Strict resume validation. Never unpickle arbitrary imported local history."""
def validate_resume_metadata(checkpoint,expected):
    errors=[]
    for key in ('model_state','optimizer_state','rng_states','train_sample_cursors'):
        if key not in checkpoint:errors.append('缺少 '+key)
    if expected.get('requires_scaler') and not checkpoint.get('grad_scaler_state'):errors.append('缺少 scaler_state')
    for key in ('rng_states','train_sample_cursors'):
        if key in checkpoint and len(checkpoint[key])!=expected['world_size']:errors.append(key+' 的 rank 数量不匹配')
    for key in ('world_size','manifest_fingerprint','args','model_config'):
        if key in expected and checkpoint.get(key)!=expected[key]:errors.append(key+' 不匹配')
    if checkpoint.get('allow_nonexact_resume') or checkpoint.get('allow_world_size_change'):errors.append('不允许非严格续跑')
    return errors
