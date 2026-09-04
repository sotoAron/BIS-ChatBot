import requests
import json

url = "http://localhost:8000/api/v1/chat"
headers = {"Content-Type": "application/json"}
data = {"message": "cuando son los examenes de aacsw?"}

response = requests.post(url, headers=headers, json=data)
print(response.json())
