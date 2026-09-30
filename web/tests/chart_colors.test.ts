import { describe, expect, it } from 'vitest';
import { chartConfiguration } from '../src/features/analysis/ExperimentChart';

describe('curve colors', () => {
  const series = Array.from({length: 20}, (_, i) => ({id: String(i), name: String(i), points: [{x: 1, y: 2}]}));
  const settings = {xAxis: 'tokens', metric: 'val_ppl', xScale: 'linear', yScale: 'logarithmic'} as any;
  it('does not repeat automatic colors after exhausting the palette', () => {
    const colors = chartConfiguration(series, settings).data.datasets.map(d => d.borderColor);
    expect(new Set(colors).size).toBe(series.length);
  });
  it('keeps manual colors and reserves them from automatic assignment', () => {
    const colors = chartConfiguration(series, settings, {'7': {color: '#4C78A8'}}).data.datasets.map(d => d.borderColor);
    expect(colors[7]).toBe('#4C78A8');
    expect(new Set(colors.map(c => c.toLowerCase())).size).toBe(series.length);
  });
});
