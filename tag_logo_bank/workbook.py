"""Workbook extraction and atomic output with embedded, portable images."""
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import os
import tempfile

from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.utils.units import pixels_to_EMU, pixels_to_points
from openpyxl.styles import Alignment, Font, PatternFill

from .logos import Fetcher, find_logo, normalize_site


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


def build_logo_bank(source, output, *, sheet='Transactions', pairs=None, header_row=1,
                    overrides=None, fetcher=None):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('Choose a separate output file to preserve the source')
    if source.suffix.lower() != '.xlsx' or output.suffix.lower() != '.xlsx':
        raise ValueError('Only .xlsx workbooks are supported')
    if sheet == 'Logos':
        raise ValueError('Source worksheet cannot be Logos')
    wb = load_workbook(source)
    try:
        if sheet not in wb:
            raise ValueError(f'Worksheet not found: {sheet}')
        companies = extract_companies(wb[sheet], pairs or [('Company', 'Website')], header_row)
        if 'Logos' in wb:
            del wb['Logos']
        ws = wb.create_sheet('Logos')
        ws.append(['Company', 'Website', 'Logo', 'Status', 'Source', 'Official page',
                   'Retrieved UTC', 'Original dimensions', 'SHA256 (embedded PNG)', 'Verification / notes'])
        overrides = {k.casefold(): v for k, v in (overrides or {}).items()}
        fetcher = fetcher or Fetcher()
        counts = {}
        for name, website in companies:
            override = overrides.get(name.casefold(), {})
            site = override.get('website', website)
            if site:
                try:
                    site = normalize_site(site)
                except ValueError:
                    pass  # find_logo reports invalid websites without aborting the workbook.
            local = Path(override['logo_path']) if override.get('logo_path') else None
            if 'approval' in override:
                result = find_logo(site, fetcher, local, approval=override['approval'])
            else:
                result = find_logo(site, fetcher, local)
            counts[result.status] = counts.get(result.status, 0) + 1
            ws.append([name, site, '', result.status, result.source, result.page,
                       datetime.now(timezone.utc).isoformat(timespec='seconds'),
                       f'{result.width} x {result.height}' if result.png else '',
                       result.sha256, result.detail[:32000]])
            row = ws.max_row
            for cell in ws[row]:
                if isinstance(cell.value, str):
                    cell.data_type = 's'  # Treat workbook/network text as literal, never a formula.
                cell.alignment = Alignment(vertical='center', wrap_text=True)
            if result.png:
                image = Image(BytesIO(result.png))
                ratio = min(180 / image.width, 75 / image.height, 1)
                image.width *= ratio
                image.height *= ratio
                image.anchor = OneCellAnchor(
                    _from=AnchorMarker(col=2, row=row - 1,
                                       colOff=pixels_to_EMU(8), rowOff=pixels_to_EMU(8)),
                    ext=XDRPositiveSize2D(pixels_to_EMU(image.width), pixels_to_EMU(image.height)))
                ws.add_image(image)
            ws.row_dimensions[row].height = pixels_to_points(96)
        for cell in ws[1]:
            cell.fill = PatternFill('solid', fgColor='17365D')
            cell.font = Font(color='FFFFFF', bold=True)
        for col, width in zip('ABCDEFGHIJ', [30, 36, 28, 24, 50, 40, 28, 22, 35, 65]):
            ws.column_dimensions[col].width = width
        ws.freeze_panes = 'D2'
        ws.auto_filter.ref = ws.dimensions
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
        wb.close()

