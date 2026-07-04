#!/usr/bin/env python3
"""
NSOC Data Usage Collector
Scrape mydata.du.ae → push to GLPI PluginFieldsComputerdata
Usage: python get_data_usage.py [--install] [--hostname PC-XXX]
"""

import sys, json, os, re, time, datetime, subprocess, tempfile, platform, urllib.request, urllib.parse

# ── GLPI Config ──
GLPI_API = "https://nsoc.aiootech.com/apirest.php"
GLPI_APP_TOKEN = "ig5tWvB2NK5DkEacnySyiNWTjqEHp0calKi7okq7"
GLPI_USER_TOKEN = "vGmLoJ74Rs1wlvN9u9zq4bwYnTeKLAeaOpHzdeD6"

# ── DU Portal Config ──
DU_USER = "NOGC.IT.IBB@GMAIL.COM"
DU_PASS = "n5UhsG62Z2f4wU7"

SILENT = "-silent" in sys.argv or "--silent" in sys.argv

def log(msg):
    if not SILENT:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

# ═══════════════════════════════════════════
# 1. GLPI HELPERS
# ═══════════════════════════════════════════

def glpi_request(method, endpoint, data=None):
    """Call GLPI REST API and return parsed JSON."""
    import http.client
    import ssl

    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection("nsoc.aiootech.com", context=ctx)
    
    headers = {
        "App-Token": GLPI_APP_TOKEN,
        "Content-Type": "application/json",
    }
    
    # Init session or use session token
    if endpoint == "/apirest.php/initSession":
        headers["Authorization"] = f"user_token {GLPI_USER_TOKEN}"
    else:
        headers["Session-Token"] = glpi_request._session_token
    
    body = json.dumps(data).encode() if data else None
    conn.request(method, endpoint, body=body, headers=headers)
    resp = conn.getresponse()
    
    # Handle errors
    if resp.status >= 400:
        error_text = resp.read().decode()
        raise Exception(f"GLPI {resp.status}: {error_text[:200]}")
    
    result = json.loads(resp.read().decode())
    conn.close()
    return result

# Cache session token
glpi_request._session_token = None

def glpi_init():
    """Initialise session et retourne le token."""
    r = glpi_request("GET", "/apirest.php/initSession")
    glpi_request._session_token = r["session_token"]
    return r["session_token"]

def glpi_search_computer(hostname):
    """Cherche un PC par hostname dans GLPI. Retourne (id, name) ou None."""
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
    data = r.get("data", [])
    if not data:
        return None
    # Try exact match first
    for pc in data:
        if pc.get("1", "").lower() == hostname.lower():
            return pc.get("2"), pc.get("1", "")
    # Fallback: first result
    return data[0].get("2"), data[0].get("1", "")

def glpi_get_plugin_data(computer_id):
    """Récupère le PluginFieldsComputerdata existant."""
    try:
        r = glpi_request("GET", f"/apirest.php/PluginFieldsComputerdata?items_id={computer_id}")
        if isinstance(r, list) and len(r) > 0:
            return r[0]
        return None
    except:
        return None

def glpi_update_plugin(plugin_id, data_gb, percentage):
    """Met à jour le champ custom."""
    now = datetime.datetime.now().strftime("%m/%d/%Y %H:%M")
    payload = {
        "datafield": json.dumps({
            "total_gb": round(data_gb, 2),
            "data_percent": round(percentage, 1),
            "last_check": now
        }),
        "executiontimefield": now
    }
    r = glpi_request("PUT", f"/apirest.php/PluginFieldsComputerdata/{plugin_id}", payload)
    return r

