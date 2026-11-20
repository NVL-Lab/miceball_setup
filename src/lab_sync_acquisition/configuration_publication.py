"""Protected publication of existing deployment configuration files; no configuration store."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import stat
from tempfile import NamedTemporaryFile
from uuid import uuid4


class ConfigurationPublicationUnconfirmed(RuntimeError):
    """Replacement may have occurred but durable exact confirmation is unavailable."""


def configuration_revision(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def read_configuration_bytes(path):
    """Read one regular, unaliased configuration and verify its identity through the read."""
    path = Path(path).absolute()
    before = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("Configuration aliases and nonregular files cannot be modified")
    with path.open("rb") as source:
        opened = os.fstat(source.fileno())
        contents = source.read()
    after = path.lstat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or (opened.st_dev, opened.st_ino) != (after.st_dev, after.st_ino)):
        raise RuntimeError("Configuration changed during readback")
    return contents


@contextmanager
def configuration_guard(path):
    """Serialize cooperating publishers using a stable, non-authoritative lock file."""
    path = Path(path).absolute()
    read_configuration_bytes(path)
    lock_path = path.with_name('.' + path.name + '.lock')
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'r+b') as lock:
        identity = os.fstat(lock.fileno())
        if (lock_path.resolve() != lock_path or identity.st_nlink != 1
                or (identity.st_dev, identity.st_ino) != (lock_path.stat().st_dev, lock_path.stat().st_ino)):
            raise ValueError("Configuration lock aliases are not permitted")
        if os.name == 'nt':
            import msvcrt
            if not identity.st_size:
                lock.write(b'\0'); lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def preserve_configuration_access(path, temporary):
    """Prepare POSIX ownership/mode/ACL; Windows replacement retains target metadata."""
    path, temporary = Path(path), Path(temporary)
    if os.name != 'nt':
        identity, replacement = path.stat(), temporary.stat()
        if (replacement.st_uid, replacement.st_gid) != (identity.st_uid, identity.st_gid):
            os.chown(temporary, identity.st_uid, identity.st_gid)
        shutil.copystat(path, temporary)
        if hasattr(os, 'listxattr'):
            for name in os.listxattr(path):
                if name.startswith(('security.', 'system.posix_acl')) and os.getxattr(temporary, name) != os.getxattr(path, name):
                    raise RuntimeError('Configuration access controls could not be preserved')
        return


def replace_configuration_file(path, temporary):
    """Perform replacement after access-control preparation."""
    path, temporary = Path(path), Path(temporary)
    if os.name != 'nt':
        os.replace(temporary, path)
        return
    import ctypes
    replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
    replace.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                        ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
    replace.restype = ctypes.c_int
    backup = path.with_name('.configuration-backup-' + uuid4().hex)
    if not replace(str(path), str(temporary), str(backup), 0, None, None):
        raise ConfigurationPublicationUnconfirmed('Configuration replacement unconfirmed; retained backup may require inspection')
    backup.unlink()


def publish_configuration(path, expected_revision, contents: bytes):
    """Publish validated bytes under a shared guard and confirm current durable content."""
    path = Path(path).absolute()
    with configuration_guard(path):
        before = read_configuration_bytes(path)
        identity = path.stat()
        if configuration_revision(before) != expected_revision:
            raise ValueError('Saved configuration revision changed; refresh and review before saving')
        temporary = None
        attempted = False
        try:
            with NamedTemporaryFile(dir=path.parent, prefix='.configuration-', delete=False) as output:
                temporary = Path(output.name)
                output.write(contents); output.flush(); os.fsync(output.fileno())
            preserve_configuration_access(path, temporary)
            with temporary.open('r+b') as staged:
                os.fsync(staged.fileno())
            current = path.stat()
            if ((current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino)
                    or read_configuration_bytes(path) != before):
                raise ValueError('Configuration changed before publication')
            attempted = True
            replace_configuration_file(path, temporary)
            with path.open('r+b') as saved:
                os.fsync(saved.fileno())
            if os.name == 'posix':
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            if read_configuration_bytes(path) != contents:
                raise ConfigurationPublicationUnconfirmed('Configuration changed during publication confirmation')
            return configuration_revision(contents)
        except Exception as error:
            if attempted:
                raise ConfigurationPublicationUnconfirmed('Configuration publication is unconfirmed; read saved configuration before another attempt') from error
            raise
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
