import time
import yaml

from plumbum.machines.paramiko_machine import ParamikoMachine

from .ssh_wrapper import SSHWrapper


class SSHWrapperPlumbum(SSHWrapper):
    '''
    A plumbum remote machine wrapper
    '''

    def __init__(self):
        self._remote = None
        self._connected = False
        self._host = ''

    def _append_command(self, cmd, marker):
        '''
        Append header/footer to `cmd`.

        Returns:
          str: new_command
        '''
        header = ''
        footer = '''
EXIT_CODE=$?
echo {marker}code: $EXIT_CODE
echo {marker}pwd: $(pwd)
echo {marker}env: $(cat -v <(env -0))
'''.format(marker=marker)

        full_command = '\n'.join([header, cmd, footer])

        return full_command

    def exec_command(self, cmd, print_function):
        '''
        Returns:
          int: exit_code
            * Return the last command exit_code
            * Return 1 if failed to execute a command

        Raises:
            plumbum.commands.processes.ProcessExecutionError: If exit_code is 0
        '''

        print_function('[INFO] host = {}\n'.format(self._host))

        timeout = None

        marker = str(time.time())
        full_command = self._append_command(cmd, marker)

        iterator = self._remote['bash'][
            '-c',
            full_command,
        ].popen().iter_lines()

        env_out = ''
        for (out, err) in iterator:
            line = out if out else err

            if line.startswith(marker):
                env_out += line.split(marker)[1]
            else:
                print_function(line)

        if env_out:
            return self.post_exec_command(env_out)
        else:
            return 1

    def connect(self, host):
        if self._remote:
            self.close()

        remote = ParamikoMachine(host, load_system_ssh_config=True)
        envdelta = {'PAGER': 'cat'}
        remote.env.update(envdelta)

        self._remote = remote
        self._connected = True
        self._host = host

    def close(self):
        self._connected = False
        self._remote.close()

    def interrupt(self):
        pass

    def isconnected(self):
        return self._connected

    # private methods
    def post_exec_command(self, env_out):
        '''Receive yaml string, update instance state with its value

        Return:
            int: exit_code
        '''
        env_at_footer = yaml.load(env_out)

        newdir = env_at_footer['pwd']
        newenv = env_at_footer['env']
        self.update_workdir(newdir)
        self.update_env(newenv)

        if 'code' in env_at_footer:
            return env_at_footer['code']
        else:
            print('[ERROR] Cannot parse exit_code. As a result, returing code=1')
            return 1

    def update_workdir(self, newdir):
        cwd = self._remote.cwd.getpath()._path
        if newdir != cwd:
            self._remote.cwd.chdir(newdir)
            print('[DEBUG] new cwd: {}'.format(newdir))

    def update_env(self, newenv):
        delimiter = '^@'
        parsed_newenv = dict([
            kv.split('=', 1) for kv in newenv.split(delimiter) if kv
        ])
        self._remote.env.update(parsed_newenv)
