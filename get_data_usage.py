#!/usr/bin/env python3
"""
NSOC Data Usage Collector v3
- Uses Microsoft Edge WebDriver (built-in on Windows 10/11, no download needed)
- No Playwright, no Chromium download
- Scrapes mydata.du.ae using existing user session
- Updates GLPI PluginFieldsComputerdata

Usage:
    python get_data_usage.py                     # Run once (verbose)
    python get_data_usage.py --silent             # Silent (scheduled task)
    python get_data_usage.py --install            # Install scheduled task
"""

import sys, json, os, re, time, subprocess, tempfile, platform, datetime, math
import urllib.request, urllib.parse, urllib.error
import http.client, ssl

# ── Config ──
GLPI_API = "https://nsoc.aiootech.com/apirest.php"
GLPI_APP_TOKEN = "ig5tWvB2NK5DkEacnySyiNWTjqEHp0calKi7okq7"
GLPI_USER_TOKEN = "vGmLoJ74Rs1wlvN9u9zq4bwYnTeKLAeaOpHzdeD6"

SILENT = "--silent" in sys.argv or "-silent" in sys.argv
VERBOSE = "--verbose" in sys.argv or "-verbose" in sys.argv

def log(msg):
    if not SILENT:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

def debug(msg):
    if VERBOSE:
        print(f"  DEBUG: {msg}")

# ═══════════════════════════════════════════
# 1. EDGE WEBDRIVER SCRAPER
# ═══════════════════════════════════════════

def _extract_phone(html):
    """Extract phone number from DU portal page HTML."""
    # Try various formats: +971581585311, +971 58 158 5311, 0581585311, etc.
    patterns = [
        r"\+971[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d",
        r"0?5[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d[\s-]?\d",
        r"(?:05|5)\d{8}",
    ]
    for p in patterns:
        m = re.search(p, html)
        if m:
            num = re.sub(r"[\s-]", "", m.group(0))
            if num.startswith("0"):
                num = "+971" + num[1:]
            elif num.startswith("5"):
                num = "+971" + num
            return num
    return ""

def _extract_usage_from_html(html):
    """
    Extract data usage values from DU portal HTML, keeping original units.
    Returns (used_value, used_unit, total_value, total_unit) or None.
    Example: "735.95 MB/15.00 GB" -> ("735.95", "MB", "15.00", "GB")
    """
    # Pattern 1: "X.XX MB / Y.YY GB" or "X.XX GB / Y.YY GB"
    m = re.search(r"(\d+[\.,]?\d*)\s*(\w[Bb])\s*/\s*(\d+[\.,]?\d*)\s*(\w[Bb])", html)
    if m:
        return (m.group(1), m.group(2), m.group(3), m.group(4))
    
    # Pattern 2: "X.XX MB out of Y.YY GB" or "X.XX of Y.YY GB"
    m = re.search(r"(\d+[\.,]?\d*)\s*(\w[Bb])\s+(?:out of|of|/)\s+(\d+[\.,]?\d*)\s*(\w[Bb])", html)
    if m:
        return (m.group(1), m.group(2), m.group(3), m.group(4))
    
    return None


def _normalize_to_gb(value, unit):
    """Convert value+unit to GB float. Returns (float_gb, original_display_string)."""
    val = float(value.replace(",", ""))
    unit_lower = unit.lower()
    if unit_lower in ("gb", "gib"):
        return val, f"{value} {unit}"
    elif unit_lower in ("mb", "mib"):
        return round(val / 1024, 4), f"{value} {unit}"
    elif unit_lower in ("kb", "kib"):
        return round(val / (1024**2), 6), f"{value} {unit}"
    else:
        return val, f"{value} {unit}"


