"""Read account quotas through installed native clients; never inspect credentials."""
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time


@dataclass(frozen=True)
class Window:
    label: str
    remaining: float | None
    resets: float | None


def percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return float(value)


def timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.timestamp() if parsed.tzinfo is not None else None
        except (ValueError, OverflowError):
            pass
    return None


def duration(minutes):
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or not math.isfinite(minutes) or minutes <= 0:
        return 'Periodo'
    if minutes % 1440 == 0:
        return {1440: 'Día', 10080: 'Semana'}.get(minutes, f'{minutes / 1440:g} días')
    return f'{minutes / 60:g} h' if minutes % 60 == 0 else f'{minutes:g} min'


def codex_windows(data):
    buckets = data.get('rateLimitsByLimitId')
    buckets = buckets if isinstance(buckets, dict) and buckets else {'codex': data.get('rateLimits')}
    windows = []
    for ident, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        for key in ('primary', 'secondary'):
            item = bucket.get(key)
            if not isinstance(item, dict):
                continue
            used = percent(item.get('usedPercent'))
            label = duration(item.get('windowDurationMins'))
            if len(buckets) > 1:
                label = str(bucket.get('limitName') or ident) + ' · ' + label
            windows.append(Window(label, None if used is None else 100-used, timestamp(item.get('resetsAt'))))
    return windows


def hermes_windows(data):
    names = {'Session': 'Sesión', 'Weekly': 'Semana', 'Monthly': 'Mes', 'Daily': 'Día'}
    windows = []
    for item in data.get('windows') or []:
        used = percent(item.get('used_percent'))
        label = str(item.get('label') or 'Periodo')
        windows.append(Window(names.get(label, label), None if used is None else 100-used, timestamp(item.get('resets_at'))))
    return windows


def antigravity_windows(data):
    command = data.get('command') or {}
    if command.get('name') != 'usage':
        raise ValueError('La versión instalada no expone /usage en formato estructurado.')
    windows = []
    for group in command.get('data', {}).get('groups', []):
        for item in group.get('buckets', []):
            fraction = item.get('remaining_fraction')
            remaining = percent(fraction*100) if isinstance(fraction, (int, float)) and not isinstance(fraction, bool) else None
            period = {'weekly': 'Semana', 'daily': 'Día', 'monthly': 'Mes'}.get(item.get('window'), item.get('name', 'Periodo'))
            label = str(group.get('name') or 'Modelos') + ' · ' + str(period)
            windows.append(Window(label, remaining, timestamp(item.get('reset_time'))))
    return windows


def native_json(argv, env=None):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=18, env=env, check=False)
    if result.returncode:
        # Native errors can contain account/config details. Keep them out of the UI.
        raise ValueError('El cliente nativo no pudo consultar la cuota; prueba u para actualizar.')
    if len(result.stdout) > 1024*1024:
        raise ValueError('Respuesta de cuota demasiado grande.')
    try:
        value = json.loads(result.stdout)
    except ValueError as error:
        raise ValueError('El cliente nativo no devolvió una cuota estructurada.') from error
    if not isinstance(value, dict):
        raise ValueError('Respuesta de cuota no compatible.')
    return value


def fetch(agent):
    if agent.kind == 'codex' and not agent.container:
        from .rpc import CodexReader
        from . import __version__
        reader = CodexReader(agent.home, timeout=6)
        try:
            reader.call('initialize', {'clientInfo': {'name': 'agent_hub', 'version': __version__}})
            reader.send({'method': 'initialized', 'params': {}})
            return codex_windows(reader.call('account/rateLimits/read', {}))
        finally:
            reader.close()
    if agent.kind == 'hermes':
        command = ['podman', 'exec', agent.container, '/usr/local/bin/hermes'] if agent.container else list(agent.command)
        env = None if agent.container else {**os.environ, 'HERMES_HOME': agent.home}
        return hermes_windows(native_json(command + ['usage', '--json'], env))
    if agent.kind == 'antigravity':
        env = {**os.environ, 'AGY_CLI_DISABLE_AUTO_UPDATE': 'true'}
        return antigravity_windows(native_json(list(agent.command) + ['--print', '/usage', '--output-format', 'json', '--print-timeout', '10s'], env))
    raise ValueError('Este agente no publica una cuota compatible. No se estima el saldo.')


def countdown(reset, now):
    if reset is None:
        return 'reinicio no informado'
    if reset <= now:
        return 'reinicio pendiente de confirmar'
    seconds = max(1, math.ceil(reset-now))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds//60
    delay = f'{days}d {hours}h' if days else f'{hours}h {minutes:02}m' if hours else f'{minutes}m' if minutes else '<1m'
    try:
        date = datetime.fromtimestamp(reset).strftime('%d/%m %H:%M')
    except (OverflowError, ValueError, OSError):
        return 'reinicio no informado'
    return f'reinicia en {delay} · {date}'


class Monitor:
    def __init__(self, agent, loader=fetch):
        self.agent, self.loader = agent, loader
        self.windows, self.error, self.updated = (), '', None
        self.loading, self.attempt = False, None
        self.lock = threading.Lock()

    def refresh(self, force=False):
        with self.lock:
            now = time.monotonic()
            if self.loading or (self.attempt is not None and now-self.attempt < (15 if force else 300)):
                return False
            self.loading, self.attempt = True, now
        threading.Thread(target=self._load, daemon=True, name='agent-hub-usage').start()
        return True

    def _load(self):
        try:
            windows = tuple(self.loader(self.agent))
            error = '' if windows else 'El proveedor no informa porcentajes de cuota.'
            if windows and self.agent is not None:
                from .manager import private_json
                state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state')))/'agent-hub'
                try:
                    private_json(state/'usage-cache'/(self.agent.id+'.json'),
                                 {'checked_at': time.time(), 'provider': self.agent.kind,
                                  'windows': [asdict(window) for window in windows]})
                except OSError:
                    pass  # Cache failure must not hide a successful native reading.
        except Exception:
            windows, error = (), 'Cuota no disponible · u reintenta · sin estimaciones'
        with self.lock:
            if windows:
                self.windows, self.updated = windows, time.time()
            self.error, self.loading = error, False

    def lines(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            windows, error, updated, loading = self.windows, self.error, self.updated, self.loading
        heading = 'CUOTA · cuenta del proveedor · u actualizar'
        if loading:
            heading += ' · consultando…'
        elif updated is not None:
            heading += ' · ' + ('dato anterior' if error else 'consultado ' + datetime.fromtimestamp(updated).strftime('%H:%M'))
        if not windows:
            return [heading, error or 'Consultando límites y próximos reinicios…']
        rows = []
        for window in windows:
            remaining = 'no informado' if window.remaining is None else f"{window.remaining:.1f}".rstrip('0').rstrip('.') + '% restante'
            rows.append(window.label + ': ' + remaining + ' · ' + countdown(window.resets, now))
        return [heading, *rows]


_MONITORS = {}


def for_agent(agent):
    key = (agent.id, agent.kind, agent.home, agent.container, tuple(agent.command))
    if key not in _MONITORS:
        _MONITORS[key] = Monitor(agent)
    monitor = _MONITORS[key]
    monitor.refresh()
    return monitor
