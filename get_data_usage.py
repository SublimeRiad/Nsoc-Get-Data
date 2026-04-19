import subprocess
import sys
import json
import platform
import re
import os

# ---------------------------------------------------------
# CONFIGURATION DES CHEMINS (Crucial pour GLPI)
# ---------------------------------------------------------
BASE_DIR = "C:\\Dataupdate"
BROWSER_PATH = os.path.join(BASE_DIR, "pw-browsers")
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = BROWSER_PATH

if not os.path.exists(BASE_DIR):
    os.makedirs(BASE_DIR)

# ---------------------------------------------------------
# FONCTION D'AUTO-INSTALLATION
# ---------------------------------------------------------
def setup_playwright():
    try:
        import playwright
    except ImportError:
        # Installation silencieuse de la lib
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "--quiet"])
    
    # Installation forcée du navigateur dans notre dossier spécifique
    # On vérifie si le dossier existe déjà pour gagner du temps
    if not os.path.exists(BROWSER_PATH) or not os.listdir(BROWSER_PATH):
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True)

# Lancer l'installation/vérification
setup_playwright()

from playwright.sync_api import sync_playwright

# ---------------------------------------------------------
# LOGIQUE D'EXTRACTION (MÉTHODE VISUELLE + RÉSEAU)
# ---------------------------------------------------------
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
            # Lancement du navigateur pointant vers notre dossier fixe
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = context.new_page()
            
            # 1. Navigation vers le portail
            page.goto("http://mydata.du.ae", wait_until="networkidle", timeout=60000)
            
            # 2. Attente que la redirection (token) et le rendu soient finis
            page.wait_for_timeout(7000) 

            # 3. Extraction du texte complet pour Analyse Regex (Méthode la plus robuste)
            text_content = page.inner_text("body")
            
            # Recherche du format "X.XX GB / Y.YY GB" (vu sur ta capture)
            usage_match = re.search(r"(\d+[\.,]?\d*)\s*GB\s*/\s*(\d+[\.,]?\d*)\s*GB", text_content)
            
            # Recherche du numéro de téléphone (format +971...)
            msisdn_match = re.search(r"\+971\s?\d+", text_content)

            if usage_match:
                # Gestion des virgules possibles selon la langue
                used_raw = usage_match.group(1).replace(',', '.')
                total_raw = usage_match.group(2).replace(',', '.')
                
                used = float(used_raw)
                total = float(total_raw)
                left = round(total - used, 2)
                
                output.update({
                    "msisdn": msisdn_match.group(0) if msisdn_match else " ",
                    "total_gb": total,
                    "used_gb": used,
                    "left_gb": left,
                    "data_percent": round((used / total) * 100, 2) if total > 0 else 0,
                    "status": "success"
                })
            else:
                # Backup : Tentative via LocalStorage si le texte n'est pas rendu
                msisdn_storage = page.evaluate("() => window.localStorage.getItem('serviceNo')")
                if msisdn_storage:
                    output["msisdn"] = msisdn_storage
                    output["status"] = "partial_success_no_data"

            browser.close()

    except Exception as e:
        output["message"] = str(e)
        output["status"] = "error"

    return output

if __name__ == "__main__":
    # Sortie JSON propre pour PowerShell
    print(json.dumps(get_du_usage()))
