"""Build the pinned, self-contained CalcpadCE bridge once (Git and .NET 10 SDK)."""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from .calcpad import REVISION, default_engine_dir


def main(argv=None):
    parser = argparse.ArgumentParser(prog='mcdxkit setup-engine', description=__doc__)
    parser.add_argument('--dotnet', default='dotnet', help='Path to the .NET 10 SDK executable')
    parser.add_argument('--source', type=Path, help='Existing clean CalcpadCE checkout at the pinned revision')
    parser.add_argument('--install-dir', type=Path, default=default_engine_dir())
    args = parser.parse_args(argv)
    try:
        dotnet = shutil.which(args.dotnet)
        if not dotnet: raise ValueError('Install the .NET 10 SDK, or pass --dotnet /path/to/dotnet')
        system = {'Darwin': 'osx', 'Linux': 'linux', 'Windows': 'win'}.get(platform.system())
        arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64', 'AMD64': 'x64'}.get(platform.machine())
        if not system or not arch: raise ValueError('Unsupported platform; build the bridge manually for your runtime')
        destination = args.install_dir.resolve()
        if destination.exists(): raise ValueError('Engine directory already exists; choose a new --install-dir to preserve it')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.mcdxkit-build-', dir=destination.parent) as temp:
            temp = Path(temp); source = args.source.resolve() if args.source else temp/'source'
            def run(command, **kwargs):
                subprocess.run(command, check=True, **kwargs)
            if not args.source:
                run(['git', 'init', '-q', str(source)])
                run(['git', '-C', str(source), 'fetch', '--depth=1', 'https://github.com/imartincei/CalcpadCE.git', REVISION])
                run(['git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD'])
            head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip()
            if head != REVISION or dirty: raise ValueError('Engine source must be a clean checkout at '+REVISION)
            bridge = temp/'bridge'; shutil.copytree(Path(__file__).parent/'calcpad_bridge', bridge)
            build = temp/'published'
            env = dict(os.environ, DOTNET_CLI_HOME=str(temp/'dotnet-home'), DOTNET_CLI_TELEMETRY_OPTOUT='1')
            run([dotnet, 'publish', str(bridge/'Bridge.csproj'), '-c', 'Release', '-r', system+'-'+arch,
                 '--self-contained', 'true', '-o', str(build), '-p:CalcpadSource='+str(source),
                 '-p:UseSharedCompilation=false', '--nologo'], env=env)
            shutil.copyfile(source/'LICENSE', build/'CalcpadCE-LICENSE')
            shutil.copyfile(source/'THIRD-PARTY-NOTICES.txt', build/'CalcpadCE-THIRD-PARTY-NOTICES.txt')
            (build/'mcdxkit-engine.json').write_text(json.dumps({'engine': 'CalcpadCE', 'revision': REVISION})+'\n')
            os.rename(build, destination)
        print('Calculator installed at '+str(destination))
        print('Set MCDXKIT_ENGINE_DIR='+str(destination)+' if this is a custom location.')
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('mcdxkit: '+str(exc), file=sys.stderr); return 2
