import socket, ssl, sys, time
port = int(sys.argv[1])
for name, payload in (('protocol error', b'*x\r\n'), ('QUIT', b'*1\r\n$4\r\nQUIT\r\n'), ('PING', b'*1\r\n$4\r\nPING\r\n')):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    s = ctx.wrap_socket(socket.create_connection(('127.0.0.1', port), timeout=10), server_hostname='localhost')
    s.sendall(payload)
    t0 = time.monotonic(); got = b''; outcome = None
    while True:
        try:
            d = s.recv(4096)
        except TimeoutError:
            outcome = 'still open after 10 s'; break
        except ssl.SSLError as e:
            outcome = f'closed ({type(e).__name__})'; break
        if not d:
            outcome = 'closed (EOF)'; break
        got += d
    print(f'{name}: reply={got!r} -> {outcome} after {time.monotonic()-t0:.2f}s')
    s.close()
