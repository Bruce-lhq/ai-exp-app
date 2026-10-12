export const commonMetrics = ["val_ppl", "train_ppl", "R_min", "R_mean", "update_rms"];

export function metricOptions(metrics: string[]) {
  return [...new Set([...commonMetrics, ...metrics])]
    .filter((metric) => !/(?:^|_)tokens$/.test(metric))
    .filter((metric) => !/^ca\/L\d+\/T\d+(?:\/|$)/.test(metric));
}
