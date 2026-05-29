import json
import getpass
import ipaddress # added to calculate ranges from CIDR notation
from datetime import datetime  # <--- Added for timestamping
from netmiko import ConnectHandler
import argparse

def get_ip_list():
        choice = input("Enter IPs by (L)ist or (R)ange? [L]: ").strip().upper()
        
        if choice == 'R':
            cidr = input("Enter CIDR block (e.g. 10.1.10.0/24): ").strip()
            try:
                # .hosts() automatically excludes network and broadcast addresses
                return [str(ip) for ip in ipaddress.IPv4Network(cidr).hosts()]
            except ValueError as e:
                print(f"Invalid CIDR: {e}")
                return []
        else:
            ips_input = input("Enter switch IP addresses (separated by commas): ")
            return [ip.strip() for ip in ips_input.split(",") if ip.strip()]
        
def get_switch_data():
    print("--- Cisco Inventory Collector (with Defaults) ---")
    
    # 1. Initial Setup
    #ips_input = input("Enter switch IP addresses (separated by commas): ")
    ip_list = get_ip_list()
    
    username = input("Username: ")
    password = getpass.getpass("Password: ")
    
    # Set a default site for the entire session
    default_site = input("Enter default Site Name (press Enter to skip): ").strip()
    # Capture the exact time for the 'last_inventoried' field
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Allowed roles for validation
    allowed_roles = ["Access", "Core", "Dist"]
    
    inventory = []

    for ip in ip_list:
        print(f"\n" + "="*50)
        print(f"Connecting to {ip}...")
        
        device_params = {
            'device_type': 'cisco_ios',
            'host': ip,
            'username': username,
            'password': password,
            'conn_timeout': 5
        }

        try:
            with ConnectHandler(**device_params) as net_connect:
                # Pull and parse 'show version'
                output = net_connect.send_command("show version", use_textfsm=True)
                # Strips whitespace first, then removes the Cisco prompt symbols
                hostname = net_connect.find_prompt().strip().rstrip('#').rstrip('>').strip()
                
                if isinstance(output, list) and len(output) > 0:
                    data = output[0]
                    model = data.get("hardware", "Unknown")
                    # Handle hardware being a list in some TextFSM templates
                    if isinstance(model, list): model = model[0]
                    version = data.get("version", "Unknown")
                    
                    raw_serial = data.get("serial", ["Unknown"])
                    serial_list = raw_serial if isinstance(raw_serial, list) else [raw_serial]
                    serial_list = [s for s in serial_list if s] or ["Unknown"]
                    is_stack = len(serial_list) > 1
                    stack_count = len(serial_list)
                    
                    uptime = data.get("uptime", "Unknown")
                    
                    # Grab total number of ports and available ports
                    total_ports_count = 0
                    total_available_ports_count = 0
                    try:
                        status_output = net_connect.send_command("show interfaces status", use_textfsm=True)
                        if isinstance(status_output, list):
                            for port in status_output:
                                status = str(port.get("status") or "").strip().lower()
                                total_ports_count += 1
                                if status in ["notconnect", "notconnected"]:
                                    total_available_ports_count += 1
                    except Exception as e:
                        print(f"  [!] Could not fetch interface status for {ip}: {e}")

                    # --- PREVIEW ---
                    print(f"\n[PARSED FROM {ip}]")
                    print(f"  Hostname: {hostname}")
                    print(f"  Model:    {model}")
                    print(f"  Firmware: {version}")
                    print(f"  Is Stack: {is_stack} (Count: {stack_count})")
                    print(f"  Serials:  {', '.join(serial_list)}")
                    print(f"  Total Ports: {total_ports_count}")
                    print(f"  Total Available Ports: {total_available_ports_count}")
                    print("-" * 30)

                    # --- SMART INPUTS ---
                    # Prompt for Site (Defaults to session site)
                    site_prompt = f"Site [{default_site}]: " if default_site else "Site: "
                    site_input = input(site_prompt).strip()
                    current_site = site_input if site_input else default_site
                    # Prompt for Location (Specific to this switch)
                    current_location = input(f"Location for {hostname}: ").strip()
                    # Role Validation Loop
                    while True:
                        role_input = input("Role (Access/Core/Dist) [Access]: ").strip()
                        
                        # Set default if empty
                        if not role_input:
                            current_role = "Access"
                            break
                        
                        # Validate against allowed list
                        if role_input in allowed_roles:
                            current_role = role_input
                            break
                        else:
                            print(f"!! Invalid Role. Please choose from: {', '.join(allowed_roles)}")

                    device_info = {
                        "hostname": hostname,
                        "ip_address": ip,
                        "is_stack": is_stack,
                        "stack_count": stack_count,
                        "serial": serial_list,
                        "model": model,
                        "firmware_version": version,
                        "uptime": uptime,
                        "total_ports": total_ports_count,
                        "total_available_ports": total_available_ports_count,
                        "last_inventoried": scan_time,
                        "site": current_site,
                        "location": current_location,
                        "role": current_role
                    }
                    inventory.append(device_info)
                    print(f"Added {hostname} to inventory.")
                
                else:
                    print(f"!! Error: Could not parse TextFSM for {ip}.")

        except Exception as e:
            print(f"!! Connection Failed for {ip}: {e}")

    # 2. Final JSON Export
    if inventory:
        filename = "switch_inventory.json"
        with open(filename, "w") as f:
            json.dump(inventory, f, indent=4)
        print(f"\n[DONE] {len(inventory)} devices exported to {filename}")
    else:
        print("\n[SKIP] No data collected; no file created.")

