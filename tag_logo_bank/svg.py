"""Small, fail-closed SVG subset; expand safe presentation CSS before rendering.

This is not a general SVG/CSS implementation. Unsupported content needs a verified
raster export. No scripts, external resources, XML entities or dynamic CSS survive.
"""
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

MAX_BYTES = 8 * 1024 * 1024
SVG_NS = 'http://www.w3.org/2000/svg'
XLINK_NS = 'http://www.w3.org/1999/xlink'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
ELEMENTS = {'svg', 'g', 'path', 'rect', 'circle', 'ellipse', 'line', 'polyline',
            'polygon', 'defs', 'clipPath', 'mask', 'linearGradient',
            'radialGradient', 'stop', 'title', 'desc', 'use', 'style', 'metadata'}
PAINT = {'fill', 'stroke', 'stop-color'}
NUMERIC = {'opacity', 'fill-opacity', 'stroke-opacity', 'stop-opacity',
           'stroke-width', 'stroke-miterlimit', 'stroke-dashoffset'}
ENUMS = {'fill-rule': {'nonzero', 'evenodd', 'inherit'},
         'clip-rule': {'nonzero', 'evenodd', 'inherit'},
         'stroke-linecap': {'butt', 'round', 'square', 'inherit'},
         'stroke-linejoin': {'miter', 'round', 'bevel', 'inherit'},
         'display': {'none', 'inline', 'inherit'},
         'visibility': {'visible', 'hidden', 'collapse', 'inherit'}}
PRESENTATION = PAINT | NUMERIC | set(ENUMS) | {'stroke-dasharray', 'clip-path', 'mask'}
ATTRIBUTES = PRESENTATION | {'id', 'class', 'version', 'viewBox', 'preserveAspectRatio',
    'width', 'height', 'x', 'y', 'x1', 'x2', 'y1', 'y2', 'cx', 'cy', 'r', 'rx', 'ry',
    'd', 'points', 'transform', 'gradientTransform', 'gradientUnits', 'spreadMethod',
    'offset', 'fx', 'fy', 'fr', 'clipPathUnits', 'maskUnits', 'maskContentUnits',
    'href', 'space', 'type'}
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
LOCAL_URL = re.compile(r'url\(\s*[\"\']?(#[A-Za-z_][\w.-]*)[\"\']?\s*\)', re.I)
SELECTOR = re.compile(r'(?:[A-Za-z][\w-]*)?(?:[.#][A-Za-z_][\w-]*)*\Z')


def local_name(name):
    return name.rsplit('}', 1)[-1]


def safe_presentation(name, value):
    """Accept a finite presentation grammar, never general CSS expressions."""
    value = value.strip()
    if name in PAINT:
        valid = (re.fullmatch(r'#[0-9a-fA-F]{3,8}|[A-Za-z]+', value) or
                 re.fullmatch(r'(?:rgb|rgba)\([0-9.,%\s]+\)', value) or
                 LOCAL_URL.fullmatch(value))
    elif name in NUMERIC:
        valid = re.fullmatch(NUMBER + r'(?:px|%)?', value)
    elif name == 'stroke-dasharray':
        valid = value == 'none' or re.fullmatch(r'[0-9.eE+,%\s-]+', value)
    elif name in {'clip-path', 'mask'}:
        valid = value == 'none' or LOCAL_URL.fullmatch(value)
    else:
        valid = value in ENUMS.get(name, set())
    if not valid:
        raise ValueError(f'Unsupported or unsafe SVG CSS value for {name}')
    return value


