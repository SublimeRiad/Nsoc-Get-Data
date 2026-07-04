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

import sys, json, os, re, time, subprocess, tempfile, platform, datetime
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
    
    # We'll use a self-contained approach: write a tiny JS that runs via Edge
    # Edge can be launched with --headless --dump-dom to get the page content
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
            "--headless",
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
            # Maybe it redirected to a login page - try with user data dir
            log(f"Empty page ({len(html) if html else 0} chars). Trying with user profile...")
            
            # Get the current Windows user's Edge profile
            user_profile = os.environ.get("USERPROFILE", "C:\\Users\\Default")
            user_data_dir = os.path.join(user_profile, "AppData", "Local", "Microsoft", "Edge", "User Data")
            
            cmd = [
                edge_path,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={user_data_dir}",
                "--virtual-time-budget=20000",
                "http://mydata.du.ae/",
                "--dump-dom",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            html = result.stdout
        
        log(f"Page loaded: {len(html)} chars")
        debug(f"HTML snippet: {html[:300]}")
        
        # Extract data usage - format: "1.85 GB/15.00 GB" or similar
        # Find any pattern like "X.XX GB / Y.YY GB" with any whitespace
        usage_match = re.search(r"(\d+[\.,]?\d*)\s*[Gg][Bb]\s*[\s]*/\s*(\d+[\.,]?\d*)\s*[Gg][Bb]", html)
        if not usage_match:
            # Try "X.XXGB / Y.YYGB" without spaces
            usage_match = re.search(r"(\d+[\.,]?\d*)[Gg][Bb]\s*/\s*(\d+[\.,]?\d*)[Gg][Bb]", html)
        if not usage_match:
            # Try "X.XX / Y.YY GB" where context is data usage
            usage_match = re.search(r"(\d+[\.,]?\d*)\s*/\s*(\d+[\.,]?\d*)\s*[Gg][Bb]", html)
            if usage_match:
                # Also find total
                total_match = re.search(r"(?:out of|Total|total)\s*(\d+[\.,]?\d*)\s*[Gg][Bb]", html)
                if total_match:
                    # Handle case where used/total are separate matches
                    used = float(usage_match.group(1).replace(",", "."))
                    total = float(total_match.group(1).replace(",", "."))
                    output["used_gb"] = used
                    output["total_gb"] = total
                    output["left_gb"] = round(total - used, 2)
                    output["data_percent"] = round((used / total) * 100, 2) if total > 0 else 0
                    output["status"] = "success"
                    log(f"Data: {used}GB / {total}GB ({output['data_percent']}%)")
                    return output
        if not usage_match:
            # Try percentage pattern
            pct_match = re.search(r"(\d+[\.,]?\d*)\s*%", html)
            if pct_match:
                output["data_percent"] = float(pct_match.group(1).replace(",", "."))
                # Find any GB number for total
                gb_match = re.findall(r"(\d+[\.,]?\d*)\s*[Gg][Bb]", html)
                if gb_match:
                    output["total_gb"] = float(gb_match[-1].replace(",", "."))
                    output["used_gb"] = round(output["total_gb"] * output["data_percent"] / 100, 2)
                    output["left_gb"] = round(output["total_gb"] - output["used_gb"], 2)
                    output["status"] = "success"
                    log(f"Data (from %): {output['used_gb']}GB / {output['total_gb']}GB ({output['data_percent']}%)")
                    return output
        
        if usage_match:
            used_raw = usage_match.group(1).replace(",", ".")
            total_raw = usage_match.group(2).replace(",", ".")
            used = float(used_raw)
            total = float(total_raw)
            output["used_gb"] = used
            output["total_gb"] = total
            output["left_gb"] = round(total - used, 2)
            output["data_percent"] = round((used / total) * 100, 2) if total > 0 else 0
            output["status"] = "success"
            log(f"Data: {used}GB / {total}GB ({output['data_percent']}%)")
        
        # Try phone number extraction
        phone_match = re.search(r"\+971[\s-]?\d+", html)
        if phone_match:
            output["msisdn"] = phone_match.group(0)
            log(f"Phone: {output['msisdn']}")
        
        if usage_match:
            return output
        
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
    conn = http.client.HTTPSConnection("nsoc.aiootech.com", context=ctx)
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

def glpi_get_plugin_data(computer_id):
    try:
        r = glpi_request("GET", f"/apirest.php/PluginFieldsComputerdata?items_id={computer_id}")
        if isinstance(r, list) and len(r) > 0:
            return r[0]
    except:
        pass
    return None

def glpi_update_plugin(plugin_id, used_gb, total_gb, percent, msisdn=""):
    now = datetime.datetime.now().strftime("%m/%d/%Y %H:%M")
    glpi_request("PUT", f"/apirest.php/PluginFieldsComputerdata/{plugin_id}", {
        "input": [{
            "id": plugin_id,
            "datafield": json.dumps({
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "data_percent": round(percent, 1),
                "last_check": now
            }),
            "executiontimefield": now,
        }]
    })

def glpi_create_plugin(computer_id, used_gb, total_gb, percent, msisdn=""):
    now = datetime.datetime.now().strftime("%m/%d/%Y %H:%M")
    glpi_request("POST", "/apirest.php/PluginFieldsComputerdata", {
        "input": [{
            "items_id": computer_id,
            "itemtype": "Computer",
            "plugin_fields_containers_id": 12,
            "entities_id": 0,
            "datafield": json.dumps({
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "data_percent": round(percent, 1),
                "last_check": now
            }),
            "executiontimefield": now,
        }]
    })


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
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("http://mydata.du.ae", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(7000)
            
            text = page.inner_text("body")
            
            result = {"hostname": platform.node(), "msisdn": "", "total_gb": 0, "used_gb": 0, "left_gb": 0, "data_percent": 0, "status": "failed"}
            
            usage_match = re.search(r"(\d+[\.,]?\d*)\s*GB\s*/\s*(\d+[\.,]?\d*)\s*GB", text)
            phone_match = re.search(r"\+971\s?\d+", text)
            
            if phone_match:
                result["msisdn"] = phone_match.group(0)
            
            if usage_match:
                used = float(usage_match.group(1).replace(",", "."))
                total = float(usage_match.group(2).replace(",", "."))
                result.update({"used_gb": used, "total_gb": total, "left_gb": round(total - used, 2), "data_percent": round((used / total) * 100, 2) if total > 0 else 0, "status": "success"})
            
            browser.close()
            return result
    except ImportError:
        log("Playwright not installed")
        return {"hostname": platform.node(), "status": "no_playwright", "message": "Install playwright: pip install playwright && playwright install chromium"}


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
    
    # Step 3: Scrape DU with Edge (fallback to Playwright)
    log("Scraping DU portal...")
    du_data = get_du_usage_with_edge()
    
    if du_data["status"] in ("success", "partial"):
        log(f"Edge result: {du_data['used_gb']}GB / {du_data['total_gb']}GB ({du_data['data_percent']}%)")
    elif du_data["status"] == "no_edge":
        log("Edge not available, trying Playwright fallback...")
        du_data = get_du_usage_playwright()
        if du_data["status"] == "success":
            log(f"Playwright result: {du_data['used_gb']}GB / {du_data['total_gb']}GB")
    else:
        log(f"Scrape failed: {du_data['status']}")
    
    # Step 4: Update GLPI
    log("Updating GLPI custom fields...")
    try:
        existing = glpi_get_plugin_data(computer_id)
        if existing and existing.get("id"):
            glpi_update_plugin(existing["id"], du_data["used_gb"], du_data["total_gb"], du_data["data_percent"], du_data.get("msisdn", ""))
            log(f"Updated plugin field #{existing['id']}")
        else:
            glpi_create_plugin(computer_id, du_data["used_gb"], du_data["total_gb"], du_data["data_percent"], du_data.get("msisdn", ""))
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
