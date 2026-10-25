"""Bounded, cancellable owned processes inside an OS worktree sandbox."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time

MAX_OUTPUT = 1024 * 1024


def token(pid):
    try:
        return Path(f'/proc/{int(pid)}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def terminate_owned(pid, expected):
    if expected and token(pid) == expected:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return True
    return False


def sandbox(argv, workspace, writable, network=False, runtime_paths=(), source_workspace=None, aliases=(), common_directory=None, inherited_proc=False):
    # Existing unprivileged Podman containers cannot mount a fresh procfs.
    # Bind theirs read-only while retaining a new PID namespace, so workers
    # still cannot signal processes outside their own execution.
    path = str(Path(workspace).resolve())
    command = ['bwrap', '--die-with-parent', '--new-session', '--unshare-pid', '--unshare-ipc', '--unshare-uts', '--ro-bind', '/', '/',
               '--ro-bind' if inherited_proc else '--proc', '/proc', *(['/proc'] if inherited_proc else []),
               '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/run']
    if not network:
        command += ['--unshare-net']
    source = str(Path(source_workspace or workspace).resolve())
    for origin, destination in aliases:
        command += ['--ro-bind', origin, destination]
    common = None
    if common_directory:
        command += ['--ro-bind', common_directory[0], common_directory[1]]
        common = Path(common_directory[1])
    elif (Path(path)/'.git').exists():
        from .workspace import git
        common = Path(git(path, 'rev-parse', '--git-common-dir').decode().strip())
        if not common.is_absolute():
            common = (Path(path)/common).resolve()
        command += ['--ro-bind', str(common), str(common)]
    command += ['--bind' if writable else '--ro-bind', source, path]
    ipc = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'ipc'
    if ipc.is_dir():
        command += ['--tmpfs', str(ipc)]
    for origin, destination in aliases:
        if (Path(origin)/'.codex/ipc').is_dir():
            command += ['--tmpfs', str(Path(destination)/'.codex/ipc')]
    for directory in runtime_paths:
        directory = Path(directory).expanduser().resolve()
        if (not directory.is_dir() or directory in (Path('/'), Path.home())
                or directory == Path(path) or directory in Path(path).parents
                or (common is not None and (directory == common or directory in common.parents or common in directory.parents))):
            raise ValueError('Excepción de estado de agente demasiado amplia o inexistente.')
        command += ['--bind', str(directory), str(directory)]
    return [*command, '--chdir', path, '--', *argv]


def execute(argv, workspace, prompt='', timeout=300, writable=False, network=False,
            runtime_paths=(), started=None, cancelled=None, environment=None):
    command = sandbox(argv, workspace, writable, network, runtime_paths)
    return run_command(command, workspace, prompt, timeout, started, cancelled, environment=environment)


def run_command(command, workspace, prompt='', timeout=300, started=None, cancelled=None, output_limit=MAX_OUTPUT, environment=None):
    environment = {**os.environ, **(environment or {})}
    for key in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'BASH_ENV', 'ENV', 'PYTHONSTARTUP'):
        environment.pop(key, None)
    # Do not let the worker invoke Git writes to the shared common directory.
    environment['GIT_TERMINAL_PROMPT'] = '0'
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    buffers = [bytearray(), bytearray()]
    exceeded = threading.Event()
    def consume(pipe, buffer):
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                room = output_limit - len(buffer)
                buffer.extend(chunk[:max(0, room)])
                if len(chunk) > room:
                    exceeded.set()
        finally:
            pipe.close()
    with tempfile.TemporaryFile() as source:
        source.write(prompt.encode('utf-8')); source.seek(0)
        begin = time.monotonic()
        if cancelled and cancelled():
            return {'code':130,'stdout':'','stderr':'','failure':'cancelled','duration':0}
        process = subprocess.Popen(command, cwd=workspace, stdin=source, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True, env=environment)
        identity = token(process.pid)
        workers = [threading.Thread(target=consume, args=(pipe, buffer), daemon=True)
                   for pipe, buffer in zip((process.stdout, process.stderr), buffers)]
        for worker in workers:
            worker.start()
        failure = None
        try:
            if started:
                started(process.pid, identity)
            while process.poll() is None:
                if time.monotonic()-begin >= timeout:
                    failure = 'timeout'
                elif exceeded.is_set():
                    failure = 'output_limit'
                elif cancelled and cancelled():
                    failure = 'cancelled'
                if failure:
                    terminate_owned(process.pid, identity)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        # This exact Popen child is still alive; never act on a reused PID.
                        process.kill(); process.wait()
                    break
                time.sleep(.05)
        except BaseException:
            terminate_owned(process.pid, identity)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
            raise
        for worker in workers:
            worker.join(timeout=1)
        if any(worker.is_alive() for worker in workers):
            failure = failure or 'open_output_pipe'
        if exceeded.is_set():
            failure = failure or 'output_limit'
        return {'code': process.returncode, 'stdout': buffers[0].decode('utf-8', errors='replace'),
                'stderr': buffers[1].decode('utf-8', errors='replace'), 'failure': failure,
                'duration': time.monotonic()-begin}
