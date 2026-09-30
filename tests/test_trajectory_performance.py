from ai_exp_app.analysis.trajectory import effective_trajectory


def test_large_managed_trajectory_does_not_rescan_all_previous_records():
    accesses = [0]
    class Row(dict):
        def __getitem__(self, key):
            accesses[0] += 1
            return super().__getitem__(key)
    records = [Row(attempt_id='a', metric='train_ppl', tokens=i, value=42) for i in range(2000)]
    result = effective_trajectory(records, [{'id': 'a'}])
    assert result == records
    assert accesses[0] < 20 * len(records)


def test_resume_cutoff_last_duplicate_and_unknown_attempt_order_remain_exact():
    records = [
        dict(attempt_id='a', metric='val_ppl', tokens=1, value=50),
        dict(attempt_id='a', metric='val_ppl', tokens=2, value=40),
        dict(attempt_id='a', metric='train_ppl', tokens=3, value=99),
        dict(attempt_id='a', metric='speed', tokens=None, value=1),
        dict(attempt_id='b', metric='val_ppl', tokens=2, value=35),
        dict(attempt_id='b', metric='val_ppl', tokens=2, value=34),
        dict(attempt_id='b', metric='train_ppl', tokens=3, value=90),
        dict(attempt_id=None, metric='legacy', tokens=0, value=1),
    ]
    result = effective_trajectory(records, [{'id': 'a'}, {'id': 'b', 'resume_tokens': 2}])
    assert result == [records[i] for i in (0, 3, 5, 6, 7)]