def update_inventory(filename="switch_inventory.json"):
    print(f"--- Updating Existing Inventory ({filename}) ---")
    try:
        with open(filename, 'r') as f:
            inventory = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading {filename}: {e}")
        return

    if not inventory:
        print("Inventory is empty. Nothing to update.")
        return

    username = input("Username: ")
    password = getpass.getpass("Password: ")
    scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for device in inventory:
        ip = device.get('ip_address')
        hostname = device.get('hostname', ip)
        if not ip:
            continue

        print(f"\n" + "="*50)
        print(f"Updating {hostname} ({ip})...")

        device_params = {
            'device_type': 'cisco_ios',
            'host': ip,
            'username': username,
            'password': password,
            'conn_timeout': 5
        }

        try:
            with ConnectHandler(**device_params) as net_connect:
                output = net_connect.send_command("show version", use_textfsm=True)
                if isinstance(output, list) and len(output) > 0:
                    data = output[0]
                    device['firmware_version'] = data.get("version", device.get("firmware_version"))
                    device['uptime'] = data.get("uptime", device.get("uptime"))
                    
                    # Update stack info on refresh
                    raw_serial = data.get("serial", device.get("serial", ["Unknown"]))
                    serial_list = raw_serial if isinstance(raw_serial, list) else [raw_serial]
                    serial_list = [s for s in serial_list if s] or ["Unknown"]
                    device['is_stack'] = len(serial_list) > 1
                    device['stack_count'] = len(serial_list)
                    device['serial'] = serial_list
                
                total_ports_count = 0
                total_available_ports_count = 0
                try:
                    status_output = net_connect.send_command("show interfaces status", use_textfsm=True)
                    if isinstance(status_output, list):
                        for port in status_output:
                            status = str(port.get("status") or "").strip().lower()
                            total_ports_count += 1
                            if status in ["notconnect", "notconnected"]:
                                total_available_ports_count += 1
                        device['total_ports'] = total_ports_count
                        device['total_available_ports'] = total_available_ports_count
                except Exception as e:
                    print(f"  [!] Could not fetch interface status for {ip}: {e}")

                device['last_inventoried'] = scan_time
                print(f"  [SUCCESS] Updated {hostname}.")
        except Exception as e:
            print(f"  [!] Connection/Update Failed for {ip}: {e}")

    with open(filename, "w") as f:
        json.dump(inventory, f, indent=4)
    print(f"\n[DONE] {len(inventory)} devices updated in {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cisco Switch Inventory Manager")
    parser.add_argument("-u", "--update", action="store_true", help="Update existing switch_inventory.json")
    args = parser.parse_args()

    if args.update:
        update_inventory()
    else:
        get_switch_data()