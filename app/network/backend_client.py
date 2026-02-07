import requests
import json
from app.config import BACKEND_URL

class BackendClient:
    def __init__(self, api_url=BACKEND_URL):
        self.api_url = api_url

    def send_document(self, document_dict: dict) -> bool:
        try:
            print(f"Sending to {self.api_url}...")
            headers = {'Content-Type': 'application/json'}
            response = requests.post(self.api_url, data=json.dumps(document_dict), headers=headers)

            if response.status_code in [200, 201]:
                print("✅ Success! Backend accepted the document.")
                return True
            else:
                print(f"❌ Failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            print(f"❌ Connection Error: {e}")
            return False