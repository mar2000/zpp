from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied
from .models import Route, Point, BackgroundImage, Edge, Drawing, DrawingObject
from .forms import PointForm, EdgeForm, RouteStyleForm 


from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import ValidationError

from django.http import HttpResponse
import matplotlib.pyplot as plt
import io
import base64
import json
import uuid
import re

from PIL import Image, ImageDraw, ImageFont
import numpy as np

from django.conf import settings
from django.views.decorators.http import require_http_methods, require_POST
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Max




DEFAULT_DRAWING_SETTINGS = {
    'canvas': {
        'width': 900,
        'height': 520,
        'gridSize': 50,
        'showGrid': True,
        'snapToGrid': False,
    },
    'tikz': {
        'scale': 100,
    },
}


def _deep_merge_settings(defaults, raw):
    merged = json.loads(json.dumps(defaults))
    if not isinstance(raw, dict):
        return merged
    for section, values in raw.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    return default


def _coerce_int(value, default, *, minimum, maximum):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def normalized_drawing_settings(drawing_or_settings):
    raw = drawing_or_settings.settings if hasattr(drawing_or_settings, 'settings') else drawing_or_settings
    settings_data = _deep_merge_settings(DEFAULT_DRAWING_SETTINGS, raw)
    canvas = settings_data.get('canvas', {})
    tikz = settings_data.get('tikz', {})
    return {
        'canvas': {
            'width': _coerce_int(canvas.get('width'), 900, minimum=300, maximum=3000),
            'height': _coerce_int(canvas.get('height'), 520, minimum=200, maximum=2000),
            'gridSize': _coerce_int(canvas.get('gridSize'), 50, minimum=5, maximum=300),
            'showGrid': _coerce_bool(canvas.get('showGrid'), True),
            'snapToGrid': _coerce_bool(canvas.get('snapToGrid'), False),
        },
        'tikz': {
            'scale': _coerce_int(tikz.get('scale'), 100, minimum=1, maximum=1000),
        },
    }


def _validate_drawing_settings_payload(payload):
    if not isinstance(payload, dict):
        return None, {'settings': 'Settings payload must be a JSON object.'}
    if 'settings' in payload:
        payload = payload['settings']
    if not isinstance(payload, dict):
        return None, {'settings': 'settings must be a JSON object.'}

    errors = {}
    canvas = payload.get('canvas', {})
    tikz = payload.get('tikz', {})
    if canvas is not None and not isinstance(canvas, dict):
        errors['canvas'] = 'canvas must be a JSON object.'
    if tikz is not None and not isinstance(tikz, dict):
        errors['tikz'] = 'tikz must be a JSON object.'
    if errors:
        return None, errors

    current = normalized_drawing_settings(payload)
    return current, {}


def _serialize_drawing_object(obj):
    """Zamienia DrawingObject na słownik gotowy do odpowiedzi JSON."""
    return {
        'id': obj.id,
        'object_id': obj.object_id,
        'type': obj.type,
        'data': obj.data,
        'style': obj.style,
        'order': obj.order,
        'created_at': obj.created_at.isoformat(),
        'updated_at': obj.updated_at.isoformat(),
    }


def _parse_json_body(request):
    """Czyta JSON z request.body i zwraca słownik.

    Dla pustego body zwracamy pusty słownik. Niepoprawny JSON obsługujemy
    kontrolowanym błędem ValueError, żeby widoki API mogły zwrócić 400.
    """
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Request body must be valid JSON') from exc
    if not isinstance(payload, dict):
        raise ValueError('Request JSON body must be an object')
    return payload


def _validate_object_payload(payload, *, partial=False):
    """Waliduje dane DrawingObject używane przez API.

    W pierwszej wersji API trzymamy walidację ogólną: core sprawdza tylko
    strukturę wspólną dla wszystkich pluginów. Szczegółową walidację pól data
    dodadzą później konkretne moduły/pluginy.
    """
    errors = {}

    if not partial or 'type' in payload:
        object_type = payload.get('type')
        if not isinstance(object_type, str) or not object_type.strip():
            errors['type'] = 'Object type must be a non-empty string.'

    if 'object_id' in payload:
        object_id = payload.get('object_id')
        if not isinstance(object_id, str) or not object_id.strip():
            errors['object_id'] = 'object_id must be a non-empty string.'

    if 'data' in payload and not isinstance(payload.get('data'), dict):
        errors['data'] = 'data must be a JSON object.'

    if 'style' in payload and not isinstance(payload.get('style'), dict):
        errors['style'] = 'style must be a JSON object.'

    if 'order' in payload:
        try:
            order = int(payload.get('order'))
            if order < 0:
                errors['order'] = 'order cannot be negative.'
        except (TypeError, ValueError):
            errors['order'] = 'order must be an integer.'

    return errors



def _validate_plot_axis(axis, errors, prefix='axis'):
    if axis is not None and not isinstance(axis, dict):
        errors[prefix] = f'{prefix} must be a JSON object.'
        return
    if not isinstance(axis, dict):
        return
    for text_field in ('title', 'xLabel', 'yLabel'):
        if text_field in axis and not isinstance(axis.get(text_field), str):
            errors[f'{prefix}.{text_field}'] = f'{prefix}.{text_field} must be a string.'
    for number_field in ('xMin', 'xMax', 'yMin', 'yMax'):
        if number_field in axis and axis.get(number_field) not in ('', None):
            try:
                float(axis.get(number_field))
            except (TypeError, ValueError):
                errors[f'{prefix}.{number_field}'] = f'{prefix}.{number_field} must be a number.'
    try:
        if 'xMin' in axis and 'xMax' in axis and axis.get('xMin') not in ('', None) and axis.get('xMax') not in ('', None):
            if float(axis.get('xMin')) >= float(axis.get('xMax')):
                errors[f'{prefix}.xRange'] = f'{prefix}.xMin must be smaller than {prefix}.xMax.'
        if 'yMin' in axis and 'yMax' in axis and axis.get('yMin') not in ('', None) and axis.get('yMax') not in ('', None):
            if float(axis.get('yMin')) >= float(axis.get('yMax')):
                errors[f'{prefix}.yRange'] = f'{prefix}.yMin must be smaller than {prefix}.yMax.'
    except (TypeError, ValueError):
        pass


def _validate_plot_series_dict(series, errors, prefix='series'):
    if not isinstance(series, dict):
        errors[prefix] = f'{prefix} must be a JSON object.'
        return
    points = series.get('points')
    if not isinstance(points, list) or len(points) < 1:
        errors[f'{prefix}.points'] = f'{prefix}.points must be a non-empty list of [x, y] pairs.'
    else:
        for index, pair in enumerate(points):
            if (not isinstance(pair, (list, tuple))) or len(pair) not in (2, 4):
                errors[f'{prefix}.points[{index}]'] = 'Each plot point must be [x, y] or [x, y, xError, yError].'
                continue
            try:
                float(pair[0]); float(pair[1])
                if len(pair) == 4:
                    x_error = float(pair[2]); y_error = float(pair[3])
                    if x_error < 0 or y_error < 0:
                        errors[f'{prefix}.points[{index}]'] = 'Plot error bars must be non-negative numbers.'
            except (TypeError, ValueError):
                errors[f'{prefix}.points[{index}]'] = 'Plot point coordinates and error bars must be numbers.'
    plot_type = series.get('plotType', 'line')
    if plot_type not in {'line', 'scatter', 'line_markers'}:
        errors[f'{prefix}.plotType'] = 'plotType must be one of: line, scatter, line_markers.'
    if 'label' in series and not isinstance(series.get('label'), str):
        errors[f'{prefix}.label'] = f'{prefix}.label must be a string.'
    if 'style' in series and not isinstance(series.get('style'), dict):
        errors[f'{prefix}.style'] = f'{prefix}.style must be a JSON object.'


