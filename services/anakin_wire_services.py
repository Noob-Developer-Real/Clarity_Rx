import requests
from django.conf import settings
import time


class AnakinWire:

    BASE_URL = "https://api.anakin.io/v1/wire"

    def __init__(self):
        self.headers = {
            "X-API-Key": settings.ANAKIN_API_KEY,
            "Content-Type": "application/json",
        }

    def execute(self, action_id, params):
        response = requests.post(
            f"{self.BASE_URL}/task",
            headers=self.headers,
            json={
                "action_id": action_id,
                "params": params,
            },
            timeout=30,
        )
    
        return response.json()

    def wait_for_result(self, job_id):

        for _ in range(60):

            response = requests.get(
                f"{self.BASE_URL}/jobs/{job_id}",
                headers=self.headers,
                timeout=30,
            )

            data = response.json()

            status = data.get("status")

            if status == "completed":
                return data

            if status == "failed":
                return None

            time.sleep(2)

        return None
