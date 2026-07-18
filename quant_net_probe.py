#!/usr/bin/env python3
"""Quant server network probe: dependency-free, read-only, Linux friendly."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime as dt
import hashlib
import http.client
import json
import math
import multiprocessing
import os
import platform
import random
import re
import shutil
import socket
import ssl
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any

VERSION = "1.2.0"
DEFAULT_CONFIG = Path(__file__).with_name("endpoints.json")

PROFILES = {
    "balanced": {"ibkr": 0.20, "futu": 0.10, "brokers":0.05,"crypto": 0.25, "polymarket": 0.15, "prediction":0.05,"market_data": 0.10, "infra": 0.10},
    "ibkr": {"ibkr": 0.57, "futu": 0.05, "brokers":0.03,"crypto": 0.10, "polymarket": 0.03, "prediction":0.02,"market_data": 0.15, "infra": 0.05},
    "futu": {"ibkr": 0.05, "futu": 0.62, "brokers":0.03,"crypto": 0.10, "polymarket": 0.03, "prediction":0.02,"market_data": 0.10, "infra": 0.05},
    "crypto": {"ibkr": 0.05, "futu": 0.02, "brokers":0.01,"crypto": 0.71, "polymarket": 0.09, "prediction":0.02,"market_data": 0.05, "infra": 0.05},
    "polymarket": {"ibkr": 0.04, "futu": 0.02, "brokers":0.01,"crypto": 0.11, "polymarket": 0.68, "prediction":0.04,"market_data": 0.05, "infra": 0.05},
    "research": {"ibkr": 0.07, "futu": 0.06, "brokers":0.03,"crypto": 0.11, "polymarket": 0.06, "prediction":0.02,"market_data": 0.34, "infra": 0.31},
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] if lo == hi else s[lo] * (hi - k) + s[hi] * (k - lo)


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "min_ms": None, "median_ms": None, "p95_ms": None, "max_ms": None, "jitter_ms": None}
    return {
        "n": len(values), "min_ms": round(min(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(pct(values, .95), 3), "max_ms": round(max(values), 3),
        "jitter_ms": round(statistics.pstdev(values), 3) if len(values) > 1 else 0.0,
    }


def timed_dns(host: str, rounds: int) -> dict[str, Any]:
    vals, ips, errors = [], set(), []
    for _ in range(rounds):
        t = time.perf_counter()
        try:
            rows = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            vals.append((time.perf_counter() - t) * 1000)
            ips.update(r[4][0] for r in rows)
        except OSError as e:
            errors.append(str(e))
    return {**stats(vals), "success_rate": round(len(vals) / rounds, 3), "ips": sorted(ips), "errors": errors[-3:]}


def tcp_once(host: str, port: int, timeout: float) -> tuple[float, str]:
    t = time.perf_counter()
    with socket.create_connection((host, port), timeout=timeout) as s:
        peer = s.getpeername()[0]
    return (time.perf_counter() - t) * 1000, peer


def timed_tcp(host: str, port: int, rounds: int, timeout: float) -> dict[str, Any]:
    vals, peers, errors = [], [], []
    for _ in range(rounds):
        try:
            v, peer = tcp_once(host, port, timeout); vals.append(v); peers.append(peer)
        except OSError as e: errors.append(str(e))
    return {**stats(vals), "success_rate": round(len(vals) / rounds, 3), "peer_ips": sorted(set(peers)), "errors": errors[-3:]}


def tls_once(host: str, port: int, timeout: float) -> tuple[float, dict[str, Any]]:
    ctx = ssl.create_default_context(); t = time.perf_counter()
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=host) as s:
            cert = s.getpeercert()
            meta = {"version": s.version(), "cipher": s.cipher()[0] if s.cipher() else None,
                    "alpn": s.selected_alpn_protocol(), "peer_ip": s.getpeername()[0],
                    "cert_not_after": cert.get("notAfter")}
    return (time.perf_counter() - t) * 1000, meta


def timed_tls(host: str, port: int, rounds: int, timeout: float) -> dict[str, Any]:
    vals, errors, meta = [], [], {}
    for _ in range(rounds):
        try: v, meta = tls_once(host, port, timeout); vals.append(v)
        except (OSError, ssl.SSLError) as e: errors.append(str(e))
    return {**stats(vals), "success_rate": round(len(vals) / rounds, 3), "last": meta, "errors": errors[-3:]}


def http_once(url: str, timeout: float, method: str = "GET", body: str | None = None, read_limit: int = 65536) -> tuple[float, float, dict[str, Any]]:
    u = urllib.parse.urlsplit(url); cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    port = u.port or (443 if u.scheme == "https" else 80); conn = cls(u.hostname, port, timeout=timeout)
    path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, "")); headers = {"User-Agent": f"quant-server-probe/{VERSION}", "Accept": "application/json,*/*"}
    if body is not None: headers["Content-Type"] = "application/json"
    t = time.perf_counter(); conn.request(method, path, body=body, headers=headers); resp = conn.getresponse(); ttfb = (time.perf_counter() - t) * 1000
    data = resp.read(read_limit); total = (time.perf_counter() - t) * 1000
    decoded = data.decode("utf-8", "replace")
    meta = {"status": resp.status, "reason": resp.reason, "bytes_read": len(data), "server": resp.getheader("server"), "date": resp.getheader("date"), "body_preview": decoded[:1000]}
    try: meta["_json"] = json.loads(decoded)
    except (ValueError, TypeError): pass
    conn.close(); return ttfb, total, meta


def timed_http(ep: dict[str, Any], rounds: int, timeout: float) -> dict[str, Any]:
    ttfb, total, statuses, errors, last = [], [], [], [], {}
    for _ in range(rounds):
        try:
            a, b, last = http_once(ep["http_url"], timeout, ep.get("http_method", "GET"), ep.get("http_body"), 2_000_000 if ep.get("capability") else 65536); ttfb.append(a); total.append(b); statuses.append(last["status"])
        except (OSError, ssl.SSLError, http.client.HTTPException) as e: errors.append(str(e))
    usable = sum(1 for x in statuses if 200 <= x < 400 or x in (400, 401, 404, 405, 426, 429))
    blocked = any(x in (403, 451) for x in statuses)
    return {"ttfb": stats(ttfb), "total": stats(total), "success_rate": round(usable / rounds, 3), "statuses": statuses, "blocked": blocked, "last": last, "errors": errors[-3:]}


def ws_send_frame(s: socket.socket, payload: bytes, opcode: int = 1) -> None:
    mask = os.urandom(4); n = len(payload); head = bytearray([0x80 | opcode])
    if n < 126: head.append(0x80 | n)
    elif n < 65536: head.extend([0x80 | 126]); head.extend(struct.pack("!H", n))
    else: head.extend([0x80 | 127]); head.extend(struct.pack("!Q", n))
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload)); s.sendall(bytes(head) + mask + masked)


def recv_exact(s: socket.socket, n: int) -> bytes:
    out = bytearray()
    while len(out) < n:
        part = s.recv(n - len(out))
        if not part: raise OSError("websocket closed")
        out.extend(part)
    return bytes(out)


def ws_recv_frame(s: socket.socket) -> tuple[int, bytes]:
    h = recv_exact(s, 2); opcode, n = h[0] & 0x0f, h[1] & 0x7f; masked = bool(h[1] & 0x80)
    if n == 126: n = struct.unpack("!H", recv_exact(s, 2))[0]
    elif n == 127: n = struct.unpack("!Q", recv_exact(s, 8))[0]
    mask = recv_exact(s, 4) if masked else b""; payload = recv_exact(s, n)
    if masked: payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def ws_once(url: str, timeout: float, send_text: str | None) -> tuple[float, float | None, dict[str, Any]]:
    u = urllib.parse.urlsplit(url); host, port = u.hostname, u.port or (443 if u.scheme == "wss" else 80); path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
    key = base64.b64encode(os.urandom(16)).decode(); t = time.perf_counter(); raw = socket.create_connection((host, port), timeout=timeout)
    s = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if u.scheme == "wss" else raw; s.settimeout(timeout)
    req = f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: quant-server-probe/{VERSION}\r\n\r\n"
    s.sendall(req.encode()); response = bytearray()
    while b"\r\n\r\n" not in response and len(response) < 16384: response.extend(s.recv(4096))
    hs_ms = (time.perf_counter() - t) * 1000; status_line = response.split(b"\r\n", 1)[0].decode("latin1", "replace")
    if " 101 " not in status_line: s.close(); raise OSError(f"websocket handshake failed: {status_line}")
    first_ms = None; preview = None
    if send_text:
        t2 = time.perf_counter(); ws_send_frame(s, send_text.encode())
        for _ in range(3):
            opcode, payload = ws_recv_frame(s)
            if opcode == 9: ws_send_frame(s, payload, 10); continue
            if opcode in (1, 2): first_ms = (time.perf_counter() - t2) * 1000; preview = payload[:160].decode("utf-8", "replace"); break
    try: ws_send_frame(s, b"", 8)
    except OSError: pass
    s.close(); return hs_ms, first_ms, {"status": 101, "first_message_preview": preview}


def timed_ws(ep: dict[str, Any], rounds: int, timeout: float) -> dict[str, Any]:
    hs, first, errors, last = [], [], [], {}
    for _ in range(rounds):
        try:
            a, b, last = ws_once(ep["ws_url"], timeout, ep.get("ws_send")); hs.append(a)
            if b is not None: first.append(b)
        except (OSError, ssl.SSLError) as e: errors.append(str(e))
    return {"handshake": stats(hs), "first_message": stats(first), "success_rate": round(len(hs) / rounds, 3), "last": last, "errors": errors[-3:]}


def latency_score(ms: float | None) -> float:
    if ms is None: return 0.0
    points = [(5,100),(10,97),(20,92),(35,84),(50,75),(75,65),(100,55),(150,43),(200,33),(300,20),(500,8)]
    prev_x, prev_y = 0.0, 100.0
    for x, y in points:
        if ms <= x: return prev_y + (y - prev_y) * (ms - prev_x) / (x - prev_x)
        prev_x, prev_y = x, y
    return 2.0


def endpoint_score(r: dict[str, Any]) -> float:
    components, weights = [], []
    tcp=r.get("tcp",{}).get("median_ms")
    http=r.get("http",{}).get("ttfb",{}).get("median_ms")
    ws=r.get("websocket",{}).get("handshake",{}).get("median_ms")
    first=r.get("websocket",{}).get("first_message",{}).get("median_ms")
    if tcp is not None: components.append(latency_score(tcp)); weights.append(.30)
    if http is not None: components.append(latency_score(http)); weights.append(.35)
    if ws is not None: components.append(latency_score(ws)); weights.append(.25)
    if first is not None: components.append(latency_score(first)); weights.append(.10)
    if not components: return 0.0
    base=sum(x*w for x,w in zip(components,weights))/sum(weights); rates = [r[x]["success_rate"] for x in ("tcp", "tls", "websocket") if x in r]
    if "http" in r: rates.append(r["http"]["success_rate"])
    reliability = statistics.mean(rates) if rates else 0
    score = base * (0.55 + 0.45 * reliability)
    if r.get("http", {}).get("blocked"): score *= 0.55
    r["score_breakdown"]={"latency":round(base,1),"reliability":round(reliability*100,1),"blocked_penalty":r.get("http",{}).get("blocked",False)}
    return round(score, 1)


def interpret_capability(ep: dict[str, Any], out: dict[str, Any]) -> None:
    """Turn public responses into explicit capability/eligibility evidence."""
    kind = ep.get("capability")
    if not kind or "http" not in out: return
    raw = out["http"].get("last", {}).pop("_json", None)
    evidence: dict[str, Any] = {"kind": kind, "technical_reachability": out["http"].get("success_rate", 0) > 0}
    if kind == "polymarket_geoblock" and isinstance(raw, dict):
        evidence.update({"blocked": raw.get("blocked"), "country": raw.get("country"), "region": raw.get("region"), "ip": raw.get("ip")})
        evidence["verdict"] = "geo_blocked" if raw.get("blocked") is True else ("geo_check_passed" if raw.get("blocked") is False else "unknown")
        evidence["warning"] = "Official IP check is necessary but not sufficient; account/wallet/order compliance can still reject trading."
    elif kind == "binance_usdm_perpetual" and isinstance(raw, dict):
        symbols = raw.get("symbols") if isinstance(raw.get("symbols"), list) else []
        perps = [x for x in symbols if x.get("contractType") == "PERPETUAL" and x.get("status") == "TRADING"]
        evidence.update({"public_catalog_ok": bool(symbols), "live_perpetual_count": len(perps), "sample": [x.get("symbol") for x in perps[:8]], "verdict": "perpetual_market_reachable" if perps else "not_confirmed"})
        evidence["warning"] = "Public derivatives access does not prove this account/entity may trade derivatives."
    elif kind == "okx_swap" and isinstance(raw, dict):
        instruments = raw.get("data") if isinstance(raw.get("data"), list) else []
        live = [x for x in instruments if x.get("instType") == "SWAP" and x.get("state") == "live"]
        evidence.update({"api_code": raw.get("code"), "public_catalog_ok": raw.get("code") == "0", "live_swap_count": len(live), "sample": [x.get("instId") for x in live[:8]], "verdict": "swap_market_reachable" if live else "not_confirmed"})
        evidence["warning"] = "Public SWAP access does not prove this account/entity may trade derivatives."
    out["capability_evidence"] = evidence


def probe_endpoint(ep: dict[str, Any], rounds: int, timeout: float) -> dict[str, Any]:
    u = urllib.parse.urlsplit(ep.get("ws_url") or ep.get("http_url") or "")
    host = ep.get("host") or u.hostname; port = ep.get("port") or u.port or (443 if u.scheme in ("https", "wss") else 80)
    out = {k: ep[k] for k in ("id", "name", "group", "weight", "notes") if k in ep}; out.update({"host": host, "port": port})
    out["dns"] = timed_dns(host, min(rounds, 3)); out["tcp"] = timed_tcp(host, port, rounds, timeout)
    if ep.get("tls", u.scheme in ("https", "wss")): out["tls"] = timed_tls(host, port, min(rounds, 3), timeout)
    if ep.get("http_url"): out["http"] = timed_http(ep, 1 if ep.get("capability") else min(rounds, 3), timeout)
    if ep.get("ws_url"): out["websocket"] = timed_ws(ep, min(rounds, 3), timeout)
    interpret_capability(ep, out)
    if "http" in out: out["http"].get("last",{}).pop("_json",None)
    out["score"] = endpoint_score(out); return out


def shell_capture(cmd: list[str], timeout: int = 20) -> dict[str, Any]:
    try:
        p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, env={**os.environ, "LC_ALL":"C"})
        return {"command": cmd, "returncode": p.returncode, "output": (p.stdout + p.stderr)[-12000:]}
    except (OSError, subprocess.TimeoutExpired) as e: return {"command": cmd, "error": str(e)}


def route_probe(host: str) -> dict[str, Any]:
    if shutil.which("mtr"): return shell_capture(["mtr", "-r", "-w", "-c", "10", "-n", host], 35)
    if shutil.which("tracepath"): return shell_capture(["tracepath", "-n", host], 25)
    if shutil.which("traceroute"): return shell_capture(["traceroute", "-n", "-w", "1", "-q", "1", host], 35)
    return {"unavailable": True, "hint": "Install mtr-tiny (Debian/Ubuntu) for loss and route diagnostics."}


def bandwidth_probe(size_bytes: int, timeout: float) -> dict[str, Any]:
    url=f"https://speed.cloudflare.com/__down?bytes={size_bytes}"; u=urllib.parse.urlsplit(url); conn=http.client.HTTPSConnection(u.hostname,443,timeout=timeout)
    try:
        t=time.perf_counter(); conn.request("GET",u.path+"?"+u.query,headers={"User-Agent":f"quant-server-probe/{VERSION}"}); resp=conn.getresponse(); data=resp.read(size_bytes+1); elapsed=time.perf_counter()-t
        return {"status":resp.status,"bytes":len(data),"elapsed_s":round(elapsed,3),"download_mbps":round(len(data)*8/elapsed/1e6,2),"note":"Small single-stream sanity check; not a line-rate benchmark."}
    except (OSError,ssl.SSLError,http.client.HTTPException) as e: return {"error":str(e)}
    finally: conn.close()


def tcp_socket_discovery(pattern: str) -> dict[str, Any]:
    if not shutil.which("ss"): return {"error": "ss not installed (package: iproute2)", "connections": []}
    raw = shell_capture(["ss", "-tinpH", "state", "established"], 15); text = raw.get("output", ""); lines = text.splitlines(); found, current = [], None
    rx = re.compile(pattern, re.I)
    for line in lines:
        if line and not line[0].isspace():
            current = None
            if rx.search(line):
                parts = line.split(); current = {"socket_line": line, "local": parts[3] if len(parts)>4 else None, "remote": parts[4] if len(parts)>4 else None}; found.append(current)
        elif current:
            m = re.search(r"\brtt:([0-9.]+)/([0-9.]+)", line)
            if m: current["kernel_rtt_ms"] = float(m.group(1)); current["rtt_variation_ms"] = float(m.group(2))
            c = re.search(r"\bcwnd:([0-9]+)", line)
            if c: current["cwnd"] = int(c.group(1))
    return {"captured_at": utc_now(), "pattern": pattern, "connections": found, "note": "Process names may require same user or root; no packets or credentials are captured."}


def _cpu_worker(args: tuple[int, int]) -> tuple[int, float]:
    size, rounds = args; data = b"q" * size; t = time.perf_counter()
    for _ in range(rounds): hashlib.sha256(data).digest()
    return rounds, time.perf_counter() - t


def host_facts() -> dict[str, Any]:
    facts: dict[str, Any] = {"logical_cpus": os.cpu_count(), "machine": platform.machine(), "loadavg": list(os.getloadavg()) if hasattr(os,"getloadavg") else None}
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(errors="replace")
        m = re.search(r"model name\s*:\s*(.+)", cpuinfo); facts["cpu_model"] = m.group(1).strip() if m else None
    except OSError: pass
    if shutil.which("systemd-detect-virt"):
        v = shell_capture(["systemd-detect-virt"], 5); facts["virtualization"] = v.get("output","").strip()
    try:
        mem = Path("/proc/meminfo").read_text(); m = re.search(r"MemTotal:\s+(\d+)",mem); facts["memory_total_mib"] = round(int(m.group(1))/1024,1) if m else None
    except OSError: pass
    facts["disk_free_gib"] = round(shutil.disk_usage(tempfile.gettempdir()).free / 2**30, 2)
    return facts


def clock_status() -> dict[str, Any]:
    out: dict[str, Any] = {}
    if shutil.which("timedatectl"):
        raw=shell_capture(["timedatectl","show","-p","NTPSynchronized","-p","NTP","-p","Timezone"],8); out["timedatectl"]=raw.get("output","").strip()
        out["ntp_synchronized"] = "NTPSynchronized=yes" in out["timedatectl"]
    if shutil.which("chronyc"): out["chrony_tracking"] = shell_capture(["chronyc","tracking"],8).get("output","").strip()
    out["clocksource"] = None
    try: out["clocksource"] = Path("/sys/devices/system/clocksource/clocksource0/current_clocksource").read_text().strip()
    except OSError: pass
    return out


def host_benchmark(level: str = "standard") -> dict[str, Any]:
    size=1024*1024; rounds=64 if level=="light" else 192; single_n,single_s=_cpu_worker((size,rounds)); workers=min(os.cpu_count() or 1, 2 if level=="light" else 8)
    load_ratio=(os.getloadavg()[0]/max(os.cpu_count() or 1,1)) if hasattr(os,"getloadavg") else 0; t=time.perf_counter()
    if load_ratio > .60:
        multi_ops=0; multi_error=f"Skipped: pre-test 1m load/vCPU ratio {load_ratio:.2f} exceeds 0.60"
    else:
        try:
            with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex: multi=list(ex.map(_cpu_worker,[(size,rounds)]*workers))
            multi_elapsed=time.perf_counter()-t; multi_ops=sum(x[0] for x in multi)/multi_elapsed
        except Exception as e: multi_ops=0; multi_error=repr(e)
    mem_size=32*1024*1024 if level=="light" else 64*1024*1024; src=bytearray(mem_size); loops=8 if level=="light" else 16; t=time.perf_counter()
    for _ in range(loops): dst=src[:]
    mem_gib_s=(mem_size*loops)/(time.perf_counter()-t)/2**30
    disk: dict[str,Any]={}; file_mib=64 if level=="light" else 128; block=b"d"*(1024*1024)
    try:
        with tempfile.NamedTemporaryFile() as f:
            t=time.perf_counter()
            for _ in range(file_mib): f.write(block)
            f.flush(); os.fsync(f.fileno()); disk["seq_write_mib_s"]=round(file_mib/(time.perf_counter()-t),1)
            f.seek(0); t=time.perf_counter()
            while f.read(len(block)): pass
            disk["seq_read_mib_s"]=round(file_mib/(time.perf_counter()-t),1)
            random_ops=2000 if level=="light" else 6000; t=time.perf_counter()
            for _ in range(random_ops): f.seek(random.randrange(0,file_mib*256)*4096); f.read(4096)
            elapsed=time.perf_counter()-t; disk["random_4k_read_iops"]=round(random_ops/elapsed,1); disk["random_4k_read_avg_us"]=round(elapsed/random_ops*1e6,1)
        fs=[]
        with tempfile.NamedTemporaryFile() as f:
            for _ in range(24 if level=="light" else 64):
                t=time.perf_counter(); f.write(b"f"*4096); f.flush(); os.fsync(f.fileno()); fs.append((time.perf_counter()-t)*1000)
        disk["fsync_ms"] = stats(fs)
    except OSError as e: disk["error"]=str(e)
    single_ops=single_n/single_s; cpu_score=min(100,30+single_ops/2.8); disk_score=min(100,(disk.get("random_4k_read_iops",0)/400)+(80/max(disk.get("fsync_ms",{}).get("p95_ms") or 999,0.1))); mem_score=min(100,mem_gib_s*4)
    score=round(.45*cpu_score+.35*disk_score+.20*mem_score,1)
    result={"level":level,"score":score,"facts":host_facts(),"clock":clock_status(),"cpu":{"single_sha256_1mib_ops_s":round(single_ops,1),"multi_sha256_1mib_ops_s":round(multi_ops,1),"workers":workers},"memory":{"copy_gib_s":round(mem_gib_s,2)},"disk":disk,"notes":["Short comparative benchmark; noisy-neighbor and burstable CPU effects require repeated tests.","Disk test uses a bounded temporary file and removes it automatically."]}
    if 'multi_error' in locals(): result["cpu"]["multi_error"]=multi_error
    return result


def group_scores(endpoints: list[dict[str, Any]], profile: str) -> tuple[dict[str,float], float]:
    groups = {}
    for g in {x.get("group") for x in endpoints}:
        rows = [x for x in endpoints if x.get("group") == g]; denom = sum(float(x.get("weight",1)) for x in rows)
        groups[g] = round(sum(x["score"] * float(x.get("weight",1)) for x in rows) / denom, 1) if denom else 0
    weights = PROFILES[profile]; used = sum(w for g,w in weights.items() if g in groups)
    overall = sum(groups.get(g,0)*w for g,w in weights.items()) / used if used else 0
    return groups, round(overall,1)


def grade(score: float) -> str:
    return "S" if score>=90 else "A" if score>=80 else "B" if score>=70 else "C" if score>=60 else "D" if score>=45 else "E"


def role_scores(report: dict[str, Any]) -> dict[str, Any]:
    g=report["summary"]["group_scores"]; perf=report.get("benchmark",{}).get("score",50); clock=100 if report.get("benchmark",{}).get("clock",{}).get("ntp_synchronized") else 45
    scores={
        "crypto_execution":round(.72*g.get("crypto",0)+.18*perf+.10*g.get("infra",0),1),
        "ibkr_execution":round(.70*g.get("ibkr",0)+.15*perf+.10*g.get("infra",0)+.05*clock,1),
        "futu_execution":round(.70*g.get("futu",0)+.15*perf+.10*g.get("infra",0)+.05*clock,1),
        "polymarket_execution":round(.72*g.get("polymarket",0)+.13*perf+.10*g.get("infra",0)+.05*clock,1),
        "market_data_node":round(.50*g.get("market_data",0)+.25*perf+.15*g.get("infra",0)+.10*g.get("crypto",0),1),
        "research_backtest":round(.48*perf+.27*g.get("market_data",0)+.20*g.get("infra",0)+.05*clock,1),
    }
    conns=report.get("live_sessions",{}).get("connections",[])
    ib_rtt=[x["kernel_rtt_ms"] for x in conns if "kernel_rtt_ms" in x and re.search(r"ibgateway|tws|java",x.get("socket_line",""),re.I) and not re.search(r"FutuOpenD|OpenD",x.get("socket_line",""),re.I)]
    futu_rtt=[x["kernel_rtt_ms"] for x in conns if "kernel_rtt_ms" in x and re.search(r"FutuOpenD|OpenD",x.get("socket_line",""),re.I)]
    if ib_rtt: scores["ibkr_execution"]=round(.50*g.get("ibkr",0)+.30*latency_score(statistics.median(ib_rtt))+.10*perf+.05*g.get("infra",0)+.05*clock,1)
    else: scores["ibkr_execution"]=min(scores["ibkr_execution"],65.0)
    if futu_rtt: scores["futu_execution"]=round(.50*g.get("futu",0)+.30*latency_score(statistics.median(futu_rtt))+.10*perf+.05*g.get("infra",0)+.05*clock,1)
    else: scores["futu_execution"]=min(scores["futu_execution"],65.0)
    geo=next((x.get("capability_evidence") for x in report["endpoints"] if x.get("capability_evidence",{}).get("kind")=="polymarket_geoblock"),None)
    if geo and geo.get("blocked") is True: scores["polymarket_execution"]=min(scores["polymarket_execution"],20.0)
    deriv=[x.get("capability_evidence",{}).get("verdict") for x in report["endpoints"]]
    if not any(x in ("perpetual_market_reachable","swap_market_reachable") for x in deriv): scores["crypto_execution"]=min(scores["crypto_execution"],55.0)
    return {k:{"score":v,"grade":grade(v)} for k,v in scores.items()}


def recommendations(report: dict[str, Any]) -> list[str]:
    g = report["summary"]["group_scores"]; out = []
    if g.get("crypto",0) >= 80: out.append("适合数字资产实盘执行/行情节点（仍需至少 24 小时稳定性复测）。")
    elif g.get("crypto",0) >= 65: out.append("可用于中低频数字资产交易；超短线执行建议寻找更近机房。")
    if g.get("polymarket",0) >= 75: out.append("适合 Polymarket 行情、做市与套利候选节点；需用真实 token 订阅继续测首包和断流率。")
    if g.get("ibkr",0) >= 70: out.append("IBKR 公共入口可达性良好，但不能据此推断订单路由延迟；请运行 IB Gateway 后执行 discover。")
    if g.get("futu",0) >= 70: out.append("Futu OpenAPI 公共入口可达性良好；安装 FutuOpenD 后需用 discover 读取真实后台会话 RTT。")
    if g.get("market_data",0) >= 70 and g.get("infra",0) >= 65: out.append("适合研究、回测、数据采集和控制面。")
    blocked = [x["name"] for x in report["endpoints"] if x.get("http",{}).get("blocked")]
    if blocked: out.append("发现可能的地域/WAF 阻断：" + "、".join(blocked) + "；不要将该节点作为这些场所的唯一生产节点。")
    geo = next((x.get("capability_evidence") for x in report["endpoints"] if x.get("capability_evidence",{}).get("kind")=="polymarket_geoblock"),None)
    if geo and geo.get("blocked") is True: out.append(f"Polymarket 官方地理检查判定阻断（{geo.get('country') or '未知国家'}）；该服务器不适合 Polymarket 交易。")
    elif geo and geo.get("blocked") is False: out.append(f"Polymarket 官方地理检查当前通过（{geo.get('country') or '未知国家'}）；仍需用账户/钱包做合规与真实下单资格验证。")
    return out or ["综合网络质量不足或测试不完整，暂不建议承担实盘主节点。"]


def render_md(report: dict[str, Any]) -> str:
    s = report["summary"]; lines = [f"# 量化服务器探针报告 — {report['label']}", "", f"- 时间：{report['created_at']}", f"- 供应商/区域：{report.get('provider','未填写')} / {report.get('region','未填写')}", f"- 配置档：{report['profile']}", f"- 网络分：**{s['overall_score']} / 100**", f"- 最终选择分：**{s.get('selection_score',s['overall_score'])} / 100（{s.get('grade',grade(s['overall_score']))}）**", "", "## 分组评分", "", "| 分组 | 分数 |", "|---|---:|"]
    for g,v in sorted(s["group_scores"].items()): lines.append(f"| {g} | {v} |")
    lines += ["", "## 端点明细", "", "| 服务 | 组 | TCP中位(ms) | HTTP TTFB(ms) | WS握手(ms) | 成功/阻断 | 分数 |", "|---|---|---:|---:|---:|---|---:|"]
    def val(x): return "—" if x is None else str(x)
    for e in sorted(report["endpoints"], key=lambda x:(x.get("group",""), -x["score"])):
        tcp=e.get("tcp",{}).get("median_ms"); http=e.get("http",{}).get("ttfb",{}).get("median_ms"); ws=e.get("websocket",{}).get("handshake",{}).get("median_ms")
        state="阻断" if e.get("http",{}).get("blocked") else ("成功" if e.get("tcp",{}).get("success_rate",0)>0 else "失败")
        lines.append(f"| {e['name']} | {e.get('group')} | {val(tcp)} | {val(http)} | {val(ws)} | {state} | {e['score']} |")
    caps=[e for e in report["endpoints"] if e.get("capability_evidence")]
    if caps:
        lines += ["", "## 交易能力与地域判断", ""]
        for e in caps:
            c=e["capability_evidence"]; detail=[]
            if c.get("country"): detail.append(f"国家/地区 {c['country']}")
            if c.get("live_perpetual_count") is not None: detail.append(f"live 永续 {c['live_perpetual_count']} 个")
            if c.get("live_swap_count") is not None: detail.append(f"live SWAP {c['live_swap_count']} 个")
            lines.append(f"- **{e['name']}**：`{c.get('verdict','unknown')}`"+(f"（{'；'.join(detail)}）" if detail else ""))
    if report.get("role_scores"):
        lines += ["", "## 用途评分", "", "| 用途 | 分数 | 等级 |", "|---|---:|:---:|"]
        names={"crypto_execution":"数字资产执行","ibkr_execution":"IBKR 执行","futu_execution":"Futu 执行","polymarket_execution":"Polymarket 执行","market_data_node":"行情采集节点","research_backtest":"研究/回测"}
        for k,v in report["role_scores"].items(): lines.append(f"| {names.get(k,k)} | {v['score']} | {v['grade']} |")
    if report.get("benchmark"):
        b=report["benchmark"]; lines += ["", "## 主机性能", "", f"- 性能分：**{b.get('score')} / 100**", f"- CPU 单核 SHA-256：{b.get('cpu',{}).get('single_sha256_1mib_ops_s')} ops/s；多进程：{b.get('cpu',{}).get('multi_sha256_1mib_ops_s')} ops/s", f"- 内存复制：{b.get('memory',{}).get('copy_gib_s')} GiB/s", f"- 磁盘：顺序写 {b.get('disk',{}).get('seq_write_mib_s')} MiB/s；4K 随机读 {b.get('disk',{}).get('random_4k_read_iops')} IOPS；fsync p95 {b.get('disk',{}).get('fsync_ms',{}).get('p95_ms')} ms", f"- NTP 同步：{b.get('clock',{}).get('ntp_synchronized','未知')}；虚拟化：{b.get('facts',{}).get('virtualization','未知')}"]
    if report.get("bandwidth"): lines += ["", "## 轻量带宽检查", "", f"- 单流下载：{report['bandwidth'].get('download_mbps','失败')} Mbps（{report['bandwidth'].get('bytes',0)} bytes）"]
    lines += ["", "## 用途判断", ""] + [f"- {x}" for x in report["recommendations"]]
    lines += ["", "## 解释边界", "", "- TCP/TLS/HTTP/WS 测的是公网入口与当前 CDN/边缘路由，不等于交易所撮合引擎或 IBKR 最终订单路由延迟。", "- IBKR 必须在纸账户 Gateway/TWS 建立会话后运行 `discover`，以内核已建立连接 RTT 补充判断。", "- 单次测试只适合淘汰差机房；购买决策应至少在亚洲、欧洲、美国交易活跃时段各测一次，并连续运行 24–72 小时。", ""]
    return "\n".join(lines)


def render_terminal(report: dict[str, Any], json_path: Path, markdown_path: Path, color: bool = True) -> str:
    use_color=color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    codes={"reset":"\033[0m","bold":"\033[1m","green":"\033[32m","yellow":"\033[33m","red":"\033[31m","cyan":"\033[36m","dim":"\033[2m"} if use_color else {k:"" for k in ("reset","bold","green","yellow","red","cyan","dim")}
    def paint(value: str, score: float) -> str:
        c=codes["green"] if score>=75 else codes["yellow"] if score>=55 else codes["red"]
        return f"{c}{value}{codes['reset']}"
    def metric(label: str, score: float) -> str: return f"{label}: {paint(f'{score:.1f}/100 {grade(score)}',score)}"
    s=report["summary"]; selection=float(s.get("selection_score",s["overall_score"])); perf=float(report.get("benchmark",{}).get("score",0)); lines=["",f"{codes['bold']}{codes['cyan']}量化服务器探针结果 · {report['label']}{codes['reset']}","="*64,metric("网络",float(s["overall_score"]))+"   "+metric("主机",perf)+"   "+metric("选择",selection),""]
    lines += [f"{codes['bold']}分组评分{codes['reset']}"]
    group_names={"ibkr":"IBKR","futu":"Futu","brokers":"其他券商","crypto":"Crypto","polymarket":"Polymarket","prediction":"预测市场","market_data":"行情源","infra":"基础设施","anchors":"区域锚点"}
    lines.append("  ".join(f"{group_names.get(k,k)} {paint(f'{v:.1f}',v)}" for k,v in sorted(s["group_scores"].items())))
    lines += ["",f"{codes['bold']}用途评分{codes['reset']}"]
    role_names={"crypto_execution":"数字资产执行","ibkr_execution":"IBKR执行","futu_execution":"Futu执行","polymarket_execution":"Polymarket执行","market_data_node":"行情采集","research_backtest":"研究回测"}
    for k,v in report.get("role_scores",{}).items():
        value=f"{v['score']:.1f}/100 {v['grade']}"
        lines.append(f"  {role_names.get(k,k):<18} {paint(value,v['score'])}")
    caps=[e for e in report["endpoints"] if e.get("capability_evidence")]
    if caps:
        lines += ["",f"{codes['bold']}交易能力与地域{codes['reset']}"]
        for e in caps:
            c=e["capability_evidence"]; verdict=c.get("verdict","unknown"); good=verdict in ("geo_check_passed","perpetual_market_reachable","swap_market_reachable"); score=80 if good else 25
            details=[]
            if c.get("country"): details.append(str(c["country"]))
            if c.get("live_perpetual_count") is not None: details.append(f"{c['live_perpetual_count']} 个 live 永续")
            if c.get("live_swap_count") is not None: details.append(f"{c['live_swap_count']} 个 live SWAP")
            lines.append(f"  {e['name']}: {paint(verdict,score)}"+(f" · {', '.join(details)}" if details else ""))
    failed=[e for e in report["endpoints"] if e.get("tcp",{}).get("success_rate",0)==0]
    blocked=[e for e in report["endpoints"] if e.get("http",{}).get("blocked")]
    if failed or blocked:
        lines += ["",f"{codes['bold']}异常摘要{codes['reset']}"]
        if blocked: lines.append("  地域/WAF阻断: "+"、".join(e["name"] for e in blocked[:8]))
        if failed: lines.append("  完全连接失败: "+"、".join(e["name"] for e in failed[:8])+(" …" if len(failed)>8 else ""))
    lines += ["",f"{codes['bold']}判断与建议{codes['reset']}"]+[f"  • {x}" for x in report.get("recommendations",[])]
    bw=report.get("bandwidth",{}).get("download_mbps")
    if bw is not None: lines.append(f"  • 轻量单流下载约 {bw} Mbps（仅作线路健康参考）")
    lines += ["",f"{codes['dim']}JSON: {json_path}",f"Markdown: {markdown_path}{codes['reset']}","="*64]
    return "\n".join(lines)


def load_config(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f: data=json.load(f)
    return data["endpoints"] if isinstance(data,dict) else data


def choose_output_dir(requested: str | None) -> tuple[Path, bool]:
    """Choose a writable report directory without failing after a long probe."""
    if requested:
        candidates=[Path(requested).expanduser()]
    else:
        candidates=[Path.cwd()/"probe-results", Path.home()/"quant-server-probe-results", Path(tempfile.gettempdir())/f"quant-server-probe-results-{os.getuid() if hasattr(os,'getuid') else 'user'}"]
    errors=[]
    for i,path in enumerate(candidates):
        try:
            path.mkdir(parents=True,exist_ok=True)
            if not os.access(path,os.W_OK|os.X_OK): raise PermissionError(f"not writable: {path}")
            return path, (not requested and i>0)
        except OSError as e: errors.append(f"{path}: {e}")
    raise PermissionError("No writable output directory. " + " | ".join(errors))


def cmd_probe(a: argparse.Namespace) -> int:
    out,fallback=choose_output_dir(a.output)
    if fallback: print(f"[i] Current directory is not writable; reports will be saved to: {out}",file=sys.stderr)
    eps=load_config(a.config); eps=[x for x in eps if a.suite=="extended" or x.get("suite","core")=="core"]; groups=set(a.groups.split(",")) if a.groups else None
    for target in a.target:
        try:
            name, addr = target.split("=",1); host, port = addr.rsplit(":",1)
            eps.append({"id":"custom-"+re.sub(r"\W+","-",name.lower()),"name":name,"group":"infra","weight":1,"host":host.strip("[]"),"port":int(port),"tls":False,"notes":"User-supplied TCP target."})
        except ValueError: raise SystemExit(f"Invalid --target {target!r}; expected NAME=HOST:PORT")
    if a.futu_host: eps.append({"id":"futu-opend-local","name":"FutuOpenD 本地网关","group":"futu","weight":6,"host":a.futu_host,"port":a.futu_port,"tls":False,"notes":"Measures strategy-to-OpenD only, not OpenD-to-Futu backend."})
    if a.ib_host: eps.append({"id":"ib-gateway-local","name":"IB Gateway/TWS 本地 API","group":"ibkr","weight":6,"host":a.ib_host,"port":a.ib_port,"tls":False,"notes":"Measures strategy-to-Gateway only, not Gateway-to-IBKR backend."})
    if groups: eps=[x for x in eps if x.get("group") in groups]
    rounds=2 if a.quick else a.rounds
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs={ex.submit(probe_endpoint,e,rounds,a.timeout):e for e in eps}; results=[]
        for f in concurrent.futures.as_completed(futs):
            e=futs[f]
            try: results.append(f.result()); print(f"[{len(results)}/{len(eps)}] {e['name']}", file=sys.stderr)
            except Exception as err: results.append({**e,"score":0,"fatal_error":repr(err)}); print(f"[!] {e['name']}: {err}",file=sys.stderr)
    gs, overall=group_scores(results,a.profile)
    report={"schema_version":1,"probe_version":VERSION,"created_at":utc_now(),"label":a.label or socket.gethostname(),"provider":a.provider,"region":a.region,"profile":a.profile,"system":{"hostname":socket.gethostname(),"platform":platform.platform(),"python":platform.python_version()},"summary":{"group_scores":gs,"overall_score":overall},"endpoints":results}
    if a.routes:
        critical=[]
        for e in eps:
            if e.get("route") and e.get("host") not in critical: critical.append(e.get("host") or urllib.parse.urlsplit(e.get("http_url") or e.get("ws_url")).hostname)
        report["routes"]={h:route_probe(h) for h in critical[:a.max_routes]}
    if not a.no_bandwidth: report["bandwidth"]=bandwidth_probe(1_000_000 if a.benchmark_level=="light" else 2_000_000,max(a.timeout,8))
    if a.live_sessions: report["live_sessions"]=tcp_socket_discovery(a.session_pattern)
    if not a.no_benchmark:
        report["benchmark"]=host_benchmark(a.benchmark_level)
        perf_weight = 0.15 if a.profile in ("crypto","polymarket") else 0.25
        report["summary"]["network_score"] = overall
        report["summary"]["selection_score"] = round(overall*(1-perf_weight)+report["benchmark"]["score"]*perf_weight,1)
        report["summary"]["grade"] = grade(report["summary"]["selection_score"])
    report["role_scores"]=role_scores(report)
    report["recommendations"]=recommendations(report)
    slug=re.sub(r"[^A-Za-z0-9_.-]+","-",report["label"]).strip("-") or "server"; stamp=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jp=out/f"probe-{slug}-{stamp}.json"; mp=out/f"probe-{slug}-{stamp}.md"; jp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8"); mp.write_text(render_md(report),encoding="utf-8")
    if not a.no_terminal_summary: print(render_terminal(report,jp,mp))
    print("RESULT_JSON="+json.dumps({"json":str(jp),"markdown":str(mp),"overall_score":overall,"selection_score":report["summary"].get("selection_score")},ensure_ascii=False)); return 0


def cmd_compare(a: argparse.Namespace) -> int:
    reports=[json.loads(Path(p).read_text(encoding="utf-8")) for p in a.files]
    rows=sorted(reports,key=lambda r:r["summary"].get("selection_score",r["summary"]["overall_score"]),reverse=True); lines=["# 量化服务器横向比较","",f"生成时间：{utc_now()}","","| 排名 | 服务器 | 供应商/区域 | 选择分 | 性能 | IBKR | Futu | Crypto | Polymarket | 行情 |","|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for i,r in enumerate(rows,1):
        g=r["summary"]["group_scores"]; lines.append(f"| {i} | {r['label']} | {r.get('provider','')}/{r.get('region','')} | {r['summary'].get('selection_score',r['summary']['overall_score'])} | {r.get('benchmark',{}).get('score','—')} | {g.get('ibkr','—')} | {g.get('futu','—')} | {g.get('crypto','—')} | {g.get('polymarket','—')} | {g.get('market_data','—')} |")
    lines += ["","## 结论",""]
    if rows: lines.append(f"- 当前配置档下首选 **{rows[0]['label']}**（选择分 {rows[0]['summary'].get('selection_score',rows[0]['summary']['overall_score'])}）。这只是同批样本的相对结论，需结合真实 IB 会话与 24–72 小时稳定性。")
    if a.output: out=Path(a.output).expanduser()
    else:
        directory,fallback=choose_output_dir(None); out=directory/"server-comparison.md"
        if fallback: print(f"[i] Current directory is not writable; report will be saved to: {out}",file=sys.stderr)
    rendered="\n".join(lines)+"\n"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(rendered,encoding="utf-8"); print(rendered); print(f"Saved: {out}"); return 0


def cmd_show(a: argparse.Namespace) -> int:
    path=Path(a.file).expanduser(); report=json.loads(path.read_text(encoding="utf-8")); markdown=path.with_suffix(".md")
    print(render_terminal(report,path,markdown,color=not a.no_color)); return 0


def build_parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Quant trading server network probe"); p.add_argument("--version",action="version",version=VERSION); sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("probe",help="Probe configured public endpoints"); q.add_argument("--config",default=str(DEFAULT_CONFIG)); q.add_argument("--label"); q.add_argument("--provider",default=""); q.add_argument("--region",default=""); q.add_argument("--profile",choices=PROFILES,default="balanced"); q.add_argument("--suite",choices=("core","extended"),default="core"); q.add_argument("--groups",help="comma-separated groups"); q.add_argument("--target",action="append",default=[],help="extra TCP target: NAME=HOST:PORT (repeatable)"); q.add_argument("--rounds",type=int,default=5); q.add_argument("--quick",action="store_true"); q.add_argument("--timeout",type=float,default=4.0); q.add_argument("--workers",type=int,default=8); q.add_argument("--routes",action="store_true"); q.add_argument("--max-routes",type=int,default=5); q.add_argument("--futu-host",help="FutuOpenD host, usually 127.0.0.1"); q.add_argument("--futu-port",type=int,default=11111); q.add_argument("--ib-host",help="IB Gateway/TWS API host, usually 127.0.0.1"); q.add_argument("--ib-port",type=int,default=4002); q.add_argument("--live-sessions",action="store_true",help="include kernel RTT for running IB/Futu gateways"); q.add_argument("--session-pattern",default=r"ibgateway|tws|java|FutuOpenD|OpenD"); q.add_argument("--no-benchmark",action="store_true"); q.add_argument("--no-bandwidth",action="store_true"); q.add_argument("--no-terminal-summary",action="store_true"); q.add_argument("--benchmark-level",choices=("light","standard"),default="light"); q.add_argument("--output",help="report directory; auto-selects a writable directory when omitted"); q.set_defaults(func=cmd_probe)
    c=sub.add_parser("compare",help="Compare JSON reports"); c.add_argument("files",nargs="+"); c.add_argument("--output"); c.set_defaults(func=cmd_compare)
    s=sub.add_parser("show",help="Render an existing JSON report in the terminal"); s.add_argument("file"); s.add_argument("--no-color",action="store_true"); s.set_defaults(func=cmd_show)
    d=sub.add_parser("discover",help="Read kernel RTT for established IB/Futu gateway sockets"); d.add_argument("--pattern",default=r"ibgateway|tws|java|FutuOpenD|OpenD"); d.add_argument("--output"); d.set_defaults(func=lambda a:(Path(a.output).write_text(json.dumps(tcp_socket_discovery(a.pattern),ensure_ascii=False,indent=2),encoding="utf-8") if a.output else print(json.dumps(tcp_socket_discovery(a.pattern),ensure_ascii=False,indent=2))) or 0)
    return p


if __name__ == "__main__":
    parser=build_parser(); args=parser.parse_args(); raise SystemExit(args.func(args))