def _validate_plot_function_dict(function, errors, prefix='functions'):
    if not isinstance(function, dict):
        errors[prefix] = f'{prefix} must be a JSON object.'
        return
    expression = function.get('expression')
    if not isinstance(expression, str) or not expression.strip():
        errors[f'{prefix}.expression'] = f'{prefix}.expression must be a non-empty string.'
    for text_field in ('label', 'color'):
        if text_field in function and not isinstance(function.get(text_field), str):
            errors[f'{prefix}.{text_field}'] = f'{prefix}.{text_field} must be a string.'
    for number_field in ('domainMin', 'domainMax', 'samples'):
        if number_field in function and function.get(number_field) not in ('', None):
            try:
                float(function.get(number_field))
            except (TypeError, ValueError):
                errors[f'{prefix}.{number_field}'] = f'{prefix}.{number_field} must be a number.'
    try:
        if function.get('domainMin') not in ('', None) and function.get('domainMax') not in ('', None):
            if float(function.get('domainMin')) >= float(function.get('domainMax')):
                errors[f'{prefix}.domain'] = f'{prefix}.domainMin must be smaller than {prefix}.domainMax.'
        if function.get('samples') not in ('', None):
            samples = int(function.get('samples'))
            if samples < 2:
                errors[f'{prefix}.samples'] = f'{prefix}.samples must be at least 2.'
    except (TypeError, ValueError):
        pass

def _validate_object_references(drawing, object_type, data):
    """Walidacja zależności między typami obiektów.

    Krok 19 rozdziela świat grafowy od geometrycznego:
    - graph.edge może łączyć tylko graph.vertex,
    - geometry.segment, geometry.circle i geometry.polygon używają tylko geometry.point,
    - graph.vertex nie może być punktem okręgu, wielokąta ani odcinka geometrycznego.
    """
    if not isinstance(data, dict):
        return {'data': 'data must be a JSON object.'}

    def object_type_for(object_id):
        if not isinstance(object_id, str) or not object_id.strip():
            return None
        return DrawingObject.objects.filter(drawing=drawing, object_id=object_id).values_list('type', flat=True).first()

    def require_reference(field, expected_type):
        ref = data.get(field)
        actual_type = object_type_for(ref)
        if actual_type != expected_type:
            return f'{field} must reference an existing {expected_type} object.'
        return None

    errors = {}

    if object_type == 'graph.edge':
        for field in ('source', 'target'):
            error = require_reference(field, 'graph.vertex')
            if error:
                errors[field] = error

    if object_type == 'geometry.segment':
        for field in ('source', 'target'):
            error = require_reference(field, 'geometry.point')
            if error:
                errors[field] = error

    if object_type == 'geometry.circle':
        for field in ('center', 'point'):
            error = require_reference(field, 'geometry.point')
            if error:
                errors[field] = error

    if object_type == 'geometry.polygon':
        point_ids = data.get('points')
        if not isinstance(point_ids, list) or len(point_ids) < 3:
            errors['points'] = 'geometry.polygon requires a list of at least three geometry.point references.'
        else:
            for index, point_id in enumerate(point_ids):
                actual_type = object_type_for(point_id)
                if actual_type != 'geometry.point':
                    errors[f'points[{index}]'] = 'Each polygon point must reference an existing geometry.point object.'

    if object_type == 'plot.series':
        # Legacy/simple plot object: one data series in one object.
        _validate_plot_series_dict({
            'points': data.get('points'),
            'plotType': data.get('plotType', 'line'),
            'label': data.get('label', ''),
            'style': {},
        }, errors, prefix='plot.series')
        _validate_plot_axis(data.get('axis', {}), errors, prefix='axis')
        # Backward-compatible error keys for older tests/UI using plot.series directly.
        for key, value in list(errors.items()):
            if key.startswith('plot.series.points'):
                errors[key.replace('plot.series.', '')] = value

    if object_type == 'plot.chart':
        series = data.get('series')
        functions = data.get('functions', [])
        if not isinstance(series, list):
            errors['series'] = 'plot.chart requires series to be a list.'
        else:
            for index, item in enumerate(series):
                _validate_plot_series_dict(item, errors, prefix=f'series[{index}]')
        if functions is None:
            functions = []
        if not isinstance(functions, list):
            errors['functions'] = 'plot.chart functions must be a list.'
        else:
            for index, item in enumerate(functions):
                _validate_plot_function_dict(item, errors, prefix=f'functions[{index}]')
        if isinstance(series, list) and len(series) == 0 and isinstance(functions, list) and len(functions) == 0:
            errors['plot.chart'] = 'plot.chart requires at least one data series or one function.'
        _validate_plot_axis(data.get('axis', {}), errors, prefix='axis')
        legend = data.get('legend', {})
        if legend is not None and not isinstance(legend, dict):
            errors['legend'] = 'legend must be a JSON object.'



    return errors

DRAWING_MODE_ALLOWED_TYPES = {
    Drawing.MODE_GRAPH: {'graph.vertex', 'graph.edge'},
    Drawing.MODE_GEOMETRY: {'geometry.point', 'geometry.segment', 'geometry.circle', 'geometry.polygon'},
    Drawing.MODE_PLOT: {'plot.series', 'plot.chart'},
    Drawing.MODE_MIXED: {'graph.vertex', 'graph.edge', 'geometry.point', 'geometry.segment', 'geometry.circle', 'geometry.polygon', 'text.latex', 'plot.series', 'plot.chart'},
}


def drawing_mode_allowed_types(mode):
    return DRAWING_MODE_ALLOWED_TYPES.get(mode, DRAWING_MODE_ALLOWED_TYPES[Drawing.MODE_MIXED])


def _validate_object_allowed_for_drawing_mode(drawing, object_type):
    """Pilnuje, żeby rysunek w trybie graf/geometria/wykresy dostawał tylko pasujące obiekty."""
    allowed = drawing_mode_allowed_types(drawing.mode)
    if object_type in allowed:
        return {}
    return {'type': f'Object type {object_type} is not allowed in drawing mode {drawing.mode}.'}


def _tikz_safe_identifier(value):
    """Zamienia object_id na identyfikator bezpieczny dla TikZ-a."""
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', str(value))
    if not safe:
        safe = 'obj'
    if safe[0].isdigit():
        safe = 'obj_' + safe
    return safe


def _tikz_coord_from_svg(x, y, *, canvas_height=520, scale=100):
    """Przelicza współrzędne SVG na współrzędne TikZ.

    W SVG oś Y rośnie w dół, a w TikZ-u standardowo rośnie w górę,
    dlatego odwracamy współrzędną y względem wysokości canvasa.
    """
    return float(x) / scale, (canvas_height - float(y)) / scale


def _format_tikz_number(value):
    formatted = f"{value:.2f}"
    return formatted.rstrip('0').rstrip('.') if '.' in formatted else formatted


def _tikz_point_reference_map(objects):
    """Zwraca mapę object_id -> DrawingObject dla punktów/wierzchołków."""
    return {
        obj.object_id: obj
        for obj in objects
        if obj.type in {'geometry.point', 'graph.vertex'}
    }


