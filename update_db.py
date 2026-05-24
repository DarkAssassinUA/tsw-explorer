#!/usr/bin/env python3
import os
import re
import sys
import json
import argparse
from datetime import datetime

# Database files in the same directory
DATA_FILE = 'tsw_data.json'
LOCO_FILE = 'tsw_locomotives.json'

def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[+] Saved updates to {filepath}")

def extract_paks(text):
    # Match any valid .pak file name (alphanumeric, hyphens, underscores)
    matches = re.findall(r'([\w\-]+\.pak)', text, re.IGNORECASE)
    
    # Normalise keys (lowercase) and save original casing as values
    unique_paks = {}
    for match in matches:
        unique_paks[match.strip().lower()] = match.strip()
    return unique_paks

def get_latest_steam_build():
    import requests
    url = "https://api.steamcmd.net/v1/info/3656800"
    print(f"[*] Fetching latest build info from: {url}")
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            app_id = '3656800'
            if 'data' in data and app_id in data['data']:
                app_info = data['data'][app_id]
                if 'depots' in app_info and 'branches' in app_info['depots'] and 'public' in app_info['depots']['branches']:
                    public_branch = app_info['depots']['branches']['public']
                    build_id = public_branch.get('buildid')
                    time_updated = public_branch.get('timeupdated')
                    
                    update_date = None
                    if time_updated:
                        update_date = datetime.fromtimestamp(int(time_updated)).strftime('%d.%m.%Y')
                        
                    return build_id, update_date
    except Exception as e:
        print(f"[!] Error fetching latest build from steamcmd.net: {e}")
    return None, None

def scrape_steamdb_auto(build_id):
    import requests
    url = f"https://steamdb.info/patchnotes/{build_id}/"
    print(f"[*] Attempting to automatically scrape SteamDB patch notes: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://steamdb.info/'
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200 and "Cloudflare" not in r.text:
            return r.text
        
        # Try with cloudscraper
        try:
            import cloudscraper
            scraper = cloudscraper.create_scraper()
            r = scraper.get(url, timeout=10)
            if r.status_code == 200 and "Cloudflare" not in r.text:
                return r.text
        except Exception as cs_err:
            print(f"[!] cloudscraper challenge failed: {cs_err}")
            
    except Exception as e:
        print(f"[!] Network error trying to scrape SteamDB: {e}")
        
    return None

def get_manual_input(build_id):
    if not sys.stdin.isatty():
        print("[!] Error: Cloudflare blocked automatic scraping, and stdin is not interactive (cannot prompt for manual copy-paste).")
        sys.exit(1)
        
    url = f"https://steamdb.info/patchnotes/{build_id}/"
    print("\n" + "="*80)
    print(f" [!] CLOUDFLARE BLOCKED AUTOMATIC ACCESS TO STEAMDB (or build not yet cached)")
    print("="*80)
    print(f"Please follow these quick steps to update your database:")
    print(f" 1. Open this URL in your web browser:")
    print(f"    {url}")
    print(" 2. Press Ctrl+A (select all) and COPY the page content, or just copy the file list table.")
    print(" 3. PASTE the copied content below and press ENTER twice (or Ctrl+D / Ctrl+Z + Enter) to finish:")
    print("="*80)
    
    lines = []
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            # Finish on double empty line or double Enter
            if line.strip() == "" and len(lines) > 0 and lines[-1].strip() == "":
                break
            lines.append(line)
        except KeyboardInterrupt:
            print("\n[!] Cancelled by user.")
            sys.exit(1)
            
    return "".join(lines)

def update_database(pak_map, patch_date):
    print(f"[*] Commencing database update for patch date: {patch_date}...")
    updated_items = []
    
    for db_path in [DATA_FILE, LOCO_FILE]:
        if not os.path.exists(db_path):
            print(f"[!] Warning: Database file {db_path} not found.")
            continue
            
        data = load_json(db_path)
        modified = False
        
        for item in data:
            req_file = item.get('required_file')
            if req_file:
                # Clean up filename for comparison
                req_file_clean = req_file.strip().lower()
                
                # Check if this pak is in the updated list
                if req_file_clean in pak_map:
                    old_date = item.get('update_date')
                    if old_date != patch_date:
                        item['update_date'] = patch_date
                        modified = True
                        updated_items.append({
                            'title': item['title'],
                            'type': item.get('type', 'DLC'),
                            'file': req_file,
                            'old_date': old_date,
                            'new_date': patch_date
                        })
        
        if modified:
            save_json(db_path, data)
            
    return updated_items

def main():
    parser = argparse.ArgumentParser(description="TSW 6 Patch Database Updater")
    parser.add_argument('--build', type=str, help="Manual Steam Build ID (e.g. 23195318)")
    parser.add_argument('--date', type=str, help="Manual patch date (format: DD.MM.YYYY)")
    parser.add_argument('--file', type=str, help="Path to local file containing copied SteamDB page text")
    args = parser.parse_args()

    build_id = args.build
    patch_date = args.date
    content = None

    print("=== TSW 6 Patch Database Auto-Updater ===")

    # 1. Resolve Build ID and Date
    if not build_id:
        print("[*] Detecting latest Train Sim World 6 build programmatically...")
        detected_build, detected_date = get_latest_steam_build()
        if detected_build:
            build_id = detected_build
            if not patch_date and detected_date:
                patch_date = detected_date
            print(f"[+] Detected Build ID: {build_id} (Date: {patch_date})")
        else:
            print("[!] Failed to auto-detect build. You can provide it manually via --build <id>.")
            sys.exit(1)

    if not patch_date:
        # Fallback to today's date if not specified and not detected
        patch_date = datetime.today().strftime('%d.%m.%Y')
        print(f"[*] No patch date provided. Defaulting to today: {patch_date}")

    # 2. Get Changed Files Content
    if args.file:
        print(f"[*] Reading copied SteamDB content from file: {args.file}")
        if os.path.exists(args.file):
            with open(args.file, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            print(f"[!] Error: File {args.file} does not exist.")
            sys.exit(1)
    else:
        # Try automatic scraping
        content = scrape_steamdb_auto(build_id)
        
        # Fallback to manual pasting if scrape failed
        if not content:
            content = get_manual_input(build_id)

    # 3. Extract updated .pak files
    if not content or content.strip() == "":
        print("[!] Error: No content to parse.")
        sys.exit(1)

    pak_map = extract_paks(content)
    print(f"[+] Successfully extracted {len(pak_map)} unique .pak files from the update files list.")
    
    if len(pak_map) == 0:
        print("[!] No .pak files found in the content. Nothing to update.")
        sys.exit(0)

    # 4. Perform updates
    updated_items = update_database(pak_map, patch_date)

    # 5. Output Summary
    print("\n" + "="*80)
    print(f" DATABASE UPDATE COMPLETE. Total DLCs updated: {len(updated_items)}")
    print("="*80)
    
    if updated_items:
        for idx, item in enumerate(updated_items, 1):
            print(f" {idx}. [{item['type']}] {item['title']}")
            print(f"    File: {item['file']}")
            print(f"    Date: {item['old_date']} -> {item['new_date']}")
            print("-"*50)
    else:
        print(" [~] No files matched our database required_files or dates were already up to date.")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
