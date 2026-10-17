"""Expose the local console on this machine's Tailscale address only (not the LAN).

    python3 scripts/tailnet_forward.py [--listen 100.64.38.18:8080] [--target 127.0.0.1:8080]

Plain TCP relay, so server-sent events stream through unchanged.
"""
import argparse
import asyncio
import subprocess


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        writer.close()


async def main(listen_host, listen_port, target_host, target_port):
    async def handle(client_r, client_w):
        try:
            up_r, up_w = await asyncio.open_connection(target_host, target_port)
        except OSError:
            client_w.close()
            return
        await asyncio.gather(pipe(client_r, up_w), pipe(up_r, client_w))

    server = await asyncio.start_server(handle, listen_host, listen_port)
    print(f"forwarding {listen_host}:{listen_port} -> {target_host}:{target_port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    default_ip = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True).stdout.strip()
    ap.add_argument("--listen", default=f"{default_ip}:8080")
    ap.add_argument("--target", default="127.0.0.1:8080")
    a = ap.parse_args()
    lh, lp = a.listen.rsplit(":", 1)
    th, tp = a.target.rsplit(":", 1)
    asyncio.run(main(lh, int(lp), th, int(tp)))
