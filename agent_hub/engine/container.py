"""Host coordinator for an isolated worker inside an existing Podman container."""
import json
import os
from pathlib import Path
import tempfile
from .process import run_command,MAX_OUTPUT
from .workspace import git


def controls(state, execution):
    return Path(state)/'process-controls'/str(execution)


def write_private(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temporary=tempfile.mkstemp(dir=path.parent,prefix='.pending-')
    try:
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600);json.dump(value,stream,ensure_ascii=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def execute_container(profile,workspace,state,execution,argv,prompt,timeout,writable,network,runtime_paths,started,cancelled):
    config=profile['container']
    host=Path(config['host_root']).resolve()
    runtime=Path(config['runtime_root'])
    def mapped(path):
        try:
            return str(runtime/Path(path).resolve().relative_to(host))
        except ValueError as error:
            raise ValueError('El contenedor no tiene montada esta ruta de trabajo/estado.') from error
    directory=controls(state,execution)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    cancel=directory/'cancel'
    complete=directory/'complete'
    common=Path(git(workspace,'rev-parse','--git-common-dir').decode().strip())
    if not common.is_absolute():common=(Path(workspace)/common).resolve()
    request={'argv':argv,'workspace':str(Path(workspace).resolve()),'source_workspace':mapped(workspace),
             'aliases':[[str(runtime),str(host)]],'common_directory':[mapped(common),str(common)],
             'timeout':timeout,'writable':writable,'network':network,'runtime_paths':runtime_paths,
             'cancel':mapped(cancel),'complete':mapped(complete)}
    descriptor=directory/'request.json';write_private(descriptor,request)
    helper=Path(__file__).resolve().with_name('container_process.py')
    command=['podman','exec','-i',config['name'],'python3','-B',mapped(helper),'--request',mapped(descriptor)]
    def watch_cancel():
        if cancelled and cancelled():
            write_private(cancel,{'cancel':True})
        # Let the inner runner terminate its own child and acknowledge; killing
        # only the Podman client would abandon a live process in the container.
        return False
    result=run_command(command,workspace,prompt,timeout+5,started,watch_cancel,output_limit=3*MAX_OUTPUT)
    if result['code'] or result['failure']:
        write_private(cancel,{'cancel':True})
        return result
    try:
        inner=json.loads(result['stdout'])
    except ValueError as error:
        raise ValueError('El runner del contenedor no devolvió una respuesta válida.') from error
    if not isinstance(inner,dict) or not {'code','stdout','stderr','failure','duration'}<=set(inner):
        raise ValueError('Respuesta incompleta del runner aislado.')
    return inner
