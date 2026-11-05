"""Three-column, uniformly sized user-facing logo sheet."""
from copy import copy
from io import BytesIO
import json
from pathlib import Path

from openpyxl.drawing.image import Image
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.units import pixels_to_EMU, pixels_to_points


def present_logos(wb, details, output, header_row, name_col, site_col, logo_col, *, archive):
    from .workbook import image_cell
    headers = {c.column: str(c.value) for c in details[header_row] if c.value is not None}
    audit = [{'row': row - header_row + 1,
              'cells': {name: details.cell(row, col).value for col, name in headers.items()}}
             for row in range(header_row + 1, details.max_row + 1)]
    # Keep retrieval diagnostics available without adding spreadsheet columns.
    Path(output).with_suffix('.logo-audit.json').write_text(
        json.dumps({'rows': audit}, indent=2, default=str), encoding='utf-8')
    position = wb.index(details)
    details.title = 'Logo Details'  # openpyxl chooses a unique name if necessary.
    clean = wb.create_sheet('Logos', position)
    clean.append(['Company', 'Website', 'Logo'])
    row_map = {}
    for old_row in range(header_row + 1, details.max_row + 1):
        row = old_row - header_row + 1
        row_map[old_row] = row
        for col, original in ((1, name_col), (2, site_col), (3, logo_col)):
            source = details.cell(old_row, original)
            target = clean.cell(row, col, source.value)
            if isinstance(target.value, str) and col != 3:
                target.data_type = 's'
            if source.hyperlink:
                target.hyperlink = copy(source.hyperlink)
            target.fill = copy(source.fill)
            target.alignment = Alignment(horizontal='center' if col == 3 else 'left',
                                         vertical='center', wrap_text=True)
    copied = set()
    for original in details._images:
        old_row, old_col = image_cell(original)
        if old_col != logo_col or old_row not in row_map or old_row in copied:
            continue
        data = original._data()
        original.ref = BytesIO(data)  # Archive and visible sheet need independent streams.
        image = Image(BytesIO(data))
        scale = min(180 / image.width, 75 / image.height, 1)
        image.width *= scale
        image.height *= scale
        image.anchor = OneCellAnchor(
            _from=AnchorMarker(col=2, row=row_map[old_row] - 1,
                               colOff=pixels_to_EMU((229 - image.width) / 2),
                               rowOff=pixels_to_EMU((96 - image.height) / 2)),
            ext=XDRPositiveSize2D(pixels_to_EMU(image.width), pixels_to_EMU(image.height)))
        clean.add_image(image)
        copied.add(old_row)
    for row in range(1, clean.max_row + 1):
        clean.row_dimensions[row].height = pixels_to_points(96)
    for cell in clean[1]:
        cell.fill = PatternFill('solid', fgColor='17365D')
        cell.font = Font(color='FFFFFF', bold=True)
        cell.alignment = Alignment(vertical='center')
    for col, width in [('A', 36), ('B', 48), ('C', 32)]:
        clean.column_dimensions[col].width = width
    clean.freeze_panes = 'C2'
    clean.auto_filter.ref = f'A1:C{clean.max_row}'
    if archive:
        details.sheet_state = 'hidden'
    else:
        wb.remove(details)
    wb.active = position
    return clean
