from subprocess import check_output
import re

from ipykernel.kernelbase import Kernel
from paramiko.ssh_exception import SSHException
import paramiko

__version__ = '0.1.0'

version_pat = re.compile(r'version (\d+(\.\d+)+)')

from .images import (
    extract_image_filenames, display_data_for_image, image_setup_cmd
)

class SSHKernel(Kernel):
    implementation = 'ssh_kernel'
    implementation_version = __version__

    @property
    def language_version(self):
        m = version_pat.search(self.banner)
        return m.group(1)

    _banner = None

    @property
    def banner(self):
        if self._banner is None:
            self._banner = check_output(['ssh', '-V']).decode('utf-8')
        return self._banner

    language_info = {'name': 'ssh',
                     'codemirror_mode': 'shell',
                     'mimetype': 'text/x-sh',
                     'file_extension': '.sh'}

    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)

        opts = dict(user='temp', password='temp')
        self._connect(**opts)

    def _connect(self, **opts):
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect('localhost', username=opts["user"], password=opts["password"], timeout=1)
        self._client = client

    def process_output(self, stream):
        if not self.silent:
            # image_filenames, output = extract_image_filenames(output)
            for line in stream:
                stream_content = {'name': 'stdout', 'text': line}
                self.send_response(self.iopub_socket, 'stream', stream_content)

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):
        self.silent = silent
        if not code.strip():
            return {'status': 'ok', 'execution_count': self.execution_count,
                    'payload': [], 'user_expressions': {}}

        interrupted = False
        try:
            _, o, e = self._client.exec_command(code)
            self.process_output(o)

        except KeyboardInterrupt:
            # fixme: sendintr
            # Use paramiko.Channel directly instead of paramiko.Client

            interrupted = True
            self.process_output('* interrupt')

        except SSHException:  # fixme: undefined
            output = 'Reconnect SSH...'
            self._connect()
            self.process_output(output)

        if interrupted:
            # fixme: Print aside tornado log
            print("interrupted = True")

            return {'status': 'abort', 'execution_count': self.execution_count}

        try:
            _, o, _ = self._client.exec_command('echo $?')
            exitcode = int(o.read().rstrip())
        except Exception as e:
            exitcode = 1
            traceback = str(e)

        # fixme: Print aside tornado log
        self.log.debug("exitcode = {}".format(exitcode))

        if exitcode:
            error_content = {
                'execution_count': self.execution_count,
                'ename': '',
                'evalue': str(exitcode),
                'traceback': [traceback],
            }

            self.send_response(self.iopub_socket, 'error', error_content)
            error_content['status'] = 'error'
            return error_content
        else:
            return {'status': 'ok', 'execution_count': self.execution_count,
                    'payload': [], 'user_expressions': {}}

    def do_complete(self, code, cursor_pos):
        code = code[:cursor_pos]
        default = {'matches': [], 'cursor_start': 0,
                   'cursor_end': cursor_pos, 'metadata': dict(),
                   'status': 'ok'}

        if not code or code[-1] == ' ':
            return default

        tokens = code.replace(';', ' ').split()
        if not tokens:
            return default

        matches = []
        token = tokens[-1]
        start = cursor_pos - len(token)

        if token[0] == '$':
            # complete variables
            cmd = 'compgen -A arrayvar -A export -A variable %s' % token[1:] # strip leading $
            output = self.bashwrapper.run_command(cmd).rstrip()
            completions = set(output.split())
            # append matches including leading $
            matches.extend(['$'+c for c in completions])
        else:
            # complete functions and builtins
            cmd = 'compgen -cdfa %s' % token
            output = self.bashwrapper.run_command(cmd).rstrip()
            matches.extend(output.split())

        if not matches:
            return default
        matches = [m for m in matches if m.startswith(token)]

        return {'matches': sorted(matches), 'cursor_start': start,
                'cursor_end': cursor_pos, 'metadata': dict(),
                'status': 'ok'}
