"""Opt-in work dashboard, sharing the original palette and Vim navigation."""
import curses
import json
import sqlite3
import textwrap
from .cli import clean,read_contract
from .tasks import TaskStore
from .profiles import Profiles
from .runs import Runs
from .quality import Quality
from .execution import Runner
from .context import Contexts
from .routing import Router
from .skills import Skills
from ..style import Style
from ..terminal import prepare_input,read_key

TABS=('Projects','Agents','Runs','Tasks','Reviews','Handoffs','Skills','Events')


class Dashboard:
    def __init__(self,screen,cache,state,demo=False):
        self.screen,self.cache,self.conn,self.state,self.demo=screen,cache,cache.conn,state,demo
        self.tab,self.index=3,0
        self.note='Datos locales · Enter detalles · n tarea · o plan · ? ayuda'
        self.style=Style()

    def rows(self):
        if TABS[self.tab]=='Tasks':return TaskStore(self.conn).list()
        if TABS[self.tab]=='Runs':return Runs(self.conn,self.state).list()
        if TABS[self.tab]=='Agents':return Profiles(self.conn).list()
        if TABS[self.tab]=='Skills':return Skills(self.conn).list()
        tables={'Projects':'projects','Reviews':'reviews','Handoffs':'structured_handoffs','Events':'engine_events'}
        table=tables.get(TABS[self.tab])
        return [dict(r) for r in self.conn.execute('SELECT * FROM '+table+' ORDER BY rowid DESC LIMIT 500')]

    def value(self,row):
        return row.json() if hasattr(row,'json') else row

    def put(self,y,text,attr=0):
        height,width=self.screen.getmaxyx()
        if 0<=y<height:
            try:self.screen.addnstr(y,2,clean(text),max(1,width-4),attr)
            except curses.error:pass

    def draw(self):
        self.screen.erase();height,width=self.screen.getmaxyx();rows=self.rows()
        self.index=max(0,min(self.index,max(0,len(rows)-1)))
        self.put(1,'AGENT HUB · WORK · '+TABS[self.tab]+(' · DEMO' if self.demo else ''),curses.A_BOLD|self.style.color(1))
        self.put(2,' | '.join('['+name+']' if i==self.tab else name for i,name in enumerate(TABS)))
        room=max(1,height-8);offset=max(0,self.index-room+1)
        for index,row in enumerate(rows[offset:offset+room],offset):
            item=self.value(row)
            title=item.get('contract',{}).get('title') or item.get('title') or item.get('description') or item.get('name') or item.get('type') or ''
            label=f"{item.get('id',item.get('task',''))}  {item.get('status',item.get('verdict',''))}  {title}"
            self.put(4+index-offset,label,self.style.color(2) if index==self.index else 0)
        if not rows:self.put(4,'Sin registros en esta sección.')
        self.put(height-3,self.note,self.style.color(1))
        self.put(height-2,'j/k mover · h/l secciones · Enter ver · n tarea · o plan · a asignar · v verificar · r review · e ejecutar')
        self.put(height-1,'c contexto · x handoff · q/Esc volver · Ctrl+C salir')
        self.screen.refresh()

    def prompt(self,label):
        value=''
        while True:
            height,_=self.screen.getmaxyx();self.screen.move(height-3,0);self.screen.clrtoeol();self.put(height-3,label+': '+value);self.screen.refresh()
            key=read_key(self.screen)
            if key in ('\n','\r',curses.KEY_ENTER):return value.strip()
            if key=='\x1b':return None
            if key in ('\x7f','\b',curses.KEY_BACKSPACE):value=value[:-1]
            elif key=='\x15':value=''
            elif isinstance(key,str) and key.isprintable():value+=key

    def detail(self,value):
        lines=[]
        for line in json.dumps(value,ensure_ascii=False,indent=2).splitlines():
            lines.extend(textwrap.wrap(clean(line),max(10,self.screen.getmaxyx()[1]-4)) or [''])
        offset=0
        while True:
            self.screen.erase();height,_=self.screen.getmaxyx()
            self.put(1,'DETALLES · j/k desplazar · Esc/q volver',self.style.color(1))
            for y,line in enumerate(lines[offset:offset+max(1,height-4)],3):self.put(y,line)
            self.screen.refresh();key=read_key(self.screen)
            if key in ('q','\x1b'):return
            if key in ('j',curses.KEY_DOWN):offset=min(max(0,len(lines)-1),offset+1)
            elif key in ('k',curses.KEY_UP):offset=max(0,offset-1)

    def operation(self,key,row):
        selected=self.value(row) if row is not None else None
        if key=='n':
            title=self.prompt('Título (Esc cancela)')
            if title:
                task=TaskStore(self.conn).create({'title':title,'objective':title})
                self.note='Creada '+task.id;self.tab=3
        elif key=='o':
            intent=self.prompt('Objetivo del plan')
            if intent:
                run=Runs(self.conn,self.state).plan(intent);self.note='Plan guardado: '+run['id'];self.tab=2
        elif key in ('\n','\r',curses.KEY_ENTER) and selected:
            self.detail(selected)
        elif key=='?' :
            self.detail({'control':'Las acciones de ejecución requieren confirmación explícita; los planes no lanzan modelos.',
                         'setup':'agent-hub work init registra perfiles. Los repositorios, checks, policies y aprobaciones se configuran por CLI JSON.',
                         'manual':'q/Esc vuelve al explorador original. Abrir sesiones nativas y raw handoff conservan sus atajos.'})
        elif selected and TABS[self.tab]=='Tasks':
            ident=selected['id']
            if key=='a':
                profile=self.prompt('Agente fixed')
                if profile:
                    Profiles(self.conn).get(profile)
                    contract={**selected['contract'],'assignment':{'mode':'fixed','agent':profile}}
                    TaskStore(self.conn).replace_contract(ident,contract,'explicit human assignment in TUI');self.note='Asignación guardada.'
            elif key=='c':
                profile=self.prompt('Perfil del context pack')
                if profile:self.detail(Contexts(self.conn,self.state).build(ident,Profiles(self.conn).get(profile)))
            elif key=='x':
                source=self.prompt('Perfil origen');target=self.prompt('Perfil destino');summary=self.prompt('Resumen de handoff')
                if source and target and summary:
                    self.detail(Contexts(self.conn,self.state).handoff(ident,source,target,'manual',{'summary':summary}))
            elif key in ('v','r','e'):
                if self.demo:raise ValueError('Demo: no ejecuta comandos ni agentes.')
                checks=self.prompt('Archivo JSON de checks') if key=='v' else None
                profile=self.prompt('Perfil reviewer') if key=='r' else None
                if (key=='v' and not checks) or (key=='r' and not profile):return
                if self.prompt('Escribe EJECUTAR para confirmar')!='EJECUTAR':return
                def run():
                    if key=='v':return Quality(self.conn,self.state).verify(ident,read_contract(checks))
                    return Runner(self.conn,self.state).run(ident,profile,role='reviewer' if key=='r' else 'worker')
                self.external(run)
        elif key=='e' and selected and TABS[self.tab]=='Runs':
            if self.demo:raise ValueError('Demo: no ejecuta agentes.')
            if self.prompt('Escribe EJECUTAR para confirmar')=='EJECUTAR':self.external(lambda:Runs(self.conn,self.state).execute(selected['id']))

    def external(self,operation):
        curses.def_prog_mode();curses.endwin()
        try:
            print('Agent Hub: ejecutando trabajo autorizado. Ctrl+C cancela los procesos propios de esta operación.')
            value=operation();self.note='Resultado: '+str(value.get('status',value.get('passed','guardado')))
        finally:
            curses.reset_prog_mode();prepare_input(self.screen);self.screen.clear()

    def run(self):
        while True:
            prepare_input(self.screen);self.draw();key=read_key(self.screen)
            if key in ('q','\x1b'):return
            height,width=self.screen.getmaxyx()
            if height<12 or width<50:continue
            rows=self.rows();row=rows[self.index] if rows else None
            try:
                if key in ('h',curses.KEY_LEFT,'l',curses.KEY_RIGHT,'\t'):
                    self.tab=(self.tab+(-1 if key in ('h',curses.KEY_LEFT) else 1))%len(TABS);self.index=0
                elif key in ('j',curses.KEY_DOWN):self.index=min(max(0,len(rows)-1),self.index+1)
                elif key in ('k',curses.KEY_UP):self.index=max(0,self.index-1)
                else:self.operation(key,row)
            except (ValueError,OSError,sqlite3.Error) as error:self.note=str(error)
            except KeyboardInterrupt:self.note='Operación cancelada.'