def build_drawing_tikz(drawing):
    """Buduje kod TikZ dla nowego strukturalnego Drawing.

    Obsługiwane typy:
    - geometry.point,
    - graph.vertex,
    - geometry.segment,
    - graph.edge,
    - geometry.circle,
    - geometry.polygon,
    - text.latex,
    - plot.series.

    Ten eksporter uwzględnia podstawowe style obiektów: stroke, fill,
    strokeWidth, radius, fontSize oraz showLabel. Jest to nadal prosty eksporter core,
    ale jego struktura jest przygotowana pod późniejsze eksportery pluginowe.
    """
    settings_data = normalized_drawing_settings(drawing)
    canvas_height = settings_data['canvas']['height']
    tikz_scale = settings_data['tikz']['scale']
    objects = list(drawing.drawing_objects.order_by('order', 'id'))
    points_by_id = _tikz_point_reference_map(objects)
    color_definitions = {}

    def tikz_color(value, default='black'):
        raw = str(value or default).strip()
        match = re.fullmatch(r'#?([0-9a-fA-F]{6})', raw)
        if match:
            hex_value = match.group(1).upper()
            name = f"mde{hex_value}"
            color_definitions[name] = f"\\definecolor{{{name}}}{{HTML}}{{{hex_value}}}"
            return name
        if re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_!.-]*', raw):
            return raw
        return default

    def tikz_style_number(value, default, *, minimum=0.1):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        if number < minimum:
            number = default
        return _format_tikz_number(number)

    def tikz_opacity(value, default=1):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        number = max(0, min(1, number))
        return _format_tikz_number(number)

    def tikz_dash(style):
        dash = (style or {}).get('lineDash')
        if dash == 'dashed':
            return 'dashed'
        if dash == 'dotted':
            return 'dotted'
        return ''

    def tikz_label_anchor(style, default='above right'):
        raw = (style or {}).get('labelPosition') or default
        mapping = {
            'above-right': 'above right',
            'above': 'above',
            'above-left': 'above left',
            'right': 'right',
            'center': '',
            'left': 'left',
            'below-right': 'below right',
            'below': 'below',
            'below-left': 'below left',
        }
        return mapping.get(raw, default)

    def label_node_options(style, default='above right'):
        style = style or {}
        has_custom_position = 'labelPosition' in style
        has_custom_font = 'fontSize' in style
        anchor = tikz_label_anchor(style, default) if has_custom_position or default != 'center' else ''
        font_size = tikz_style_number(style.get('fontSize'), 14, minimum=1)
        scale = tikz_style_number(float(font_size) / 14, 1, minimum=0.1)
        return style_options(anchor, f'scale={scale}' if has_custom_font else '')

    def style_options(*options):
        return ', '.join(option for option in options if option)

    body_lines = []

    def object_is_visible(obj):
        style = obj.style if isinstance(obj.style, dict) else {}
        return style.get('visible', True) is not False

    for obj in objects:
        if obj.type not in {'geometry.point', 'graph.vertex'}:
            continue

        data = obj.data or {}
        style = obj.style or {}
        try:
            x, y = _tikz_coord_from_svg(data.get('x'), data.get('y'), canvas_height=canvas_height, scale=tikz_scale)
        except (TypeError, ValueError):
            body_lines.append(f"  % Skipped {obj.object_id}: invalid point coordinates")
            continue

        name = _tikz_safe_identifier(obj.object_id)
        visible = object_is_visible(obj)
        label = data.get('label') or ''
        show_label = style.get('showLabel', True) is not False
        x_text = _format_tikz_number(x)
        y_text = _format_tikz_number(y)
        stroke = tikz_color(style.get('stroke'), 'black')
        fill = tikz_color(style.get('fill'), 'white' if obj.type == 'graph.vertex' else 'black')
        stroke_width = tikz_style_number(style.get('strokeWidth'), 1.0)
        radius_cm = tikz_style_number(float(style.get('radius', 5)) / 100, 0.05)

        if not visible:
            body_lines.append(f"  \\coordinate ({name}) at ({x_text}, {y_text});")
            continue

        if obj.type == 'graph.vertex':
            minimum_size = tikz_style_number(2 * float(style.get('radius', 12)) / 100, 0.24)
            text = f"$ {label} $" if label and show_label else ""
            options = style_options(
                'circle',
                f'draw={stroke}',
                f'fill={fill}',
                f'line width={stroke_width}pt',
                f'draw opacity={tikz_opacity(style.get('strokeOpacity'), 1)}' if tikz_opacity(style.get('strokeOpacity'), 1) != '1' else '',
                f'fill opacity={tikz_opacity(style.get('fillOpacity'), 1)}' if tikz_opacity(style.get('fillOpacity'), 1) != '1' else '',
                'inner sep=0pt',
                f'minimum size={minimum_size}cm',
            )
            body_lines.append(f"  \\node[{options}] ({name}) at ({x_text}, {y_text}) {{{text}}};")
        else:
            body_lines.append(f"  \\coordinate ({name}) at ({x_text}, {y_text});")
            options = style_options(
                f'fill={fill}',
                f'draw={stroke}',
                f'line width={stroke_width}pt',
                f'draw opacity={tikz_opacity(style.get('strokeOpacity'), 1)}' if tikz_opacity(style.get('strokeOpacity'), 1) != '1' else '',
                f'fill opacity={tikz_opacity(style.get('fillOpacity'), 1)}' if tikz_opacity(style.get('fillOpacity'), 1) != '1' else '',
            )
            body_lines.append(f"  \\filldraw[{options}] ({name}) circle ({radius_cm}cm);")
            if label and show_label:
                label_options = label_node_options(style, 'above right')
                body_lines.append(f"  \\node[{label_options}] at ({name}) {{$ {label} $}};")

    for obj in objects:
        if obj.type != 'text.latex':
            continue

        data = obj.data or {}
        style = obj.style or {}
        if not object_is_visible(obj):
            continue
        if style.get('showLabel', True) is False:
            continue
        try:
            x, y = _tikz_coord_from_svg(data.get('x'), data.get('y'), canvas_height=canvas_height, scale=tikz_scale)
        except (TypeError, ValueError):
            body_lines.append(f"  % Skipped {obj.object_id}: invalid text coordinates")
            continue

        text = data.get('text') or data.get('label') or ''
        if not text:
            continue

        x_text = _format_tikz_number(x)
        y_text = _format_tikz_number(y)
        color = tikz_color(style.get('fill') or style.get('stroke'), 'black')
        font_size = tikz_style_number(style.get('fontSize'), 18, minimum=1)
        scale = tikz_style_number(float(font_size) / 18, 1, minimum=0.1)
        options = style_options('anchor=center', f'text={color}', f'scale={scale}', f'opacity={tikz_opacity(style.get('fillOpacity'), 1)}')
        body_lines.append(f"  \\node[{options}] at ({x_text}, {y_text}) {{$ {text} $}};")

    for obj in objects:
        if obj.type != 'geometry.circle':
            continue

        data = obj.data or {}
        style = obj.style or {}
        if not object_is_visible(obj):
            continue
        center = points_by_id.get(data.get('center'))
        point = points_by_id.get(data.get('point'))
        if not center or not point:
            body_lines.append(f"  % Skipped {obj.object_id}: missing center or circle point")
            continue

        center_data = center.data or {}
        point_data = point.data or {}
        try:
            cx, cy = _tikz_coord_from_svg(center_data.get('x'), center_data.get('y'), canvas_height=canvas_height, scale=tikz_scale)
            px, py = _tikz_coord_from_svg(point_data.get('x'), point_data.get('y'), canvas_height=canvas_height, scale=tikz_scale)
        except (TypeError, ValueError):
            body_lines.append(f"  % Skipped {obj.object_id}: invalid circle point coordinates")
            continue

        radius = ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
        if radius <= 0:
            body_lines.append(f"  % Skipped {obj.object_id}: zero circle radius")
            continue

        x_text = _format_tikz_number(cx)
        y_text = _format_tikz_number(cy)
        radius_text = _format_tikz_number(radius)
        stroke = tikz_color(style.get('stroke'), 'black')
        stroke_width = tikz_style_number(style.get('strokeWidth'), 1.0)
        fill_value = str(style.get('fill', 'none')).strip()
        fill = None if fill_value == 'none' else tikz_color(fill_value, 'none')
        options = style_options(f'draw={stroke}', f'line width={stroke_width}pt', tikz_dash(style), f'draw opacity={tikz_opacity(style.get('strokeOpacity'), 1)}' if tikz_opacity(style.get('strokeOpacity'), 1) != '1' else '', f'fill opacity={tikz_opacity(style.get('fillOpacity'), 1)}' if fill and tikz_opacity(style.get('fillOpacity'), 1) != '1' else '', f'fill={fill}' if fill else '')
        command = '\\filldraw' if fill else '\\draw'
        body_lines.append(f"  {command}[{options}] ({x_text}, {y_text}) circle ({radius_text}cm);")

        visible = object_is_visible(obj)
        label = data.get('label') or ''
        show_label = style.get('showLabel', True) is not False
        if label and show_label:
            if 'labelPosition' in style or 'fontSize' in style:
                label_options = label_node_options(style, 'right')
                body_lines.append(f"  \\node[{label_options}] at ({x_text}, {y_text}) {{$ {label} $}};")
            else:
                label_x = _format_tikz_number(cx + radius)
                body_lines.append(f"  \\node[right] at ({label_x}, {y_text}) {{$ {label} $}};")

    for obj in objects:
        if obj.type != 'geometry.polygon':
            continue

        data = obj.data or {}
        style = obj.style or {}
        if not object_is_visible(obj):
            continue
        point_ids = data.get('points') or []
        if not isinstance(point_ids, list) or len(point_ids) < 3:
            body_lines.append(f"  % Skipped {obj.object_id}: polygon requires at least three points")
            continue

        polygon_points = []
        missing_point = False
        for point_id in point_ids:
            point = points_by_id.get(point_id)
            if not point:
                missing_point = True
                break
            polygon_points.append(point)
        if missing_point:
            body_lines.append(f"  % Skipped {obj.object_id}: missing polygon point")
            continue

        stroke = tikz_color(style.get('stroke'), 'black')
        stroke_width = tikz_style_number(style.get('strokeWidth'), 1.0)
        fill_value = str(style.get('fill', 'none')).strip()
        fill = None if fill_value == 'none' else tikz_color(fill_value, 'none')
        command = '\\filldraw' if fill else '\\draw'
        options = style_options(f'draw={stroke}', f'line width={stroke_width}pt', tikz_dash(style), f'draw opacity={tikz_opacity(style.get('strokeOpacity'), 1)}' if tikz_opacity(style.get('strokeOpacity'), 1) != '1' else '', f'fill opacity={tikz_opacity(style.get('fillOpacity'), 1)}' if fill and tikz_opacity(style.get('fillOpacity'), 1) != '1' else '', f'fill={fill}' if fill else '')
        path = ' -- '.join(f"({_tikz_safe_identifier(point.object_id)})" for point in polygon_points)
        if data.get('closed', True) is not False:
            path += ' -- cycle'
        body_lines.append(f"  {command}[{options}] {path};")

        visible = object_is_visible(obj)
        label = data.get('label') or ''
        show_label = style.get('showLabel', True) is not False
        if label and show_label:
            coords = []
            for point in polygon_points:
                try:
                    coords.append(_tikz_coord_from_svg((point.data or {}).get('x'), (point.data or {}).get('y'), canvas_height=canvas_height, scale=tikz_scale))
                except (TypeError, ValueError):
                    coords = []
                    break
            if coords:
                label_x = _format_tikz_number(sum(x for x, _ in coords) / len(coords))
                label_y = _format_tikz_number(sum(y for _, y in coords) / len(coords))
                label_options = label_node_options(style, 'center')
                if label_options:
                    body_lines.append(f"  \\node[{label_options}] at ({label_x}, {label_y}) {{$ {label} $}};")
                else:
                    body_lines.append(f"  \\node at ({label_x}, {label_y}) {{$ {label} $}};")

    for obj in objects:
        if obj.type not in {'geometry.segment', 'graph.edge'}:
            continue

        data = obj.data or {}
        style = obj.style or {}
        if not object_is_visible(obj):
            continue
        source_id = data.get('source')
        target_id = data.get('target')
        source = points_by_id.get(source_id)
        target = points_by_id.get(target_id)
        if not source or not target:
            body_lines.append(f"  % Skipped {obj.object_id}: missing source or target")
            continue

        source_name = _tikz_safe_identifier(source.object_id)
        target_name = _tikz_safe_identifier(target.object_id)
        arrow = '->' if style.get('directed') else '-'
        stroke = tikz_color(style.get('stroke'), 'black')
        stroke_width = tikz_style_number(style.get('strokeWidth'), 1.0)
        visible = object_is_visible(obj)
        label = data.get('label') or ''
        show_label = style.get('showLabel', True) is not False
        label_options = label_node_options(style, 'above')
        label_part = f" node[midway, {label_options}] {{$ {label} $}}" if label and show_label else ''
        options = style_options(arrow, f'draw={stroke}', f'line width={stroke_width}pt', tikz_dash(style), f'draw opacity={tikz_opacity(style.get('strokeOpacity'), 1)}' if tikz_opacity(style.get('strokeOpacity'), 1) != '1' else '')
        body_lines.append(f"  \\draw[{options}] ({source_name}) --{label_part} ({target_name});")

    def axis_options_from(axis):
        axis = axis if isinstance(axis, dict) else {}
        axis_title = axis.get('title') or ''
        x_label = axis.get('xLabel') or 'x'
        y_label = axis.get('yLabel') or 'y'
        axis_options = [
            'axis lines=middle',
            'grid=major',
            f'xlabel={{${x_label}$}}',
            f'ylabel={{${y_label}$}}',
            'legend style={at={(1.02,1)}, anchor=north west}',
        ]
        if axis_title:
            axis_options.insert(0, f'title={{${axis_title}$}}')
        for key, pgf_key in (('xMin', 'xmin'), ('xMax', 'xmax'), ('yMin', 'ymin'), ('yMax', 'ymax')):
            value = axis.get(key)
            if value not in ('', None):
                try:
                    axis_options.append(f'{pgf_key}={_format_tikz_number(float(value))}')
                except (TypeError, ValueError):
                    pass
        return axis_options

    def add_axis_start(axis):
        body_lines.append('  \\begin{axis}[')
        for option in axis_options_from(axis):
            body_lines.append(f'    {option},')
        body_lines.append('  ]')

    def add_series_to_axis(series, inherited_style=None):
        inherited_style = inherited_style or {}
        raw_points = series.get('points') or []
        coordinates = []
        has_error_bars = False
        for pair in raw_points:
            try:
                x_value = float(pair[0])
                y_value = float(pair[1])
            except (TypeError, ValueError, IndexError):
                continue
            if isinstance(pair, (list, tuple)) and len(pair) >= 4:
                try:
                    x_error = float(pair[2])
                    y_error = float(pair[3])
                    if x_error >= 0 and y_error >= 0:
                        has_error_bars = True
                        coordinates.append(f"({_format_tikz_number(x_value)}, {_format_tikz_number(y_value)}) +- ({_format_tikz_number(x_error)}, {_format_tikz_number(y_error)})")
                        continue
                except (TypeError, ValueError):
                    pass
            coordinates.append(f"({_format_tikz_number(x_value)}, {_format_tikz_number(y_value)})")
        if not coordinates:
            return False
        series_style = series.get('style') if isinstance(series.get('style'), dict) else {}
        stroke = tikz_color(series_style.get('stroke') or inherited_style.get('stroke'), 'blue')
        stroke_width = tikz_style_number(series_style.get('strokeWidth') or inherited_style.get('strokeWidth'), 1.0)
        plot_type = series.get('plotType', 'line')
        mark = '*' if plot_type in {'scatter', 'line_markers'} or series_style.get('showPoints') or inherited_style.get('showPoints') else 'none'
        only_marks = 'only marks, ' if plot_type == 'scatter' else ''
        error_options = 'error bars/.cd, y dir=both, y explicit, x dir=both, x explicit, ' if has_error_bars else ''
        body_lines.append(f"    \\addplot+[{only_marks}color={stroke}, line width={stroke_width}pt, {tikz_dash(series_style) or tikz_dash(inherited_style)}, opacity={tikz_opacity(series_style.get('strokeOpacity') or inherited_style.get('strokeOpacity'), 1)}, mark={mark}, {error_options}] coordinates {{")
        for coordinate in coordinates:
            body_lines.append(f"      {coordinate}")
        body_lines.append('    };')
        label = series.get('label') or ''
        if label:
            body_lines.append(f"    \\addlegendentry{{$ {label} $}}")
        return True

    def add_function_to_axis(function):
        expression = str(function.get('expression') or '').strip()
        if not expression:
            return False
        color = tikz_color(function.get('color'), 'red')
        domain_min = function.get('domainMin', -5)
        domain_max = function.get('domainMax', 5)
        try:
            domain_min = _format_tikz_number(float(domain_min))
            domain_max = _format_tikz_number(float(domain_max))
        except (TypeError, ValueError):
            domain_min, domain_max = '-5', '5'
        samples = function.get('samples', 100)
        try:
            samples = int(samples)
            if samples < 2:
                samples = 100
        except (TypeError, ValueError):
            samples = 100
        body_lines.append('    \\addplot [')
        body_lines.append(f'      domain={domain_min}:{domain_max},')
        body_lines.append(f'      samples={samples},')
        body_lines.append(f'      color={color},')
        body_lines.append('    ]')
        body_lines.append(f'    {{{expression}}};')
        label = function.get('label') or expression
        if label:
            body_lines.append(f"    \\addlegendentry{{$ {label} $}}")
        return True

    for obj in objects:
        if obj.type != 'plot.chart':
            continue
        data = obj.data or {}
        style = obj.style or {}
        if not object_is_visible(obj):
            continue
        series_list = data.get('series') if isinstance(data.get('series'), list) else []
        functions = data.get('functions') if isinstance(data.get('functions'), list) else []
        add_axis_start(data.get('axis') if isinstance(data.get('axis'), dict) else {})
        rendered_any = False
        for series in series_list:
            if isinstance(series, dict):
                rendered_any = add_series_to_axis(series, style) or rendered_any
        for function in functions:
            if isinstance(function, dict):
                rendered_any = add_function_to_axis(function) or rendered_any
        if not rendered_any:
            body_lines.append(f"    % Skipped {obj.object_id}: plot.chart has no valid series or functions")
        body_lines.append('  \\end{axis}')

    for obj in objects:
        if obj.type != 'plot.series':
            continue

        data = obj.data or {}
        style = obj.style or {}
        if not object_is_visible(obj):
            continue
        add_axis_start(data.get('axis') if isinstance(data.get('axis'), dict) else {})
        rendered = add_series_to_axis({
            'points': data.get('points') or [],
            'label': data.get('label') or '',
            'plotType': data.get('plotType', 'line'),
            'style': style,
        }, style)
        if not rendered:
            body_lines.append(f"    % Skipped {obj.object_id}: plot.series has no valid points")
        body_lines.append('  \\end{axis}')


    lines = ['% Generated by Mathematical Drawing Editor']
    if any(obj.type in {'plot.series', 'plot.chart'} and object_is_visible(obj) for obj in objects):
        lines.append('% For plot.series/plot.chart, include \\usepackage{pgfplots} and \\pgfplotsset{compat=1.18} in the LaTeX preamble.')
    lines.extend(color_definitions.values())
    lines.append('\\begin{tikzpicture}[x=1cm,y=1cm]')
    lines.extend(body_lines)
    lines.append('\\end{tikzpicture}')
    return '\n'.join(lines) + '\n'



