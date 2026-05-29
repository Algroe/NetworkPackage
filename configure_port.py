import sys
import json
import getpass
import os
import logging
from datetime import datetime
from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException

# Import the backup function from your existing backup script
from backup_config import backup_switch

INVENTORY_FILE = 'switch_inventory.json'

# Set up logging
LOG_DIR = os.path.join("Log", "configure_port")
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"configure_port_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(filename=log_file, level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

def load_inventory(file_path=INVENTORY_FILE):
    """Loads inventory and maps hostnames to IP addresses."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
            return {item['hostname']: item['ip_address'] for item in data if 'hostname' in item and 'ip_address' in item}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading inventory: {e}")
        logging.error(f"Error loading inventory: {e}")
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

def get_description_for_vlan(vlan):
    """Returns the appropriate port description based on the assigned VLAN."""
    if vlan == "10":
        return "Management"
    elif vlan == "12":
        return "PC"
    elif vlan == "13":
        return "Printer"
    else:
        return "Configured by Automation"

def main():
    # 1. Load Data and Get Credentials
    inventory_map = load_inventory()
    hostnames = list(inventory_map.keys())
    username, password, secret = get_credentials()

    logging.info("Starting port configuration script.")
    print("\n--- Port Configuration ---")
    print("1. Search for ports to configure")
    print("2. Manual entry")
    
    choice = input("\nSelect an option (1-2): ").strip()
    target_ports = []
    
    if choice == '1':
        try:
            from port_search import interactive_search_menu, load_inventory as ps_load_inventory
        except ImportError:
            print("[!] Error: Could not import port_search.py. Ensure it is in the same directory.")
            logging.error("Could not import port_search.py.")
            return
            
        inventory = ps_load_inventory()

        all_matches = interactive_search_menu(inventory, username, password, secret)
        
        if all_matches is None:
            return

        if not all_matches:
            print("\nNo matching ports found. Exiting.")
            logging.info("No matching ports found during search.")
            return
            
        target_ports = all_matches
        logging.info(f"Search found {len(target_ports)} matching port(s).")
        
    elif choice == '2':
        # 2. Collect Configuration Inputs
        completer = WordCompleter(hostnames, ignore_case=True, sentence=True, match_middle=True)
        selected_host = prompt("\nEnter Switch Hostname (Tab to complete): ", completer=completer).strip()

        if selected_host not in inventory_map:
            print(f"Error: '{selected_host}' not found in inventory.")
            logging.warning(f"Host '{selected_host}' not found in inventory.")
            return

        target_ip = inventory_map[selected_host]
        target_port = input(f"Enter port on {selected_host} (e.g. Gi1/0/1): ").strip()
        target_ports.append((selected_host, target_ip, target_port))
        logging.info(f"Manual entry selected for {selected_host} ({target_ip}) on port {target_port}.")
    else:
        print("Invalid choice. Exiting.")
        logging.warning(f"Invalid option selected: {choice}")
        return

    if not target_ports:
        print("\nNo targets selected. Exiting.")
        logging.info("No targets selected. Exiting.")
        return

    new_vlan = input(f"\nEnter new VLAN for the {len(target_ports)} targeted port(s): ").strip()
    if not new_vlan:
        print("No VLAN provided. Exiting.")
        logging.info("No VLAN provided. Exiting.")
        return

    port_description = get_description_for_vlan(new_vlan)

    bounce_choice = input("\nDo you want to bounce (shutdown / no shutdown) the configured ports? (y/n): ").strip().lower()
    bounce_ports = bounce_choice == 'y'

    print("\n[PREVIEW] The following changes will be made:")
    for selected_host, target_ip, target_port in target_ports:
        print(f"  - {selected_host} ({target_ip}) Port: {target_port} -> VLAN {new_vlan} (Desc: '{port_description}')")

    if input("\nProceed with backup and configuration for all ports? (y/n): ").strip().lower() != 'y':
        print("Aborted.")
        logging.info("User aborted before configuration.")
        return

    backed_up_hosts = set()

    for selected_host, target_ip, target_port in target_ports:
        print(f"\n" + "="*50)
        print(f"Target: {selected_host} ({target_ip}) - Port: {target_port}")
        logging.info(f"Applying configuration to {selected_host} ({target_ip}) on port {target_port} - VLAN: {new_vlan}, Bounce: {bounce_ports}")
        
        # 3. Perform Pre-Change Backup
        if target_ip not in backed_up_hosts:
            print("\n--- Initiating Pre-Change Backup ---")
            logging.info(f"Initiating Pre-Change Backup for {target_ip}.")
            backup_switch(target_ip, username, password, secret, selected_host)
            backed_up_hosts.add(target_ip)
        else:
            print("\n--- Pre-Change Backup already completed for this host ---")
    
        # 4. Apply Configuration Changes
        print("\n--- Applying Configuration Changes ---")
        device = {
            'device_type': 'cisco_ios',
            'host': target_ip,
            'username': username,
            'password': password,
            'secret': secret,
        }
    
        try:
            with ConnectHandler(**device) as net_connect:
                net_connect.enable()
                
                # Pre-validation for Trunk/Uplink labels
                desc_output = net_connect.send_command(f"show interfaces {target_port} description")
                if "trunk" in desc_output.lower() or "uplink" in desc_output.lower() or "downlink" in desc_output.lower():
                    print(f"\n[!] WARNING: Port {target_port} on {selected_host} is currently labeled as a Trunk or Uplink.")
                    logging.warning(f"Port {target_port} on {selected_host} is labeled Trunk/Uplink. Prompting user for acknowledgment.")
                    ack = input("Modifying this port could cause network outages. Type AWKNOWLEDGE to accept risk and proceed: ").strip().upper()
                    if ack != 'AWKNOWLEDGE':
                        print(f"Skipping configuration for {target_port}.")
                        logging.info(f"User declined risk for {target_port} on {selected_host}. Skipping.")
                        continue

                # Build the list of commands to send
                commands = [
                    f"interface {target_port}",
                    f"switchport access vlan {new_vlan}",
                    f"description {port_description}",
                    f"authentication event server dead action authorize vlan {new_vlan}"
                ]
                
                if bounce_ports:
                    commands.extend(["shutdown", "no shutdown"])
                
                output = net_connect.send_config_set(commands)
                print(output)
                logging.info(f"Configuration output for {target_ip} port {target_port}:\n{output}")
                
                net_connect.send_command("write memory")
                print(f"\n[SUCCESS] Configuration applied and saved for {target_port}.")
                logging.info(f"Configuration applied and saved for {target_ip} port {target_port}.")
                
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
            print(f"\n[FAILED] Connection error while configuring {target_ip}: {e}")
            logging.error(f"Connection error while configuring {target_ip}: {e}")
        except Exception as e:
            print(f"\n[FAILED] An unexpected error occurred: {e}")
            logging.error(f"An unexpected error occurred for {target_ip}: {e}")

if __name__ == "__main__":
    main()