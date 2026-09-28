export function partitionSeries(
  selectedIds: string[],
  byId: Record<string, unknown[]>,
) {
  return {
    visible: selectedIds.filter((id) => (byId[id]?.length ?? 0) > 0),
    missing: selectedIds.filter((id) => (byId[id]?.length ?? 0) === 0),
  };
}
