#!/usr/bin/env python3
"""Package a source-based GPU web service without private workspaces or SSH."""
import argparse
from pathlib import Path
import tarfile


def build_bundle(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not (root / 'web/dist/index.html').is_file():
        raise ValueError('Build the frontend first: npm --prefix web run build')
    files = [root / name for name in ('pyproject.toml', 'requirements.lock', 'README.md', 'LICENSE')]
    files += sorted((root / 'src').rglob('*.py'))
    files += sorted((root / 'remote').rglob('*.py'))
    files += sorted(path for path in (root / 'web/dist').rglob('*') if path.is_file())
    files += [root / 'docs/mobile-web.md']
    if any(path.is_symlink() or not path.resolve().is_relative_to(root) for path in files):
        raise ValueError('Refusing symbolic links or files outside the source tree')
    if any(not path.is_file() for path in files):
        raise ValueError('The source checkout is incomplete')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    try:
        with tarfile.open(temporary, 'w:gz') as archive:
            for path in files:
                if '__pycache__' in path.parts:
                    continue
                entry = archive.gettarinfo(str(path), arcname='ai-experiment-web/' + path.relative_to(root).as_posix())
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = ''
                entry.mode = 0o644
                with path.open('rb') as stream:
                    archive.addfile(entry, stream)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='dist/releases/AI-Experiment-GPU-Web.tar.gz')
    args = parser.parse_args()
    print(build_bundle(Path(__file__).resolve().parents[1], args.output))


if __name__ == '__main__':
    main()
