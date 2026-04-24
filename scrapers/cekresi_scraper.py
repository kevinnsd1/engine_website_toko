import asyncio
from playwright.async_api import async_playwright
from scrapers.base_scraper import BaseScraper
from bs4 import BeautifulSoup

class CekResiScraper(BaseScraper):
    def __init__(self):
        self.url = "https://cekresi.com/"

    async def track(self, resi: str, courier: str = None) -> dict:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1366, 'height': 768}
            )
            page = await context.new_page()
            
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
                
                # 1. Fill resi
                await page.wait_for_selector('#noresi', timeout=15000)
                await page.fill('#noresi', resi)
                
                # 2. Click Cek Resi
                await page.click('#cekresi')
                
                # 3. Handle ads
                await asyncio.sleep(2)
                await self.handle_ads(page)

                # 4. Select Courier
                try:
                    await page.wait_for_selector('a.btn', timeout=15000)
                    
                    target = courier or ""
                    if not target:
                        # Auto-detection logic including J&T Cargo
                        if resi.startswith(('JX', 'JP')): 
                            target = "J&T Express"
                        elif (resi.startswith(('3', '8')) and len(resi) >= 11) or resi.startswith('JT'):
                            target = "J&T Cargo"
                        elif resi.startswith(('TJ', '01', '88', 'JNA')): 
                            target = "JNE"
                        elif resi.startswith(('00', 'SG', 'P')): 
                            target = "SICEPAT"
                        elif resi.upper().startswith('SPX'): 
                            target = "SPX Express"
                        elif resi.startswith(('SHP', 'NL', 'NV')): 
                            target = "Ninja Xpress"
                        elif resi.startswith('LP'):
                            target = "Lion Parcel"
                        elif resi.startswith('P2'):
                            target = "Pos Indonesia"
                    
                    if target:
                        btn = page.locator(f'a.btn:has-text("{target}")').first
                        if await btn.count() > 0:
                            await btn.click()
                        else:
                            await page.click('a.btn:first-of-type')
                    else:
                        await page.click('a.btn:first-of-type')
                except:
                    pass

                # 5. Handle ads after courier click
                await asyncio.sleep(2)
                await self.handle_ads(page)

                # 6. Wait for result
                await page.wait_for_selector('.alert-success', timeout=30000)

                # 7. Expand History
                try:
                    expand_btn = page.get_by_text("Lihat perjalanan paket").first
                    if await expand_btn.count() > 0:
                        await expand_btn.click()
                        await asyncio.sleep(2)
                except:
                    pass

                # 8. Extract
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                history = []
                tables = soup.find_all('table')
                for table in tables:
                    text = table.get_text().lower()
                    if "tanggal" in text and "keterangan" in text:
                        rows = table.find_all('tr')
                        for row in rows:
                            cols = row.find_all('td')
                            if len(cols) >= 2:
                                date = cols[0].get_text(strip=True)
                                desc = cols[1].get_text(strip=True)
                                if "tanggal" in date.lower(): continue
                                if date and desc:
                                    history.append({"date": date, "description": desc})
                        if history: break
                
                status = "Unknown"
                status_box = soup.select_one('.alert-success')
                if status_box:
                    status = status_box.get_text(strip=True)
                elif history:
                    status = history[0]['description']
                
                await browser.close()
                return self.format_response(status, history)
                
            except Exception as e:
                await browser.close()
                return self.error_response(str(e))

    async def handle_ads(self, page):
        try:
            for frame in page.frames:
                for selector in ['#dismiss-button', '.dismiss-button', '#close-button']:
                    try:
                        btn = await frame.query_selector(selector)
                        if btn and await btn.is_visible():
                            await btn.click()
                    except:
                        pass
            
            for text in ["Tutup", "Close", "X"]:
                try:
                    btn = page.get_by_text(text, exact=False).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                except:
                    pass
        except:
            pass
