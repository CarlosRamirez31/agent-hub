"""Public Antigravity stream/hooks only; never native databases or credentials."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import uuid


def state_home():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'agent-hub'


def index_home():
    return state_home()/'adapters'/'antigravity'


def record(native, cwd, messages=(), transcript=None, home=None):
    uuid.UUID(native)
    directory=Path(cwd)
    if not directory.is_absolute() or not directory.is_dir():raise ValueError('Antigravity workspace no válido.')
    directory=directory.resolve();home=Path(home) if home else index_home();home.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(home/'index.lock','a+') as lock:
        os.fchmod(lock.fileno(),0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        path=home/'index.json'
        value=json.loads(path.read_text()) if path.exists() else {'version':1,'projects':[],'conversations':[]}
        folder='cwd:'+str(directory)
        if not any(p['id']==folder for p in value['projects']):
            value['projects'].append({'id':folder,'name':directory.name or str(directory),'roots':[str(directory)]})
        item=next((c for c in value['conversations'] if c['id']==native),None)
        if item and item['cwd']!=str(directory):raise ValueError('El ID ya pertenece a otro workspace; no se reasoció.')
        if item is None:
            item={'id':native,'title':'Antigravity · '+native[:8],'cwd':str(directory),'project_id':folder,'messages':[]}
            value['conversations'].append(item)
        for message in messages:
            if message.get('role') not in ('user','assistant') or not isinstance(message.get('text'),str):
                raise ValueError('Solo texto visible de usuario/asistente.')
            item['messages'].append(message)
        if messages:
            title=next((m['text'] for m in messages if m['role']=='user'),None)
            if title:item['title']=title[:240]
        item['updated']=int(time.time())
        # This is a documented hook field, stored as a reference, never read.
        if transcript and isinstance(transcript,str):item['transcript_reference']=transcript
        fd,name=tempfile.mkstemp(dir=home,prefix='.index-')
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno());os.fchmod(stream.fileno(),0o600)
            os.replace(name,path)
        finally:Path(name).unlink(missing_ok=True)
    return {'version':1,'agente':'antigravity','idCarpeta':folder,'idMessage':native}


def run(prompt, session=None, probe=False, model=None, schema=None, timeout=300, command=None, cwd=None):
    if session:uuid.UUID(session)
    if probe and not session:raise ValueError('Probe requiere un ID exacto.')
    argv=[*(command or ['agy']),'--input-format','stream-json','--output-format','stream-json']
    if session:argv+=['--conversation',session]
    if model:argv+=['--model',model]
    if schema:argv+=['--json-schema',schema]
    environment={**os.environ,'AGY_CLI_DISABLE_AUTO_UPDATE':'true'}
    for key in ('LD_PRELOAD','LD_LIBRARY_PATH'):environment.pop(key,None)
    native=None;answer='';usage=None;error=None;result_seen=False;sent=False;cancelled=False
    def cancel(signum,frame):
        nonlocal cancelled
        cancelled=True
    previous=signal.signal(signal.SIGTERM,cancel)
    def stop(process):
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    try:
        with tempfile.TemporaryFile() as errors:
            process=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,
                env=environment,start_new_session=True,cwd=cwd)
            selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
            deadline=time.monotonic()+timeout;buffer=b'';total=0
            try:
                while selector.get_map():
                    if cancelled:raise ValueError('Ejecución Antigravity cancelada.')
                    if time.monotonic()>deadline:raise ValueError('Antigravity excedió su tiempo límite.')
                    for key,_ in selector.select(.05):
                        chunk=os.read(key.fileobj.fileno(),65536)
                        if not chunk:
                            selector.unregister(key.fileobj);break
                        total+=len(chunk)
                        if total>1024*1024:raise ValueError('Antigravity excedió el límite de salida.')
                        buffer+=chunk
                        while b'\n' in buffer:
                            line,buffer=buffer.split(b'\n',1)
                            if not line.strip():continue
                            event=json.loads(line)
                            if event.get('event')=='init':
                                observed=event['conversation_id'];uuid.UUID(observed)
                                actual_cwd=event.get('init',{}).get('cwd')
                                if actual_cwd and Path(actual_cwd).resolve()!=Path(cwd or os.getcwd()).resolve():
                                    raise ValueError('El CLI devolvió otro workspace; no se envió el prompt.')
                                if (session and observed!=session) or (native and native!=observed):
                                    raise ValueError('El CLI devolvió otra conversación; no se envió el prompt.')
                                native=observed
                                if not sent:
                                    sent=True
                                    if not probe:
                                        process.stdin.write((json.dumps({'event':'user','message':{'content':prompt}},ensure_ascii=False)+'\n').encode());process.stdin.flush()
                                    process.stdin.close()
                            elif event.get('event')=='result':
                                item=event.get('result',{})
                                if not native and item.get('status')!='SUCCESS':
                                    raise ValueError(item.get('error') or 'Antigravity requiere autenticación antes de iniciar la sesión.')
                                observed=item.get('conversation_id') or (native if item.get('status')!='SUCCESS' else None)
                                if not native or observed!=native:raise ValueError('Resultado de otra conversación; no se reasoció.')
                                result_seen=True;answer=item.get('response','');usage=item.get('usage',{})
                                if item.get('status')!='SUCCESS':error=item.get('error') or str(item.get('status'))
                code=process.wait(timeout=max(.1,deadline-time.monotonic()))
                errors.seek(0);diagnostic=errors.read(4000).decode('utf-8',errors='replace')
                if code:error=error or diagnostic.strip() or 'Antigravity terminó con un error.'
                if not native:raise ValueError(error or 'Antigravity no devolvió un ID verificable. Inicia sesión con agy.')
                if not probe and not result_seen:error=error or 'El CLI no devolvió un resultado final.'
                tokens=usage.get('total_tokens') if isinstance(usage,dict) else None
                return {'text':answer,'native_id':native,'tokens':tokens,'cost':None,**({'error':error} if error else {})}
            finally:
                stop(process);selector.close();process.stdout.close()
                if not process.stdin.closed:process.stdin.close()
    finally:signal.signal(signal.SIGTERM,previous)


def main(argv=None):
    parser=argparse.ArgumentParser(prog='agent-hub agy-run')
    parser.add_argument('--conversation');parser.add_argument('--probe',action='store_true')
    parser.add_argument('--no-record',action='store_true');parser.add_argument('--model');parser.add_argument('--schema')
    parser.add_argument('--json',action='store_true');parser.add_argument('--observe',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.observe:
            item=json.load(sys.stdin)
            print(json.dumps(record(item['conversationId'],item['workspacePaths'][0],transcript=item.get('transcriptPath'))));return 0
        prompt='' if args.probe else sys.stdin.read(200001)
        if not args.probe and (not prompt.strip() or len(prompt)>200000):raise ValueError('Prompt vacío o demasiado grande.')
        value=run(prompt,args.conversation,args.probe,args.model,args.schema)
        if not args.no_record and not args.probe:
            value['route']=record(value['native_id'],os.getcwd(),[{'role':'user','text':prompt},{'role':'assistant','text':value['text']}])
        print(json.dumps(value,ensure_ascii=False));return 1 if value.get('error') else 0
    except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr);return 1
