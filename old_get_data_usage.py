import json
import platform
from seleniumwire import webdriver
import sys
import os

# ------------------------
# 1) Get data via Selenium
# ------------------------
try:
    driver = webdriver.Chrome()
    driver.get("http://mydata.du.ae")

    total = 0
    used = 0
    left = 0
    msisdn = ""

    # Search for the network request with the data
    for request in driver.requests:
        if request.response and "dashBoard/query" in request.url:
            json_response = json.loads(request.response.body.decode("utf-8"))
            total = float(json_response["resultBody"]["dashBoardValue"]["monthTotal"]) / 1024 / 1024
            used = float(json_response["resultBody"]["dashBoardValue"]["monthUsed"]) / 1024 / 1024
            left = float(json_response["resultBody"]["dashBoardValue"]["monthLeft"]) / 1024 / 1024
            msisdn = driver.execute_script("return window.localStorage.getItem('serviceNo');")
            break

    driver.quit()

    # Format phone number and calculate percentage
    if msisdn:
        msisdn_formatted = f"+971 {msisdn[2:4]} {msisdn[4:7]} {msisdn[7:]}"
        data_percent = round((used / total) * 100, 2)
    else:
        msisdn_formatted = "Not Found"
        data_percent = 0
        total = 0
        used = 0
        left = 0

    # Store values in a dictionary
    output_values = {
        "hostname": platform.node(),
        "msisdn": msisdn_formatted,
        "total_gb": round(total, 2),
        "used_gb": round(used, 2),
        "left_gb": round(left, 2),
        "data_percent": data_percent
    }

    # Use sys.stdout.write to ensure only the JSON is printed to standard output
    sys.stdout.write(json.dumps(output_values, indent=4))
    
except Exception as e:
    # Use sys.stderr.write to print error messages to standard error
    error_output = {
        "error": True,
        "message": str(e)
    }
    sys.stderr.write(json.dumps(error_output, indent=4))
    sys.exit(1) # Exit with a non-zero code to signal an error