def build_drawing_json_document(drawing):
    """Buduje strukturalny dokument JSON dla całego rysunku."""
    return {
        'schema_version': 1,
        'title': drawing.title,
        'mode': drawing.mode,
        'metadata': drawing.metadata if isinstance(drawing.metadata, dict) else {},
        'settings': normalized_drawing_settings(drawing),
        'objects': [
            {
                'object_id': obj.object_id,
                'type': obj.type,
                'data': obj.data if isinstance(obj.data, dict) else {},
                'style': obj.style if isinstance(obj.style, dict) else {},
                'order': obj.order,
            }
            for obj in drawing.drawing_objects.order_by('order', 'id')
        ],
    }


def _validate_import_document(document):
    """Wstępna walidacja formatu importowanego pliku JSON."""
    errors = {}
    if not isinstance(document, dict):
        return {'json': 'Imported JSON must be an object.'}

    title = document.get('title', '')
    if title is not None and not isinstance(title, str):
        errors['title'] = 'title must be a string.'

    mode = document.get('mode') or Drawing.MODE_GRAPH
    valid_modes = {choice[0] for choice in Drawing.MODE_CHOICES}
    if mode not in valid_modes:
        errors['mode'] = 'mode must be one of: graph, geometry, plot.'

    settings_data, settings_errors = _validate_drawing_settings_payload(document.get('settings', {}))
    if settings_errors:
        errors.update({f'settings.{key}': value for key, value in settings_errors.items()})

    metadata = document.get('metadata', {})
    if metadata is not None and not isinstance(metadata, dict):
        errors['metadata'] = 'metadata must be a JSON object.'

    objects = document.get('objects', [])
    if not isinstance(objects, list):
        errors['objects'] = 'objects must be a list.'
        return errors

    seen_ids = set()
    for index, raw_obj in enumerate(objects):
        prefix = f'objects[{index}]'
        if not isinstance(raw_obj, dict):
            errors[prefix] = 'Each object must be a JSON object.'
            continue
        obj_errors = _validate_object_payload(raw_obj)
        for key, value in obj_errors.items():
            errors[f'{prefix}.{key}'] = value
        object_id = raw_obj.get('object_id')
        if not isinstance(object_id, str) or not object_id.strip():
            errors[f'{prefix}.object_id'] = 'object_id is required for imported objects.'
        elif object_id in seen_ids:
            errors[f'{prefix}.object_id'] = 'object_id must be unique inside imported file.'
        else:
            seen_ids.add(object_id)

    return errors


