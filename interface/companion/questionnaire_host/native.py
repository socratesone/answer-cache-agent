"""Chrome native messaging. stdout is reserved for length-prefixed protocol frames."""
import concurrent.futures
import json
import os
import struct
import sys
import threading
from pathlib import Path

MAX_FRAME = 900_000  # below Chrome's 1 MiB native-host response limit

def read_exact(stream, length):
    out = bytearray()
    while len(out) < length:
        chunk = stream.read(length - len(out))
        if not chunk:
            raise EOFError("Truncated native message")
        out.extend(chunk)
    return bytes(out)

def read_message(stream):
    first = stream.read(1)
    if not first:
        return None
    size = struct.unpack("<I", first + read_exact(stream, 3))[0]
    if size == 0 or size > MAX_FRAME:
        raise ValueError("Invalid native message size")
    value = json.loads(read_exact(stream, size))
    if not isinstance(value, dict):
        raise ValueError("Native message must be an object")
    return value

def write_message(stream, value):
    data = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FRAME:
        data = json.dumps({"id": value.get("id"), "ok": False, "error": "Response exceeds transport limit; narrow the request"}).encode()
    stream.write(struct.pack("<I", len(data)) + data)
    stream.flush()

def allowed_origin(origin, origins):
    return isinstance(origin, str) and origin in origins and origin.startswith("chrome-extension://") and origin.endswith("/")

def main():
    origin_file = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                   else Path(__file__).parent) / "allowed-origins.json"
    origins = json.loads(origin_file.read_text()) if origin_file.exists() else []
    if len(sys.argv) < 2 or not allowed_origin(sys.argv[1], origins) or os.name != "nt":
        return 2
    directory = Path(os.environ["LOCALAPPDATA"]) / "SocratesOne" / "QuestionnaireAssistant"
    import ctypes
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, "Local\\SocratesOne.QuestionnaireAssistant")
    if not mutex or ctypes.get_last_error() == 183:
        return 3
    protocol_out = sys.stdout.buffer
    # Imported libraries may print: protect the native framing channel before importing the engine.
    sys.stdout = sys.stderr
    from .service import Service
    lock = threading.Lock()
    service = None
    pending = {}
    pending_lock = threading.Lock()
    def process(request):
        nonlocal service
        try:
            service = service or Service(directory)
            return {"id": request.get("id"), "ok": True, "data": service.dispatch(request)}
        except (ValueError, KeyError):
            # Never serialize exception input: validation errors can contain secrets.
            return {"id": request.get("id"), "ok": False, "error": "Request unavailable or invalid. Check compatibility, required values, and refresh the form after settings changes."}
        except Exception:
            return {"id": request.get("id"), "ok": False, "error": "Local operation failed. Your request may need reconciliation; no new paid request was started by this error response."}
    def complete(future, identity):
        with pending_lock:
            pending.pop(identity, None)
        reply = {"id": identity, "ok": False, "error": "Queued operation stopped"} if future.cancelled() else future.result()
        try:
            with lock:
                write_message(protocol_out, reply)
        except (BrokenPipeError, OSError):
            pass
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as worker:
        while True:
            try:
                request = read_message(sys.stdin.buffer)
                if request is None:
                    break
                # Stop is transport-only and never becomes an engine event.
                if request.get("operation") == "stop":
                    from .service import CONTRACT
                    if request.get("fingerprint") != CONTRACT["fingerprint"] or request.get("protocol") != 1:
                        raise ValueError("Incompatible stop request")
                    with pending_lock:
                        target = pending.get(request.get("data", {}).get("requestId"))
                    canceled = bool(target and target.cancel())
                    with lock:
                        write_message(protocol_out, {"id": request.get("id"), "ok": True, "data": {"queuedCanceled": canceled, "activeMayFinish": not canceled}})
                    continue
                identity = request.get("id")
                if not isinstance(identity, str) or len(identity) > 128:
                    raise ValueError("Invalid request id")
                with pending_lock:
                    if identity in pending or len(pending) >= 64:
                        raise ValueError("Duplicate or excessive pending requests")
                    future = worker.submit(process, request)
                    pending[identity] = future
                future.add_done_callback(lambda f, i=identity: complete(f, i))
            except (ValueError, EOFError, json.JSONDecodeError):
                break
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
