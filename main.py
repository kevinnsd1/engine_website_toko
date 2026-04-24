import asyncio
import argparse
import json
import sys
from scrapers.cekresi_scraper import CekResiScraper

async def track_with_failover(resi, courier=None):
    # Focus only on CekResiScraper as requested
    scraper = CekResiScraper()
    name = scraper.__class__.__name__
    print(f"Tracking with {name}...")
    try:
        result = await scraper.track(resi, courier)
        return result
    except Exception as e:
        print(f"{name} raised exception: {str(e)}")
        return {
            "success": False,
            "message": f"Scraper error: {str(e)}",
            "errors": [{name: str(e)}]
        }

async def main():
    parser = argparse.ArgumentParser(description="Shipping Tracking Scraper Engine")
    parser.add_argument("--resi", required=True, help="Receipt number (Nomor Resi)")
    parser.add_argument("--courier", help="Courier name (optional)")
    parser.add_argument("--json", action="store_true", help="Output only JSON")
    
    args = parser.parse_args()
    
    if not args.json:
        print(f"Tracking Resi: {args.resi} (Courier: {args.courier or 'AutoDetect'})")
    
    result = await track_with_failover(args.resi, args.courier)
    
    if args.json:
        print(json.dumps(result))
    else:
        print("\n--- TRACKING RESULT ---")
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
