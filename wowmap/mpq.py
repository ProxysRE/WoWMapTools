"""Read-only StormLib 9.40 binding. Windows build must use STORM_UNICODE=ON."""
import ctypes as C
import os
from pathlib import Path

U32 = C.c_uint32
HANDLE = C.c_void_p
INVALID = C.c_void_p(-1).value
READ_ONLY = 0x100
PATCH_FILE = 0x00100000
DELETE_MARKER = 0x02000000
# StormLib 9.40 StormPort.h defines MAX_PATH=1024 on non-Windows platforms.
# Windows uses its native MAX_PATH=260. This is part of the C struct ABI.
FIND_NAME_BYTES = 260 if os.name == 'nt' else 1024


class FindData(C.Structure):
    _fields_ = [('name', C.c_char * FIND_NAME_BYTES), ('plain', C.c_char_p)] + [
        (name, U32) for name in ('hash', 'block', 'size', 'flags', 'compressed',
                                'time_lo', 'time_hi', 'locale')]


class Storm:
    def __init__(self, library=None):
        library = library or os.environ.get('WOWMAP_STORMLIB')
        if not library:
            library = Path(__file__).resolve().parents[1] / 'tools' / 'StormLib.dll'
        path = str(Path(library).resolve())
        if not Path(path).is_file():
            raise OSError('StormLib is missing. Use the Windows bundle from GitHub Actions.')
        self.lib = C.WinDLL(path, use_last_error=True) if os.name == 'nt' else C.CDLL(path)
        native_path = C.c_wchar_p if os.name == 'nt' else C.c_char_p
        self.bind('SFileOpenArchive', [native_path, U32, U32, C.POINTER(HANDLE)], C.c_bool)
        self.bind('SFileCloseArchive', [HANDLE], C.c_bool)
        self.bind('SFileFindFirstFile', [HANDLE, C.c_char_p, C.POINTER(FindData), native_path], HANDLE)
        self.bind('SFileFindNextFile', [HANDLE, C.POINTER(FindData)], C.c_bool)
        self.bind('SFileFindClose', [HANDLE], C.c_bool)
        self.bind('SFileOpenFileEx', [HANDLE, C.c_char_p, U32, C.POINTER(HANDLE)], C.c_bool)
        self.bind('SFileGetFileSize', [HANDLE, C.POINTER(U32)], U32)
        self.bind('SFileReadFile', [HANDLE, C.c_void_p, U32, C.POINTER(U32), C.c_void_p], C.c_bool)
        self.bind('SFileCloseFile', [HANDLE], C.c_bool)
        self.bind('SFileSetLocale', [U32], U32)
        self._error = self.bind('GetLastError' if os.name == 'nt' else 'SErrGetLastError', [], U32)

    def bind(self, name, arguments, result):
        function = getattr(self.lib, name)
        function.argtypes = arguments
        function.restype = result
        return function

    @staticmethod
    def path_arg(path):
        return str(Path(path).resolve()) if os.name == 'nt' else os.fsencode(Path(path).resolve())

    def error(self):
        return self._error()

    def open(self, path):
        handle = HANDLE()
        if not self.lib.SFileOpenArchive(self.path_arg(path), 0, READ_ONLY, C.byref(handle)):
            raise OSError(f'Cannot open archive {Path(path).name} (StormLib error {self.error()})')
        return Archive(self, handle, Path(path).name)


class Archive:
    def __init__(self, storm, handle, name):
        self.storm, self.handle, self.name = storm, handle, name

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.storm.lib.SFileCloseArchive(self.handle)

    def entries(self, listfile=None, pattern='*'):
        storm = self.storm
        data = FindData()
        external = storm.path_arg(listfile) if listfile else None
        search = storm.lib.SFileFindFirstFile(self.handle, pattern.encode('utf-8'), C.byref(data), external)
        if not search or search == INVALID:
            code = storm.error()
            if code in (2, 18 if os.name == 'nt' else 1001):
                return
            raise OSError(f'Cannot enumerate {self.name} (StormLib error {code})')
        try:
            while True:
                # Game internal paths are ASCII. Reject undecodable names rather than changing them.
                name = bytes(data.name).decode('utf-8', errors='strict')
                yield dict(path=name, size=data.size, flags=data.flags, locale=data.locale)
                if not storm.lib.SFileFindNextFile(search, C.byref(data)):
                    code = storm.error()
                    if code not in (0, 2, 18 if os.name == 'nt' else 1001):
                        raise OSError(f'Enumeration failed for {self.name} (StormLib error {code})')
                    break
        finally:
            storm.lib.SFileFindClose(search)

    def read(self, name, locale=0, max_bytes=256 * 1024 * 1024):
        storm = self.storm
        old_locale = storm.lib.SFileSetLocale(locale)
        handle = HANDLE()
        try:
            if not storm.lib.SFileOpenFileEx(self.handle, name.encode('utf-8'), 0, C.byref(handle)):
                raise OSError(f'Cannot read {name} from {self.name} (StormLib error {storm.error()})')
            high = U32()
            low = storm.lib.SFileGetFileSize(handle, C.byref(high))
            size = (high.value << 32) | low
            if low == 0xffffffff and storm.error():
                raise OSError(f'Cannot get size for {name}')
            if size > max_bytes:
                raise ValueError(f'Resource exceeds {max_bytes} bytes: {name}')
            chunks = []
            remaining = size
            while remaining:
                amount = min(remaining, 1024 * 1024)
                buffer = C.create_string_buffer(amount)
                actual = U32()
                ok = storm.lib.SFileReadFile(handle, buffer, amount, C.byref(actual), None)
                if not ok or actual.value != amount:
                    raise OSError(f'Short read for {name} in {self.name}')
                chunks.append(buffer.raw)
                remaining -= amount
            return b''.join(chunks)
        finally:
            if handle.value:
                storm.lib.SFileCloseFile(handle)
            storm.lib.SFileSetLocale(old_locale)
