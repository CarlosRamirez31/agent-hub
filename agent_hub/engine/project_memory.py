"""Directory-keyed external architecture; never infer identity from Git."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def helper():
    command = shutil.which('dotfiles-project-context')
    if not command:
        candidate = Path('/host-home/.dotfiles/bin/dotfiles-project-context')
        if candidate.is_file():
            command = str(candidate)
    if not command:
        raise ValueError('Falta dotfiles-project-context para consultar la arquitectura externa.')
    return command


def call(action, project, *args, content=None):
    result = subprocess.run([helper(), action, '--project', str(project), *args],
                            input=content, text=True, capture_output=True, timeout=10, check=False)
    if result.returncode:
        raise ValueError('No se pudo '+action+' la memoria externa del proyecto.')
    return json.loads(result.stdout)


def load(project, initialize=False):
    root = Path(project).expanduser().resolve(strict=True)
    try:
        info = call('show', root)
    except ValueError:
        if not initialize:
            return {'directory': str(root), 'status': 'missing', 'content': '', 'revision': 'missing', 'path': None}
        info = call('init', root)
    doc = info['documents']['architecture']
    path = Path(doc['path']).resolve()
    if path.is_relative_to(root):
        raise ValueError('La arquitectura del agente debe estar fuera del proyecto.')
    content = ''
    if doc['revision'] != 'missing':
        if path.stat().st_size > 200000:
            raise ValueError('Arquitectura demasiado grande.')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != doc['revision']:
            raise ValueError('La arquitectura cambió durante la lectura; vuelve a consultar.')
        content = raw.decode('utf-8')
    return {'directory': info['directory'], 'status': info.get('architecture_status', 'defined' if content else 'missing'),
            'content': content, 'revision': doc['revision'], 'path': str(path)}


def require(project):
    memory = load(project)
    if memory['status'] != 'defined' or not memory['content'].strip():
        raise ValueError('Antes de modificar código hay que definir y consultar la arquitectura externa de '+str(project)+'.')
    return memory