def get_du_usage_selenium():
    """
    Use Selenium with Edge WebDriver (built-in on Windows 10/11).
    No Playwright, no greenlet DLL issues. Falls back to Edge headless.
    """
    output = {
        "hostname": platform.node(),
        "msisdn": "",
        "total_gb": 0,
        "used_gb": 0,
        "left_gb": 0,
        "data_percent": 0,
        "status": "failed",
    }
    
    try:
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
        
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--window-size=1920,1080")
        
        # Add a realistic user agent
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0")
        
        # Try to use real user profile for cookies/session
        for u in sorted(os.listdir(r"C:\Users")):
            u_lower = u.lower()
            if u_lower in ("public", "default", "default user", "all users", "defaultuser0", "administrator"):
                continue
            candidate = os.path.join(r"C:\Users", u, "AppData", "Local", "Microsoft", "Edge", "User Data")
            if os.path.isdir(candidate):
                options.add_argument(f"--user-data-dir={candidate}")
                log(f"Using Edge profile: {u}")
                break
        
        log("Launching Selenium Edge headless...")
        driver = webdriver.Edge(options=options)
        
        try:
            driver.get("http://mydata.du.ae")
            
            # Wait for Angular to render - wait for body to have real content
            WebDriverWait(driver, 30).until(
                lambda d: len(d.find_element(By.TAG_NAME, "body").text) > 50
            )
            
            text = driver.find_element(By.TAG_NAME, "body").text
            html = driver.page_source
            log(f"Page loaded: {len(text)} chars text")
            debug(f"Text: {text[:500]}")
            
            # Phone
            extracted_phone = _extract_phone(html) or _extract_phone(text)
            if extracted_phone:
                output["msisdn"] = extracted_phone
                log(f"Phone: {output['msisdn']}")
            
            # Usage
            usage = _extract_usage_from_html(text) or _extract_usage_from_html(html)
            if usage:
                used_val_str, used_unit, total_val_str, total_unit = usage
                log(f"Found usage: {used_val_str} {used_unit} / {total_val_str} {total_unit}")
                output["_used_display"] = f"{used_val_str} {used_unit}"
                output["_total_display"] = f"{total_val_str} {total_unit}"
                used_gb, _ = _normalize_to_gb(used_val_str, used_unit)
                total_gb, _ = _normalize_to_gb(total_val_str, total_unit)
                output["used_gb"] = used_gb
                output["total_gb"] = total_gb
                output["left_gb"] = round(total_gb - used_gb, 4)
                output["data_percent"] = round((used_gb / total_gb) * 100, 2) if total_gb > 0 else 0
                output["status"] = "success"
                log(f"Data: {used_gb:.4f}GB / {total_gb}GB ({output['data_percent']}%)")
                return output
            
            log("Could not parse data usage from Selenium result")
            return output
        finally:
            driver.quit()
    except ImportError:
        log("Selenium not installed")
        output["status"] = "no_selenium"
    except Exception as e:
        log(f"Selenium error: {e}")
        output["status"] = "selenium_error"
        output["message"] = str(e)
    
    return output


