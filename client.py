import socket
import json
import threading
import uuid
import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime
import time



class MessagingApp:
    
    def __init__(self, root, discovery_port=5010):

        # Discovery port and multicast group
        self.discovery_port = discovery_port
        self.multicast_group = '224.1.1.1'

        # Discovery socket for server communication
        self.discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.discovery_socket.bind(('', self.discovery_port))
        
        # Join multicast group
        mreq = socket.inet_aton(self.multicast_group) + socket.inet_aton('0.0.0.0')
        self.discovery_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.discovery_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

        # Client socket for messages
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.client_socket.bind(('', 0))

        # Server connection data
        self.server_id = None
        self.server_address = None

        # Client identification
        self.id = str(uuid.uuid4())
        self.port = self.client_socket.getsockname()[1]
        self.username = ""

        # Connection monitoring
        self.last_heartbeat = time.time()
        self.is_connected = False
        self.reconnecting = False

        # UI setup
        self.root = root
        self.root.title("Instant Messenger")
        self.root.geometry("400x700")
        self.root.configure(bg='#E5DDD5')
        
        # Color scheme
        self.theme_colors = {
            'header_green': '#075E54',
            'header_dark_green': '#054C44',
            'chat_bg': '#E5DDD5',
            'text_primary': '#303030',
            'text_secondary': '#667781',
            'text_white': '#FFFFFF',
            'input_bg': '#FFFFFF'
        }
        
        self.create_interface()
        
        # Handle window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Start background threads
        threading.Thread(target=self.find_server, daemon=True).start()
        threading.Thread(target=self.receive_messages, daemon=True).start()
        threading.Thread(target=self.monitor_heartbeat, daemon=True).start()

    def create_interface(self):

        # Main container
        main_frame = tk.Frame(self.root, bg=self.theme_colors['chat_bg'])
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = tk.Frame(main_frame, bg=self.theme_colors['header_green'], height=60)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        header_content = tk.Frame(header_frame, bg=self.theme_colors['header_green'])
        header_content.pack(fill=tk.BOTH, padx=15, pady=10)
        
        title_label = tk.Label(header_content, text="💬 Group Chat", 
                              font=('Segoe UI', 16, 'bold'), 
                              fg=self.theme_colors['text_white'], 
                              bg=self.theme_colors['header_green'])
        title_label.pack(side=tk.LEFT)
        
        self.status_label = tk.Label(header_content, text="🔍 Connecting...", 
                                    font=('Segoe UI', 10), 
                                    fg=self.theme_colors['text_white'], 
                                    bg=self.theme_colors['header_green'])
        self.status_label.pack(side=tk.RIGHT)
        
        # Chat area
        chat_container = tk.Frame(main_frame, bg=self.theme_colors['chat_bg'])
        chat_container.pack(fill=tk.BOTH, expand=True)
        
        self.chat_display = scrolledtext.ScrolledText(
            chat_container, 
            wrap=tk.WORD, 
            height=20, 
            width=50,
            font=('Segoe UI', 11),
            bg=self.theme_colors['chat_bg'],
            fg=self.theme_colors['text_primary'],
            insertbackground=self.theme_colors['text_primary'],
            selectbackground=self.theme_colors['header_green'],
            relief=tk.FLAT,
            borderwidth=0,
            padx=10,
            pady=10,
            spacing1=5,
            spacing2=2,
            spacing3=5
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.chat_display.config(state='disabled')
        
        # Input area
        input_container = tk.Frame(main_frame, bg=self.theme_colors['input_bg'], height=70)
        input_container.pack(fill=tk.X, padx=10, pady=10)
        input_container.pack_propagate(False)
        
        input_inner = tk.Frame(input_container, bg=self.theme_colors['input_bg'])
        input_inner.pack(fill=tk.BOTH, padx=10, pady=10)

        # Message input
        self.message_input = tk.Entry(
            input_inner, 
            font=('Segoe UI', 12),
            bg=self.theme_colors['input_bg'],
            fg=self.theme_colors['text_primary'],
            insertbackground=self.theme_colors['text_primary'],
            relief=tk.FLAT,
            borderwidth=0
        )
        self.message_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.message_input.bind("<Return>", lambda event: self.send_message_from_ui())
        
        self.send_button = tk.Button(
            input_inner, 
            text="➤",
            command=self.send_message_from_ui,
            font=('Segoe UI', 16, 'bold'),
            bg=self.theme_colors['header_green'],
            fg=self.theme_colors['text_white'],
            activebackground=self.theme_colors['header_dark_green'],
            activeforeground=self.theme_colors['text_white'],
            relief=tk.FLAT,
            borderwidth=0,
            cursor='hand2',
            width=3,
            height=1
        )
        self.send_button.pack(side=tk.RIGHT)
        
        # Hover effects
        self.send_button.bind('<Enter>', lambda e: self.send_button.configure(bg=self.theme_colors['header_dark_green']))
        self.send_button.bind('<Leave>', lambda e: self.send_button.configure(bg=self.theme_colors['header_green']))

    def find_server(self):

        # Listen for heartbeats from leader
        self.display_message("🔍 Connecting to server...", "system")
        while True:
            response, address = self.discovery_socket.recvfrom(1024)
            data = json.loads(response.decode())
            
            # Accept both heartbeat and discover messages from leader
            if data["type"] in ["heartbeat", "discover"] and data.get("isLeader", False):
                server_id = data['id']
                
                # Update heartbeat time
                self.last_heartbeat = time.time()
                
                if self.server_id != server_id:
                    self.server_id = server_id
                    self.server_address = (address[0], data["port"])
                    self.is_connected = True
                    self.reconnecting = False
                    self.join_server()
                    self.status_label.config(text="🟢 Online")
                    self.display_message(f"✅ Connected to server", "system")

    def monitor_heartbeat(self):

        while True:
            time.sleep(5)  # Check every 5 seconds
            
            if self.is_connected and not self.reconnecting:
                time_since_heartbeat = time.time() - self.last_heartbeat
                
                # If no heartbeat for 15 seconds, consider server lost
                if time_since_heartbeat > 15:
                    self.is_connected = False
                    self.reconnecting = True
                    self.server_address = None
                    self.server_id = None
                    
                    # Update status and show reconnecting message
                    self.status_label.config(text="🔄 Reconnecting...")
                    self.display_message("🔌 Connection lost. Reconnecting to server...", "system")
                    print(f"Server connection lost after {time_since_heartbeat:.1f}s without heartbeat")

    def join_server(self):

        # Send JOIN request to leader server
        join_message = {
            "type": "join",
            "id": self.id,
            "port": self.port
        }
        self.client_socket.sendto(json.dumps(
            join_message).encode(), self.server_address)
        self.display_message("🔗 Joined chat!", "system")

    def send_message_from_ui(self):

        # Send message from UI
        message = self.message_input.get().strip()
        if message:
            if self.is_connected and not self.reconnecting:
                self.transmit_message(message)
                self.message_input.delete(0, tk.END)
                self.display_message(f"{message}", "own")
            else:
                self.display_message("❌ Cannot send message - not connected to server", "error")

    def transmit_message(self, message):

        # Send message to leader server
        if self.server_address and self.is_connected:
            try:
                msg = json.dumps({
                    "type": "message",
                    "id": self.id,
                    "text": message
                })
                self.client_socket.sendto(msg.encode(), self.server_address)
            except Exception as e:
                self.display_message(f"❌ Error sending message: {e}", "error")
                # Mark as disconnected if send fails
                self.is_connected = False
                self.reconnecting = True
                self.status_label.config(text="�� Reconnecting...")

    def receive_messages(self):

        # Listen for incoming messages from server
        while True:
            try:
                response, _ = self.client_socket.recvfrom(1024)
                data = json.loads(response.decode())

                if data["type"] == "welcome":
                    # Receive username from server after connection
                    self.username = data["name"]
                    self.display_message(f"🎉 Welcome to the chat!", "system")

                elif data["type"] == "message":
                    # Receive message from another client (forwarded by server)
                    sender_name = data.get("sender_name", "Unknown")
                    self.display_message(f"{data['text']}", "other", sender_name)

                elif data["type"] == "notice":
                    # System message (client joined/left)
                    self.display_message(f"🔔 {data['text']}", "system")

            except Exception as e:
                # Only show error if we're supposed to be connected
                if self.is_connected:
                    self.display_message(f"❌ Reception error: {e}", "error")
                    # Mark as disconnected if receive fails
                    self.is_connected = False
                    self.reconnecting = True
                    self.status_label.config(text="🔄 Reconnecting...")
                    self.display_message("🔌 Connection lost. Reconnecting to server...", "system")

    def on_close(self):

        # Send leave message to server when closing
        if self.server_address and self.is_connected:
            leave_message = {
                "type": "leave",
                "id": self.id
            }
            try:
                self.client_socket.sendto(json.dumps(
                    leave_message).encode(), self.server_address)
            except:
                pass  # Ignore errors when closing
        self.root.destroy()

    def display_message(self, message, message_type="normal", sender_name=""):

        timestamp = datetime.now().strftime("%H:%M")
        
        self.chat_display.config(state='normal')
        
        if message_type == "system":
            self.chat_display.insert(tk.END, f"\n", "normal")
            self.chat_display.insert(tk.END, f"  {message}  ", "system")
            self.chat_display.insert(tk.END, f"\n", "normal")
            
        elif message_type == "own":
            self.chat_display.insert(tk.END, f"\n", "normal")
            self.chat_display.insert(tk.END, f"                                    {message}", "own_message")
            self.chat_display.insert(tk.END, f" {timestamp}", "timestamp_own")
            self.chat_display.insert(tk.END, f"\n", "normal")
            
        elif message_type == "other":
            self.chat_display.insert(tk.END, f"\n", "normal")
            if sender_name:
                self.chat_display.insert(tk.END, f"{sender_name}\n", "sender_name")
            self.chat_display.insert(tk.END, f"{message}", "other_message")
            self.chat_display.insert(tk.END, f" {timestamp}", "timestamp_other")
            self.chat_display.insert(tk.END, f"\n", "normal")
            
        elif message_type == "error":
            self.chat_display.insert(tk.END, f"\n", "normal")
            self.chat_display.insert(tk.END, f"  ❌ {message}  ", "error")
            self.chat_display.insert(tk.END, f"\n", "normal")
        
        self.chat_display.see(tk.END)
        self.chat_display.config(state='disabled')
        
        # Configure message tags
        self.chat_display.tag_config("normal", foreground=self.theme_colors['text_primary'], font=('Segoe UI', 11))
        self.chat_display.tag_config("system", foreground=self.theme_colors['text_secondary'], font=('Segoe UI', 10), justify='center')
        self.chat_display.tag_config("own_message", foreground=self.theme_colors['text_primary'], font=('Segoe UI', 11), justify='right')
        self.chat_display.tag_config("other_message", foreground=self.theme_colors['text_primary'], font=('Segoe UI', 11), justify='left')
        self.chat_display.tag_config("sender_name", foreground=self.theme_colors['header_green'], font=('Segoe UI', 10, 'bold'), justify='left')
        self.chat_display.tag_config("timestamp_own", foreground=self.theme_colors['text_secondary'], font=('Segoe UI', 9), justify='right')
        self.chat_display.tag_config("timestamp_other", foreground=self.theme_colors['text_secondary'], font=('Segoe UI', 9), justify='left')
        self.chat_display.tag_config("error", foreground='#FF0000', font=('Segoe UI', 10), justify='center')


if __name__ == "__main__":

    # Start the application
    root = tk.Tk()
    app = MessagingApp(root)
    root.mainloop()
