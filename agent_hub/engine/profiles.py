"""Provider-independent execution profiles; no guessing headless support."""
import json
import shutil
import time

from .tasks import AGENT_ID, fields, strings, text

ROLES = ('worker', 'reviewer', 'verifier', 'orchestrator')


def validate(raw):
    fields(raw, ('version', 'id', 'provider', 'description', 'capabilities', 'specializations',
                 'skills', 'tools', 'priority_domains', 'context_max_chars', 'cost_class',
                 'roles', 'command', 'resume_command', 'format', 'model', 'enabled', 'container', 'adapter', 'permissions'), 'agent profile')
    ident = raw.get('id')
    if not isinstance(ident, str) or not AGENT_ID.fullmatch(ident):
        raise ValueError('ID de perfil inválido.')
    if raw.get('version', 1) != 1 or type(raw.get('version', 1)) is not int:
        raise ValueError('Versión de perfil no compatible.')
    value = {'version': 1, 'id': ident, 'provider': text(raw.get('provider'), 'provider', 100),
             'description': text(raw.get('description', ident), 'description', 2000)}
    for k in ('capabilities', 'specializations', 'skills', 'tools', 'priority_domains'):
        value[k] = strings(raw.get(k, []), k)
    value['roles'] = strings(raw.get('roles', ['worker']), 'roles')
    if not value['roles'] or any(role not in ROLES for role in value['roles']):
        raise ValueError('Roles de perfil inválidos.')
    value['context_max_chars'] = raw.get('context_max_chars', 40000)
    if type(value['context_max_chars']) is not int or not 1000 <= value['context_max_chars'] <= 1000000:
        raise ValueError('Capacidad de contexto inválida.')
    value['cost_class'] = raw.get('cost_class', 'unknown')
    if value['cost_class'] not in ('local', 'low', 'medium', 'high', 'unknown'):
        raise ValueError('Clase de costo inválida.')
    command = raw.get('command', [])
    if not isinstance(command, list) or not all(isinstance(a, str) and a and '\0' not in a for a in command):
        raise ValueError('command debe ser argv, sin shell implícita.')
    value['command'] = command
    resume=raw.get('resume_command',[])
    if not isinstance(resume,list) or not all(isinstance(a,str) and a and '\0' not in a for a in resume):
        raise ValueError('resume_command debe ser argv.')
    if resume and not any('{session}' in part for part in resume):
        raise ValueError('resume_command debe contener {session}; nunca se usa latest.')
    value['resume_command']=resume
    value['format'] = raw.get('format', 'json')
    if value['format'] not in ('json', 'codex-jsonl', 'hermes-jsonl', 'gemini-jsonl', 'text'):
        raise ValueError('Formato de ejecución no compatible.')
    value['model'] = raw.get('model')
    if value['model'] is not None:
        text(value['model'], 'model', 256)
        if value['provider'] not in ('codex','hermes','gemini') and not any('{model}' in part for part in command):
            raise ValueError('El modelo declarado debe usarse en command mediante {model}.')
    value['enabled'] = raw.get('enabled', True)
    if type(value['enabled']) is not bool:
        raise ValueError('enabled debe ser booleano.')
    caps={'filesystem':'write','network':True,'dependencies':True,'git_commit':True,'git_push':False,'shell':True}
    fields(raw.get('permissions',{}),caps,'profile permissions')
    caps.update(raw.get('permissions',{}))
    if caps['filesystem'] not in ('read','write') or any(type(caps[key]) is not bool for key in caps if key!='filesystem'):
        raise ValueError('Límites de permisos del perfil no válidos.')
    value['permissions']=caps  # A ceiling, never a grant: contract + policy still apply.
    adapter=raw.get('adapter')
    if adapter is not None and (not isinstance(adapter,str) or not AGENT_ID.fullmatch(adapter)):
        raise ValueError('Adaptador de conversación inválido.')
    value['adapter']=adapter
    container=raw.get('container')
    if container is not None:
        fields(container,('name','host_root','runtime_root'),'container')
        for key in ('name','host_root','runtime_root'):
            text(container.get(key),'container.'+key,4096)
        if not container['name'].replace('-','').replace('_','').isalnum():
            raise ValueError('Nombre de contenedor inválido.')
        from pathlib import Path
        if any(not Path(container[key]).is_absolute() for key in ('host_root','runtime_root')):
            raise ValueError('Los montajes de contenedor deben ser absolutos.')
        value['container']=dict(container)
    else:
        value['container']=None
    return value


class Profiles:
    def __init__(self, conn):
        self.conn = conn

    def register(self, value):
        value = validate(value)
        with self.conn:
            self.conn.execute('INSERT INTO agent_profiles VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET spec=excluded.spec,updated=excluded.updated',
                              (value['id'], json.dumps(value, ensure_ascii=False), int(time.time())))
        return self.get(value['id'])

    def get(self, ident):
        row = self.conn.execute('SELECT spec FROM agent_profiles WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('Perfil no registrado: ' + str(ident))
        return json.loads(row[0])

    def available(self, profile):
        return bool(profile['enabled'] and profile['command'] and shutil.which('podman' if profile.get('container') else profile['command'][0]))

    def list(self):
        return [{**self.get(r[0]), 'available': self.available(self.get(r[0]))}
                for r in self.conn.execute('SELECT id FROM agent_profiles ORDER BY id')]

    def unregister(self, ident):
        # Keep identity/evidence and explicitly disable instead of erasing history.
        value = self.get(ident)
        value['enabled'] = False
        return self.register(value)
