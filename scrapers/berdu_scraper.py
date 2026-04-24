import asyncio
import re
from playwright.async_api import async_playwright
from scrapers.base_scraper import BaseScraper
from bs4 import BeautifulSoup

class BerduScraper(BaseScraper):
    def __init__(self):
        self.url = "https://berdu.id/cek-resi"

    async def track(self, resi: str, courier: str = None) -> dict:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            try:
                await page.goto(self.url, wait_until="networkidle")
                
                # Close ad if present
                try:
                    tutup_btn = await page.wait_for_selector('text="Tutup"', timeout=3000)
                    if tutup_btn:
                        await tutup_btn.click()
                except:
                    pass

                # Fill resi
                await page.fill('input.p1, input[placeholder="000123456"]', resi)
                
                # Handle Courier Selection
                if courier:
                    try:
                        await page.select_option('select', label=courier)
                    except:
                        try:
                            options = await page.query_selector_all('select option')
                            for opt in options:
                                text = await opt.inner_text()
                                if courier.lower() in text.lower():
                                    val = await opt.get_attribute('value')
                                    await page.select_option('select', value=val)
                                    break
                        except:
                            pass
                elif resi.startswith('JX'):
                    try:
                        await page.select_option('select', label='J&T')
                    except:
                        pass
                
                # Click Cek Resi - Use more reliable selector
                # We can use the button that contains the text
                btn = page.get_by_text("Cek Resi", exact=True).first
                await btn.click()
                
                # Wait for results or error
                try:
                    await page.wait_for_function(f"""
                        () => {{
                            const text = document.body.innerText;
                            return (text.includes('Resi') && !text.includes('BERDU_CONTOH')) || 
                                   text.includes('tidak ditemukan');
                        }}
                    """, timeout=25000)
                    
                    content_text = await page.inner_text('body')
                    
                    if "tidak ditemukan" in content_text.lower():
                        await browser.close()
                        return self.error_response("Nomor resi tidak ditemukan atau kurir tidak sesuai.")
                        
                except Exception as e:
                    content_text = await page.inner_text('body')
                    if "BERDU_CONTOH" in content_text:
                        await browser.close()
                        return self.error_response("Hanya menampilkan hasil demo. Resi mungkin belum terupdate.")
                    else:
                        await browser.close()
                        return self.error_response(f"Timeout atau error: {str(e)}")

                # Extract data
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                history = []
                timestamp_pattern = re.compile(r'^[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2} [ap]m$')
                
                all_divs = soup.find_all('div')
                for div in all_divs:
                    text = div.get_text(strip=True)
                    if timestamp_pattern.match(text):
                        parent = div.parent
                        p_text = parent.get_text(" | ", strip=True)
                        parts = p_text.split(" | ")
                        if len(parts) >= 2:
                            desc = " ".join(parts[1:])
                            if not any(h['date'] == parts[0] and h['description'] == desc for h in history):
                                history.append({
                                    "date": parts[0],
                                    "description": desc
                                })
                
                status = "Unknown"
                if history:
                    status = history[0]['description']
                
                await browser.close()
                return self.format_response(status, history)
                
            except Exception as e:
                await browser.close()
                return self.error_response(str(e))
