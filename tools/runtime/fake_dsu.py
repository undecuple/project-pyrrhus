#!/usr/bin/env python3
"""A fake DSU (cemuhook) motion server for tests of KZ2 patch 6062: UDP on 127.0.0.1:PORT, answers
each client's pad-data registration with slot-0 pad data at ~250 Hz for 5 s after it, the pad rolled to and fro
(roll = 30 deg x sin(t), accel in g, gyro in deg/s). Loopback only; no game data. Writes one line per event to stdout
and a summary every 5 s and at the end ("FAKE_DSU t=T requests=N sent=M clients=K"; the sandbox may stop it before the
end).

    python3 tools/runtime/fake_dsu.py [--port 26760] [--seconds 60]
"""
import argparse
import math
import socket
import struct
import time
import zlib


def pad_packet(num, t, roll_deg):
    r = math.radians(roll_deg)
    acc = (math.sin(r), math.cos(r), 0.0)
    rate = math.degrees(math.radians(30.0) * math.cos(t))   # d(roll)/dt for roll = 30 sin t
    gyr = (0.0, 0.0, rate)
    body = bytearray(100)
    body[0:4] = b"DSUS"
    struct.pack_into("<HH", body, 4, 1001, 84)
    struct.pack_into("<I", body, 12, 0x46414B45)               # sender id
    struct.pack_into("<I", body, 16, 0x100002)
    body[20], body[21], body[22], body[23] = 0, 2, 2, 2        # slot, connected, DS4 model, USB
    body[30], body[31] = 5, 1                                  # battery full, active
    struct.pack_into("<I", body, 32, num)
    struct.pack_into("<Q", body, 68, int(t * 1e6))
    struct.pack_into("<3f", body, 76, *acc)
    struct.pack_into("<3f", body, 88, *gyr)
    struct.pack_into("<I", body, 8, zlib.crc32(bytes(body)) & 0xFFFFFFFF)
    return bytes(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=26760)
    ap.add_argument("--seconds", type=float, default=60.0)
    a = ap.parse_args()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", a.port))
    s.settimeout(0.004)
    t0 = time.monotonic()
    clients = {}   # addr -> expiry
    reqs = sent = 0
    next_note = 5.0
    print(f"FAKE_DSU listening on 127.0.0.1:{a.port}", flush=True)
    while time.monotonic() - t0 < a.seconds:
        try:
            data, addr = s.recvfrom(512)
            ok = len(data) >= 20 and data[:4] == b"DSUC" and struct.unpack_from("<I", data, 16)[0] == 0x100002
            if ok:
                crc = struct.unpack_from("<I", data, 8)[0]
                ok = zlib.crc32(data[:8] + b"\0\0\0\0" + data[12:]) & 0xFFFFFFFF == crc
            if ok:
                reqs += 1
                if addr not in clients:
                    print(f"FAKE_DSU client {addr[0]}:{addr[1]} registered", flush=True)
                clients[addr] = time.monotonic() + 5.0
        except socket.timeout:
            pass
        now = time.monotonic()
        if now - t0 >= next_note:
            print(f"FAKE_DSU t={now - t0:.0f} requests={reqs} sent={sent} clients={len(clients)}", flush=True)
            next_note += 5.0
        for addr, exp in list(clients.items()):
            if now > exp:
                del clients[addr]
                continue
            t = now - t0
            s.sendto(pad_packet(sent, t, 30.0 * math.sin(t)), addr)
            sent += 1
    print(f"FAKE_DSU t={time.monotonic() - t0:.0f} DONE requests={reqs} sent={sent} clients={len(clients)}", flush=True)


if __name__ == "__main__":
    main()