def glpi_create_plugin(computer_id, data_gb, percentage):
    """Crée un nouveau PluginFieldsComputerdata."""
    now = datetime.datetime.now().strftime("%m/%d/%Y %H:%M")
    payload = {
        "items_id": computer_id,
        "itemtype": "Computer",
        "plugin_fields_containers_id": 14,
        "entities_id": 0,
        "datafield": json.dumps({
            "total_gb": round(data_gb, 2),
            "data_percent": round(percentage, 1),
            "last_check": now
        }),
        "executiontimefield": now
    }
    r = glpi_request("POST", "/apirest.php/PluginFieldsComputerdata", payload)
    return r

# ═══════════════════════════════════════════
# 2. DU SCRAPER (sans Playwright)
# ═══════════════════════════════════════════

def get_du_usage():
    """
    Scrape mydata.du.ae en utilisant curl (présent sur tous les PCs Windows).
    Retourne dict {total_gb, used_gb, left_gb, data_percent, msisdn, status}
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
    
    cookie_file = os.path.join(tempfile.gettempdir(), "du_cookies.txt")
    
    try:
        # Step 1: GET index → récupérer cookies + token
        cmd1 = [
            "curl", "-s", "-L", "-c", cookie_file,
            "https://mydata.du.ae/du/",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ]
        log("Fetching DU portal...")
        subprocess.run(cmd1, capture_output=True, text=True, timeout=30)
        
        # Step 2: POST login
        cmd2 = [
            "curl", "-s", "-L", "-b", cookie_file, "-c", cookie_file,
            "https://mydata.du.ae/du/api/v1/sessions",
            "-H", "Content-Type: application/json",
            "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "-d", json.dumps({
                "username": DU_USER,
                "password": DU_PASS,
                "deviceName": platform.node()
            })
        ]
        log("Logging in to DU...")
        resp = subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
        login_data = json.loads(resp.stdout) if resp.stdout else {}
        
        if not login_data.get("sessionId") and not login_data.get("token"):
            # Fallback: try extracting token from response
            log("Login response: " + resp.stdout[:200])
            return output
        
        session_id = login_data.get("sessionId") or login_data.get("token", "")
        
        # Step 3: GET data usage
        cmd3 = [
            "curl", "-s", "-L", "-b", cookie_file,
            "https://mydata.du.ae/du/api/v1/devices/" + urllib.parse.quote(platform.node()) + "/usage",
            "-H", "Authorization: Bearer " + session_id,
            "-H", "User-Agent: Mozilla/5.0"
        ]
        log("Fetching data usage...")
        resp = subprocess.run(cmd3, capture_output=True, text=True, timeout=30)
        usage_data = json.loads(resp.stdout) if resp.stdout else {}
        
        # Parse response (format may vary)
        if usage_data.get("dataUsedGb") is not None:
            output["used_gb"] = float(usage_data["dataUsedGb"])
            output["total_gb"] = float(usage_data.get("totalGb", 0))
            output["data_percent"] = float(usage_data.get("percentageUsed", 
                round(output["used_gb"] / output["total_gb"] * 100, 2) if output["total_gb"] > 0 else 0))
        elif usage_data.get("data") and usage_data["data"].get("usage"):
            # Alternative format
            u = usage_data["data"]["usage"]
            output["used_gb"] = float(u.get("used", 0))
            output["total_gb"] = float(u.get("total", 0))
            output["data_percent"] = float(u.get("percentage", 
                round(output["used_gb"] / output["total_gb"] * 100, 2) if output["total_gb"] > 0 else 0))
        
        output["left_gb"] = round(output["total_gb"] - output["used_gb"], 2)
        
        # Get MSISDN
        if login_data.get("msisdn"):
            output["msisdn"] = login_data["msisdn"]
        
        output["status"] = "success" if output["used_gb"] > 0 else "partial"
        
    except subprocess.TimeoutExpired:
        log("DU portal timeout")
        output["status"] = "timeout"
    except json.JSONDecodeError:
        log("Failed to parse DU response")
        output["status"] = "parse_error"
    except Exception as e:
        log(f"Error: {e}")
        output["status"] = "error"
        output["message"] = str(e)
    finally:
        # Cleanup cookie file
        try:
            os.remove(cookie_file)
        except:
            pass
    
    return output

# ═══════════════════════════════════════════
# 3. INSTALLER (Scheduled Task)
# ═══════════════════════════════════════════

def install_scheduled_task():
    """Crée une tâche planifiée Windows pour exécution quotidienne."""
    script_path = os.path.abspath(__file__)
    
    ps1 = f'''
$taskName = "NSOC Data Usage Collector"
$scriptPath = "{script_path}"
$action = New-ScheduledTaskAction -Execute "python.exe" -Argument "`"$scriptPath`" --silent"
$trigger = New-ScheduledTaskTrigger -Daily -At 08:00AM
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
Write-Host "Scheduled task installed: $taskName"
'''
    try:
        subprocess.run(["powershell", "-Command", ps1], check=True, capture_output=True, text=True, timeout=30)
        log("Scheduled task created successfully!")
        return True
    except subprocess.CalledProcessError as e:
        log(f"Failed to create task: {e.stderr[:200] if e.stderr else e}")
        return False
    except FileNotFoundError:
        log("PowerShell not found (not Windows?). Skipping task install.")
        return False

# ═══════════════════════════════════════════
# 4. MAIN
# ═══════════════════════════════════════════

def main():
    log("=" * 40)
    log("NSOC Data Usage Collector v2")
    log(f"Hostname: {platform.node()}")
    log(f"Date: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    log("=" * 40)
    
    # Install mode?
    if "--install" in sys.argv or "/install" in sys.argv.lower():
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
    
    # Step 2: Get computer ID
    hostname = None
    for i, arg in enumerate(sys.argv):
        if arg in ("--hostname", "-h", "/h") and i + 1 < len(sys.argv):
            hostname = sys.argv[i + 1]
            break
    
    if not hostname:
        hostname = platform.node()
    
    log(f"Searching GLPI for: {hostname}")
    try:
        pc_info = glpi_search_computer(hostname)
        if not pc_info:
            log(f"PC '{hostname}' NOT FOUND in GLPI")
            sys.exit(1)
        computer_id, computer_name = pc_info
        log(f"Found: {computer_name} (ID: {computer_id})")
    except Exception as e:
        log(f"GLPI search failed: {e}")
        sys.exit(1)
    
    # Step 3: Scrape DU
    log("Scraping DU portal...")
    du_data = get_du_usage()
    
    if du_data["status"] == "success" or du_data["status"] == "partial":
        log(f"DU Data: {du_data['used_gb']}GB / {du_data['total_gb']}GB ({du_data['data_percent']}%)")
    else:
        log(f"DU scrape: {du_data['status']}")
        # Still try to update GLPI with what we have
    
    # Step 4: Update GLPI PluginFieldsComputerdata
    log("Updating GLPI custom fields...")
    try:
        existing = glpi_get_plugin_data(computer_id)
        if existing and existing.get("id"):
            glpi_update_plugin(existing["id"], du_data["used_gb"], du_data["data_percent"])
            log(f"Updated plugin field #{existing['id']}")
        else:
            glpi_create_plugin(computer_id, du_data["used_gb"], du_data["data_percent"])
            log("Created new plugin field entry")
    except Exception as e:
        log(f"GLPI update failed: {e}")
        sys.exit(1)
    
    # Output JSON for caller (if not silent)
    if not SILENT:
        print()
        print(json.dumps({
            "hostname": du_data["hostname"],
            "computer_id": computer_id,
            "computer_name": computer_name,
            "msisdn": du_data["msisdn"],
            "total_gb": du_data["total_gb"],
            "used_gb": du_data["used_gb"],
            "left_gb": du_data["left_gb"],
            "data_percent": du_data["data_percent"],
            "status": du_data["status"],
        }, indent=2))
    
    log("Done ✓")

if __name__ == "__main__":
    main()
