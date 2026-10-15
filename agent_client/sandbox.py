"""Optional Linux execution isolation; configured servers fail closed."""
import os
import shutil


def prepare(policy, tokens, environment):
    mode = os.environ.get('CODESPIDER_EXECUTION_SANDBOX', '')
    if not mode:
        return tokens, environment
    if mode != 'bubblewrap':
        raise ValueError('Unsupported execution sandbox: ' + mode)
    executable = shutil.which('bwrap')
    if not executable:
        raise ValueError('执行隔离未就绪：请安装 bubblewrap；不会降级为宿主机执行')
    # The child sees system runtimes and only this workspace, never service state,
    # other projects, SSH credentials, IPC sockets or the host process namespace.
    command = [executable, '--die-with-parent', '--unshare-all', '--share-net', '--new-session']
    for directory in ('/usr', '/bin', '/sbin', '/lib', '/lib64'):
        if os.path.exists(directory):
            command += ['--ro-bind', directory, directory]
    command += ['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/etc']
    for path in ('/etc/alternatives','/etc/ssl','/etc/ca-certificates','/etc/resolv.conf','/etc/hosts','/etc/localtime','/etc/nsswitch.conf','/etc/passwd','/etc/group','/etc/java-21-openjdk','/etc/maven/m2.conf','/etc/maven/logging'):
        if os.path.exists(path):
            command += ['--ro-bind', path, path]
    command += ['--bind', policy.root, policy.root, '--chdir', policy.root, '--dir', '/tmp/home', '--']
    environment = {k:v for k,v in environment.items() if k in ('PATH','LANG','LC_ALL','JAVA_HOME')}
    environment.update(HOME='/tmp/home', TMPDIR='/tmp', PATH='/usr/local/bin:/usr/bin:/bin',
                       JAVA_TOOL_OPTIONS='-Duser.home=/tmp/home')
    return command + tokens, environment
