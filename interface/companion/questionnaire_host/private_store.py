"""Windows user-bound DPAPI storage. There is deliberately no plaintext fallback."""
import ctypes
import json
import os
from pathlib import Path
from ctypes import wintypes

class Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

def protect(data: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows credential protection is required")
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    dll = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError("Windows credential protection failed")
    try:
        return ctypes.string_at(result.data, result.length)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(result.data)

class PrivateStore:
    def __init__(self, path: Path):
        self.path = path
    def read(self):
        return json.loads(protect(self.path.read_bytes(), True)) if self.path.exists() else {"credentials": {}, "bindings": {}}
    def write(self, value):
        data = protect(json.dumps(value).encode())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".pending")
        temporary.write_bytes(data)
        temporary.replace(self.path)
