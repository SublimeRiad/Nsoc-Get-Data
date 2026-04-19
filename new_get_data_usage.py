import subprocess
import sys
import json
import platform
import os

# ---------------------------------------------------------
# FONCTION D'AUTO-INSTALLATION SILENCIEUSE
# ---------------------------------------------------------
def setup_playwright():
    try:
        import playwright
    except ImportError:
        # On installe silencieusement (--quiet)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "--quiet"])
        # On installe le binaire sans afficher les logs de téléchargement
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# Exécuter l'installation sans rien afficher sur stdout
setup_playwright()

from playwright.sync_api import sync_playwright

def get_du_usage():
    output = {
        "hostname": platform.node(),
        "msisdn": " ",
        "total_gb": 0,
        "used_gb": 0,
        "left_gb": 0,
        "data_percent": 0,
        "status": "failed"
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0")
            page = context.new_page()

            api_payload = {}
            def capture_api(response):
                if "dashBoard/query" in response.url:
                    try:
                        api_payload['data'] = response.json()
                    except:
                        pass

            page.on("response", capture_api)
            page.goto("http://mydata.du.ae", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)

            msisdn = page.evaluate("() => window.localStorage.getItem('serviceNo')")
            
            if 'data' in api_payload:
                raw = api_payload['data']["resultBody"]["dashBoardValue"]
                total = float(raw["monthTotal"]) / 1024 / 1024
                used = float(raw["monthUsed"]) / 1024 / 1024
                left = float(raw["monthLeft"]) / 1024 / 1024

                output.update({
                    "msisdn": f"+971 {msisdn[2:4]} {msisdn[4:7]} {msisdn[7:]}" if msisdn else " ",
                    "total_gb": round(total, 2),
                    "used_gb": round(used, 2),
                    "left_gb": round(left, 2),
                    "data_percent": round((used / total) * 100, 2) if total > 0 else 0,
                    "status": "success"
                })

            browser.close()
    except Exception as e:
        output["message"] = str(e)

    return output

if __name__ == "__main__":
    result = get_du_usage()
    # On garantit que SEUL le JSON sort ici
    print(json.dumps(result))
