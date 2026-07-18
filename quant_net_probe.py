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

VERSION = "1.4.0"


def normalize_ui_language(value: Any) -> str | None:
    value=str(value or "").split(".",1)[0].replace("_","-").lower()
    if value=="en" or value.startswith("en-"): return "en"
    if value in ("zh-cn","zh-sg","zh-hans") or value.startswith("zh-hans-"): return "zh-CN"
    if value in ("zh-tw","zh-hk","zh-mo","zh-hant") or value.startswith("zh-hant-"): return "zh-TW"
    return None


UI_LANG=normalize_ui_language(os.environ.get("QUANT_PROBE_LANG") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG")) or "en"

# Polymarket policy snapshot: https://docs.polymarket.com/api-reference/geoblock
# Keep the raw /api/geoblock result in evidence as well: the official page currently
# says both that `blocked` means order-blocked and that JP/NL are frontend-only.
POLY_FULL_COUNTRIES = {"IR", "SY", "CU", "KP"}
POLY_FULL_REGIONS = {("UA", "43"), ("UA", "14"), ("UA", "09")}
POLY_API_CLOSE_ONLY_COUNTRIES = {
    "AU", "BY", "BE", "BI", "BR", "CF", "CD", "ET", "FR", "DE", "IQ",
    "IT", "LB", "LY", "MM", "NI", "KP", "PL", "RU", "SG", "SO", "SK",
    "SS", "SD", "TW", "TH", "GB", "US", "UM", "VE", "YE", "ZW",
}
POLY_API_CLOSE_ONLY_REGIONS = {
    ("CA", "BC"), ("CA", "ON"), ("CA", "AB"), ("CA", "QC"),
}
POLY_FRONTEND_ONLY_COUNTRIES = {"JP", "NL", "MT"}


def polymarket_policy(country: Any, region: Any) -> dict[str, Any]:
    """Interpret Polymarket's published three-tier jurisdiction table."""
    country = str(country or "").upper()
    region = str(region or "").upper()
    # Providers sometimes return ISO-3166-2 (CA-ON), sometimes just ON.
    if region.startswith(country + "-"):
        region = region[len(country) + 1:]
    key = (country, region)
    if country in POLY_FULL_COUNTRIES or key in POLY_FULL_REGIONS:
        return {"policy_tier":"full_block", "api_new_orders_allowed":False, "api_close_allowed":False, "frontend_new_orders_allowed":False}
    if country in POLY_API_CLOSE_ONLY_COUNTRIES or key in POLY_API_CLOSE_ONLY_REGIONS:
        return {"policy_tier":"api_and_frontend_close_only", "api_new_orders_allowed":False, "api_close_allowed":True, "frontend_new_orders_allowed":False}
    if country in POLY_FRONTEND_ONLY_COUNTRIES:
        return {"policy_tier":"frontend_close_only_api_available", "api_new_orders_allowed":True, "api_close_allowed":True, "frontend_new_orders_allowed":False, "sports_only_scope":country == "MT"}
    return {"policy_tier":"not_listed", "api_new_orders_allowed":True, "api_close_allowed":True, "frontend_new_orders_allowed":True}
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


def timed_ping(host: str, rounds: int, timeout: float) -> dict[str, Any]:
    """Optional ICMP supplement. TCP service-port results remain authoritative."""
    if not shutil.which("ping"): return {**stats([]),"success_rate":0.0,"unavailable":True,"errors":["ping command not installed"]}
    try:
        p=subprocess.run(["ping","-n","-c",str(rounds),"-W",str(max(1,math.ceil(timeout))),host],text=True,capture_output=True,timeout=max(5,rounds*timeout+3),env={**os.environ,"LC_ALL":"C"})
        text_out=p.stdout+p.stderr; values=[]
        for raw in re.findall(r"\btime[=<]([0-9.]+)\s*ms",text_out):
            try: values.append(float(raw))
            except ValueError: pass
        errors=[] if values else [text_out.strip()[-500:] or f"ping exited {p.returncode}"]
        return {**stats(values),"success_rate":round(min(len(values),rounds)/rounds,3),"errors":errors}
    except (OSError,subprocess.TimeoutExpired) as e: return {**stats([]),"success_rate":0.0,"errors":[str(e)]}


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


def interpolate_score(value: float, points: list[tuple[float,float]]) -> float:
    if value <= points[0][0]: return points[0][1]
    for (x0,y0),(x1,y1) in zip(points,points[1:]):
        if value <= x1: return y0+(y1-y0)*(value-x0)/(x1-x0)
    return points[-1][1]


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
    raw_blocked=r.get("http", {}).get("blocked",False)
    policy_allows=r.get("capability_evidence",{}).get("api_new_orders_allowed") is True
    blocked_penalty=bool(raw_blocked and not policy_allows)
    if blocked_penalty: score *= 0.55
    r["score_breakdown"]={"latency":round(base,1),"reliability":round(reliability*100,1),"blocked_penalty":blocked_penalty,"raw_http_blocked":raw_blocked}
    return round(score, 1)


def interpret_capability(ep: dict[str, Any], out: dict[str, Any]) -> None:
    """Turn public responses into explicit capability/eligibility evidence."""
    kind = ep.get("capability")
    if not kind or "http" not in out: return
    raw = out["http"].get("last", {}).pop("_json", None)
    evidence: dict[str, Any] = {"kind": kind, "technical_reachability": out["http"].get("success_rate", 0) > 0}
    if kind == "polymarket_geoblock" and isinstance(raw, dict):
        policy=polymarket_policy(raw.get("country"),raw.get("region"))
        evidence.update({"blocked": raw.get("blocked"), "country": raw.get("country"), "region": raw.get("region"), "ip": raw.get("ip"), **policy})
        tier=policy["policy_tier"]
        evidence["verdict"] = {"full_block":"fully_blocked", "api_and_frontend_close_only":"api_close_only_no_new_orders", "frontend_close_only_api_available":"frontend_close_only_api_available", "not_listed":"geo_check_passed" if raw.get("blocked") is False else "raw_geoblock_conflict"}[tier]
        evidence["policy_raw_conflict"] = bool(raw.get("blocked") is True and policy.get("api_new_orders_allowed") is True)
        evidence["warning"] = "Policy-table interpretation plus raw official IP check; account/wallet/order compliance can still reject trading. JP/NL frontend-only wording conflicts with the endpoint's generic blocked-field description."
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


def enriched_polymarket_evidence(evidence: dict[str, Any] | None) -> dict[str, Any] | None:
    """Upgrade evidence saved by older probe versions to the three-tier policy model."""
    if not evidence or evidence.get("kind")!="polymarket_geoblock": return evidence
    if "api_new_orders_allowed" in evidence: return evidence
    out={**evidence,**polymarket_policy(evidence.get("country"),evidence.get("region"))}; tier=out["policy_tier"]
    out["verdict"]={"full_block":"fully_blocked","api_and_frontend_close_only":"api_close_only_no_new_orders","frontend_close_only_api_available":"frontend_close_only_api_available","not_listed":"geo_check_passed" if out.get("blocked") is False else "raw_geoblock_conflict"}[tier]
    out["policy_raw_conflict"]=bool(out.get("blocked") is True and out.get("api_new_orders_allowed") is True)
    return out


def probe_endpoint(ep: dict[str, Any], rounds: int, timeout: float) -> dict[str, Any]:
    u = urllib.parse.urlsplit(ep.get("ws_url") or ep.get("http_url") or "")
    host = ep.get("host") or u.hostname; port = ep.get("port") or u.port or (443 if u.scheme in ("https", "wss") else 80)
    out = {k: ep[k] for k in ("id", "name", "group", "weight", "notes", "ibkr_region", "ibkr_service", "ibkr_role", "official", "proxy_only", "anchor_provider", "futu_region", "futu_quote_for", "futu_trade_for") if k in ep}; out.update({"host": host, "port": port})
    out["dns"] = timed_dns(host, min(rounds, 3)); out["tcp"] = timed_tcp(host, port, rounds, timeout)
    if ep.get("ping"): out["ping"] = timed_ping(host,rounds,timeout)
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


def calibrated_benchmark_score(benchmark: dict[str, Any]) -> tuple[float, dict[str,float]]:
    cpu=benchmark.get("cpu",{}); memory=benchmark.get("memory",{}); disk=benchmark.get("disk",{}); workers=max(cpu.get("workers") or 1,1)
    single=float(cpu.get("single_sha256_1mib_ops_s") or 0); per_worker=float(cpu.get("per_worker_ops_s") or ((cpu.get("multi_sha256_1mib_ops_s") or 0)/workers)); mem=float(memory.get("copy_gib_s") or 0); fsync=float(disk.get("fsync_ms",{}).get("p95_ms") or 999); write=float(disk.get("seq_write_mib_s") or 0)
    parts={"cpu_single":interpolate_score(single,[(0,5),(250,25),(500,45),(800,60),(1200,75),(1800,90),(2600,100)]),"cpu_per_worker":interpolate_score(per_worker,[(0,5),(200,25),(400,45),(700,60),(1100,78),(1700,92),(2400,100)]),"memory":interpolate_score(mem,[(0,5),(.5,25),(1,40),(2,60),(4,80),(8,95),(12,100)]),"fsync":interpolate_score(fsync,[(0,100),(.5,98),(1,90),(2,76),(4,56),(8,35),(15,18),(30,5)]),"sequential_write":interpolate_score(write,[(0,5),(75,25),(150,42),(300,60),(500,75),(800,90),(1400,100)])}
    score=.40*parts["cpu_single"]+.15*parts["cpu_per_worker"]+.15*parts["memory"]+.20*parts["fsync"]+.10*parts["sequential_write"]
    return round(score,1),{k:round(v,1) for k,v in parts.items()}


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
    single_ops=single_n/single_s; per_worker=multi_ops/max(workers,1); result={"level":level,"facts":host_facts(),"clock":clock_status(),"cpu":{"single_sha256_1mib_ops_s":round(single_ops,1),"multi_sha256_1mib_ops_s":round(multi_ops,1),"per_worker_ops_s":round(per_worker,1),"workers":workers},"memory":{"copy_gib_s":round(mem_gib_s,2)},"disk":disk,"notes":["Short comparative benchmark; noisy-neighbor and burstable CPU effects require repeated tests.","Disk test uses a bounded temporary file and removes it automatically."]}
    score,breakdown=calibrated_benchmark_score(result); result["score"]=score; result["score_breakdown"]=breakdown
    if 'multi_error' in locals(): result["cpu"]["multi_error"]=multi_error
    return result


def summarize_ibkr_official(endpoints: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows=[e for e in endpoints if e.get("group")=="ibkr_official" and e.get("ibkr_role")=="primary"]
    if not rows: return None
    regions=[]
    for region in sorted({e.get("ibkr_region") for e in rows if e.get("ibkr_region")}):
        items=[e for e in rows if e.get("ibkr_region")==region]; services={}
        for e in items:
            tcp=e.get("tcp",{}); ping=e.get("ping",{}); tls=e.get("tls",{})
            services[e.get("ibkr_service") or str(e.get("port"))]={"host":e.get("host"),"port":e.get("port"),"tcp_median_ms":tcp.get("median_ms"),"tcp_p95_ms":tcp.get("p95_ms"),"tcp_jitter_ms":tcp.get("jitter_ms"),"tcp_success_rate":tcp.get("success_rate"),"icmp_median_ms":ping.get("median_ms"),"icmp_success_rate":ping.get("success_rate"),"tls_success_rate":tls.get("success_rate") if tls else None,"score":e.get("score")}
        score=round(statistics.mean([float(e.get("score",0)) for e in items]),1) if items else 0
        regions.append({"region":region,"score":score,"grade":grade(score),"services":services})
    regions.sort(key=lambda x:x["score"],reverse=True); best=regions[0] if regions and regions[0]["score"]>0 else None
    return {"source":"IBKR Host and Ports Documentation, updated 2026-04-27","best_region":best.get("region") if best else None,"best_score":best.get("score") if best else None,"regions":regions,"warning":"Official ports measure reachability to TWS back-end hosts, not final exchange matching or SmartRouting latency."}


def summarize_futu_anchors(endpoints: list[dict[str, Any]], account: str | None = None) -> dict[str, Any] | None:
    rows=[e for e in endpoints if e.get("group")=="futu_anchor"]
    if not rows: return None
    anchors=[]
    for e in rows:
        anchors.append({"id":e.get("id"),"provider":e.get("anchor_provider"),"region":e.get("futu_region"),"score":e.get("score"),"grade":grade(float(e.get("score",0))),"tcp_median_ms":e.get("tcp",{}).get("median_ms"),"tcp_p95_ms":e.get("tcp",{}).get("p95_ms"),"http_median_ms":e.get("http",{}).get("ttfb",{}).get("median_ms"),"icmp_median_ms":e.get("ping",{}).get("median_ms"),"success_rate":e.get("tcp",{}).get("success_rate"),"quote_for":e.get("futu_quote_for",[]),"trade_for":e.get("futu_trade_for",[])})
    selected_quote=[x for x in anchors if account and account in x["quote_for"]]; selected_trade=[x for x in anchors if account and account in x["trade_for"]]
    best_quote=max(selected_quote,key=lambda x:float(x.get("score") or 0),default=None); best_trade=max(selected_trade,key=lambda x:float(x.get("score") or 0),default=None)
    if best_quote and float(best_quote.get("score") or 0)<=0: best_quote=None
    if best_trade and float(best_trade.get("score") or 0)<=0: best_trade=None
    parts=[float(x["score"]) for x in (best_quote,best_trade) if x and x.get("score") is not None]; selected_score=round(statistics.mean(parts),1) if parts else None
    anchors.sort(key=lambda x:float(x.get("score") or 0),reverse=True)
    return {"account_profile":account,"selected_score":selected_score,"best_quote_anchor":best_quote,"best_trade_anchor":best_trade,"anchors":anchors,"warning":"Cloud-region substitute only. FutuOpenD established-session RTT is the authoritative network measurement."}


def group_scores(endpoints: list[dict[str, Any]], profile: str, futu_account: str | None = None) -> tuple[dict[str,float], float]:
    groups = {}
    for g in {x.get("group") for x in endpoints}:
        rows = [x for x in endpoints if x.get("group") == g]; denom = sum(float(x.get("weight",1)) for x in rows)
        groups[g] = round(sum(x["score"] * float(x.get("weight",1)) for x in rows) / denom, 1) if denom else 0
    official=summarize_ibkr_official(endpoints)
    if official:
        public=groups.get("ibkr",0); best=float(official.get("best_score") or 0); groups["ibkr_official_best"]=best; groups["ibkr"]=round(.80*best+.20*public,1); groups.pop("ibkr_official",None)
    futu_anchors=summarize_futu_anchors(endpoints,futu_account)
    groups.pop("futu_anchor",None)
    if futu_anchors and futu_anchors.get("selected_score") is not None:
        anchor_score=float(futu_anchors["selected_score"]); groups["futu_anchor_selected"]=anchor_score; groups["futu"]=round(.85*anchor_score+.15*groups.get("futu",0),1)
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
    elif report.get("ibkr_official"): scores["ibkr_execution"]=min(scores["ibkr_execution"],82.0)
    else: scores["ibkr_execution"]=min(scores["ibkr_execution"],65.0)
    if futu_rtt: scores["futu_execution"]=round(.50*g.get("futu",0)+.30*latency_score(statistics.median(futu_rtt))+.10*perf+.05*g.get("infra",0)+.05*clock,1)
    else: scores["futu_execution"]=min(scores["futu_execution"],65.0)
    geo=enriched_polymarket_evidence(next((x.get("capability_evidence") for x in report["endpoints"] if x.get("capability_evidence",{}).get("kind")=="polymarket_geoblock"),None))
    if geo and geo.get("api_new_orders_allowed") is False: scores["polymarket_execution"]=min(scores["polymarket_execution"],20.0)
    deriv=[x.get("capability_evidence",{}).get("verdict") for x in report["endpoints"]]
    if not any(x in ("perpetual_market_reachable","swap_market_reachable") for x in deriv): scores["crypto_execution"]=min(scores["crypto_execution"],55.0)
    return {k:{"score":v,"grade":grade(v)} for k,v in scores.items()}


def recommendations(report: dict[str, Any]) -> list[str]:
    g = report["summary"]["group_scores"]; out = []
    if g.get("crypto",0) >= 80: out.append("适合数字资产实盘执行/行情节点（仍需至少 24 小时稳定性复测）。")
    elif g.get("crypto",0) >= 65: out.append("可用于中低频数字资产交易；超短线执行建议寻找更近机房。")
    if g.get("polymarket",0) >= 75: out.append("适合 Polymarket 行情、做市与套利候选节点；需用真实 token 订阅继续测首包和断流率。")
    if report.get("ibkr_official") and g.get("ibkr",0)>=70: out.append(f"IBKR 官方TWS服务端口最佳区域为 {report['ibkr_official'].get('best_region')}；仍需运行Gateway/TWS确认账户实际分配和真实会话。")
    elif g.get("ibkr",0) >= 70: out.append("IBKR 公共入口可达性良好，但不能据此推断订单路由延迟；请运行 IB Gateway 后执行 discover。")
    if g.get("futu",0) >= 70: out.append("Futu OpenAPI 公共入口可达性良好；安装 FutuOpenD 后需用 discover 读取真实后台会话 RTT。")
    if g.get("market_data",0) >= 70 and g.get("infra",0) >= 65: out.append("适合研究、回测、数据采集和控制面。")
    blocked = [x["name"] for x in report["endpoints"] if x.get("http",{}).get("blocked")]
    if blocked: out.append("发现可能的地域/WAF 阻断：" + "、".join(blocked) + "；不要将该节点作为这些场所的唯一生产节点。")
    geo = enriched_polymarket_evidence(next((x.get("capability_evidence") for x in report["endpoints"] if x.get("capability_evidence",{}).get("kind")=="polymarket_geoblock"),None))
    if geo and geo.get("api_new_orders_allowed") is False: out.append(f"Polymarket 地区表判定 API 禁止新开仓（{geo.get('country') or '未知国家'}，{geo.get('policy_tier')}）；不适合新开仓交易节点。")
    elif geo and geo.get("policy_tier")=="frontend_close_only_api_available": out.append(f"Polymarket 地区表显示 {geo.get('country')} 仅前端 close-only、API 可用；原始 geoblock={geo.get('blocked')}，生产前须用已认证账户确认。")
    elif geo and geo.get("api_new_orders_allowed") is True: out.append(f"Polymarket 地区表未限制 API 新开仓（{geo.get('country') or '未知国家'}）；仍需用账户/钱包做合规与下单资格验证。")
    return out or ["综合网络质量不足或测试不完整，暂不建议承担实盘主节点。"]


def render_md_zh(report: dict[str, Any]) -> str:
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


def render_terminal_zh(report: dict[str, Any], json_path: Path, markdown_path: Path, color: bool = True, details: str = "all") -> str:
    use_color=color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    codes={"reset":"\033[0m","bold":"\033[1m","green":"\033[32m","yellow":"\033[33m","red":"\033[31m","cyan":"\033[36m","dim":"\033[2m"} if use_color else {k:"" for k in ("reset","bold","green","yellow","red","cyan","dim")}
    def paint(value: str, score: float) -> str:
        c=codes["green"] if score>=75 else codes["yellow"] if score>=55 else codes["red"]
        return f"{c}{value}{codes['reset']}"
    def metric(label: str, score: float) -> str: return f"{label}: {paint(f'{score:.1f}/100 {grade(score)}',score)}"
    s=report["summary"]; stored_perf=float(report.get("benchmark",{}).get("score",0)); perf=stored_perf; recalibrated=False; display_report=report
    if report.get("benchmark") and not report["benchmark"].get("score_breakdown"):
        perf,legacy_breakdown=calibrated_benchmark_score(report["benchmark"]); recalibrated=True; display_report={**report,"benchmark":{**report["benchmark"],"score":perf,"score_breakdown":legacy_breakdown}}
    perf_weight=.15 if report.get("profile") in ("crypto","polymarket") else .25; selection=round(float(s["overall_score"])*(1-perf_weight)+perf*perf_weight,1) if recalibrated else float(s.get("selection_score",s["overall_score"])); display_roles=role_scores(display_report) if recalibrated else report.get("role_scores",{})
    lines=["",f"{codes['bold']}{codes['cyan']}量化服务器探针结果 · {report['label']}{codes['reset']}","="*78,metric("网络",float(s["overall_score"]))+"   "+metric("主机",perf)+"   "+metric("选择",selection),f"时间: {report.get('created_at')}   配置: {report.get('profile')}   版本: {report.get('probe_version','旧版')}",""]
    group_names={"ibkr":"IBKR综合","ibkr_official":"IBKR官方TWS主机","ibkr_official_best":"IBKR最佳官方区域","futu":"Futu","futu_anchor":"Futu区域替代锚点","futu_anchor_selected":"Futu所选账户锚点","brokers":"其他券商","crypto":"Crypto","polymarket":"Polymarket","prediction":"预测市场","market_data":"行情源","infra":"基础设施","anchors":"区域锚点"}
    lines += [f"{codes['bold']}分组评分{codes['reset']}","  ".join(f"{group_names.get(k,k)} {paint(f'{v:.1f}',v)}" for k,v in sorted(s["group_scores"].items())),"",f"{codes['bold']}用途评分{codes['reset']}"]
    role_names={"crypto_execution":"数字资产执行","ibkr_execution":"IBKR执行","futu_execution":"Futu执行","polymarket_execution":"Polymarket执行","market_data_node":"行情采集","research_backtest":"研究回测"}
    if recalibrated: lines.append(f"  注: 此为旧版报告，主机分已按v1.3从 {stored_perf:.1f} 重算为 {perf:.1f}，选择分和用途分同步重算。")
    for k,v in display_roles.items():
        value=f"{v['score']:.1f}/100 {v['grade']}"; lines.append(f"  {role_names.get(k,k):<18} {paint(value,v['score'])}")

    b=display_report.get("benchmark",{}); facts=b.get("facts",{}); cpu=b.get("cpu",{}); memory=b.get("memory",{}); disk=b.get("disk",{}); clock=b.get("clock",{})
    if b:
        ram=(facts.get("memory_total_mib") or 0)/1024; per_worker=cpu.get("per_worker_ops_s") or ((cpu.get("multi_sha256_1mib_ops_s") or 0)/max(cpu.get("workers") or 1,1)); timezone=next((x.split("=",1)[1] for x in clock.get("timedatectl","").splitlines() if x.startswith("Timezone=")),"未知")
        lines += ["",f"{codes['bold']}主机与量化关键性能{codes['reset']}",f"  CPU: {facts.get('cpu_model') or facts.get('machine') or '未知'} · {facts.get('logical_cpus','?')} vCPU · 架构 {facts.get('machine','?')} · 虚拟化 {facts.get('virtualization','?')}",f"  容量: {ram:.1f} GiB RAM · 临时盘剩余 {facts.get('disk_free_gib','?')} GiB",f"  CPU轻测: 单核 {cpu.get('single_sha256_1mib_ops_s','?')} ops/s · 多进程 {cpu.get('multi_sha256_1mib_ops_s','?')} ops/s · 每worker {per_worker:.1f}",f"  内存复制: {memory.get('copy_gib_s','?')} GiB/s",f"  磁盘: 写 {disk.get('seq_write_mib_s','?')} MiB/s · 读(可能含缓存) {disk.get('seq_read_mib_s','?')} MiB/s · 4K读 {disk.get('random_4k_read_iops','?')} IOPS",f"  fsync: 中位 {disk.get('fsync_ms',{}).get('median_ms','?')} ms · p95 {disk.get('fsync_ms',{}).get('p95_ms','?')} ms · 最大 {disk.get('fsync_ms',{}).get('max_ms','?')} ms",f"  时钟: NTP={clock.get('ntp_synchronized','未知')} · clocksource={clock.get('clocksource','未知')} · timezone={timezone}"]
        if b.get("score_breakdown"): lines.append("  性能子分: "+" · ".join(f"{k}={v}" for k,v in b["score_breakdown"].items()))
    bw=report.get("bandwidth",{}).get("download_mbps")
    if bw is not None: lines.append(f"  网络吞吐: 1MB轻量单流下载 {bw} Mbps（不是线路上限）")

    ibo=report.get("ibkr_official")
    if ibo:
        best_text=f"{ibo.get('best_region')} · {ibo.get('best_score')}/100" if ibo.get("best_region") else "无区域可达"
        lines += ["",f"{codes['bold']}IBKR 官方 TWS 后台主机（端口4001登录/下单，4000行情）{codes['reset']}",f"  当前线路最佳区域: {best_text}"]
        for region in ibo.get("regions",[]):
            order=region.get("services",{}).get("login_orders",{}); data=region.get("services",{}).get("market_data",{})
            lines.append(f"  {region['region']:<24} {region['score']:>5.1f}/{region['grade']} · 4001 TCP {order.get('tcp_median_ms','—')}/{order.get('tcp_p95_ms','—')}ms 成功{float(order.get('tcp_success_rate') or 0)*100:.0f}% · 4000 TCP {data.get('tcp_median_ms','—')}/{data.get('tcp_p95_ms','—')}ms 成功{float(data.get('tcp_success_rate') or 0)*100:.0f}% · ICMP {order.get('icmp_median_ms','—')}ms")
        lines.append("  注意: 这是到IBKR官方TWS后台主机的服务端口延迟，不是最终交易所撮合或SmartRouting延迟。")
    fa=report.get("futu_anchors")
    if fa:
        account=fa.get("account_profile") or "未选择（仅展示，不进入Futu评分）"; bq=fa.get("best_quote_anchor") or {}; bt=fa.get("best_trade_anchor") or {}
        lines += ["",f"{codes['bold']}Futu/moomoo 云区域替代锚点{codes['reset']}",f"  账户类型: {account} · 行情候选: {bq.get('provider','—')} {bq.get('region','—')} · 交易候选: {bt.get('provider','—')} {bt.get('region','—')}"]
        for x in fa.get("anchors",[]): lines.append(f"  {x.get('provider','?')} {x.get('region','?'):<22} {float(x.get('score') or 0):>5.1f}/{x.get('grade')} · TCP {x.get('tcp_median_ms','—')}/{x.get('tcp_p95_ms','—')}ms · HTTP {x.get('http_median_ms','—')}ms · ICMP {x.get('icmp_median_ms','—')}ms")
        lines.append("  注意: 这些是对应云区域的替代端点，不是富途服务器IP；登录FutuOpenD后应以真实会话RTT复核。")

    caps=[e for e in report["endpoints"] if e.get("capability_evidence")]
    if caps:
        lines += ["",f"{codes['bold']}交易能力与地域{codes['reset']}"]
        for e in caps:
            c=enriched_polymarket_evidence(e["capability_evidence"]) or e["capability_evidence"]; verdict=c.get("verdict","unknown"); good=verdict in ("geo_check_passed","frontend_close_only_api_available","perpetual_market_reachable","swap_market_reachable"); cap_score=80 if good else 25; cap_details=[]
            if c.get("country"): cap_details.append(f"国家 {c['country']} / region {c.get('region','?')} / IP {c.get('ip','?')}")
            if c.get("kind")=="polymarket_geoblock": cap_details.append(f"API新开仓={'允许(按地区表)' if c.get('api_new_orders_allowed') else '禁止'} / 前端新开仓={'允许' if c.get('frontend_new_orders_allowed') else '禁止'} / 原始blocked={c.get('blocked')}")
            if c.get("live_perpetual_count") is not None: cap_details.append(f"{c['live_perpetual_count']} 个 live 永续")
            if c.get("live_swap_count") is not None: cap_details.append(f"{c['live_swap_count']} 个 live SWAP")
            lines.append(f"  {e['name']}: {paint(verdict,cap_score)}"+(f" · {' · '.join(cap_details)}" if cap_details else ""))

    if details != "none":
        group_order={"crypto":0,"ibkr":1,"ibkr_official":2,"futu":3,"futu_anchor":4,"brokers":5,"polymarket":6,"prediction":7,"market_data":8,"infra":9,"anchors":10}; endpoints=sorted(report["endpoints"],key=lambda e:(group_order.get(e.get("group"),99),-e.get("score",0)))
        if details=="key": endpoints=[e for e in endpoints if float(e.get("weight",1))>=3 or e.get("score",0)<55 or e.get("capability_evidence")]
        lines += ["",f"{codes['bold']}逐端点实测（中位/p95，单位ms）{codes['reset']}","  TCP成功率可视作连接失败率的反面；WS首包为空表示仅握手或未收到业务消息。"]
        last_group=None
        for e in endpoints:
            if e.get("group")!=last_group: last_group=e.get("group"); lines.append(f"\n  [{group_names.get(last_group,last_group)}]")
            score=float(e.get("score",0)); quality="优秀" if score>=85 else "良好" if score>=70 else "可用" if score>=55 else "偏慢" if score>=40 else "较差"; tcp=e.get("tcp",{}); peer=(tcp.get("peer_ips") or e.get("dns",{}).get("ips") or ["—"])[0]; ok="✓" if tcp.get("success_rate",0)>0 else "✗"
            lines.append(f"  {ok} {e.get('name')} · {paint(f'{score:.1f}/{grade(score)} {quality}',score)} · 对端 {peer}")
            parts=[]
            if tcp: parts.append(f"TCP {tcp.get('median_ms','—')}/{tcp.get('p95_ms','—')} 抖动{tcp.get('jitter_ms','—')} 成功{float(tcp.get('success_rate',0))*100:.0f}%")
            ping=e.get("ping",{})
            if ping: parts.append(f"ICMP {ping.get('median_ms','—')}/{ping.get('p95_ms','—')} 成功{float(ping.get('success_rate',0))*100:.0f}%")
            http=e.get("http",{})
            if http:
                h=http.get("ttfb",{}); status="/".join(map(str,sorted(set(http.get("statuses",[]))))) or "—"; parts.append(f"HTTP {h.get('median_ms','—')}/{h.get('p95_ms','—')} 状态{status} 成功{float(http.get('success_rate',0))*100:.0f}%"+(" BLOCK" if http.get("blocked") else ""))
            ws=e.get("websocket",{})
            if ws:
                h=ws.get("handshake",{}); first=ws.get("first_message",{}); parts.append(f"WS {h.get('median_ms','—')}/{h.get('p95_ms','—')} 首包{first.get('median_ms','—')} 成功{float(ws.get('success_rate',0))*100:.0f}%")
            lines.append("    "+" | ".join(parts)); errors=(tcp.get("errors") or [])+(http.get("errors") or [])+(ws.get("errors") or [])
            if errors and score<55: lines.append(f"    最近错误: {errors[-1][:180]}")

    failed=[e for e in report["endpoints"] if e.get("tcp",{}).get("success_rate",0)==0]; blocked=[e for e in report["endpoints"] if e.get("http",{}).get("blocked")]
    diagnostics=[]; by_id={e.get("id"):e for e in report["endpoints"]}; ib_http=[e.get("http",{}).get("ttfb",{}).get("median_ms") for e in report["endpoints"] if e.get("group")=="ibkr" and e.get("http",{}).get("ttfb",{}).get("median_ms") is not None]
    if ib_http and statistics.median(ib_http)>350: diagnostics.append(f"IBKR公共入口HTTP中位约 {statistics.median(ib_http):.0f}ms，偏慢；必须安装Gateway测真实后台会话。")
    poly_ws=by_id.get("polymarket-ws",{}).get("websocket",{}).get("handshake",{}).get("median_ms")
    if poly_ws and poly_ws>400: diagnostics.append(f"Polymarket CLOB WS握手 {poly_ws:.0f}ms，实时盘口连接偏慢。")
    slow_ws=[e["name"] for e in report["endpoints"] if (e.get("websocket",{}).get("handshake",{}).get("median_ms") or 0)>700]
    if slow_ws: diagnostics.append("WS握手超过700ms: "+"、".join(slow_ws)+"。")
    if cpu.get("single_sha256_1mib_ops_s",9999)<500: diagnostics.append(f"单核CPU仅 {cpu.get('single_sha256_1mib_ops_s')} ops/s，明显偏弱，不适合高并发策略或密集事件处理。")
    if facts.get("memory_total_mib",999999)<8192: diagnostics.append(f"内存仅 {(facts.get('memory_total_mib') or 0)/1024:.1f}GiB，需限制策略、行情缓存和回测并发。")
    if disk.get("fsync_ms",{}).get("p95_ms",0)>4: diagnostics.append(f"fsync p95 {disk.get('fsync_ms',{}).get('p95_ms')}ms，账本/日志同步落盘延迟一般。")
    weak_data=[e["name"] for e in report["endpoints"] if e.get("group")=="market_data" and e.get("score",100)<40]
    if weak_data: diagnostics.append("明显偏慢的行情源: "+"、".join(weak_data)+"。")
    poly_geo=enriched_polymarket_evidence(next((e.get("capability_evidence") for e in report["endpoints"] if e.get("capability_evidence",{}).get("kind")=="polymarket_geoblock"),None))
    if poly_geo and poly_geo.get("policy_raw_conflict"): diagnostics.append(f"Polymarket {poly_geo.get('country')}：地区表称API可用，但原始geoblock=true；这是官方口径冲突，不能仅凭公开探针确认真实账户可开仓。")
    ordinary_blocked=[e for e in blocked if e.get("capability_evidence",{}).get("kind")!="polymarket_geoblock" or e.get("capability_evidence",{}).get("api_new_orders_allowed") is False]
    if ordinary_blocked: diagnostics.append("地域/WAF阻断: "+"、".join(e["name"] for e in ordinary_blocked[:8])+"。")
    if failed: diagnostics.append("完全连接失败: "+"、".join(e["name"] for e in failed[:8])+(" …" if len(failed)>8 else "")+"。")
    lines += ["",f"{codes['bold']}自动诊断与用途结论{codes['reset']}"]+[f"  • {x}" for x in diagnostics]+[f"  • {x}" for x in recommendations(display_report)]
    lines += ["",f"{codes['dim']}JSON: {json_path}",f"Markdown: {markdown_path}{codes['reset']}","="*78]
    return "\n".join(lines)


def _traditionalize(text: str) -> str:
    """Small built-in UI conversion; venue/product names and user labels stay unchanged."""
    phrases={"量化服务器探针结果":"量化伺服器探針結果","网络":"網路","主机":"主機","选择":"選擇","配置":"設定檔","版本":"版本","分组评分":"分組評分","用途评分":"用途評分","数字资产执行":"數位資產執行","执行":"執行","行情采集":"行情採集","研究回测":"研究回測","主机与量化关键性能":"主機與量化關鍵效能","架构":"架構","虚拟化":"虛擬化","容量":"容量","临时盘剩余":"暫存磁碟剩餘","内存复制":"記憶體複製","磁盘":"磁碟","写":"寫","读":"讀","可能含缓存":"可能含快取","时钟":"時鐘","性能子分":"效能子分","网络吞吐":"網路吞吐","轻量单流下载":"輕量單流下載","不是线路上限":"不是線路上限","交易能力与地域":"交易能力與地區","国家":"國家","允许":"允許","禁止":"禁止","按地区表":"按地區表","前端":"前端","原始":"原始","逐端点实测":"逐端點實測","中位":"中位數","单位":"單位","成功率":"成功率","连接失败率":"連線失敗率","业务消息":"業務訊息","优秀":"優秀","良好":"良好","可用":"可用","偏慢":"偏慢","较差":"較差","对端":"對端","状态":"狀態","首包":"首包","最近错误":"最近錯誤","自动诊断与用途结论":"自動診斷與用途結論","发现":"發現","地区":"地區","官方":"官方","检查":"檢查","账户":"帳戶","确认":"確認","报告":"報告","旧版":"舊版","重算":"重算","同步":"同步","明显":"明顯","不适合":"不適合","服务器":"伺服器","供应商":"供應商","区域":"區域","生成时间":"產生時間"}
    for src,dst in sorted(phrases.items(),key=lambda x:len(x[0]),reverse=True): text=text.replace(src,dst)
    return text


def _display_scores(report: dict[str, Any]) -> tuple[dict[str, Any],float,float,dict[str,Any],str | None]:
    s=report["summary"]; benchmark=report.get("benchmark",{}); stored=float(benchmark.get("score",0)); perf=stored; display=report; note=None
    if benchmark and not benchmark.get("score_breakdown"):
        perf,parts=calibrated_benchmark_score(benchmark); display={**report,"benchmark":{**benchmark,"score":perf,"score_breakdown":parts}}
        weight=.15 if report.get("profile") in ("crypto","polymarket") else .25; selection=round(float(s["overall_score"])*(1-weight)+perf*weight,1); note=f"Legacy report: host score recalibrated from {stored:.1f} to {perf:.1f} using v1.3."
    else: selection=float(s.get("selection_score",s["overall_score"]))
    return display,perf,selection,role_scores(display),note


def render_terminal_en(report: dict[str, Any], json_path: Path, markdown_path: Path, color: bool = True, details: str = "all") -> str:
    use=color and sys.stdout.isatty() and not os.environ.get("NO_COLOR"); c={"x":"\033[0m","b":"\033[1m","g":"\033[32m","y":"\033[33m","r":"\033[31m","q":"\033[36m","d":"\033[2m"} if use else {k:"" for k in "xbgyrqd"}
    def paint(value: str, score: float) -> str: return f"{c['g'] if score>=75 else c['y'] if score>=55 else c['r']}{value}{c['x']}"
    def scored(name: str,value: float) -> str: return f"{name}: {paint(f'{value:.1f}/100 {grade(value)}',value)}"
    display,perf,selection,roles,note=_display_scores(report); s=report["summary"]
    lines=["",f"{c['b']}{c['q']}Quant Trading Server Probe · {report['label']}{c['x']}","="*84,scored("Network",float(s["overall_score"]))+"   "+scored("Host",perf)+"   "+scored("Selection",selection),f"Time: {report.get('created_at')}   Profile: {report.get('profile')}   Version: {report.get('probe_version','legacy')}","",f"{c['b']}Group scores{c['x']}","  ".join(f"{k} {paint(f'{v:.1f}',v)}" for k,v in sorted(s["group_scores"].items())),"",f"{c['b']}Role scores{c['x']}"]
    if note: lines.append("  Note: "+note)
    role_names={"crypto_execution":"Crypto execution","ibkr_execution":"IBKR execution","futu_execution":"Futu execution","polymarket_execution":"Polymarket execution","market_data_node":"Market-data node","research_backtest":"Research/backtest"}
    for key,item in roles.items():
        role_value=f"{item['score']:.1f}/100 {item['grade']}"
        lines.append(f"  {role_names.get(key,key):<24} {paint(role_value,item['score'])}")
    b=display.get("benchmark",{}); facts=b.get("facts",{}); cpu=b.get("cpu",{}); memory=b.get("memory",{}); disk=b.get("disk",{}); clock=b.get("clock",{})
    if b:
        ram=(facts.get("memory_total_mib") or 0)/1024; workers=max(cpu.get("workers") or 1,1); per=cpu.get("per_worker_ops_s") or ((cpu.get("multi_sha256_1mib_ops_s") or 0)/workers)
        lines += ["",f"{c['b']}Host and trading-critical performance{c['x']}",f"  CPU: {facts.get('cpu_model') or facts.get('machine') or 'unknown'} · {facts.get('logical_cpus','?')} vCPU · {facts.get('machine','?')} · virtualization {facts.get('virtualization','?')}",f"  Capacity: {ram:.1f} GiB RAM · temporary-volume free {facts.get('disk_free_gib','?')} GiB",f"  CPU light test: single {cpu.get('single_sha256_1mib_ops_s','?')} ops/s · multi {cpu.get('multi_sha256_1mib_ops_s','?')} ops/s · per worker {per:.1f}",f"  Memory copy: {memory.get('copy_gib_s','?')} GiB/s",f"  Disk: write {disk.get('seq_write_mib_s','?')} MiB/s · cached-read sanity {disk.get('seq_read_mib_s','?')} MiB/s · 4K read {disk.get('random_4k_read_iops','?')} IOPS",f"  fsync: median {disk.get('fsync_ms',{}).get('median_ms','?')} ms · p95 {disk.get('fsync_ms',{}).get('p95_ms','?')} ms · max {disk.get('fsync_ms',{}).get('max_ms','?')} ms",f"  Clock: NTP={clock.get('ntp_synchronized','unknown')} · source={clock.get('clocksource','unknown')}"]
        if b.get("score_breakdown"): lines.append("  Performance components: "+" · ".join(f"{k}={v}" for k,v in b["score_breakdown"].items()))
    if report.get("bandwidth",{}).get("download_mbps") is not None: lines.append(f"  Network throughput: 1 MB single-stream sanity {report['bandwidth']['download_mbps']} Mbps (not line rate)")
    ibo=report.get("ibkr_official")
    if ibo:
        best_text=f"{ibo.get('best_region')} · {ibo.get('best_score')}/100" if ibo.get("best_region") else "no reachable region"
        lines += ["",f"{c['b']}Official IBKR TWS back-end hosts (4001 login/orders, 4000 market data){c['x']}",f"  Best region from this server: {best_text}"]
        for region in ibo.get("regions",[]):
            order=region.get("services",{}).get("login_orders",{}); data=region.get("services",{}).get("market_data",{})
            lines.append(f"  {region['region']:<24} {region['score']:>5.1f}/{region['grade']} · 4001 TCP {order.get('tcp_median_ms','—')}/{order.get('tcp_p95_ms','—')} ms success {float(order.get('tcp_success_rate') or 0)*100:.0f}% · 4000 TCP {data.get('tcp_median_ms','—')}/{data.get('tcp_p95_ms','—')} ms success {float(data.get('tcp_success_rate') or 0)*100:.0f}% · ICMP {order.get('icmp_median_ms','—')} ms")
        lines.append("  Service-port latency to an official IBKR host is not exchange matching or SmartRouting latency.")
    fa=report.get("futu_anchors")
    if fa:
        account=fa.get("account_profile") or "not selected (display only; excluded from Futu score)"; bq=fa.get("best_quote_anchor") or {}; bt=fa.get("best_trade_anchor") or {}
        lines += ["",f"{c['b']}Futu/moomoo cloud-region substitute anchors{c['x']}",f"  Account profile: {account} · quote candidate: {bq.get('provider','—')} {bq.get('region','—')} · trade candidate: {bt.get('provider','—')} {bt.get('region','—')}"]
        for x in fa.get("anchors",[]): lines.append(f"  {x.get('provider','?')} {x.get('region','?'):<22} {float(x.get('score') or 0):>5.1f}/{x.get('grade')} · TCP {x.get('tcp_median_ms','—')}/{x.get('tcp_p95_ms','—')} ms · HTTP {x.get('http_median_ms','—')} ms · ICMP {x.get('icmp_median_ms','—')} ms")
        lines.append("  These are cloud-region substitutes, not Futu server IPs. Confirm with the established FutuOpenD session RTT.")
    caps=[e for e in report.get("endpoints",[]) if e.get("capability_evidence")]
    if caps:
        lines += ["",f"{c['b']}Trading capability and geography{c['x']}"]
        for e in caps:
            cap=enriched_polymarket_evidence(e["capability_evidence"]) or e["capability_evidence"]; verdict=cap.get("verdict","unknown"); good=verdict in ("geo_check_passed","frontend_close_only_api_available","perpetual_market_reachable","swap_market_reachable"); extra=[]
            if cap.get("country"): extra.append(f"country={cap.get('country')} region={cap.get('region')} source-IP={cap.get('ip')}")
            if cap.get("live_perpetual_count") is not None: extra.append(f"{cap['live_perpetual_count']} live perpetuals")
            if cap.get("live_swap_count") is not None: extra.append(f"{cap['live_swap_count']} live swaps")
            if cap.get("kind")=="polymarket_geoblock": extra.append(f"API new orders={'allowed by table' if cap.get('api_new_orders_allowed') else 'blocked'}; frontend new orders={'allowed' if cap.get('frontend_new_orders_allowed') else 'blocked'}; raw blocked={cap.get('blocked')}")
            lines.append(f"  {e['name']}: {paint(verdict,80 if good else 25)}"+(" · "+" · ".join(extra) if extra else ""))
    if details!="none":
        endpoints=sorted(report.get("endpoints",[]),key=lambda e:(e.get("group",""),-e.get("score",0)))
        if details=="key": endpoints=[e for e in endpoints if float(e.get("weight",1))>=3 or e.get("score",0)<55 or e.get("capability_evidence")]
        lines += ["",f"{c['b']}Endpoint measurements (median/p95, milliseconds){c['x']}"]
        group=None
        for e in endpoints:
            if e.get("group")!=group: group=e.get("group"); lines.append(f"\n  [{group}]")
            score=float(e.get("score",0)); tcp=e.get("tcp",{}); peer=(tcp.get("peer_ips") or e.get("dns",{}).get("ips") or ["—"])[0]; lines.append(f"  {'OK' if tcp.get('success_rate',0)>0 else 'FAIL'} {e.get('name')} · {paint(f'{score:.1f}/{grade(score)}',score)} · peer {peer}")
            parts=[]
            if tcp: parts.append(f"TCP {tcp.get('median_ms','—')}/{tcp.get('p95_ms','—')} jitter {tcp.get('jitter_ms','—')} success {float(tcp.get('success_rate',0))*100:.0f}%")
            ping=e.get("ping",{})
            if ping: parts.append(f"ICMP {ping.get('median_ms','—')}/{ping.get('p95_ms','—')} success {float(ping.get('success_rate',0))*100:.0f}%")
            http=e.get("http",{});
            if http:
                h=http.get("ttfb",{}); status="/".join(map(str,sorted(set(http.get("statuses",[]))))) or "—"; parts.append(f"HTTP {h.get('median_ms','—')}/{h.get('p95_ms','—')} status {status} success {float(http.get('success_rate',0))*100:.0f}%"+(" BLOCK" if http.get("blocked") else ""))
            ws=e.get("websocket",{})
            if ws:
                h=ws.get("handshake",{}); parts.append(f"WS {h.get('median_ms','—')}/{h.get('p95_ms','—')} first {ws.get('first_message',{}).get('median_ms','—')} success {float(ws.get('success_rate',0))*100:.0f}%")
            lines.append("    "+" | ".join(parts))
    diagnostics=[]; geo=enriched_polymarket_evidence(next((e.get("capability_evidence") for e in report.get("endpoints",[]) if e.get("capability_evidence",{}).get("kind")=="polymarket_geoblock"),None))
    if geo and geo.get("policy_raw_conflict"): diagnostics.append(f"Polymarket {geo.get('country')}: the published table says API available while raw geoblock=true; a public probe cannot confirm authenticated order eligibility.")
    ib=[e.get("http",{}).get("ttfb",{}).get("median_ms") for e in report.get("endpoints",[]) if e.get("group")=="ibkr" and e.get("http",{}).get("ttfb",{}).get("median_ms") is not None]
    if ib and statistics.median(ib)>350: diagnostics.append(f"IBKR public HTTP median is about {statistics.median(ib):.0f} ms; run Gateway/TWS and measure the established backend session.")
    if cpu.get("single_sha256_1mib_ops_s",9999)<500: diagnostics.append(f"Single-worker CPU is weak ({cpu.get('single_sha256_1mib_ops_s')} ops/s); avoid dense event processing or high strategy concurrency.")
    if facts.get("memory_total_mib",999999)<8192: diagnostics.append(f"RAM is only {(facts.get('memory_total_mib') or 0)/1024:.1f} GiB; limit strategies, order-book caches, and backtest concurrency.")
    if disk.get("fsync_ms",{}).get("p95_ms",0)>4: diagnostics.append(f"fsync p95 is {disk.get('fsync_ms',{}).get('p95_ms')} ms; synchronous journals may be slow.")
    failed=[e.get("name") for e in report.get("endpoints",[]) if e.get("tcp",{}).get("success_rate",0)==0]
    if failed: diagnostics.append("Complete connection failures: "+", ".join(failed[:8]))
    lines += ["",f"{c['b']}Automatic diagnostics{c['x']}"]+[f"  • {x}" for x in diagnostics or ["No critical automatic warning; repeat across multiple time windows before production use."]]
    lines += ["",f"{c['d']}JSON: {json_path}",f"Markdown: {markdown_path}{c['x']}","="*84]
    return "\n".join(lines)


def render_terminal(report: dict[str, Any], json_path: Path, markdown_path: Path, color: bool = True, details: str = "all") -> str:
    if UI_LANG=="en": return render_terminal_en(report,json_path,markdown_path,color,details)
    rendered=render_terminal_zh(report,json_path,markdown_path,color,details)
    return _traditionalize(rendered) if UI_LANG=="zh-TW" else rendered


def render_md_en(report: dict[str, Any]) -> str:
    display,perf,selection,roles,note=_display_scores(report); s=report["summary"]; lines=[f"# Quant server probe — {report['label']}","",f"- Time: {report.get('created_at')}",f"- Provider/region: {report.get('provider') or 'not supplied'} / {report.get('region') or 'not supplied'}",f"- Profile: {report.get('profile')}",f"- Network: **{s.get('overall_score')} / 100**",f"- Host: **{perf} / 100**",f"- Selection: **{selection} / 100 ({grade(selection)})**"]
    if note: lines.append(f"- {note}")
    lines += ["","## Role scores","","| Role | Score | Grade |","|---|---:|:---:|"]
    for key,item in roles.items(): lines.append(f"| {key} | {item['score']} | {item['grade']} |")
    lines += ["","## Endpoints","","| Service | Group | TCP median | HTTP TTFB | WS handshake | Score |","|---|---|---:|---:|---:|---:|"]
    val=lambda x:"—" if x is None else str(x)
    for e in sorted(report.get("endpoints",[]),key=lambda x:(x.get("group",""),-x.get("score",0))): lines.append(f"| {e.get('name')} | {e.get('group')} | {val(e.get('tcp',{}).get('median_ms'))} | {val(e.get('http',{}).get('ttfb',{}).get('median_ms'))} | {val(e.get('websocket',{}).get('handshake',{}).get('median_ms'))} | {e.get('score')} |")
    lines += ["","Public reachability does not prove account, KYC, legal, derivatives, or order eligibility.",""]
    return "\n".join(lines)


def render_md(report: dict[str, Any]) -> str:
    if UI_LANG=="en": return render_md_en(report)
    rendered=render_md_zh(report)
    return _traditionalize(rendered) if UI_LANG=="zh-TW" else rendered


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
    gs, overall=group_scores(results,a.profile,a.futu_account)
    report={"schema_version":1,"probe_version":VERSION,"created_at":utc_now(),"label":a.label or socket.gethostname(),"provider":a.provider,"region":a.region,"profile":a.profile,"system":{"hostname":socket.gethostname(),"platform":platform.platform(),"python":platform.python_version()},"summary":{"group_scores":gs,"overall_score":overall},"endpoints":results}
    ibkr_official=summarize_ibkr_official(results)
    if ibkr_official: report["ibkr_official"]=ibkr_official
    futu_anchors=summarize_futu_anchors(results,a.futu_account)
    if futu_anchors: report["futu_anchors"]=futu_anchors
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
    if not a.no_terminal_summary: print(render_terminal(report,jp,mp,details=a.terminal_details))
    print("RESULT_JSON="+json.dumps({"json":str(jp),"markdown":str(mp),"overall_score":overall,"selection_score":report["summary"].get("selection_score")},ensure_ascii=False)); return 0


def cmd_compare(a: argparse.Namespace) -> int:
    reports=[json.loads(Path(p).read_text(encoding="utf-8")) for p in a.files]
    rows=sorted(reports,key=lambda r:r["summary"].get("selection_score",r["summary"]["overall_score"]),reverse=True)
    if UI_LANG=="en": lines=["# Quant Server Comparison","",f"Generated: {utc_now()}","","| Rank | Server | Provider/region | Selection | Host | IBKR | Futu | Crypto | Polymarket | Market data |","|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    else: lines=["# 量化服务器横向比较","",f"生成时间：{utc_now()}","","| 排名 | 服务器 | 供应商/区域 | 选择分 | 性能 | IBKR | Futu | Crypto | Polymarket | 行情 |","|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for i,r in enumerate(rows,1):
        g=r["summary"]["group_scores"]; lines.append(f"| {i} | {r['label']} | {r.get('provider','')}/{r.get('region','')} | {r['summary'].get('selection_score',r['summary']['overall_score'])} | {r.get('benchmark',{}).get('score','—')} | {g.get('ibkr','—')} | {g.get('futu','—')} | {g.get('crypto','—')} | {g.get('polymarket','—')} | {g.get('market_data','—')} |")
    lines += ["","## Conclusion" if UI_LANG=="en" else "## 结论",""]
    if rows:
        score=rows[0]['summary'].get('selection_score',rows[0]['summary']['overall_score'])
        lines.append(f"- Best in this profile: **{rows[0]['label']}** ({score}). This is a relative sample result; confirm real gateway sessions and 24–72 hour stability." if UI_LANG=="en" else f"- 当前配置档下首选 **{rows[0]['label']}**（选择分 {score}）。这只是同批样本的相对结论，需结合真实 IB 会话与 24–72 小时稳定性。")
    if UI_LANG=="zh-TW": lines=[_traditionalize(x) for x in lines]
    if a.output: out=Path(a.output).expanduser()
    else:
        directory,fallback=choose_output_dir(None); out=directory/"server-comparison.md"
        if fallback: print(f"[i] Current directory is not writable; report will be saved to: {out}",file=sys.stderr)
    rendered="\n".join(lines)+"\n"; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(rendered,encoding="utf-8"); print(rendered); print(f"Saved: {out}"); return 0


def cmd_show(a: argparse.Namespace) -> int:
    path=Path(a.file).expanduser(); report=json.loads(path.read_text(encoding="utf-8")); markdown=path.with_suffix(".md")
    print(render_terminal(report,path,markdown,color=not a.no_color,details=a.details)); return 0


def public_sample(report: dict[str, Any], provider: str, region: str, plan: str) -> dict[str, Any]:
    """Create an explicitly shareable sample with host/IP/route/error data removed."""
    geo=enriched_polymarket_evidence(next((e.get("capability_evidence") for e in report.get("endpoints",[]) if e.get("capability_evidence",{}).get("kind")=="polymarket_geoblock"),None)) or {}
    benchmark=report.get("benchmark",{}); perf=float(benchmark.get("score",0))
    if benchmark and not benchmark.get("score_breakdown"): perf,_=calibrated_benchmark_score(benchmark)
    endpoints=[]
    for e in report.get("endpoints",[]):
        item={"id":e.get("id"),"group":e.get("group"),"score":e.get("score")}
        for proto,field in (("tcp","tcp"),("ping","ping"),("http","http")):
            obj=e.get(field,{})
            timing=obj.get("ttfb",{}) if field=="http" else obj
            if obj: item[proto]={k:timing.get(k) for k in ("median_ms","p95_ms","jitter_ms") if timing.get(k) is not None}|{"success_rate":obj.get("success_rate")}
        ws=e.get("websocket",{})
        if ws: item["websocket"]={"median_ms":ws.get("handshake",{}).get("median_ms"),"p95_ms":ws.get("handshake",{}).get("p95_ms"),"first_message_ms":ws.get("first_message",{}).get("median_ms"),"success_rate":ws.get("success_rate")}
        cap=e.get("capability_evidence",{})
        if cap: item["capability"]={k:cap.get(k) for k in ("kind","verdict","live_perpetual_count","live_swap_count","api_new_orders_allowed") if k in cap}
        endpoints.append(item)
    facts=benchmark.get("facts",{}); ram=(facts.get("memory_total_mib") or 0)/1024
    sample={"public_schema_version":1,"probe_version":report.get("probe_version"),"sample_id":hashlib.sha256(os.urandom(32)).hexdigest()[:20],"date":str(report.get("created_at",utc_now()))[:10],"location":{"country":geo.get("country") or "","region_code":geo.get("region") or "","provider":provider or report.get("provider","") or "unknown","datacenter":region or report.get("region","") or "unknown","plan":plan or "unknown"},"scores":{"network":report.get("summary",{}).get("overall_score"),"performance":perf,"roles":role_scores({**report,"benchmark":{**benchmark,"score":perf}})},"host_bucket":{"arch":facts.get("machine"),"vcpus":facts.get("logical_cpus"),"ram_gib_bucket":math.ceil(ram/2)*2 if ram else None},"endpoints":endpoints,"privacy":{"removed":["source IP","hostname","CPU model","route hops","peer IPs","DNS answers","raw errors","timestamps finer than day"],"automatic_upload":False}}
    return sample


def cmd_public(a: argparse.Namespace) -> int:
    report=json.loads(Path(a.file).read_text(encoding="utf-8")); sample=public_sample(report,a.provider,a.region,a.plan)
    out=Path(a.output).expanduser() if a.output else Path(f"public-sample-{sample['sample_id']}.json")
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(sample,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if UI_LANG=="en": print(f"Sanitized public sample created (not uploaded): {out}"); print("Inspect it manually before submitting it under public-samples/.")
    elif UI_LANG=="zh-TW": print(f"已產生脫敏公開樣本（未上傳）：{out}"); print("請先人工檢查，再提交到儲存庫 public-samples/ 目錄。")
    else: print(f"已生成脱敏公开样本（未上传）：{out}"); print("请先人工检查，再提交到仓库 public-samples/ 目录。")
    return 0


def cmd_aggregate(a: argparse.Namespace) -> int:
    samples=[]
    for pattern in a.files:
        paths=list(Path().glob(pattern)) if any(x in pattern for x in "*?[") else [Path(pattern)]
        for path in paths:
            data=json.loads(path.read_text(encoding="utf-8"))
            if data.get("public_schema_version")==1: samples.append(data)
    groups: dict[tuple[str,str,str],list[dict[str,Any]]]={}
    for s in samples:
        loc=s.get("location",{}); key=(loc.get("country") or "?",loc.get("provider") or "unknown",loc.get("datacenter") or "unknown"); groups.setdefault(key,[]).append(s)
    if UI_LANG=="en": lines=["# Quant Server Community Ranking","",f"Samples: {len(samples)}. A combination is shown only with at least {a.min_samples} public samples.","","| Country | Provider | Datacenter | Samples | Network median | Host median | Crypto | IBKR | Polymarket |","|---|---|---|---:|---:|---:|---:|---:|---:|"]
    else: lines=["# 量化服务器社区样本榜单","",f"样本数：{len(samples)}；仅显示至少 {a.min_samples} 个公开样本的组合。","","| 国家 | 供应商 | 机房 | 样本 | 网络中位 | 性能中位 | Crypto | IBKR | Polymarket |","|---|---|---|---:|---:|---:|---:|---:|---:|"]
    ranked=[]
    for key,rows in groups.items():
        if len({x.get("sample_id") for x in rows})<a.min_samples: continue
        med=lambda vals:round(statistics.median([float(v) for v in vals if v is not None]),1) if any(v is not None for v in vals) else None
        roles=lambda name:[x.get("scores",{}).get("roles",{}).get(name,{}).get("score") for x in rows]
        item=(*key,len(rows),med([x.get("scores",{}).get("network") for x in rows]),med([x.get("scores",{}).get("performance") for x in rows]),med(roles("crypto_execution")),med(roles("ibkr_execution")),med(roles("polymarket_execution")))
        ranked.append(item)
    ranked.sort(key=lambda x:statistics.mean([v for v in x[4:] if isinstance(v,(int,float))]),reverse=True)
    for x in ranked: lines.append(f"| {x[0]} | {x[1]} | {x[2]} | {x[3]} | {x[4] if x[4] is not None else '—'} | {x[5] if x[5] is not None else '—'} | {x[6] if x[6] is not None else '—'} | {x[7] if x[7] is not None else '—'} | {x[8] if x[8] is not None else '—'} |")
    if not ranked: lines += ["","No provider/datacenter combination has enough samples; no ranking is published from a single sample." if UI_LANG=="en" else "尚无达到最小样本数的供应商/机房组合；不能据单一样本发布排名。"]
    if UI_LANG=="zh-TW": lines=[_traditionalize(x) for x in lines]
    rendered="\n".join(lines)+"\n"; out=Path(a.output).expanduser(); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(rendered,encoding="utf-8"); print(rendered); print(f"Saved: {out}"); return 0


def build_parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="Quant trading server network probe"); p.add_argument("--version",action="version",version=VERSION); sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("probe",help="Probe configured public endpoints"); q.add_argument("--config",default=str(DEFAULT_CONFIG)); q.add_argument("--label"); q.add_argument("--provider",default=""); q.add_argument("--region",default=""); q.add_argument("--profile",choices=PROFILES,default="balanced"); q.add_argument("--suite",choices=("core","extended"),default="core"); q.add_argument("--groups",help="comma-separated groups"); q.add_argument("--target",action="append",default=[],help="extra TCP target: NAME=HOST:PORT (repeatable)"); q.add_argument("--rounds",type=int,default=5); q.add_argument("--quick",action="store_true"); q.add_argument("--timeout",type=float,default=4.0); q.add_argument("--workers",type=int,default=8); q.add_argument("--routes",action="store_true"); q.add_argument("--max-routes",type=int,default=5); q.add_argument("--futu-host",help="FutuOpenD host, usually 127.0.0.1"); q.add_argument("--futu-port",type=int,default=11111); q.add_argument("--futu-account",choices=("futu-hk","moomoo-us","moomoo-sg","moomoo-au","moomoo-my","moomoo-ca","moomoo-jp"),help="select applicable Futu/moomoo quote and trade region anchors"); q.add_argument("--ib-host",help="IB Gateway/TWS API host, usually 127.0.0.1"); q.add_argument("--ib-port",type=int,default=4002); q.add_argument("--live-sessions",action="store_true",help="include kernel RTT for running IB/Futu gateways"); q.add_argument("--session-pattern",default=r"ibgateway|tws|java|FutuOpenD|OpenD"); q.add_argument("--no-benchmark",action="store_true"); q.add_argument("--no-bandwidth",action="store_true"); q.add_argument("--no-terminal-summary",action="store_true"); q.add_argument("--terminal-details",choices=("all","key","none"),default="all"); q.add_argument("--benchmark-level",choices=("light","standard"),default="light"); q.add_argument("--output",help="report directory; auto-selects a writable directory when omitted"); q.set_defaults(func=cmd_probe)
    c=sub.add_parser("compare",help="Compare JSON reports"); c.add_argument("files",nargs="+"); c.add_argument("--output"); c.set_defaults(func=cmd_compare)
    s=sub.add_parser("show",help="Render an existing JSON report in the terminal"); s.add_argument("file"); s.add_argument("--details",choices=("all","key","none"),default="all"); s.add_argument("--no-color",action="store_true"); s.set_defaults(func=cmd_show)
    u=sub.add_parser("public",help="Create a privacy-scrubbed, opt-in community sample"); u.add_argument("file"); u.add_argument("--provider",default=""); u.add_argument("--region",default=""); u.add_argument("--plan",default=""); u.add_argument("--output"); u.set_defaults(func=cmd_public)
    ag=sub.add_parser("aggregate",help="Build a community leaderboard from public samples"); ag.add_argument("files",nargs="+"); ag.add_argument("--min-samples",type=int,default=3); ag.add_argument("--output",default="COMMUNITY_LEADERBOARD.md"); ag.set_defaults(func=cmd_aggregate)
    d=sub.add_parser("discover",help="Read kernel RTT for established IB/Futu gateway sockets"); d.add_argument("--pattern",default=r"ibgateway|tws|java|FutuOpenD|OpenD"); d.add_argument("--output"); d.set_defaults(func=lambda a:(Path(a.output).write_text(json.dumps(tcp_socket_discovery(a.pattern),ensure_ascii=False,indent=2),encoding="utf-8") if a.output else print(json.dumps(tcp_socket_discovery(a.pattern),ensure_ascii=False,indent=2))) or 0)
    return p


if __name__ == "__main__":
    parser=build_parser(); args=parser.parse_args(); raise SystemExit(args.func(args))
