import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from scrapers.base_scraper import BaseScraper
from bs4 import BeautifulSoup

class CekResiScraper(BaseScraper):
    def __init__(self):
        self.url = "https://cekresi.com/"

    def _detect_courier(self, resi: str) -> str:
        resi = resi.strip()
        if resi.startswith(('JX', 'JP')):        return "J&T Express"
        if resi.startswith(('JT',)) or (resi.startswith(('3', '8')) and len(resi) >= 11): return "J&T Cargo"
        if resi.startswith(('TJ', '01', '88', 'JNA')): return "JNE"
        if resi.startswith(('00', 'SG', 'P')):   return "SICEPAT"
        if resi.upper().startswith('SPX'):        return "SPX Express"
        if resi.startswith(('SHP', 'NL', 'NV')): return "Ninja Xpress"
        if resi.startswith('LP'):                 return "Lion Parcel"
        if resi.startswith('P2'):                 return "Pos Indonesia"
        return ""

    async def handle_ads(self, page):
        """Tutup iklan/popup dengan cepat, tidak block lama."""
        try:
            for selector in ['#dismiss-button', '.dismiss-button', '#close-button', '[aria-label="Close"]']:
                try:
                    btn = page.locator(selector).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(timeout=1000)
                except:
                    pass
            # Cek frame iklan
            for frame in page.frames:
                for selector in ['#dismiss-button', '.dismiss-button']:
                    try:
                        btn = await frame.query_selector(selector)
                        if btn and await btn.is_visible():
                            await btn.click()
                    except:
                        pass
        except:
            pass

    async def track(self, resi: str, courier: str = None) -> dict:
        resi = resi.strip()
        target_courier = courier or self._detect_courier(resi)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
                '--no-sandbox', '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
            ])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1366, 'height': 768}
            )
            page = await context.new_page()

            try:
                # 1. Buka halaman
                await page.goto(self.url, wait_until="domcontentloaded", timeout=30000)

                # 2. Isi nomor resi
                await page.wait_for_selector('#noresi', timeout=10000)
                await page.fill('#noresi', resi)

                # 3. Klik cek
                await page.click('#cekresi')
                await asyncio.sleep(1)
                await self.handle_ads(page)

                # 4. Pilih kurir
                try:
                    await page.wait_for_selector('a.btn', timeout=10000)
                    if target_courier:
                        btn = page.locator(f'a.btn:has-text("{target_courier}")').first
                        if await btn.count() > 0:
                            await btn.click()
                        else:
                            await page.locator('a.btn').first.click()
                    else:
                        await page.locator('a.btn').first.click()
                except:
                    pass

                await asyncio.sleep(1)
                await self.handle_ads(page)

                # 5. Tunggu hasil — coba beberapa selector
                result_found = False
                for selector in ['.alert-success', '.tracking-result', 'table.table', '#hasil']:
                    try:
                        await page.wait_for_selector(selector, timeout=20000)
                        result_found = True
                        break
                    except PlaywrightTimeout:
                        continue

                if not result_found:
                    # Fallback: tunggu network idle dan coba baca apapun yang ada
                    try:
                        await page.wait_for_load_state('networkidle', timeout=10000)
                    except:
                        pass

                # 6. Expand history jika ada
                try:
                    expand_btn = page.get_by_text("Lihat perjalanan paket").first
                    if await expand_btn.count() > 0:
                        await expand_btn.click()
                        await asyncio.sleep(1)
                except:
                    pass

                # 7. Parse hasil
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')

                # Parse history dari tabel
                history = []
                for table in soup.find_all('table'):
                    text = table.get_text().lower()
                    if "tanggal" in text and "keterangan" in text:
                        for row in table.find_all('tr'):
                            cols = row.find_all('td')
                            if len(cols) >= 2:
                                date = cols[0].get_text(strip=True)
                                desc = cols[1].get_text(strip=True)
                                if "tanggal" in date.lower():
                                    continue
                                if date and desc:
                                    history.append({"date": date, "description": desc})
                        if history:
                            break

                # Parse status
                status = "Unknown"
                status_box = soup.select_one('.alert-success')
                if status_box:
                    status = status_box.get_text(strip=True)
                elif history:
                    status = history[0]['description']

                await browser.close()

                if not history and status == "Unknown":
                    return self.error_response("Tidak ada data tracking ditemukan")

                return self.format_response(status, history)

            except Exception as e:
                try:
                    await browser.close()
                except:
                    pass
                return self.error_response(str(e))