def import_drawing_from_document(*, user, document, title_override=None):
    """Tworzy nowy Drawing z dokumentu JSON.

    Referencje między obiektami są walidowane przy tworzeniu, więc obiekty zależne
    muszą występować po obiektach, na które wskazują. Eksport z aplikacji już
    zapisuje obiekty w poprawnej kolejności.
    """
    errors = _validate_import_document(document)
    if errors:
        raise ValidationError(errors)

    title = (title_override or document.get('title') or 'Imported drawing').strip()
    mode = document.get('mode') or Drawing.MODE_GRAPH
    metadata = document.get('metadata') if isinstance(document.get('metadata'), dict) else {}
    settings_data, _ = _validate_drawing_settings_payload(document.get('settings', {}))
    objects = document.get('objects', [])

    with transaction.atomic():
        drawing = Drawing.objects.create(
            user=user,
            title=title,
            mode=mode,
            metadata={
                **metadata,
                'imported_from_json': True,
                'schema_version': document.get('schema_version', 1),
            },
            settings=settings_data,
        )

        for index, raw_obj in enumerate(objects):
            payload = {
                'object_id': raw_obj['object_id'].strip(),
                'type': raw_obj['type'].strip(),
                'data': raw_obj.get('data', {}),
                'style': raw_obj.get('style', {}),
                'order': raw_obj.get('order', index),
            }
            mode_errors = _validate_object_allowed_for_drawing_mode(drawing, payload['type'])
            if mode_errors:
                raise ValidationError({f'objects[{index}].type': mode_errors['type']})
            reference_errors = _validate_object_references(drawing, payload['type'], payload['data'])
            if reference_errors:
                raise ValidationError({f'objects[{index}].{key}': value for key, value in reference_errors.items()})
            DrawingObject.objects.create(
                drawing=drawing,
                object_id=payload['object_id'],
                type=payload['type'],
                data=payload['data'],
                style=payload['style'],
                order=int(payload['order']),
            )

    return drawing



