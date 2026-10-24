"""Controlling-PTY regressions: terminal control keys and native stdin theft."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KeyboardTests(unittest.TestCase):
    def start_hub(self, directory, args):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        original = termios.tcgetattr(slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 28, 120, 0, 0))
        env = {**os.environ, 'TERM': 'xterm-256color', 'PYTHONDONTWRITEBYTECODE': '1',
               'XDG_CONFIG_HOME': str(directory/'config'), 'XDG_STATE_HOME': str(directory/'state')}
        process = subprocess.Popen([str(ROOT/'bin/agent-hub'), *args], stdin=slave, stdout=slave, stderr=slave,
                                   env=env, start_new_session=True,
                                   preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait()
        self.addCleanup(cleanup)
        return process, master, slave, original

    def expect(self, master, marker):
        output = bytearray()
        deadline = time.monotonic()+5
        while marker not in output and time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                output.extend(os.read(master, 65536))
        self.assertIn(marker, output, output.decode(errors='replace'))

    def test_ctrl_keys_never_suspend_output_and_dialogs_return_to_menu(self):
        with tempfile.TemporaryDirectory() as temporary:
            process, master, slave, original = self.start_hub(Path(temporary), ['--demo'])
            self.expect(master, b'R sincronizar')
            # Ctrl-X is unassigned; Ctrl-S/Q are tty flow control; Ctrl-Z suspends
            # a cbreak application. All must remain ordinary keys in our menu.
            os.write(master, b'\x18\x13\x1aS')
            self.expect(master, b'AJUSTES DE COLORES')
            os.write(master, b'\x11\x18\x13\x1al')
            self.expect(master, b'violet')
            os.write(master, b'\x1b')
            self.expect(master, b'R sincronizar')
            os.write(master, b'?')
            self.expect(master, b'AYUDA')
            os.write(master, b'\x1b')
            self.expect(master, b'R sincronizar')
            os.write(master, b'p')
            self.expect(master, b'AGREGAR CARPETA')
            os.write(master, b'\x1b')
            self.expect(master, b'R sincronizar')
            os.write(master, b'q')
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(termios.tcgetattr(slave), original)

    def test_native_delete_cannot_read_navigation_keys_or_take_controlling_terminal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root/'history'; home.mkdir()
            work = root/'work'; work.mkdir()
            index = home/'index.json'
            index.write_text(json.dumps({'version': 1, 'projects': [{'id': 'ppe', 'name': 'PPE', 'roots': [str(work)]}],
                'conversations': [{'id': 'first', 'title': 'Delete fixture', 'cwd': str(work), 'updated': 2},
                                  {'id': 'remaining', 'title': 'Remaining fixture', 'cwd': str(work), 'updated': 1}]}))
            script = root/'native.py'
            script.write_text('''import json,os,pathlib,sys
# Previously this inherited curses stdin and waited for EOF indefinitely.
assert sys.stdin.read() == ''
try:
 fd=os.open('/dev/tty',os.O_RDWR)
except OSError:
 pass
else:
 os.close(fd)
 raise RuntimeError('native operation still owns the menu tty')
path=pathlib.Path(sys.argv[1])
data=json.loads(path.read_text())
data['conversations']=[c for c in data['conversations'] if c['id'] != sys.argv[2]]
path.write_text(json.dumps(data))
''')
            config = root/'config/agent-hub/agents.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'version': 1, 'agents': [
                *[{'id': ident, 'enabled': False} for ident in ('codex', 'hermes', 'claude', 'gemini', 'opencode', 'antigravity')],
                {'id': 'fixture', 'kind': 'normalized', 'home': str(home), 'command': [sys.executable, str(script)],
                 'delete': [str(index), '{session}']}]}))
            process, master, _, _ = self.start_hub(root, ['--agent', 'fixture'])
            self.expect(master, b'Delete fixture')
            os.write(master, b'td')
            self.expect(master, b'CONFIRMACI')
            os.write(master, b'cELIMINAR\n')
            self.expect(master, b'eliminada.')
            self.assertEqual([c['id'] for c in json.loads(index.read_text())['conversations']], ['remaining'])
            os.write(master, b'\x18\x13\x1ahjjl?')
            self.expect(master, b'AYUDA')
            os.write(master, b'\x1b')
            self.expect(master, b'R sincronizar')
            os.write(master, b'S')
            self.expect(master, b'AJUSTES DE COLORES')
            os.write(master, b'\x1b')
            self.expect(master, b'R sincronizar')
            os.write(master, b'q')
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertTrue(work.exists())

    def test_ctrl_c_still_exits_and_restores_shell_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            process, master, slave, original = self.start_hub(Path(temporary), ['--demo'])
            self.expect(master, b'R sincronizar')
            os.write(master, b'\x03')
            self.assertEqual(process.wait(timeout=5), 130)
            self.assertEqual(termios.tcgetattr(slave), original)

    def test_task_dashboard_returns_to_existing_browser_and_restores_terminal(self):
        with tempfile.TemporaryDirectory() as temporary:
            process,master,slave,original=self.start_hub(Path(temporary),['--demo'])
            self.expect(master,b'R sincronizar')
            os.write(master,b'T')
            self.expect(master,b'AGENT HUB')
            os.write(master,b'hl\x1b')
            self.expect(master,b'R sincronizar')
            os.write(master,b'q')
            self.assertEqual(process.wait(timeout=5),0)
            self.assertEqual(termios.tcgetattr(slave),original)
