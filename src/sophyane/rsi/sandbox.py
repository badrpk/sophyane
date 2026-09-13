"""OS-enforced read-only verification boundary. Never fall back to host execution."""
import shutil


class SandboxUnavailable(PermissionError):
    """Automatic RSI cannot execute candidate code on this host safely."""


def sandbox_command(command, cwd, scratch):
    executable = shutil.which('bwrap')
    if not executable:
        raise SandboxUnavailable('RSI requires Bubblewrap/user namespaces; unrestricted execution is forbidden')
    return [executable, '--die-with-parent', '--unshare-all', '--ro-bind', '/', '/',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', str(scratch),
            '--chdir', str(cwd), '--', *command]
