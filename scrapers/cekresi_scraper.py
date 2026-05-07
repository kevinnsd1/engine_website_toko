import asyncio
import requests
import re
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper

class CekResiScraper(BaseScraper):
    def __init__(self):
        self.base_url = "https://www.cekpengiriman.com"
        # We use a session to maintain cookies/headers if needed
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        })

    def _detect_courier(self, resi: str) -> str:
        resi = resi.strip().upper()
        if resi.startswith(('JX', 'JP')):        return "jnt"
        if resi.startswith(('JT',)) or (resi.startswith(('3', '8')) and len(resi) >= 11): return "jtcargo"
        if resi.startswith(('TJ', '01', '88', 'JNA')): return "jne"
        if resi.startswith(('00', 'SG', 'P')):   return "sicepat"
        if resi.startswith('SPX'):               return "spx"
        if resi.startswith(('SHP', 'NL', 'NV')): return "ninja"
        if resi.startswith('LP'):                return "lion"
        if resi.startswith('P2'):                return "pos"
        return ""

    def _fetch_sync(self, resi: str, courier: str) -> dict:
        try:
            url = f"{self.base_url}/cek-resi?resi={resi}&kurir={courier}"
            res = self.session.get(url, timeout=10)
            res.raise_for_status()
            
            # Extract token
            match = re.search(r'\"token\",\s*\"([a-f0-9]+)\"', res.text)
            if not match:
                return self.error_response("Token keamanan tidak ditemukan di cekpengiriman.com")
            
            token = match.group(1)
            api_url = f"{self.base_url}/wp-content/themes/simple/includes/widget/resultResi.php"
            files = {
                'token': (None, token),
                'resi': (None, resi),
                'kurir': (None, courier)
            }
            headers = {
                'Origin': self.base_url,
                'Referer': url,
                'X-Requested-With': 'XMLHttpRequest'
            }
            
            api_res = self.session.post(api_url, files=files, headers=headers, timeout=10)
            api_res.raise_for_status()
            html_result = api_res.text
            
            if "Kode resi tidak ditemukan" in html_result or "tidak terdaftar" in html_result.lower():
                return self.error_response("Resi tidak ditemukan atau belum terdaftar")
                
            soup = BeautifulSoup(html_result, 'html.parser')
            
            # Parse Status
            status = "Unknown"
            status_td = soup.find('td', string=re.compile(r'Status', re.I))
            if status_td:
                next_td = status_td.find_next_sibling('td')
                if next_td:
                    status = next_td.get_text(strip=True)
                    
            # Parse History
            history = []
            riwayat_header = soup.find('h4', string=re.compile(r'Riwayat Pengiriman', re.I))
            if riwayat_header:
                table = riwayat_header.find_next_sibling('table')
                if table:
                    for tr in table.find_all('tr'):
                        td = tr.find('td')
                        if td:
                            text = td.get_text(strip=True)
                            parts = text.split(' - ', 1)
                            if len(parts) == 2:
                                date_str, desc = parts
                                history.append({
                                    "date": date_str.strip(),
                                    "description": desc.strip()
                                })
                            else:
                                history.append({
                                    "date": "",
                                    "description": text
                                })
            
            if not history and status == "Unknown":
                return self.error_response("Gagal membaca hasil pelacakan dari cekpengiriman")
                
            return self.format_response(status, history)
            
        except requests.RequestException as e:
            return self.error_response(f"Terjadi kesalahan jaringan: {str(e)}")
        except Exception as e:
            return self.error_response(f"Kesalahan internal: {str(e)}")

    async def track(self, resi: str, courier: str = None) -> dict:
        resi = resi.strip()
        
        # Convert internal courier name to cekpengiriman code if possible
        target_courier = ""
        if courier:
            # simple mapping just in case
            c_lower = courier.lower()
            if "j&t" in c_lower and "cargo" not in c_lower: target_courier = "jnt"
            elif "j&t cargo" in c_lower: target_courier = "jtcargo"
            elif "jne" in c_lower: target_courier = "jne"
            elif "sicepat" in c_lower: target_courier = "sicepat"
            elif "shopee" in c_lower or "spx" in c_lower: target_courier = "spx"
            elif "ninja" in c_lower: target_courier = "ninja"
            elif "lion" in c_lower: target_courier = "lion"
            elif "pos" in c_lower: target_courier = "pos"
        
        if not target_courier:
            target_courier = self._detect_courier(resi)
            
        if not target_courier:
            return self.error_response("Kurir tidak terdeteksi")
            
        # Run synchronous requests code in a separate thread so it doesn't block the async event loop
        return await asyncio.to_thread(self._fetch_sync, resi, target_courier)
