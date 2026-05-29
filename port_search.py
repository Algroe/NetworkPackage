import json
import sys
import getpass
import re
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException

INVENTORY_FILE = 'switch_inventory.json'

def load_inventory(file_path=INVENTORY_FILE):
    """Loads the switch inventory from the JSON file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading inventory: {e}")
        sys.exit(1)

def get_credentials():
    """Prompts the user for SSH credentials securely."""
    print("\n--- Device Authentication ---")
    username = input("Username: ")
    password = getpass.getpass("Password: ")
    secret = getpass.getpass("Enable Secret (Leave blank if same as password): ")
    
    if not secret:
        secret = password
        
    return username, password, secret

def normalize_mac(mac):
    """Strips formatting from MAC addresses and standardizes to xxxx.xxxx.xxxx."""
    clean_mac = re.sub(r'[^a-fA-F0-9]', '', mac).lower()
    # If the MAC is extracted from DHCP, it might have '01' prepended (hardware type Ethernet)
    if len(clean_mac) == 14 and clean_mac.startswith('01'):
        clean_mac = clean_mac[2:]
    
    if len(clean_mac) == 12:
        return f"{clean_mac[0:4]}.{clean_mac[4:8]}.{clean_mac[8:12]}"
    return mac

def search_mac(net_connect, search_target_mac):
    """Searches the MAC address table for a specific MAC."""
    target_mac = normalize_mac(search_target_mac)
    try:
        output = net_connect.send_command("show mac address-table", use_textfsm=True)
        if isinstance(output, list):
            for entry in output:
                dest_mac = entry.get('destination_address')
                if dest_mac and normalize_mac(dest_mac) == target_mac:
                    return [entry.get('destination_port')]
    except Exception as e:
        pass
    return []

def search_ip(net_connect, target_ip):
    """Searches DHCP bindings for an IP, extracts the MAC, and searches the MAC table."""
    try:
        output = net_connect.send_command("show ip dhcp binding")
        target_mac = None
        # Parse raw output to find the row with our IP
        for line in output.splitlines():
            if target_ip in line:
                parts = line.split()
                if len(parts) >= 2:
                    target_mac = parts[1] # Usually the Client-ID / Hardware address
                    break
        
        if target_mac:
            return search_mac(net_connect, target_mac)
    except Exception as e:
        pass
    return []

def search_vlan(net_connect, target_vlan):
    """Searches interface status for ports assigned to a specific VLAN."""
    results = []
    try:
        output = net_connect.send_command("show interfaces status", use_textfsm=True)
        if isinstance(output, list):
            for entry in output:
                port_vlan = str(entry.get('vlan') or entry.get('vlan_id')).strip()
                if port_vlan == str(target_vlan):
                    results.append(entry.get('port'))
    except Exception as e:
        pass
    return results

def search_description(net_connect, target_desc):
    """Searches interface descriptions for a matching substring."""
    results = []
    try:
        output = net_connect.send_command("show interfaces description", use_textfsm=True)
        if isinstance(output, list):
            for entry in output:
                port_desc = str(entry.get('desc') or entry.get('description') or "").strip()
                if target_desc.lower() in port_desc.lower():
                    results.append(entry.get('port'))
    except Exception as e:
        pass
    return results

def perform_search(choice, search_val, username, password, secret, inventory):
    """Executes the search across the inventory and returns the matching ports."""
    if choice == '1': search_func = search_mac
    elif choice == '2': search_func = search_ip
    elif choice == '3': search_func = search_vlan
    elif choice == '4': search_func = search_description
    else: return []

    all_matches = []
    for device in inventory:
        ip = device.get('ip_address')
        hostname = device.get('hostname', ip)
        
        device_params = {
            'device_type': 'cisco_ios',
            'host': ip,
            'username': username,
            'password': password,
            'secret': secret,
            'timeout': 5,
            'session_log': None
        }
        
        try:
            with ConnectHandler(**device_params) as net_connect:
                net_connect.enable()
                ports = search_func(net_connect, search_val)
                
                if ports:
                    # MAC and IP searches aim for a single result output format
                    if choice in ['1', '2']:
                        print(f"\n[MATCH FOUND] {hostname} ({ip}) -> Port: {ports[0]}")
                        all_matches.append((hostname, ip, ports[0]))
                    else:
                        # VLAN and Description searches return multiple lists
                        print(f"\n[MATCH FOUND] {hostname} ({ip})")
                        for p in ports:
                            print(f"  - {p}")
                            all_matches.append((hostname, ip, p))

        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            print(f"  [!] Failed to connect to {hostname} ({ip}): {e}")
            
    return all_matches

def interactive_search_menu(inventory, username, password, secret):
    """Displays interactive menus for scope and criteria, then executes the search."""
    print("\n--- Scope of Search ---")
    print("1. Search ALL switches")
    print("2. Search a SPECIFIC switch")
    
    scope_choice = input("\nSelect an option (1-2) [1]: ").strip() or '1'
    
    if scope_choice == '2':
        hostnames = [dev.get('hostname', dev.get('ip_address')) for dev in inventory]
        completer = WordCompleter(hostnames, ignore_case=True, sentence=True, match_middle=True)
        selected_host = prompt("\nEnter Switch Hostname (Tab to complete): ", completer=completer).strip()
        
        filtered_inventory = [dev for dev in inventory if dev.get('hostname') == selected_host or dev.get('ip_address') == selected_host]
        if not filtered_inventory:
            print(f"Error: '{selected_host}' not found in inventory. Exiting.")
            return None
        inventory = filtered_inventory

    print("\n--- Network Port Search ---")
    print("1. Search by MAC Address")
    print("2. Search by IP Address (DHCP Binding)")
    print("3. Search by VLAN")
    print("4. Search by Port Description")
    
    choice = input("\nSelect search criteria (1-4): ").strip()
    
    if choice == '1':
        search_val = input("Enter MAC Address (e.g., 0011.2233.4455): ").strip()
    elif choice == '2':
        search_val = input("Enter IP Address (e.g., 10.1.10.50): ").strip()
    elif choice == '3':
        search_val = input("Enter VLAN ID (e.g., 10): ").strip()
    elif choice == '4':
        search_val = input("Enter Port Description (e.g., Uplink, PC): ").strip()
    else:
        print("Invalid choice. Exiting.")
        return None

    print(f"\nSearching {len(inventory)} switch(es)...")
    return perform_search(choice, search_val, username, password, secret, inventory)

def main():
    inventory = load_inventory()
    if not inventory:
        print("No devices found in inventory.")
        return

    username, password, secret = get_credentials()
    
    all_matches = interactive_search_menu(inventory, username, password, secret)
    
    if all_matches is not None and not all_matches:
        print("\nNo matching ports found across the inventory.")

if __name__ == "__main__":
    main()