def register(request):
    """Widok rejestracji nowego użytkownika"""
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'routes/register.html', {'form': form})

class RouteListView(LoginRequiredMixin, ListView):
    """Widok listy tras użytkownika"""
    model = Route
    template_name = 'routes/route_list.html'
    
    def get_queryset(self):
        return Route.objects.filter(user=self.request.user).order_by('-created_at')

class RouteCreateView(LoginRequiredMixin, CreateView):
    """Widok tworzenia nowej trasy"""
    model = Route
    fields = ['title', 'background']
    template_name = 'routes/route_form.html'
    
    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)
        
    def get_success_url(self):
        return reverse('route_detail', kwargs={'pk': self.object.pk})

class RouteDetailView(LoginRequiredMixin, DetailView):
    model = Route
    template_name = 'routes/route_detail.html'

    def get_queryset(self):
        return Route.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['style_form'] = RouteStyleForm(instance=self.object)
        return context



class DrawingListView(LoginRequiredMixin, ListView):
    """Lista nowych, ogólnych rysunków użytkownika."""
    model = Drawing
    template_name = 'routes/drawing_list.html'
    context_object_name = 'drawings'

    def get_queryset(self):
        return Drawing.objects.filter(user=self.request.user)


class DrawingCreateView(LoginRequiredMixin, CreateView):
    """Tworzenie pustego rysunku strukturalnego."""
    model = Drawing
    fields = ['title', 'mode']
    template_name = 'routes/drawing_form.html'

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.metadata = {
            'schema_version': 1,
            'description': 'Structured drawing document',
        }
        form.instance.settings = normalized_drawing_settings({})
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('drawing_detail', kwargs={'pk': self.object.pk})


