import json
import csv
import os

INVENTORY_FILE = 'switch_inventory.json'
CSV_EXPORT_FILE = 'switch_inventory.csv'

def export_to_csv(json_file=INVENTORY_FILE, csv_file=CSV_EXPORT_FILE):
    if not os.path.exists(json_file):
        print(f"Error: Could not find '{json_file}'. Please run the inventory collection script first.")
        return

    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
            
        if not data:
            print("The inventory JSON file is empty. Nothing to export.")
            return
            
        # Extract headers automatically from the keys of the first device entry
        headers = list(data[0].keys())
        
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(data)
            
        print(f"[SUCCESS] Exported {len(data)} device(s) to '{csv_file}'")
        
    except Exception as e:
        print(f"[FAILED] An error occurred during export: {e}")

if __name__ == "__main__":
    export_to_csv()