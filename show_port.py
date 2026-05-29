import tkinter as tk
from tkinter import scrolledtext
import threading
from netmiko import ConnectHandler

class PortViewerApp:
    def __init__(self, root, port_list, username, password, secret):
        self.root = root
        self.port_list = port_list
        self.username = username
        self.password = password
        self.secret = secret
        self.current_index = 0
        
        self.root.title("Port Configuration Viewer")
        self.root.geometry("600x450")
        
        # Navigation Frame
        nav_frame = tk.Frame(root)
        nav_frame.pack(fill=tk.X, padx=10, pady=10)
        
        self.prev_btn = tk.Button(nav_frame, text="< Previous", command=self.go_prev)
        self.prev_btn.pack(side=tk.LEFT)
        
        self.lbl_status = tk.Label(nav_frame, text="", font=("Arial", 12, "bold"))
        self.lbl_status.pack(side=tk.LEFT, expand=True)
        
        self.next_btn = tk.Button(nav_frame, text="Next >", command=self.go_next)
        self.next_btn.pack(side=tk.RIGHT)
        
        # Text Area
        self.text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Courier", 12))
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.load_current()

    def go_prev(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.load_current()

    def go_next(self):
        if self.current_index < len(self.port_list) - 1:
            self.current_index += 1
            self.load_current()

    def update_ui_state(self, is_loading=False):
        hostname, ip, port = self.port_list[self.current_index]
        self.lbl_status.config(text=f"{hostname} - {port} ({self.current_index + 1} of {len(self.port_list)})")
        
        if is_loading:
            self.prev_btn.config(state=tk.DISABLED)
            self.next_btn.config(state=tk.DISABLED)
        else:
            self.prev_btn.config(state=tk.NORMAL if self.current_index > 0 else tk.DISABLED)
            self.next_btn.config(state=tk.NORMAL if self.current_index < len(self.port_list) - 1 else tk.DISABLED)

    def load_current(self):
        self.update_ui_state(is_loading=True)
        self.text_area.configure(state='normal')
        self.text_area.delete(1.0, tk.END)
        
        hostname, ip, port = self.port_list[self.current_index]
        
        # Start fetch in a background thread to keep the GUI responsive
        thread = threading.Thread(
            target=self.fetch_and_display, 
            args=(ip, port), 
            daemon=True
        )
        thread.start()

    def fetch_and_display(self, ip, port):
        def insert_safe(text):
            """Safely update the Tkinter Text widget from a background thread."""
            self.root.after(0, lambda: self.text_area.insert(tk.END, text))
            
        def finalize_safe():
            """Safely finalize the UI state from a background thread."""
            self.root.after(0, lambda: self.text_area.configure(state='disabled'))
            self.root.after(0, lambda: self.update_ui_state(is_loading=False))

        try:
            device = {
                'device_type': 'cisco_ios',
                'host': ip,
                'username': self.username,
                'password': self.password,
                'secret': self.secret,
                'timeout': 10
            }
            insert_safe(f"Establishing SSH connection to {ip}...\n")
            with ConnectHandler(**device) as net_connect:
                net_connect.enable()
                insert_safe(f"Connection successful. Fetching configuration for {port}...\n\n")
                
                output = net_connect.send_command(f"show running-config interface {port}")
                
                insert_safe("="*50 + "\n")
                insert_safe(output + "\n")
                insert_safe("="*50 + "\n")
                
        except Exception as e:
            insert_safe(f"\n[!] Error connecting or fetching data: {e}\n")
        finally:
            finalize_safe()

def show_port_gui(port_list, username, password, secret):
    root = tk.Tk()
    app = PortViewerApp(root, port_list, username, password, secret)
    root.mainloop()

if __name__ == "__main__":
    import sys
    import getpass
    
    if len(sys.argv) == 3:
        # Direct CLI override mode (e.g. python show_port.py 192.168.0.7 Gi1/0/1)
        cli_port_list = [(sys.argv[1], sys.argv[1], sys.argv[2])]
        show_port_gui(cli_port_list, input("Username: "), getpass.getpass("Password: "), getpass.getpass("Secret (Leave blank if same): "))
    else:
        # Interactive Search mode
        try:
            from port_search import load_inventory, interactive_search_menu, get_credentials
        except ImportError:
            print("[!] Error: Could not import port_search.py. Ensure it is in the same directory.")
            sys.exit(1)
            
        inventory = load_inventory()
        if not inventory:
            print("No devices found in inventory.")
            sys.exit(1)

        print("\n--- Network Port Configuration Viewer ---")
        username, password, secret = get_credentials()
        
        all_matches = interactive_search_menu(inventory, username, password, secret)
        
        if all_matches is None:
            sys.exit(1)

        if all_matches:
            ans = input(f"\nFound {len(all_matches)} matching port(s). View configuration in a popup window? (y/n): ").strip().lower()
            if ans == 'y':
                print(f"\nLaunching configuration viewer...")
                show_port_gui(all_matches, username, password, secret)
        else:
            print("\nNo matching ports found. Exiting.")