class DrawingDetailView(LoginRequiredMixin, DetailView):
    """Szczegóły rysunku strukturalnego.

    Na tym etapie to prosty podgląd danych. W kolejnych krokach ten widok
    stanie się edytorem canvasowym opartym o DrawingObject.
    """
    model = Drawing
    template_name = 'routes/drawing_detail.html'
    context_object_name = 'drawing'

    def get_queryset(self):
        return Drawing.objects.filter(user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['objects'] = self.object.drawing_objects.order_by('order', 'id')
        drawing_settings = normalized_drawing_settings(self.object)
        canvas = drawing_settings['canvas']
        context['drawing_settings'] = drawing_settings
        context['canvas_width'] = canvas['width']
        context['canvas_height'] = canvas['height']
        context['grid_x'] = range(0, canvas['width'] + 1, canvas['gridSize'])
        context['grid_y'] = range(0, canvas['height'] + 1, canvas['gridSize'])
        context['allowed_object_types'] = drawing_mode_allowed_types(self.object.mode)
        context['is_graph_mode'] = self.object.mode in (Drawing.MODE_GRAPH, Drawing.MODE_MIXED)
        context['is_geometry_mode'] = self.object.mode in (Drawing.MODE_GEOMETRY, Drawing.MODE_MIXED)
        context['is_text_mode'] = self.object.mode == Drawing.MODE_MIXED
        context['is_plot_mode'] = self.object.mode in (Drawing.MODE_PLOT, Drawing.MODE_MIXED)
        return context




@login_required
@require_POST
def duplicate_drawing(request, pk):
    """Tworzy pełną kopię rysunku wraz z obiektami i ustawieniami."""
    drawing = get_object_or_404(Drawing, id=pk, user=request.user)
    with transaction.atomic():
        copy = Drawing.objects.create(
            user=request.user,
            title=f"Kopia: {drawing.title}",
            mode=drawing.mode,
            metadata={
                **(drawing.metadata if isinstance(drawing.metadata, dict) else {}),
                'duplicated_from': drawing.id,
                'schema_version': 1,
            },
            settings=normalized_drawing_settings(drawing),
        )
        for obj in drawing.drawing_objects.order_by('order', 'id'):
            DrawingObject.objects.create(
                drawing=copy,
                object_id=obj.object_id,
                type=obj.type,
                data=obj.data if isinstance(obj.data, dict) else {},
                style=obj.style if isinstance(obj.style, dict) else {},
                order=obj.order,
            )
    return redirect('drawing_detail', pk=copy.pk)

class DrawingDeleteView(LoginRequiredMixin, DeleteView):
    model = Drawing
    success_url = reverse_lazy('drawing_list')
    template_name = 'routes/drawing_confirm_delete.html'
    context_object_name = 'drawing'

    def get_queryset(self):
        return Drawing.objects.filter(user=self.request.user)


@login_required
def export_drawing_tikz(request, pk):
    """Eksportuje strukturalny Drawing do kodu TikZ."""
    drawing = get_object_or_404(Drawing, id=pk, user=request.user)
    tikz_content = build_drawing_tikz(drawing)
    response = HttpResponse(tikz_content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="drawing_{drawing.id}.tex"'
    return response


@login_required
@require_http_methods(["GET"])
def drawing_tikz_preview(request, pk):
    """Zwraca kod TikZ jako JSON do podglądu i kopiowania w edytorze."""
    drawing = get_object_or_404(Drawing, id=pk, user=request.user)
    tikz_content = build_drawing_tikz(drawing)
    return JsonResponse({
        'success': True,
        'drawing_id': drawing.id,
        'tikz': tikz_content,
    })


@login_required
@require_http_methods(["GET"])
def export_drawing_json(request, pk):
    """Eksportuje cały rysunek jako strukturalny plik JSON."""
    drawing = get_object_or_404(Drawing, id=pk, user=request.user)
    document = build_drawing_json_document(drawing)
    content = json.dumps(document, ensure_ascii=False, indent=2)
    response = HttpResponse(content, content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="drawing_{drawing.id}.json"'
    return response


@login_required
@require_http_methods(["GET", "POST"])
def import_drawing_json(request):
    """Importuje plik JSON jako nowy rysunek użytkownika."""
    context = {'errors': None}
    if request.method == 'GET':
        return render(request, 'routes/drawing_import.html', context)

    uploaded = request.FILES.get('json_file')
    raw_json = request.POST.get('json_text', '').strip()
    title_override = request.POST.get('title', '').strip() or None

    if uploaded:
        try:
            raw_json = uploaded.read().decode('utf-8')
        except UnicodeDecodeError:
            context['errors'] = {'json_file': 'Plik musi być poprawnym tekstowym JSON-em w kodowaniu UTF-8.'}
            return render(request, 'routes/drawing_import.html', context, status=400)

    if not raw_json:
        context['errors'] = {'json': 'Wybierz plik JSON albo wklej treść JSON.'}
        return render(request, 'routes/drawing_import.html', context, status=400)

    try:
        document = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        context['errors'] = {'json': f'Niepoprawny JSON: {exc.msg}.'}
        return render(request, 'routes/drawing_import.html', context, status=400)

    try:
        drawing = import_drawing_from_document(
            user=request.user,
            document=document,
            title_override=title_override,
        )
    except ValidationError as exc:
        context['errors'] = exc.message_dict if hasattr(exc, 'message_dict') else {'import': exc.messages}
        return render(request, 'routes/drawing_import.html', context, status=400)

    return redirect('drawing_detail', pk=drawing.pk)


@login_required
@require_http_methods(["GET", "PATCH", "PUT"])
def drawing_settings_api(request, pk):
    """Zwraca albo aktualizuje ustawienia rysunku: canvas, siatkę, snap i skalę TikZ."""
    drawing = get_object_or_404(Drawing, id=pk, user=request.user)

    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'drawing_id': drawing.id,
            'settings': normalized_drawing_settings(drawing),
        })

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({'success': False, 'errors': {'json': str(exc)}}, status=400)

    settings_data, errors = _validate_drawing_settings_payload(payload)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    drawing.settings = settings_data
    drawing.save(update_fields=['settings', 'updated_at'])
    return JsonResponse({
        'success': True,
        'drawing_id': drawing.id,
        'settings': normalized_drawing_settings(drawing),
    })


@login_required
@require_http_methods(["GET", "POST"])
def drawing_objects_collection(request, drawing_id):
    """Lista obiektów rysunku albo utworzenie nowego DrawingObject.

    GET zwraca wszystkie obiekty danego rysunku.
    POST tworzy nowy obiekt. To jest pierwszy endpoint, którego będzie używał
    przyszły edytor canvasowy i przyszłe pluginy.
    """
    drawing = get_object_or_404(Drawing, id=drawing_id, user=request.user)

    if request.method == 'GET':
        objects = [_serialize_drawing_object(obj) for obj in drawing.drawing_objects.order_by('order', 'id')]
        return JsonResponse({
            'success': True,
            'drawing_id': drawing.id,
            'objects': objects,
        })

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({'success': False, 'errors': {'json': str(exc)}}, status=400)

    errors = _validate_object_payload(payload)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    object_id = payload.get('object_id') or f"obj_{uuid.uuid4().hex[:12]}"
    object_id = object_id.strip()

    if DrawingObject.objects.filter(drawing=drawing, object_id=object_id).exists():
        return JsonResponse({
            'success': False,
            'errors': {'object_id': 'object_id must be unique inside this drawing.'},
        }, status=400)

    if 'order' in payload:
        order = int(payload['order'])
    else:
        max_order = drawing.drawing_objects.aggregate(max_order=Max('order'))['max_order']
        order = 0 if max_order is None else max_order + 1

    object_type = payload['type'].strip()
    mode_errors = _validate_object_allowed_for_drawing_mode(drawing, object_type)
    if mode_errors:
        return JsonResponse({'success': False, 'errors': mode_errors}, status=400)

    reference_errors = _validate_object_references(
        drawing,
        object_type,
        payload.get('data', {}),
    )
    if reference_errors:
        return JsonResponse({'success': False, 'errors': reference_errors}, status=400)

    obj = DrawingObject.objects.create(
        drawing=drawing,
        object_id=object_id,
        type=object_type,
        data=payload.get('data', {}),
        style=payload.get('style', {}),
        order=order,
    )

    return JsonResponse({
        'success': True,
        'object': _serialize_drawing_object(obj),
    }, status=201)


@login_required
@require_http_methods(["GET", "PATCH", "PUT", "DELETE"])
def drawing_object_detail(request, drawing_id, object_id):
    """Szczegóły, aktualizacja albo usunięcie pojedynczego DrawingObject."""
    drawing = get_object_or_404(Drawing, id=drawing_id, user=request.user)
    obj = get_object_or_404(DrawingObject, drawing=drawing, object_id=object_id)

    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'object': _serialize_drawing_object(obj),
        })

    if request.method == 'DELETE':
        obj.delete()
        return JsonResponse({
            'success': True,
            'deleted_object_id': object_id,
        })

    try:
        payload = _parse_json_body(request)
    except ValueError as exc:
        return JsonResponse({'success': False, 'errors': {'json': str(exc)}}, status=400)

    partial = request.method == 'PATCH'
    errors = _validate_object_payload(payload, partial=partial)
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    proposed_type = payload['type'].strip() if 'type' in payload else obj.type
    mode_errors = _validate_object_allowed_for_drawing_mode(drawing, proposed_type)
    if mode_errors:
        return JsonResponse({'success': False, 'errors': mode_errors}, status=400)

    proposed_data = payload.get('data', obj.data if partial else {})
    reference_errors = _validate_object_references(drawing, proposed_type, proposed_data)
    if reference_errors:
        return JsonResponse({'success': False, 'errors': reference_errors}, status=400)

    if request.method == 'PUT':
        # PUT traktujemy jako pełną podmianę pól wspólnych obiektu.
        obj.type = payload['type'].strip()
        obj.data = payload.get('data', {})
        obj.style = payload.get('style', {})
        if 'order' in payload:
            obj.order = int(payload['order'])
    else:
        # PATCH zmienia tylko przekazane pola.
        if 'type' in payload:
            obj.type = payload['type'].strip()
        if 'data' in payload:
            obj.data = payload['data']
        if 'style' in payload:
            obj.style = payload['style']
        if 'order' in payload:
            obj.order = int(payload['order'])

    obj.save()
    return JsonResponse({
        'success': True,
        'object': _serialize_drawing_object(obj),
    })


class RouteDeleteView(LoginRequiredMixin, DeleteView):
    """Widok usuwania trasy"""
    model = Route
    success_url = reverse_lazy('route_list')
    template_name = 'routes/route_confirm_delete.html'

    def get_queryset(self):
        return Route.objects.filter(user=self.request.user)







