from io import BytesIO
import zipfile
import pytest
from PIL import Image, ImageDraw
from openpyxl import Workbook, load_workbook
from tag_logo_bank.logos import candidates, find_logo, public_url, verify_image
from tag_logo_bank.workbook import build_logo_bank, extract_companies


def png(size=(240, 100)):
    img = Image.new('RGB', size, 'white')
    ImageDraw.Draw(img).rectangle((3, 3, size[0] // 2, size[1] // 2), fill='navy')
    data = BytesIO()
    img.save(data, 'PNG')
    return data.getvalue()


class FakeFetcher:
    def __init__(self, routes):
        self.routes = routes
    def get(self, url):
        result = self.routes[url]
        if isinstance(result, Exception):
            raise result
        return result, url


def test_candidates_rank_and_deduplicate():
    html = '''<script type="application/ld+json">{"@graph":[{"@type":"Organization","logo":{"url":"/brand.png"}}]}</script>
    <header><img alt="logo" src="/header.png"></header><link rel="icon" href="/icon.png">'''
    assert candidates(html, 'https://sample.example')[0] == ('https://sample.example/brand.png', 'organization_schema')


def test_invalid_candidate_falls_back():
    fetcher = FakeFetcher({'https://sample.example': b'<img alt="logo" src="/bad.svg"><link rel="icon" href="/good.png">',
                           'https://sample.example/bad.svg': b'<svg/>', 'https://sample.example/good.png': png()})
    result = find_logo('sample.example', fetcher)
    assert result.png and result.status == 'REVIEW_REQUIRED'
    assert result.source.endswith('good.png')
    assert result.width == 240 and len(result.sha256) == 64


def test_no_site_and_network_error():
    assert find_logo('').status == 'NEEDS_WEBSITE'
    result = find_logo('sample.example', FakeFetcher({'https://sample.example': OSError('timeout')}))
    assert result.status == 'ERROR' and 'timeout' in result.detail


@pytest.mark.parametrize('data', [b'not an image', png((10, 10))])
def test_invalid_images(data):
    with pytest.raises((ValueError, OSError)):
        verify_image(data)


def test_blank_rejected():
    data = BytesIO()
    Image.new('RGBA', (200, 100)).save(data, 'PNG')
    with pytest.raises(ValueError, match='Blank'):
        verify_image(data.getvalue())


def test_private_url_blocked():
    with pytest.raises(ValueError, match='nonpublic'):
        public_url('http://127.0.0.1/logo.png')


def test_workbook_end_to_end_and_rerun(tmp_path):
    source = tmp_path / 'source.xlsx'
    logo = tmp_path / 'local.png'
    logo.write_bytes(png())
    wb = Workbook()
    ws = wb.active
    ws.title = 'Transactions'
    ws.append(['Company', 'Website'])
    ws.append(['Sample', None])
    ws.append(['Sample', None])
    ws.append(['=Literal Company', None])
    wb.save(source)
    output = tmp_path / 'output.xlsx'
    counts = build_logo_bank(source, output, overrides={'Sample': {'logo_path': str(logo)}})
    assert counts == {'MANUAL_REVIEW': 1, 'NEEDS_WEBSITE': 1}
    result = load_workbook(output)
    assert result['Transactions'].max_row == 4
    assert result['Logos'].max_row == 3
    assert result['Logos']['A3'].data_type == 's'
    assert len(result['Logos']._images) == 1
    assert 'Logos' not in load_workbook(source).sheetnames
    with zipfile.ZipFile(output) as archive:
        assert len([p for p in archive.namelist() if p.startswith('xl/media/')]) == 1
    second = tmp_path / 'second.xlsx'
    build_logo_bank(output, second)
    assert load_workbook(second).sheetnames.count('Logos') == 1
    with pytest.raises(ValueError, match='separate'):
        build_logo_bank(source, source)


def test_multiple_pairs_and_hyperlinks():
    ws = Workbook().active
    ws.append(['Target', 'Target Website', 'Buyer'])
    ws.append(['Target Ltd', 'Visit', 'Buyer Ltd'])
    ws['B2'].hyperlink = 'https://target.example'
    assert extract_companies(ws, [('Target', 'Target Website'), ('Buyer', '')]) == [
        ('Target Ltd', 'https://target.example'), ('Buyer Ltd', '')]
    with pytest.raises(ValueError, match='Missing'):
        extract_companies(ws, [('Unknown', '')])


def test_cli_corrupt_workbook(tmp_path, monkeypatch, capsys):
    import sys
    from tag_logo_bank.cli import main
    source = tmp_path / 'bad.xlsx'
    source.write_bytes(b'not a zip')
    monkeypatch.setattr(sys, 'argv', ['tag-logos', str(source), str(tmp_path / 'out.xlsx')])
    assert main() == 1
    assert 'Error:' in capsys.readouterr().err
    assert not (tmp_path / 'out.xlsx').exists()


def test_invalid_local_image(tmp_path):
    missing = tmp_path / 'missing.png'
    assert find_logo('', local=missing).status == 'ERROR'
