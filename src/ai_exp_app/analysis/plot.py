"""Offline PNG rendering for the CLI; uses the same cached series as the UI."""
import colorsys
import io
import math
import threading
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties, findfont

_PALETTE = ['#4C78A8', '#2ca02c', '#D45B5B', '#F58518', '#17BECF', '#E377C2', '#9467bd', '#8C564B', '#FF9DA7']
_RENDER_LOCK = threading.Lock()


def number(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f'{name} is outside the supported range')
    return value


def create_figure(data, body):
    settings = body.get('settings', {})
    appearance = body.get('appearance', {})
    if not isinstance(settings, dict) or not isinstance(appearance, dict):
        raise ValueError('settings and appearance must be objects')
    width = number(settings.get('width', 1536), 'width', 200, 6000)
    height = number(settings.get('height', 1044), 'height', 150, 6000)
    ratio = number(settings.get('pixelRatio', 1.5), 'pixelRatio', .5, 4)
    if width*height*ratio*ratio > 16_000_000:
        raise ValueError('image exceeds 16 million pixels')
    metric = body.get('metric', 'val_ppl')
    axis = body.get('x_axis', body.get('axis', 'tokens'))
    xscale = settings.get('xScale', 'linear')
    yscale = settings.get('yScale', 'logarithmic' if 'ppl' in metric.lower() else 'linear')
    if xscale not in {'linear', 'logarithmic'} or yscale not in {'linear', 'logarithmic'}:
        raise ValueError('scale must be linear or logarithmic')
    limits = {}
    for prefix, scale in (('x', xscale), ('y', yscale)):
        low, high = settings.get(prefix+'Min'), settings.get(prefix+'Max')
        for value in (low, high):
            if value is not None:
                number(value, prefix+' limit')
                if scale == 'logarithmic' and value <= 0:
                    raise ValueError('logarithmic limits must be positive')
        if low is not None and high is not None and low >= high:
            raise ValueError('minimum must be below maximum')
        limits[prefix] = (low, high)
    for style in appearance.values():
        if not isinstance(style, dict):
            raise ValueError('each appearance must be an object')
        if style.get('color') and not is_color_like(style['color']):
            raise ValueError('invalid series color')
        if 'order' in style:
            number(style['order'], 'order')
    family = 'DejaVu Sans'
    for candidate in ['Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC']:
        try:
            findfont(FontProperties(family=candidate), fallback_to_default=False)
            family = candidate
            break
        except ValueError:
            pass
    font = {'family': family}
    fig = Figure(figsize=(width/100, height/100), dpi=100*ratio, facecolor='white')
    ax = fig.add_subplot(111)
    ax.set_xscale('log' if xscale == 'logarithmic' else 'linear')
    ax.set_yscale('log' if yscale == 'logarithmic' else 'linear')
    ax.set_xlabel(settings.get('xLabel') or ('Trained tokens (B)' if axis == 'tokens' else axis), fontsize=17, **font)
    ax.set_ylabel(settings.get('yLabel') or metric, fontsize=17, **font)
    ax.set_title(settings.get('title') or body.get('title') or metric, fontsize=24, fontweight='bold', **font)
    ax.tick_params(labelsize=15)
    ax.grid(True, which='major', color='#D7E0EA', linewidth=1)
    ax.grid(True, which='minor', color='#EAF0F6', linewidth=.7)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    curves = sorted(data['series'], key=lambda row: appearance.get(row['id'], {}).get('order', 0))
    used = {str(style['color']).lower() for style in appearance.values() if style.get('color')}
    for index, row in enumerate(curves):
        style = appearance.get(row['id'], {})
        color = style.get('color') or next((c for c in _PALETTE if c.lower() not in used), None)
        attempt = index
        while not color:
            candidate = '#' + ''.join(f'{round(v*255):02x}' for v in colorsys.hls_to_rgb((attempt*.381966)%1, .45, .62))
            if candidate not in used:
                color = candidate
            attempt += 1
        used.add(color.lower())
        xs, ys, last = [], [], None
        for point in row['points']:
            x, y = point['x'], point['y']
            valid = isinstance(x, (int, float)) and math.isfinite(x) and isinstance(y, (int, float)) and math.isfinite(y)
            if valid and (xscale != 'logarithmic' or x > 0) and (yscale != 'logarithmic' or y > 0):
                x = x/1e9 if axis == 'tokens' else x
                xs.append(x); ys.append(y); last = (x, y)
            else:
                xs.append(x/1e9 if axis == 'tokens' else x); ys.append(math.nan)
        ax.plot(xs, ys, color=color, linewidth=2.6, label=style.get('name') or row['name'])
        if last:
            ax.annotate(format(last[1], '.4g'), last, xytext=(8, 0), textcoords='offset points',
                        color=color, fontsize=16, fontweight='bold', va='center', **font)
    ax.set_xlim(*limits['x'])
    ax.set_ylim(*limits['y'])
    if curves:
        ax.legend(loc='upper right', frameon=False, prop={**font, 'size':16})
    fig.subplots_adjust(left=.10, right=.97, bottom=.11, top=.91)
    return fig


def render_png(data, body):
    if not data['series']:
        raise ValueError('no cached samples for the selected metric and axis')
    with _RENDER_LOCK:
        fig = create_figure(data, body)
        output = io.BytesIO()
        FigureCanvasAgg(fig).print_png(output)
        return output.getvalue()