@login_required
@require_POST
def delete_point(request, pk):
    """Usuwa punkt należący do zalogowanego użytkownika i renumeruje pozostałe punkty."""
    point = get_object_or_404(Point, id=pk, route__user=request.user)
    route_id = point.route.id
    point.delete()

    for index, remaining_point in enumerate(Point.objects.filter(route_id=route_id).order_by('order'), start=1):
        if remaining_point.order != index:
            remaining_point.order = index
            remaining_point.save(update_fields=['order'])

    return redirect('route_detail', pk=route_id)


def _wants_json(request):
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )


@login_required
def add_point(request, route_id):
    """Dodaje punkt do trasy. Dla AJAX zwraca JSON, dla zwykłego POST robi redirect."""
    route = get_object_or_404(Route, id=route_id, user=request.user)

    if request.method != 'POST':
        if _wants_json(request):
            return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)
        return redirect('route_detail', pk=route_id)

    try:
        x = int(request.POST.get('x', ''))
        y = int(request.POST.get('y', ''))
    except (TypeError, ValueError):
        if _wants_json(request):
            return JsonResponse({'success': False, 'error': 'Coordinates must be integers'}, status=400)
        return redirect('route_detail', pk=route_id)

    if x < 0 or y < 0:
        if _wants_json(request):
            return JsonResponse({'success': False, 'error': 'Coordinates cannot be negative'}, status=400)
        return redirect('route_detail', pk=route_id)

    point = Point.objects.create(
        route=route,
        x=x,
        y=y,
        order=route.points.count() + 1,
    )

    if _wants_json(request):
        return JsonResponse({
            'success': True,
            'point': {
                'id': point.id,
                'x': point.x,
                'y': point.y,
                'order': point.order,
            },
        }, status=201)

    return redirect('route_detail', pk=route_id)
    
    




@login_required
@require_POST
def delete_edge(request, pk):
    edge = get_object_or_404(Edge, id=pk, route__user=request.user)
    route_id = edge.route.id
    edge.delete()
    return redirect('route_detail', pk=route_id)


@login_required
def add_edge(request, route_id):
    """Widok dodawania krawędzi do trasy"""
    route = get_object_or_404(Route, id=route_id, user=request.user)
    
    if request.method == 'POST':
        try:
            start_point_id = request.POST.get('start_point')
            end_point_id = request.POST.get('end_point')
            
            if not start_point_id or not end_point_id:
                raise ValidationError("Both points must be selected")
                
            if start_point_id == end_point_id:
                raise ValidationError("Start and end points cannot be the same")
            
            start_point = Point.objects.get(id=start_point_id, route=route)
            end_point = Point.objects.get(id=end_point_id, route=route)
            
            # Sprawdź czy krawędź już istnieje
            if Edge.objects.filter(route=route, start_point=start_point, end_point=end_point).exists():
                raise ValidationError("This edge already exists")
            
            edge = Edge.objects.create(
                route=route,
                start_point=start_point,
                end_point=end_point
            )
            
            return JsonResponse({
                'success': True,
                'edge_id': edge.id,
                'message': 'Edge added successfully'
            })
            
        except Point.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Selected point does not exist'
            }, status=400)
        except ValidationError as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)
    
    return JsonResponse({
        'success': False,
        'error': 'Invalid request method'
    }, status=405)





   
@login_required
def update_route_style(request, route_id):
    route = get_object_or_404(Route, id=route_id, user=request.user)
    if request.method == 'POST':
        form = RouteStyleForm(request.POST, instance=route)
        if form.is_valid():
            form.save()
            return JsonResponse({'success': True})
        return JsonResponse({'success': False, 'errors': form.errors}, status=400)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)




@login_required
def export_png(request, route_id):
    route = get_object_or_404(Route, id=route_id, user=request.user)
    
    try:
        # Otwórz obraz tła
        bg_image = Image.open(route.background.image.path)
        draw = ImageDraw.Draw(bg_image)
        
        # Użyj domyślnej czcionki (możesz też użyć konkretnej czcionki jeśli potrzebujesz)
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except:
            font = ImageFont.load_default()  # Awaryjna czcionka jeśli arial.ttf nie istnieje

        # Narysuj krawędzie
        for edge in route.edges.all():
        
            # Niestety ImageDraw nie obsługuje dash bezpośrednio, więc rysujemy linię ciągłą
            draw.line(
                [(edge.start_point.x, edge.start_point.y), 
                 (edge.end_point.x, edge.end_point.y)],
                fill=route.edge_color, 
                width=3
            )

        # Narysuj punkty
        for point in route.points.all():
            # Okrąg
            draw.ellipse(
                [(point.x - 15, point.y - 15),
                 (point.x + 15, point.y + 15)],
                fill=route.vertex_color
            )
            # Numer
            draw.text(
                (point.x, point.y), 
                str(point.order),
                fill=route.vertex_text_color,
                font=font,
                anchor='mm'  # Wyśrodkuj tekst
            )

        # Zapisz do bufora
        buffer = io.BytesIO()
        bg_image.save(buffer, format='PNG')
        buffer.seek(0)
        
        response = HttpResponse(buffer, content_type='image/png')
        response['Content-Disposition'] = f'attachment; filename="route_{route.id}.png"'
        return response

    except Exception as e:
        return HttpResponse(f"Error generating PNG: {str(e)}", status=500)
    

    
    







@login_required
def export_latex(request, route_id):
    route = get_object_or_404(Route, id=route_id, user=request.user)
    
    latex_template = """
\\documentclass{{article}}
\\usepackage{{tikz}}
\\begin{{document}}

\\begin{{figure}}[h]
\\centering
\\begin{{tikzpicture}}[x=4cm,y=4cm] 
  \\tikzset{{     
    node/.style={{circle,draw,minimum size=0.75cm,inner sep=0}}, 
    edge/.style={{sloped,above,font=\\footnotesize}}
  }}
  {nodes}
  
  \\path[draw,thick]
  {edges}
  ;
\\end{{tikzpicture}}
\\caption{{Route: {title}}}
\\label{{fig:route_{id}}}
\\end{{figure}}

\\end{{document}}
"""
    
    # W aktualnym eksporcie LaTeX nie osadzamy tła, a wysokość jest potrzebna
    # tylko do odwrócenia osi OY. Używamy stałej wartości, żeby eksport TikZ
    # był niezależny od dostępu do pliku obrazu i szybszy w testach.
    img_height = 1000

    # Generuj węzły - odwróć współrzędne Y
    nodes = []
    for point in route.points.all().order_by('order'):
        # Odwróć oś OY: y = wysokość_obrazka - y
        y_coord = (img_height - point.y) / 100  # Podziel przez 100 dla lepszego skalowania
        x_coord = point.x / 100
        nodes.append(f"\\node[node] ({point.order}) at ({x_coord:.2f}, {y_coord:.2f}) {{{point.order}}};")
    
    # Generuj krawędzie
    edges = []
    for edge in route.edges.all():
        edges.append(f"({edge.start_point.order}) edge[edge] ({edge.end_point.order})")
    
    latex_content = latex_template.format(
        nodes="\n  ".join(nodes),
        edges="\n  ".join(edges),
        title=route.title,
        id=route.id
    )
    
    response = HttpResponse(latex_content, content_type='text/plain')
    response['Content-Disposition'] = f'attachment; filename="route_{route.id}.tex"'
    return response