def get_du_usage_urllib():
    """
    Direct HTTP request to mydata.du.ae using Python's built-in urllib.
    No browser, no dependencies. Works on any PC with internet access.
    """
    output = {
        "hostname": platform.node(),
        "msisdn": "",
        "total_gb": 0,
        "used_gb": 0,
        "left_gb": 0,
        "data_percent": 0,
        "status": "failed",
    }
    
    try:
        log("Fetching mydata.du.ae via direct HTTP...")
        req = urllib.request.Request("http://mydata.du.ae", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        resp = urllib.request.urlopen(req, timeout=30)
        html = resp.read().decode("utf-8", errors="replace")
        log(f"Loaded: {len(html)} chars, status {resp.status}")
        debug(f"HTML: {html[:800]}")
        
        # Phone number
        extracted_phone = _extract_phone(html)
        if extracted_phone:
            output["msisdn"] = extracted_phone
            log(f"Phone: {output['msisdn']}")
        
        # Extract usage
        usage = _extract_usage_from_html(html)
        if usage:
            used_val_str, used_unit, total_val_str, total_unit = usage
            log(f"Found usage: {used_val_str} {used_unit} / {total_val_str} {total_unit}")
            output["_used_display"] = f"{used_val_str} {used_unit}"
            output["_total_display"] = f"{total_val_str} {total_unit}"
            used_gb, _ = _normalize_to_gb(used_val_str, used_unit)
            total_gb, _ = _normalize_to_gb(total_val_str, total_unit)
            output["used_gb"] = used_gb
            output["total_gb"] = total_gb
            output["left_gb"] = round(total_gb - used_gb, 4)
            output["data_percent"] = round((used_gb / total_gb) * 100, 2) if total_gb > 0 else 0
            output["status"] = "success"
            log(f"Data: {used_gb:.4f}GB / {total_gb}GB ({output['data_percent']}%)")
            return output
        
        # Fallback percentage
        log("Usage pattern not found via HTTP...")
        pct_match = re.search(r"(\d+[\.,]?\d*)\s*%", html)
        all_gb = re.findall(r"(\d+[\.,]?\d*)\s*(?:[Gg][Bb])", html)
        if pct_match and all_gb:
            output["data_percent"] = float(pct_match.group(1).replace(",", "."))
            output["total_gb"] = float(all_gb[-1].replace(",", ""))
            output["used_gb"] = round(output["total_gb"] * output["data_percent"] / 100, 4)
            output["left_gb"] = round(output["total_gb"] - output["used_gb"], 4)
            output["status"] = "success"
            log(f"Data (from %): {output['used_gb']}GB / {output['total_gb']}GB ({output['data_percent']}%)")
            return output
        
        log("Could not parse data usage from HTTP response")
        return output
    
    except urllib.error.HTTPError as e:
        log(f"HTTP Error {e.code}: {e.reason}")
        output["status"] = "http_error"
        output["message"] = str(e)
    except urllib.error.URLError as e:
        log(f"URL Error: {e.reason}")
        output["status"] = "network_error"
        output["message"] = str(e.reason)
    except Exception as e:
        log(f"HTTP fetch error: {e}")
        output["status"] = "http_failed"
        output["message"] = str(e)
    
    return output


def get_du_usage_with_edge():
    """
    Use Microsoft Edge (msedgedriver) in headless mode to scrape mydata.du.ae.
    Edge is built-in on all Windows 10/11.
    Falls back to Selenium/Edge, or uses pure edge driver.
    """
    output = {
        "hostname": platform.node(),
        "msisdn": "",
        "total_gb": 0,
        "used_gb": 0,
        "left_gb": 0,
        "data_percent": 0,
        "status": "failed",
    }
    
    # Find the real user's Edge profile (not SYSTEM's)
    real_user_profile = None
    users_dir = r"C:\Users"
    if os.path.isdir(users_dir):
        for u in sorted(os.listdir(users_dir)):
            u_lower = u.lower()
            # Skip system accounts
            if u_lower in ("public", "default", "default user", "all users", "defaultuser0", "administrator"):
                continue
            candidate = os.path.join(users_dir, u, "AppData", "Local", "Microsoft", "Edge", "User Data")
            if os.path.isdir(candidate):
                default_profile = os.path.join(candidate, "Default", "Cookies")
                if not os.path.exists(default_profile):
                    default_profile = os.path.join(candidate, "Default", "Network", "Cookies")
                if os.path.exists(default_profile):
                    real_user_profile = candidate
                    log(f"Found Edge profile: {u}")
                    break
    
    if not real_user_profile:
        real_user_profile = os.environ.get("USERPROFILE", "C:\\Users\\Default")
        real_user_profile = os.path.join(real_user_profile, "AppData", "Local", "Microsoft", "Edge", "User Data")
    
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    
    edge_path = None
    for p in edge_paths:
        if os.path.exists(p):
            edge_path = p
            break
    
    if not edge_path:
        # Try finding in PATH
        import shutil
        edge_path = shutil.which("msedge") or shutil.which("edge") or shutil.which("msedge.exe")
    
    if not edge_path:
        log("Edge not found. Fallback to Playwright approach.")
        output["status"] = "no_edge"
        return output
    
    log(f"Using Edge: {edge_path}")
    
    try:
        # Create a simple HTML file and launch Edge headless to get the page
        # Edge --headless --virtual-time-budget=15000 http://mydata.du.ae --dump-dom
        cmd = [
            edge_path,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-software-rasterizer",
            "--virtual-time-budget=15000",
            "http://mydata.du.ae/",
            "--dump-dom",
        ]
        
        log("Launching Edge headless to scrape DU portal...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        
        html = result.stdout
        
        if not html or len(html) < 100:
            # Maybe it redirected - try with real user's Edge profile
            log(f"Empty page ({len(html) if html else 0} chars). Trying with user profile: {real_user_profile}")
            
            cmd = [
                edge_path,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={real_user_profile}",
                "--virtual-time-budget=20000",
                "http://mydata.du.ae/",
                "--dump-dom",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            html = result.stdout
        
        log(f"Page loaded: {len(html)} chars")
        debug(f"HTML snippet: {html[:500]}")
        
        # Try phone number extraction
        extracted_phone = _extract_phone(html)
        if extracted_phone:
            output["msisdn"] = extracted_phone
            log(f"Phone: {output['msisdn']}")
        
        # Extract usage with original units
        usage = _extract_usage_from_html(html)
        if usage:
            used_val_str, used_unit, total_val_str, total_unit = usage
            log(f"Found usage: {used_val_str} {used_unit} / {total_val_str} {total_unit}")
            
            # Store original display strings
            output["_used_display"] = f"{used_val_str} {used_unit}"
            output["_total_display"] = f"{total_val_str} {total_unit}"
            
            # Convert to GB for numeric fields
            used_gb, _ = _normalize_to_gb(used_val_str, used_unit)
            total_gb, _ = _normalize_to_gb(total_val_str, total_unit)
            
            output["used_gb"] = used_gb
            output["total_gb"] = total_gb
            output["left_gb"] = round(total_gb - used_gb, 4)
            output["data_percent"] = round((used_gb / total_gb) * 100, 2) if total_gb > 0 else 0
            output["status"] = "success"
            log(f"Data: {used_gb:.4f}GB / {total_gb}GB ({output['data_percent']}%)")
            return output
        
        # Fallback: percentage
        log("Usage pattern not found, trying percentage...")
        pct_match = re.search(r"(\d+[\.,]?\d*)\s*%", html)
        all_gb = re.findall(r"(\d+[\.,]?\d*)\s*(?:[Gg][Bb])", html)
        if pct_match and all_gb:
            output["data_percent"] = float(pct_match.group(1).replace(",", "."))
            output["total_gb"] = float(all_gb[-1].replace(",", ""))
            output["used_gb"] = round(output["total_gb"] * output["data_percent"] / 100, 4)
            output["left_gb"] = round(output["total_gb"] - output["used_gb"], 4)
            output["status"] = "success"
            log(f"Data (from %): {output['used_gb']}GB / {output['total_gb']}GB ({output['data_percent']}%)")
            return output
        
        log("Could not parse data usage from DU page")
        return output
        
    except subprocess.TimeoutExpired:
        log("Edge timeout - page did not load in time")
        output["status"] = "timeout"
    except Exception as e:
        log(f"Edge error: {e}")
        output["status"] = "error"
        output["message"] = str(e)
    
    return output


# ═══════════════════════════════════════════
# 2. GLPI HELPERS
# ═══════════════════════════════════════════

_glpi_token = None

def glpi_init():
    global _glpi_token
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("nsoc.aiootech.com", context=ctx)
    conn.request("GET", "/apirest.php/initSession", headers={
        "App-Token": GLPI_APP_TOKEN,
        "Authorization": f"user_token {GLPI_USER_TOKEN}",
    })
    resp = conn.getresponse()
    _glpi_token = json.loads(resp.read().decode())["session_token"]
    conn.close()
    return _glpi_token

def glpi_request(method, endpoint, data=None):
    global _glpi_token
    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("nsoc.aiootech.com", context=ctx, timeout=30)
    headers = {
        "App-Token": GLPI_APP_TOKEN,
        "Session-Token": _glpi_token,
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    conn.request(method, endpoint, body=body, headers=headers)
    resp = conn.getresponse()
    if resp.status >= 400:
        raise Exception(f"GLPI {resp.status}: {resp.read().decode()[:200]}")
    return json.loads(resp.read().decode())

def glpi_search_computer(hostname):
    params = urllib.parse.urlencode({
        "expand_dropdowns": "true",
        "range": "0-20",
        "criteria[0][field]": "1",
        "criteria[0][searchtype]": "contains",
        "criteria[0][value]": hostname,
        "forcedisplay[0]": "1",
        "forcedisplay[1]": "2",
    })
    r = glpi_request("GET", f"/apirest.php/search/Computer?{params}")
    for pc in r.get("data", []):
        if pc.get("1", "").lower() == hostname.lower():
            return pc.get("2"), pc.get("1", "")
    if r.get("data"):
        return r["data"][0].get("2"), r["data"][0].get("1", "")
    return None, None

def glpi_search_plugin_by_items_id(computer_id):
    """
    Search for existing PluginFieldsComputerdata entries by items_id.
    Fetches in small batches and filters locally because GLPI API doesn't
    support items_id as a filter parameter on GET PluginFieldsComputerdata.
    """
    matches = []
    try:
        # Fetch in small ranges to avoid timeout, filter locally by items_id
        for start in range(0, 20000, 50):
            r = glpi_request("GET", f"/apirest.php/PluginFieldsComputerdata?range={start}-{start+49}")
            if not isinstance(r, list) or len(r) == 0:
                break
            for item in r:
                entry_items_id = item.get("items_id") or item.get("2") or item.get("1")
                if entry_items_id == computer_id:
                    matches.append(item)
            if len(r) < 50:
                break
    except Exception as e:
        debug(f"glpi_search_plugin_by_items_id error: {e}")
    return matches

def glpi_delete_plugin(plugin_id):
    """Delete a PluginFieldsComputerdata entry by its own ID."""
    try:
        glpi_request("DELETE", f"/apirest.php/PluginFieldsComputerdata/{plugin_id}")
        return True
    except Exception as e:
        log(f"Delete plugin #{plugin_id} failed: {e}")
        return False

def glpi_update_plugin(plugin_id, used_gb, total_gb, percent, msisdn="", used_display=None, total_display=None):
    now = datetime.datetime.now().strftime("%m/%d/%Y %H:%M")
    left_gb = round(total_gb - used_gb, 2)
    used_str = used_display if used_display else f"{round(used_gb, 2)} Gb"
    total_str = total_display if total_display else f"{round(total_gb, 2)} Gb"
    left_str = total_display if total_display else f"{left_gb} Gb"
    glpi_request("PUT", f"/apirest.php/PluginFieldsComputerdata/{plugin_id}", {
        "input": [{
            "id": plugin_id,
            "totaldatafield": total_str,
            "datausedfield": used_str,
            "dataleftfield": left_str,
            "percentfield": f"{round(percent, 1)} %",
            "executiontimefield": now,
        }]
    })

def glpi_create_plugin(computer_id, used_gb, total_gb, percent, msisdn="", comment="", used_display=None, total_display=None):
    now = datetime.datetime.now().strftime("%m/%d/%Y %H:%M")
    left_gb = round(total_gb - used_gb, 4)
    used_str = used_display if used_display else f"{round(used_gb, 2)} Gb"
    total_str = total_display if total_display else f"{round(total_gb, 2)} Gb"
    left_str = total_display if total_display else f"{left_gb} Gb"
    payload = {
        "input": [{
            "items_id": computer_id,
            "itemtype": "Computer",
            "plugin_fields_containers_id": 12,
            "entities_id": 0,
            "phonenumberfield": msisdn,
            "totaldatafield": total_str,
            "datausedfield": used_str,
            "dataleftfield": left_str,
            "percentfield": f"{round(percent, 1)} %",
            "executiontimefield": now,
        }]
    }
    if comment:
        payload["input"][0]["commentfield"] = comment
    glpi_request("POST", "/apirest.php/PluginFieldsComputerdata", payload)


# ═══════════════════════════════════════════
# 3. SCHEDULED TASK INSTALLER
# ═══════════════════════════════════════════

def install_scheduled_task():
    script_path = os.path.abspath(__file__)
    ps_script = f'''
$taskName = "NSOC Data Usage Collector"
$scriptPath = "{script_path}"
$action = New-ScheduledTaskAction -Execute "python.exe" -Argument '"`"$scriptPath`"" --silent'
$trigger = New-ScheduledTaskTrigger -Daily -At 08:00AM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
Write-Host "Scheduled task installed: $taskName"
'''
    try:
        subprocess.run(["powershell", "-Command", ps_script], check=True, capture_output=True, timeout=30)
        log("Scheduled task created!")
        return True
    except:
        log("Failed to create scheduled task")
        return False


# ═══════════════════════════════════════════
# 4. FALLBACK: Playwright (if Edge fails)
# ═══════════════════════════════════════════

def get_du_usage_playwright():
    """Fallback if Edge is not available - uses Playwright with Chromium"""
    log("Attempting Playwright fallback...")
    try:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu", "--disable-setuid-sandbox"])
            page = browser.new_page()
            page.goto("http://mydata.du.ae", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(7000)
            
            text = page.inner_text("body")
            
            result = {"hostname": platform.node(), "msisdn": "", "total_gb": 0, "used_gb": 0, "left_gb": 0, "data_percent": 0, "status": "failed"}
            
            phone_match = re.search(r"\+971\s?\d+", text)
            if phone_match:
                result["msisdn"] = phone_match.group(0)
            
            # Extract usage with original units
            usage = _extract_usage_from_html(text)
            if usage:
                used_val_str, used_unit, total_val_str, total_unit = usage
                log(f"Playwright - Found usage: {used_val_str} {used_unit} / {total_val_str} {total_unit}")
                
                result["_used_display"] = f"{used_val_str} {used_unit}"
                result["_total_display"] = f"{total_val_str} {total_unit}"
                
                used_gb, _ = _normalize_to_gb(used_val_str, used_unit)
                total_gb, _ = _normalize_to_gb(total_val_str, total_unit)
                
                result["used_gb"] = used_gb
                result["total_gb"] = total_gb
                result["left_gb"] = round(total_gb - used_gb, 4)
                result["data_percent"] = round((used_gb / total_gb) * 100, 2) if total_gb > 0 else 0
                result["status"] = "success"
            
            browser.close()
            return result
    except ImportError:
        log("Playwright package not installed")
        return {"hostname": platform.node(), "status": "no_playwright", "message": "Playwright package not installed"}
    except Exception as e:
        err = str(e)
        if "Executable doesn't exist" in err or "playwright install" in err:
            log("Chromium not installed for Playwright")
            return {"hostname": platform.node(), "status": "playwright_failed", "message": "Chromium not installed for Playwright"}
        log(f"Playwright error: {e}")
        return {"hostname": platform.node(), "status": "playwright_failed", "message": str(e)}


# ═══════════════════════════════════════════
# 5. MAIN
# ═══════════════════════════════════════════

def main():
    log("=" * 40)
    log("NSOC Data Usage Collector v3")
    log(f"Hostname: {platform.node()}")
    log(f"Date: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log("=" * 40)
    
    if "--install" in sys.argv or any(a.lower().startswith("/install") for a in sys.argv):
        install_scheduled_task()
        return
    
    # Step 1: Init GLPI
    log("Connecting to GLPI...")
    try:
        glpi_init()
        log("GLPI session OK")
    except Exception as e:
        log(f"GLPI connection failed: {e}")
        sys.exit(1)
    
    # Step 2: Find computer in GLPI
    hostname = None
    for i, arg in enumerate(sys.argv):
        if arg in ("--hostname", "-h") and i + 1 < len(sys.argv):
            hostname = sys.argv[i + 1]
    
    if not hostname:
        hostname = platform.node()
    
    log(f"Searching GLPI for: {hostname}")
    computer_id, computer_name = glpi_search_computer(hostname)
    if not computer_id:
        log(f"PC '{hostname}' NOT found in GLPI")
        sys.exit(1)
    log(f"Found: {computer_name} (ID: {computer_id})")
    
    # Step 3: Scrape DU portal — try HTTP, Selenium, Edge headless, Playwright
    log("Scraping DU portal...")
    du_data = get_du_usage_urllib()
    
    if du_data["status"] != "success":
        log(f"HTTP direct failed ({du_data['status']}), trying Selenium Edge...")
        du_data = get_du_usage_selenium()
        if du_data["status"] == "success":
            log(f"Selenium result: {du_data['used_gb']}GB / {du_data['total_gb']}GB ({du_data['data_percent']}%)")
    
    if du_data["status"] != "success":
        log(f"Selenium failed ({du_data['status']}), trying Edge headless dump-dom...")
        du_data = get_du_usage_with_edge()
        if du_data["status"] == "success":
            log(f"Edge result: {du_data['used_gb']}GB / {du_data['total_gb']}GB ({du_data['data_percent']}%)")
    
    if du_data["status"] != "success":
        log("Edge failed, trying Playwright fallback...")
        du_data = get_du_usage_playwright()
        if du_data["status"] == "success":
            log(f"Playwright result: {du_data['used_gb']}GB / {du_data['total_gb']}GB")
        else:
            log(f"All methods failed: {du_data['status']}")
    
    # Determine comment based on failure reason
    comment = ""
    if du_data["status"] == "playwright_failed":
        comment = du_data.get("message", "Playwright/Chromium execution failed")
    elif du_data["status"] == "no_edge":
        comment = "Edge not found, Playwright failed"
    elif du_data["status"] in ("timeout", "error"):
        comment = f"Scraping failed: {du_data.get('status', 'unknown')}"
    
    # Step 4: Update GLPI — delete existing entries then create fresh
    log("Updating GLPI custom fields...")
    try:
        # Search for existing entries by computer_id
        existing_entries = glpi_search_plugin_by_items_id(computer_id)
        if existing_entries:
            count = len(existing_entries)
            log(f"Found {count} existing entry/entries for computer #{computer_id}, deleting...")
            for entry in existing_entries:
                entry_id = entry.get("id") or entry.get("3")
                if entry_id:
                    log(f"Deleting existing plugin field #{entry_id} (items_id={computer_id})...")
                    glpi_delete_plugin(entry_id)
        else:
            log(f"No existing entries found for computer #{computer_id}, creating fresh...")
        
        # Always create fresh entry
        glpi_create_plugin(
            computer_id,
            du_data["used_gb"],
            du_data["total_gb"],
            du_data["data_percent"],
            du_data.get("msisdn", ""),
            comment,
            used_display=du_data.get("_used_display"),
            total_display=du_data.get("_total_display"),
        )
        log("Created new plugin field entry")
    except Exception as e:
        log(f"GLPI update failed: {e}")
        sys.exit(1)
    
    # Output
    if not SILENT:
        print()
        print(json.dumps({
            "hostname": du_data["hostname"],
            "computer_id": computer_id,
            "computer_name": computer_name,
            "msisdn": du_data.get("msisdn", ""),
            "total_gb": du_data["total_gb"],
            "used_gb": du_data["used_gb"],
            "left_gb": du_data["left_gb"],
            "data_percent": du_data["data_percent"],
            "status": du_data["status"],
        }, indent=2))
    
    log("Done OK")


if __name__ == "__main__":
    main()
