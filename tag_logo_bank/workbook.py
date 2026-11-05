"""Workbook extraction and atomic output with embedded, portable images."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import os
import tempfile
import hashlib
import re

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.utils.units import pixels_to_EMU, pixels_to_points
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from .logos import find_logo, normalize_site
from .hybrid import Hybrid


def save_png(directory, name, result):
    """Keep the original downloaded PNG, with a safe content-addressed filename."""
    data = result.downloaded_png or result.png
    label = re.sub(r'[^a-z0-9.-]+', '-', (result.domain or name).casefold()).strip('.-')[:60] or 'logo'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f'{label}-{hashlib.sha256(data).hexdigest()}.png'
    fd, temporary = tempfile.mkstemp(suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return str(destination.resolve())


def text(cell):
    return str(cell.value).strip() if cell.value is not None else ''


def extract_companies(sheet, pairs, header_row=1):
    headers = {}
    for cell in sheet[header_row]:
        key = text(cell).casefold()
        if key:
            if key in headers:
                raise ValueError(f'Duplicate header: {cell.value}')
            headers[key] = cell.column
    for company, website in pairs:
        for name in (company, website):
            if name and name.casefold() not in headers:
                raise ValueError(f'Missing column: {name}')
    companies = {}
    for row in sheet.iter_rows(min_row=header_row + 1):
        for name_col, site_col in pairs:
            name = text(row[headers[name_col.casefold()] - 1])
            if not name:
                continue
            site = ''
            if site_col:
                cell = row[headers[site_col.casefold()] - 1]
                site = cell.hyperlink.target if cell.hyperlink and cell.hyperlink.target else text(cell)
                if site:
                    try:
                        site = normalize_site(site)
                    except ValueError:
                        pass
            key = (name.casefold(), site.rstrip('/').casefold())
            companies.setdefault(key, (name, site))
    return list(companies.values())


def image_cell(image):
    anchor = image.anchor
    if isinstance(anchor, str):
        from openpyxl.utils.cell import coordinate_to_tuple
        return coordinate_to_tuple(anchor)
    return anchor._from.row + 1, anchor._from.col + 1


def build_logo_bank(source, output, *, sheet=None, pairs=None, header_row=1,
                    overrides=None, fetcher=None, logos_dir=None, cache_dir=None,
                    use_api=True, web_search=False, search_domains=(), refresh=False, max_wait=2,
                    limit=None):
    source, output = Path(source), Path(output)
    logos_dir = Path(logos_dir) if logos_dir is not None else output.parent / f'{output.stem}_logos'
    if source.resolve() == output.resolve():
        raise ValueError('Choose a separate output file to preserve the source')
    if source.suffix.lower() != '.xlsx' or output.suffix.lower() != '.xlsx':
        raise ValueError('Only .xlsx workbooks are supported')
    wb = load_workbook(source)
    owned = fetcher is None
    try:
        sheet = sheet or ('Logos' if 'Logos' in wb else 'Transactions' if 'Transactions' in wb else wb.active.title)
        if sheet not in wb:
            raise ValueError(f'Worksheet not found: {sheet}')
        source_ws = wb[sheet]
        source_headers = {text(c).casefold(): c.column for c in source_ws[header_row] if text(c)}
        if pairs is None:
            name = next((text(source_ws.cell(header_row, source_headers[k])) for k in
                         ('company', 'company name', 'target', 'target company') if k in source_headers), 'Company')
            website = next((text(source_ws.cell(header_row, source_headers[k])) for k in
                            ('website', 'company website', 'url') if k in source_headers), '')
            pairs = [(name, website)]
        # Validate configured headers using the same extraction rules as before.
        companies = extract_companies(source_ws, pairs, header_row)
        existing = 'Logos' in wb
        ws = wb['Logos'] if existing else wb.create_sheet('Logos')
        logo_header_row = header_row if sheet == 'Logos' else 1
        if not existing:
            ws.append(['Company', 'Website', 'Current Logo', 'Status', 'Source', 'Official page',
                       'Retrieved UTC', 'Original dimensions', 'SHA256 (embedded PNG)', 'Verification / notes', 'Local PNG'])
        headers = {text(c).casefold(): c.column for c in ws[logo_header_row] if text(c)}

        def column(name, aliases=()):
            for key in (name.casefold(), *aliases):
                if key in headers:
                    return headers[key]
            col = ws.max_column + 1 if any(text(c) for c in ws[logo_header_row]) else 1
            ws.cell(logo_header_row, col, name)
            headers[name.casefold()] = col
            return col

        name_col = column('Company', ('company name', 'target', 'target company'))
        site_col = column('Website', ('company website', 'url'))
        logo_col = column('Current Logo', ('logo',))
        # Existing statuses, notes and source fields are historical information.
        # Append our own latest-attempt fields instead of overwriting those cells.
        names = (['Latest Retrieval Status', 'Latest Retrieval Source', 'Latest Official Page',
                  'Latest Retrieved UTC', 'Latest Dimensions', 'Latest Embedded SHA256',
                  'Latest Retrieval Notes', 'Latest Local PNG'] if existing else
                 ['Status', 'Source', 'Official page', 'Retrieved UTC', 'Original dimensions',
                  'SHA256 (embedded PNG)', 'Verification / notes', 'Local PNG'])
        metadata_cols = [column(n) for n in names]
        method_col, retry_col = column('Retrieval Method'), column('Retry After UTC')
        overrides = {k.casefold(): v for k, v in (overrides or {}).items()}
        aliases = {k: v.get('identity_names', []) for k, v in overrides.items() if v.get('identity_names')}
        fetcher = fetcher or Hybrid(cache_dir or output.parent / '.tag-logo-cache', use_api=use_api,
                                    web_search=web_search, search_domains=search_domains,
                                    aliases=aliases, refresh=refresh, max_wait=max_wait)
        occupied = {image_cell(image) for image in ws._images}
        tasks = []
        if sheet == 'Logos':
            if len(pairs) != 1:
                raise ValueError('Use one company/website pair when updating Logos directly')
            nc = source_headers[pairs[0][0].casefold()]
            sc = source_headers[pairs[0][1].casefold()] if pairs[0][1] else None
            for row in range(header_row + 1, ws.max_row + 1):
                company = text(ws.cell(row, nc))
                if company:
                    cell = ws.cell(row, sc) if sc else None
                    site = (cell.hyperlink.target if cell is not None and cell.hyperlink else text(cell)) if cell is not None else ''
                    tasks.append((row, company, site))
        else:
            def key(name, site):
                try:
                    from .logos import website_domain
                    domain = website_domain(site) if site else ''
                except ValueError:
                    domain = str(site).casefold()
                return name.casefold(), domain
            rows = {key(text(ws.cell(r, name_col)), text(ws.cell(r, site_col))): r
                    for r in range(logo_header_row + 1, ws.max_row + 1) if text(ws.cell(r, name_col))}
            for name, site in companies:
                row = rows.get(key(name, site))
                if row is None:
                    row = ws.max_row + 1
                    ws.cell(row, name_col, name).data_type = 's'
                    ws.cell(row, site_col, site).data_type = 's'
                    rows[key(name, site)] = row
                tasks.append((row, name, site))
        counts = {}
        attempted = 0
        for row, name, website in tasks:
            if (row, logo_col) in occupied or ws.cell(row, logo_col).value is not None:
                counts['ALREADY_PRESENT'] = counts.get('ALREADY_PRESENT', 0) + 1
                continue
            if limit is not None and attempted >= limit:
                break
            attempted += 1
            override = overrides.get(name.casefold(), {})
            site = override.get('website', website)
            if site:
                try:
                    site = normalize_site(site)
                except ValueError:
                    pass
            local = Path(override['logo_path']) if override.get('logo_path') else None
            kwargs = {'company': name}
            if 'approval' in override:
                kwargs['approval'] = override['approval']
            result = find_logo(site, fetcher, local, **kwargs)
            saved = ''
            if result.png:
                try:
                    saved = save_png(logos_dir, name, result)
                except OSError as error:
                    result.png, result.status = None, 'ERROR'
                    result.detail = f'Local PNG save: {type(error).__name__}: {error}'
            counts[result.status] = counts.get(result.status, 0) + 1
            values = [result.status, result.source, result.page,
                      datetime.now(timezone.utc).isoformat(timespec='seconds'),
                      f'{result.width} x {result.height}' if result.png else '', result.sha256,
                      result.detail[:32000], saved]
            for col, value in zip(metadata_cols, values):
                if isinstance(value, str):
                    value = ILLEGAL_CHARACTERS_RE.sub('', value)
                cell = ws.cell(row, col, value)
                cell.data_type = 's'
                cell.alignment = Alignment(vertical='center', wrap_text=True)
            ws.cell(row, method_col, result.method or ('manual_raster' if local else 'logoapi')).data_type = 's'
            ws.cell(row, retry_col, datetime.fromtimestamp(result.retry_at, timezone.utc).isoformat() if result.retry_at else '').data_type = 's'
            if result.png:
                image = Image(BytesIO(result.png))
                ratio = min(180 / image.width, 75 / image.height, 1)
                image.width *= ratio
                image.height *= ratio
                image.anchor = OneCellAnchor(_from=AnchorMarker(col=logo_col - 1, row=row - 1,
                    colOff=pixels_to_EMU(8), rowOff=pixels_to_EMU(8)),
                    ext=XDRPositiveSize2D(pixels_to_EMU(image.width), pixels_to_EMU(image.height)))
                ws.add_image(image)
                occupied.add((row, logo_col))
                ws.row_dimensions[row].height = max(ws.row_dimensions[row].height or 15, pixels_to_points(96))
            else:
                ws.cell(row, metadata_cols[0]).fill = PatternFill('solid', fgColor='FFF2CC')
                if not existing:
                    for cell in ws[row]:
                        cell.fill = PatternFill('solid', fgColor='FFF2CC')
        # Style only newly created sheets/columns; preserve the user's layout.
        if not existing:
            for cell in ws[1]:
                cell.fill = PatternFill('solid', fgColor='17365D')
                cell.font = Font(color='FFFFFF', bold=True)
            for col, width in zip('ABCDEFGHIJK', [30, 36, 28, 24, 50, 40, 28, 22, 35, 65, 55]):
                ws.column_dimensions[col].width = width
            ws.freeze_panes = 'D2'
            ws.auto_filter.ref = ws.dimensions
        ws.column_dimensions[get_column_letter(logo_col)].width = max(ws.column_dimensions[get_column_letter(logo_col)].width or 13, 28)
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(suffix='.xlsx', dir=output.parent)
        os.close(fd)
        try:
            wb.save(temporary)
            os.replace(temporary, output)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return counts
    finally:
        if owned and fetcher is not None:
            fetcher.close()
        wb.close()