def declarations(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    if any(char in text for char in '\\@{}<>!'):
        raise ValueError('Unsupported or unsafe SVG CSS syntax')
    result = {}
    for entry in text.split(';'):
        if not entry.strip():
            continue
        name, separator, value = entry.partition(':')
        name = name.strip().lower()
        if name == 'enable-background' and re.fullmatch(r'(?:new(?:\s+' + NUMBER + r'){4}|accumulate)', value.strip()):
            continue  # Harmless legacy exporter hint, omitted from the output.
        if not separator or name not in PRESENTATION:
            raise ValueError(f'Unsupported SVG CSS property: {name}')
        result[name] = safe_presentation(name, value)
    return result


def matches(node, selector):
    tag = re.match(r'^[A-Za-z][\w-]*', selector)
    if tag and local_name(node.tag) != tag.group():
        return False
    for prefix, token in re.findall(r'([.#])([A-Za-z_][\w-]*)', selector):
        if prefix == '#' and node.get('id') != token:
            return False
        if prefix == '.' and token not in node.get('class', '').split():
            return False
    return True


def sanitize_svg(data):
    """Return sanitized XML and an audit note. Never fetch DTDs or expand entities."""
    if len(data) > MAX_BYTES:
        raise ValueError('SVG exceeds 8 MB')
    text = data.decode('utf-8-sig')
    notes = []
    parser = expat.ParserCreate()
    depth = count = 0

    def reject(*args):
        raise ValueError('SVG entities and processing instructions are forbidden')

    def doctype(name, system, public, subset):
        # Exporters commonly emit this standard identifier. It is removed, never loaded.
        standard = system in {'http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd',
                              'https://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd'}
        if subset or name != 'svg' or not standard or public != '-//W3C//DTD SVG 1.1//EN':
            raise ValueError('Unsupported SVG DOCTYPE; entities/internal subsets are forbidden')
        notes.append('standard SVG 1.1 DOCTYPE removed without loading it')

    def start(name, attributes):
        nonlocal depth, count
        depth += 1
        count += 1
        if depth > 100 or count > 10000:
            raise ValueError('SVG exceeds depth/element limits')

    def end(name):
        nonlocal depth
        depth -= 1

    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    parser.ProcessingInstructionHandler = reject
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(text, True)
    except expat.ExpatError as error:
        raise ValueError(f'Invalid SVG XML: {error}') from error
    root = ET.fromstring(text)  # Preflight above rejects entities before this parser sees them.
    if local_name(root.tag) != 'svg':
        raise ValueError('Expected SVG root')
    rules = []
    # Validate the whole tree, including metadata, before removing anything.
    for node in root.iter():
        namespace = node.tag[1:].split('}', 1)[0] if node.tag.startswith('{') else ''
        tag = local_name(node.tag)
        if namespace not in {'', SVG_NS} or tag not in ELEMENTS:
            raise ValueError(f'Unsupported or unsafe SVG element: {tag}')
        for key, value in list(node.attrib.items()):
            attr = local_name(key)
            ns = key[1:].split('}', 1)[0] if key.startswith('{') else ''
            if (attr.lower().startswith('on') or attr == 'base' or
                    (ns and (ns, attr) not in {(XLINK_NS, 'href'), (XML_NS, 'space')})):
                raise ValueError(f'Unsupported or unsafe SVG attribute: {attr}')
            if attr == 'style':
                declarations(value)
            elif attr == 'href':
                if not re.fullmatch(r'#[A-Za-z_][\w.-]*', value):
                    raise ValueError('SVG external references are forbidden')
            elif attr in PRESENTATION:
                safe_presentation(attr, value)
            elif attr == 'enable-background':
                # Illustrator legacy rendering hint; not used by CairoSVG.
                del node.attrib[key]
                notes.append('legacy enable-background hint removed')
            elif attr not in ATTRIBUTES and not attr.startswith(('aria-', 'data-')) and attr != 'role':
                raise ValueError(f'Unsupported SVG attribute: {attr}')
            elif re.search(r'url\s*\(|[\\@]', value, re.I):
                raise ValueError('SVG resource/CSS syntax outside presentation is forbidden')
        if tag == 'style':
            if node.get('type', 'text/css') != 'text/css':
                raise ValueError('Unsupported SVG stylesheet type')
            css = re.sub(r'/\*.*?\*/', '', node.text or '', flags=re.S)
            while css.strip():
                match = re.match(r'\s*([^{}]+)\{([^{}]*)\}', css)
                if not match:
                    raise ValueError('Unsupported SVG stylesheet syntax')
                selectors = [s.strip() for s in match[1].split(',')]
                properties = declarations(match[2])
                for selector in selectors:
                    if not selector or not SELECTOR.fullmatch(selector):
                        raise ValueError('Unsupported SVG CSS selector')
                    specificity = (selector.count('#'), selector.count('.'),
                                   int(bool(re.match(r'^[A-Za-z]', selector))))
                    rules.append((selector, specificity, properties))
                css = css[match.end():]
    # Expand the supported stylesheet cascade and inline styles into presentation
    # attributes, so the renderer never receives any CSS text.
    for node in root.iter():
        selected = {}
        for order, (selector, specificity, properties) in enumerate(rules):
            if matches(node, selector):
                for name, value in properties.items():
                    priority = (specificity, order)
                    if name not in selected or priority >= selected[name][0]:
                        selected[name] = (priority, value)
        for name, (_, value) in selected.items():
            node.set(name, value)
        if 'style' in node.attrib:
            node.attrib.update(declarations(node.attrib.pop('style')))
            notes.append('safe inline presentation style expanded')
    for parent in root.iter():
        for child in list(parent):
            if local_name(child.tag) in {'style', 'metadata'}:
                parent.remove(child)
    if rules:
        notes.append('safe stylesheet rules expanded into presentation attributes')
    # Bound internal <use>/gradient/clip expansion as well as the source tree.
    nodes = list(root.iter())
    ids = {}
    for node in nodes:
        if node.get('id'):
            if node.get('id') in ids:
                raise ValueError('Duplicate SVG identifier')
            ids[node.get('id')] = node
    edges = {}
    for node in nodes:
        targets = list(node)
        for key, value in node.attrib.items():
            references = []
            if local_name(key) == 'href':
                references.append(value)
            references.extend(match[1] for match in LOCAL_URL.finditer(value))
            for reference in references:
                if reference[1:] not in ids:
                    raise ValueError('Unresolved SVG local reference')
                targets.append(ids[reference[1:]])
        edges[node] = targets
    active, sizes = set(), {}

    def expanded_size(node, depth=0):
        if node in active or depth > 100:
            raise ValueError('Cyclic or excessive SVG reference depth')
        if node in sizes:
            return sizes[node]
        active.add(node)
        size = 1
        for target in edges[node]:
            size += expanded_size(target, depth + 1)
            if size > 50000:
                raise ValueError('SVG reference expansion exceeds limit')
        active.remove(node)
        sizes[node] = size
        return size

    expanded_size(root)
    # ElementTree drops XML declarations, comments and DOCTYPE on serialization.
    return ET.tostring(root, encoding='utf-8'), list(dict.fromkeys(notes))

