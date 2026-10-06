"""Check that a built wheel includes the browser assets and calculator bridge."""
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
        missing = required - set(wheel.namelist())
        if missing:
            raise SystemExit('Missing package assets: ' + ', '.join(sorted(missing)))
        if any(not wheel.read(name) for name in required):
            raise SystemExit('Package contains an empty required asset')
    print(f'{wheels[0].name}: browser assets, font license and bridge included')


if __name__ == '__main__':
    main()
