"""Collect installed Python distributions and embedded license texts for release review."""
import importlib.metadata as metadata
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
parts = ['Dependency notices — review alongside npm lockfile and model distribution license.\n']
python_license = Path(sys.base_prefix) / 'LICENSE.txt'
if not python_license.is_file():
    raise RuntimeError('CPython LICENSE.txt missing from the build interpreter')
parts.append(f'\n## CPython {sys.version}\n' + python_license.read_text(encoding='utf-8'))
for dist in sorted(metadata.distributions(), key=lambda d: d.metadata.get('Name','')):
    parts.append(f"\n## {dist.metadata.get('Name')} {dist.version}\nLicense: {dist.metadata.get('License-Expression') or dist.metadata.get('License','unspecified')}\n")
    for entry in dist.files or []:
        if Path(str(entry)).name.lower().startswith(('license','copying','notice')):
            try: parts.append(dist.locate_file(entry).read_text(errors='replace'))
            except (OSError, IsADirectoryError): pass
(root/'artifacts').mkdir(exist_ok=True)
(root/'artifacts'/'dependency-notices.txt').write_text('\n'.join(parts),encoding='utf-8')
