import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_auth():
    print("--- Testing Register ---")
    reg_data = {"username": "testuser", "password": "password123"}
    resp = requests.post(f"{BASE_URL}/auth/register", json=reg_data)
    print(f"Register Response: {resp.status_code} - {resp.json()}")

    print("\n--- Testing Login ---")
    login_data = {"username": "testuser", "password": "password123"}
    resp = requests.post(f"{BASE_URL}/auth/login", json=login_data)
    print(f"Login Response: {resp.status_code} - {resp.json()}")

    print("\n--- Testing List Users ---")
    resp = requests.get(f"{BASE_URL}/users")
    print(f"Users: {resp.json()}")

if __name__ == "__main__":
    try:
        test_auth()
    except Exception as e:
        print(f"Error: {e}")
        print("Pastikan server API berjalan di http://127.0.0.1:8000")
