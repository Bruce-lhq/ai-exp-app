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
  it('uses dark chart colors only when requested, preserving white export defaults', () => {
    const light = chartConfiguration(series, settings);
    const dark = chartConfiguration(series, settings, {}, true);
    expect(dark.options.scales.x.ticks.color).toBe('#e1e9f4');
    expect(light.options.scales.x.ticks.color).toBe('#666666');
    const background = (config: any) => {
      const ctx = {save() {}, restore() {}, fillStyle: '', fillRect() {}, globalCompositeOperation: ''};
      config.plugins.find((p: any) => p.id === 'white-background').beforeDraw({ctx, width:100, height:100});
      return ctx.fillStyle;
    };
    expect(background(light)).toBe('white');
    expect(background(dark)).toBe('#1b2433');
    expect(dark.data.datasets.map(d=>d.borderColor)).toEqual(light.data.datasets.map(d=>d.borderColor));
  });
});
