"""Start the local LECO app from an extracted source ZIP."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent
INPUTS = ('BZ0109kmz.zip', 'DATA BZ0109.xls', 'BZ0109LP.xlsx', 'SOLAR REPORT on Poles (1).xlsx')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--skip-install', action='store_true', help='Use an already installed environment')
    parser.add_argument('--venv', default='.local-venv')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise RuntimeError('Install Python 3.12 (64-bit) and try again.')
    folder = ROOT / 'data'
    folder.mkdir(exist_ok=True)
    missing = [name for name in INPUTS if not (folder / name).is_file()]
    if missing:
        raise RuntimeError('Copy the original uploaded files into this folder:\n' + str(folder) + '\n\nMissing:\n' + '\n'.join('  - ' + name for name in missing))
    environment = ROOT / args.venv
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        if args.skip_install:
            raise RuntimeError('The selected virtual environment does not exist.')
        print('Creating Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    if not args.skip_install:
        print('Installing dependencies (Internet needed)...', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], cwd=ROOT, check=True)
    port = None
    for candidate in range(8000, 8011):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', candidate))
                port = candidate
                break
            except OSError:
                continue
    if port is None:
        raise RuntimeError('Ports 8000-8010 are busy. Close a previous local app and try again.')
    server = subprocess.Popen([str(python), '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', str(port)], cwd=ROOT)
    address = f'http://127.0.0.1:{port}'
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError('The server stopped. Read the error printed above.')
            try:
                with urllib.request.urlopen(address + '/api/network', timeout=2) as response:
                    if response.status == 200:
                        break
            except (OSError, ValueError):
                time.sleep(.25)
        else:
            raise RuntimeError('The server did not become ready within 45 seconds.')
        print('READY: ' + address + '\nKeep this window open. Press Ctrl+C to stop.', flush=True)
        if not args.no_browser:
            webbrowser.open(address)
        server.wait()
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print('\nSETUP ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
