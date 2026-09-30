def effective_trajectory(records, attempts):
    if not attempts:
        return records
    kept = {}
    known = {a['id'] for a in attempts}
    grouped = {identity: [] for identity in known}
    for row in records:
        if row.get('attempt_id') in known:
            grouped[row['attempt_id']].append(row)
    for index, attempt in enumerate(attempts):
        boundary = attempt.get('resume_tokens')
        if index and boundary is not None:
            kept = {key: row for key, row in kept.items() if row.get('tokens') is None or row['tokens'] <= boundary}
        for row in grouped[attempt['id']]:
            key = (row['metric'], row['tokens']) if row.get('tokens') is not None else object()
            # A replacement takes its latest observation's position, as before.
            kept.pop(key, None)
            kept[key] = row
    return [*kept.values(), *(r for r in records if r.get('attempt_id') not in known)]
