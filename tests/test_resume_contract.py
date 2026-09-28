from ai_exp_remote.resume import validate_resume_metadata

def test_model_only_not_exact():
    errors=validate_resume_metadata({'model_state':{}},{'world_size':2,'requires_scaler':False})
    assert any('optimizer_state' in e for e in errors)
    assert any('rng_states' in e for e in errors)

def test_all_rank_states_required():
    c=dict(model_state={},optimizer_state={},rng_states=[{}],train_sample_cursors=[0],world_size=2)
    assert len(validate_resume_metadata(c,{'world_size':2}))==2
