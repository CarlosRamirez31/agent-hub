"""Bounded snapshots for existing/new directories, without creating Git metadata."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

SKIP = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', '.next', '.cache', '.gradle'}
def sensitive(name):
    name=Path(name).name.casefold()
    return (name in ('web.config','app.config','auth.json','credentials.json','secrets.json','.env')
            or name.startswith('appsettings') and name.endswith('.json')
            or name.startswith('.env.') and name not in ('.env.example','.env.sample')
            or name.endswith(('.pem','.pfx','.p12','.key')))


MAX_BYTES, MAX_FILES = 256*1024*1024, 20000


def entries(root):
    root = Path(root)
    count = total = 0
    skip = SKIP | {'.vs'}
    if any(root.glob('*.sln')) or (root/'MasterPage.master').exists():skip = skip | {'bin','obj','packages'}
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if name not in skip and not (Path(directory)/name).is_symlink())
        for name in sorted(files):
            if name == ".git" or sensitive(name):
                continue
            path = Path(directory)/name
            if path.is_symlink():
                raise ValueError('El snapshot no sigue enlaces de archivos: '+str(path))
            if not path.is_file():
                raise ValueError('Archivo especial no admitido en el snapshot.')
            count += 1; total += path.stat().st_size
            if count > MAX_FILES or total > MAX_BYTES:
                raise ValueError('Proyecto demasiado grande para el snapshot acotado; define un alcance menor.')
            yield path.relative_to(root).as_posix(), path


def manifest(root):
    result = {}
    for name, path in entries(root):
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(65536), b''):
                digest.update(block)
        result[name] = [digest.hexdigest(), path.stat().st_mode & 0o777]
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def copy(root, destination):
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name, source in entries(root):
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def diff(baseline, current, limit=12000):
    before, after = manifest(baseline), manifest(current)
    result = []
    for name in sorted(set(before)|set(after)):
        if before.get(name) == after.get(name):
            continue
        texts = []
        for root in (baseline, current):
            path = Path(root)/name
            if path.exists() and path.stat().st_size > 128000:
                texts.append('[archivo grande omitido]\n')
            else:
                texts.append(path.read_text(errors='replace') if path.exists() else '')
        result.extend(difflib.unified_diff(texts[0].splitlines(True), texts[1].splitlines(True), fromfile='a/'+name, tofile='b/'+name))
        if sum(map(len, result)) >= limit:
            break
    return ''.join(result)[:limit]


def apply(baseline, current, target):
    original = manifest(baseline)
    if manifest(target) != original:
        raise ValueError('El proyecto original cambió mientras trabajaba el agente; conserva el resultado aislado para revisar.')
    final = manifest(current)
    changed = sorted(name for name in set(original)|set(final) if original.get(name) != final.get(name))
    root = Path(target).resolve()
    # Validate every destination before the first mutation. No symlink traversal.
    for name in changed:
        path = root/name
        if not path.parent.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('Destino de aplicación fuera del proyecto o enlazado.')
    for name in changed:
        path = root/name
        if name not in final:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            pending = Path(output.name)
            with (Path(current)/name).open('rb') as source:
                shutil.copyfileobj(source, output)
        try:
            pending.chmod(final[name][1]);os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)
    return changed
