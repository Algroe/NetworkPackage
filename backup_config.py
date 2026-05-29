import os
import sys
import json
import argparse
import getpass
from datetime import datetime
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter

INVENTORY_FILE = 'switch_inventory.json'
BACKUP_DIR_NAME = 'Backups'

def load_inventory(file_path):
    """Loads inventory and maps hostnames to IP addresses."""
    inventory_map = {}
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            for item in data:
                hostname = item.get('hostname')
                ip = item.get('ip_address')
                if hostname and ip:
                    inventory_map[hostname] = ip
    except FileNotFoundError:
        pass  # It's okay if the file doesn't exist, we just won't have tab completion
    except json.JSONDecodeError:
        print(f"Warning: Could not parse {file_path}. Invalid JSON.")
    return inventory_map

def get_credentials():
    """Prompts the user for SSH credentials securely."""
    print("\n--- Device Authentication ---")
    username = input("Username: ")
    password = getpass.getpass("Password: ")
    secret = getpass.getpass("Enable Secret (Leave blank if same as password): ")
    
    if not secret:
        secret = password
        
    return username, password, secret

def backup_switch(ip, username, password, secret, expected_hostname=None):
    """Connects to the switch and downloads the running config."""
    device = {
        'device_type': 'cisco_ios',
        'host': ip,
        'username': username,
        'password': password,
        'secret': secret
    }

    print(f"\nConnecting to {ip}...")
    try:
        with ConnectHandler(**device) as net_connect:
            net_connect.enable()
            
            # Get actual hostname from the prompt if expected_hostname is not provided
            prompt_str = net_connect.find_prompt()
            actual_hostname = prompt_str.strip('#> ')
            switch_name = expected_hostname if expected_hostname else actual_hostname
            
            print(f"Fetching running configuration for {switch_name}...")
            running_config = net_connect.send_command("show running-config")
            
            # Create directory
            backup_dir = os.path.join(BACKUP_DIR_NAME, switch_name)
            os.makedirs(backup_dir, exist_ok=True)
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{switch_name}_backup_{timestamp}.txt"
            filepath = os.path.join(backup_dir, filename)
            
            with open(filepath, 'w') as f:
                f.write(running_config)
                
            print(f"[SUCCESS] Backup saved to {filepath}")
            
    except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
        print(f"[FAILED] Could not connect to {ip}: {e}")
    except Exception as e:
        print(f"[FAILED] An error occurred with {ip}: {e}")

def main():
    # Setup Argument Parser
    parser = argparse.ArgumentParser(description="Backup Cisco Switch Configurations")
    parser.add_argument("ips", nargs="*", help="List of IP addresses to backup (space-separated)")
    args = parser.parse_args()

    inventory_map = load_inventory(INVENTORY_FILE)
    target_devices = []  # List of tuples: (ip, expected_hostname)

    if args.ips:
        # IPs were passed as arguments
        for ip in args.ips:
            # Try to find the hostname for this IP in the inventory, otherwise default to None
            hostname = next((name for name, inv_ip in inventory_map.items() if inv_ip == ip), None)
            target_devices.append((ip, hostname))
    else:
        # No IPs passed, prompt using prompt_toolkit for tab completion
        hostnames = list(inventory_map.keys())
        completer = WordCompleter(hostnames, ignore_case=True, sentence=True, match_middle=True)
        selected_input = prompt("Enter Switch Hostname or IP (Tab to complete): ", completer=completer).strip()
        
        if selected_input in inventory_map:
            target_devices.append((inventory_map[selected_input], selected_input))
        elif selected_input:
            # Treat the input as an IP address if not found in inventory
            target_devices.append((selected_input, None))

    if not target_devices:
        print("No valid targets provided. Exiting.")
        sys.exit(0)

    # Get Credentials once for the batch
    username, password, secret = get_credentials()

    # Loop over and backup each switch
    for ip, hostname in target_devices:
        backup_switch(ip, username, password, secret, hostname)

if __name__ == "__main__":
    main()