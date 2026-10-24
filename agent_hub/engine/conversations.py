"""An execution's exact native conversation, resolved by its declared adapter."""
import json
import re
from .profiles import Profiles
from .tasks import task_id,number


def execution_number(ident):
    if not isinstance(ident,str) or not re.fullmatch(r'EXEC-[0-9]{3,12}',ident):
        raise ValueError('ID de ejecución inválido.')
    value=int(ident[5:])
    if value<1 or ident!=f'EXEC-{value:03d}':raise ValueError('ID de ejecución no canónico.')
    return value


class Conversations:
    def __init__(self,conn,state):self.conn,self.state=conn,state
    def get(self,ident):
        row=self.conn.execute('SELECT * FROM executions WHERE id=?',(execution_number(ident),)).fetchone()
        if not row:raise ValueError('Ejecución no encontrada.')
        return {**dict(row),'id':ident,'task':task_id(row['task']),'result':json.loads(row['result']) if row['result'] else None}
    def list(self,task):
        from .tasks import TaskStore
        TaskStore(self.conn).get(task)
        return [self.get(f'EXEC-{r[0]:03d}') for r in self.conn.execute('SELECT id FROM executions WHERE task=? ORDER BY id',(number(task),))]
    def route(self,ident):
        execution=self.get(ident)
        if execution['status']=='running':raise ValueError('La ejecución está activa; detén/libera su proceso antes de abrir otra instancia.')
        profile=(execution['result'] or {}).get('profile_snapshot') or Profiles(self.conn).get(execution['profile'])
        adapter=profile.get('adapter')
        native=(execution['result'] or {}).get('native_id')
        if not adapter or not native:raise ValueError('La ejecución no tiene un adaptador/ID nativo verificados; no se abrirá otra conversación.')
        from ..manager import Manager
        from ..agents import registry
        matches=[agent for agent in registry() if agent.id==adapter]
        if len(matches)!=1:raise ValueError('El adaptador de esta ejecución ya no está registrado.')
        manager=Manager(matches,self.state)
        try:
            manager.sync([adapter])
            if manager.errors:raise ValueError(manager.errors[adapter])
            chats,projects=manager.snapshot(adapter)
            found=[chat for chat in chats if chat.id==native]
            if len(found)!=1:raise ValueError('La conversación nativa ya no está disponible; no se recreó ni se eligió otra.')
            saved=(execution['result'] or {}).get('route')
            if saved:
                if saved['agente']!=adapter:
                    raise ValueError('El descriptor guardado no pertenece al adaptador real de esta ejecución.')
                manager.resolve(saved)
                route=saved
            else:
                route=manager.route(adapter,found[0],projects)
                stored={**(execution['result'] or {}),'route':route}
                with self.conn:
                    self.conn.execute('UPDATE executions SET result=? WHERE id=?',(json.dumps(stored,ensure_ascii=False),execution_number(ident)))
            return {'execution':ident,'task':execution['task'],'profile':profile['id'],'native_id':native,'route':route}
        finally:manager.close()
    def open(self,ident,dry_run=False):
        value=self.route(ident)
        from ..manager import Manager
        manager=Manager(state=self.state)
        try:
            manager.resolve(value['route'])
            return value if dry_run else manager.open(value['route'])
        finally:manager.close()

    def bind(self,ident,native):
        execution=self.get(ident)
        if execution['status']=='running':
            raise ValueError('La ejecución todavía está activa.')
        from ..agents import check_id
        check_id(native)
        result=execution['result'] or {}
        if result.get('native_id') and result['native_id']!=native:
            raise ValueError('Esta ejecución ya tiene otro ID verificado; no se reemplazará.')
        snapshot=result.get('profile_snapshot') or {k:v for k,v in Profiles(self.conn).get(execution['profile']).items() if k in ('id','provider','adapter','container','model','format')}
        if not snapshot.get('adapter'):
            raise ValueError('Falta el adaptador original de esta ejecución.')
        # Resolve/validate against the public native index before any association
        # is committed; rollback on a missing/deleted or ambiguous session.
        from ..agents import registry
        from ..manager import Manager
        matches=[a for a in registry() if a.id==snapshot['adapter']]
        if len(matches)!=1:raise ValueError('Adaptador original no disponible.')
        manager=Manager(matches,self.state)
        try:
            manager.sync([matches[0].id])
            if manager.errors:raise ValueError(manager.errors[matches[0].id])
            chats,projects=manager.snapshot(matches[0].id)
            found=[chat for chat in chats if chat.id==native]
            if len(found)!=1:raise ValueError('ID nativo no encontrado; no se adivinó otra conversación.')
            route=manager.route(matches[0].id,found[0],projects)
            manager.resolve(route)
        finally:manager.close()
        result={**result,'native_id':native,'profile_snapshot':snapshot,'route':route}
        with self.conn:
            self.conn.execute('UPDATE executions SET result=? WHERE id=?',(json.dumps(result,ensure_ascii=False),execution_number(ident)))
            from .tasks import TaskStore
            TaskStore(self.conn).event(execution['task'],'execution.bound',{'execution':ident,'native_id':native,'route':route})
        return self.get(ident)
