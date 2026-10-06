"""Check that a built wheel includes the browser assets and calculator bridge."""
from email.parser import BytesParser
import re
from pathlib import Path
from zipfile import ZipFile


def main():
    wheels = list(Path('dist').glob('gdcalc-*.whl'))
    if len(wheels) != 1:
        raise SystemExit('Expected exactly one gdcalc wheel in dist/')
    required = {
        'gdcalc/web/index.html', 'gdcalc/web/app.js', 'gdcalc/web/style.css',
        'gdcalc/web/fonts/plex-regular.ttf', 'gdcalc/web/fonts/plex-medium.ttf',
        'gdcalc/web/fonts/plex-semibold.ttf', 'gdcalc/web/fonts/OFL.txt',
        'gdcalc/calcpad_bridge/Program.cs', 'gdcalc/calcpad_bridge/Bridge.csproj',
    }
    with ZipFile(wheels[0]) as wheel:
        metadata_path = next(name for name in wheel.namelist() if name.endswith('.dist-info/METADATA'))
        metadata = BytesParser().parsebytes(wheel.read(metadata_path))
        description = metadata.get_payload()
        for target in re.findall(r'\]\(([^)]+)\)', description):
            if not re.match(r'(https?://|mailto:|#)', target):
                raise SystemExit('PyPI description contains a relative link: ' + target)
        missing = required - set(wheel.namelist())
        if missing:
            raise SystemExit('Missing package assets: ' + ', '.join(sorted(missing)))
        if any(not wheel.read(name) for name in required):
            raise SystemExit('Package contains an empty required asset')
    print(f'{wheels[0].name}: browser assets, font license and bridge included')


if __name__ == '__main__':
    main()
