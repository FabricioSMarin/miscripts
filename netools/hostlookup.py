#!/usr/bin/env python3
"""
Scan a subnet for live devices and resolve their hostnames — no root/sudo required.

Approach:
  1. Ping-sweep every address in the subnet (concurrently) to populate the
     kernel's ARP/neighbor cache and find which hosts are alive.
  2. Read the ARP cache (`ip neigh` / `arp -a`) to get MAC addresses for
     responding hosts.
  3. Resolve hostnames via reverse DNS, with an optional NetBIOS fallback
     (nmblookup) for Windows-style devices without DNS entries.

Usage:
    python3 scan_subnet_hostnames_noroot.py 192.168.1.0/24
"""

import argparse
import ipaddress
import re
import shutil
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

# Resolved once at import time so we don't repeatedly hit a broken PATH entry
NMBLOOKUP_PATH = shutil.which("nmblookup")


def ping(ip: str, timeout: int = 1) -> bool:
    """Return True if the host responds to a single ping."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except FileNotFoundError:
        print("The 'ping' command was not found on this system.")
        sys.exit(1)


def get_arp_table() -> dict:
    """
    Return a dict of {ip: mac} from the system's neighbor/ARP cache.
    Tries `ip neigh` first (modern Linux), falls back to `arp -a`.
    """
    table = {}

    try:
        out = subprocess.run(["ip", "neigh"], capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            # e.g. "192.168.1.5 dev eth0 lladdr aa:bb:cc:dd:ee:ff STALE"
            m = re.match(r"^(\S+)\s+dev\s+\S+\s+lladdr\s+(\S+)", line)
            if m:
                table[m.group(1)] = m.group(2)
        if table:
            return table
    except FileNotFoundError:
        pass

    try:
        out = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=5)
        for line in out.stdout.splitlines():
            # e.g. "? (192.168.1.5) at aa:bb:cc:dd:ee:ff [ether] on eth0"
            m = re.search(r"\(([\d.]+)\)\s+at\s+([0-9a-fA-F:]+)", line)
            if m:
                table[m.group(1)] = m.group(2)
    except FileNotFoundError:
        pass

    return table


def get_hostname(ip: str) -> str:
    """Try reverse DNS, then NetBIOS, then give up."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except (socket.herror, socket.gaierror):
        pass

    if NMBLOOKUP_PATH:
        try:
            result = subprocess.run(
                [NMBLOOKUP_PATH, "-A", ip], capture_output=True, text=True, timeout=2
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and "<00>" in line and "GROUP" not in line:
                    return line.split()[0]
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            pass

    return "Unknown"


def scan_subnet(subnet: str, timeout: int, workers: int):
    network = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(ip) for ip in network.hosts()]

    alive = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(ping, ip, timeout): ip for ip in hosts}
        for future in as_completed(futures):
            ip = futures[future]
            if future.result():
                alive.append(ip)

    arp_table = get_arp_table()

    devices = []
    for ip in alive:
        devices.append({
            "ip": ip,
            "mac": arp_table.get(ip, "Unknown"),
        })

    return devices


def main():
    parser = argparse.ArgumentParser(
        description="Discover devices on a subnet (no root) and resolve hostnames."
    )
    parser.add_argument("subnet", help="Subnet in CIDR notation, e.g. 192.168.1.0/24")
    parser.add_argument("--timeout", type=int, default=1, help="Ping timeout in seconds (default: 1)")
    parser.add_argument("--workers", type=int, default=64, help="Concurrent ping workers (default: 64)")
    args = parser.parse_args()

    print(f"Scanning {args.subnet} (no root, ping-sweep based)...\n")
    devices = scan_subnet(args.subnet, args.timeout, args.workers)

    if not devices:
        print("No devices responded. Some devices block ICMP pings and won't show up "
              "with this method — a root-based ARP scan will find those.")
        return

    print(f"{'IP Address':<16} {'MAC Address':<20} {'Hostname'}")
    print("-" * 60)

    for device in sorted(devices, key=lambda d: tuple(int(o) for o in d["ip"].split("."))):
        hostname = get_hostname(device["ip"])
        print(f"{device['ip']:<16} {device['mac']:<20} {hostname}")


if __name__ == "__main__":
    main()
