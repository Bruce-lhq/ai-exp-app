def effective_trajectory(records, attempts):
    if not attempts:
        return records
    kept = []
    known = {a['id'] for a in attempts}
    for index, attempt in enumerate(attempts):
        boundary = attempt.get('resume_tokens')
        if index and boundary is not None:
            kept = [r for r in kept if r.get('tokens') is None or r['tokens'] <= boundary]
        for row in records:
            if row.get('attempt_id') != attempt['id']:
                continue
            if row.get('tokens') is not None:
                kept = [r for r in kept if (r['metric'], r.get('tokens')) != (row['metric'], row['tokens'])]
            kept.append(row)
    kept.extend(r for r in records if r.get('attempt_id') not in known)
    return kept
