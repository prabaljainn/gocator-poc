"""Minimal HTTP/CONNECT proxy, stdlib only. Gives an offline host internet
through this machine over an `ssh -R` forward. Resolves DNS locally, which is
the point: the Jetson's resolver is dead too.
"""
import socket, threading, sys, select

LISTEN = ("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 3128)


def pump(a, b):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 60)
            if not r:
                break
            for s in r:
                d = s.recv(65536)
                if not d:
                    return
                (b if s is a else a).sendall(d)
    except OSError:
        pass


def handle(c):
    up = None
    try:
        c.settimeout(30)
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = c.recv(65536)
            if not d:
                return
            buf += d
        head, _, rest = buf.partition(b"\r\n\r\n")
        lines = head.split(b"\r\n")
        method, target, _ = lines[0].decode("latin1").split(" ", 2)

        if method == "CONNECT":
            host, _, port = target.rpartition(":")
            up = socket.create_connection((host, int(port)), 30)
            c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            # absolute-form URI: http://host[:port]/path
            rest_uri = target.split("://", 1)[1] if "://" in target else target
            hostport, _, path = rest_uri.partition("/")
            host, _, port = hostport.partition(":")
            up = socket.create_connection((host, int(port or 80)), 30)
            req = [f"{method} /{path} HTTP/1.1".encode("latin1")]
            for ln in lines[1:]:
                if not ln.lower().startswith((b"proxy-connection:", b"connection:")):
                    req.append(ln)
            req += [b"Connection: close", b"", b""]
            up.sendall(b"\r\n".join(req) + rest

            )
        c.settimeout(None); up.settimeout(None)
        pump(c, up)
    except Exception as e:
        try:
            c.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n" + str(e).encode())
        except OSError:
            pass
    finally:
        for s in (c, up):
            try:
                s and s.close()
            except OSError:
                pass


s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(LISTEN); s.listen(128)
print(f"proxy on {LISTEN[0]}:{LISTEN[1]}", flush=True)
while True:
    conn, _ = s.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
