import socket
import threading
import json
import uuid
import time



class Server:
    
    def __init__(self):

        # Server attributes
        self.port = 5001
        self.multicast_group = '224.1.1.1'
        self.discovery_port = 5010
        
        # Get IP address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            self.ip = s.getsockname()[0]
            s.close()
        except:
            self.ip = "127.0.0.1"
            
        # Server ID using IP:Port
        self.id = f"{self.ip}:{self.port}"
        self.is_leader = False
        self.last_heartbeat = time.time()
        self.voted = False


        # Multicast discovery socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_socket.bind(('', self.port))
        self.discovery_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass  
        self.discovery_socket.bind(('', self.discovery_port))
        # Join multicast group
        mreq = socket.inet_aton(self.multicast_group) + socket.inet_aton('0.0.0.0')
        self.discovery_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.discovery_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)

        # group view
        self.clients = {}  # client_id: {ip, port, name}
        self.servers = {}  # server_id: {ip, port, isLeader}

    def multicast_server_leader(self):

        # Multicast that this server is the new leader
        msg = {
            "type": "leader",
            "id": self.id,
            "port": self.port
        }
        self.discovery_socket.sendto(json.dumps(
            msg).encode(), (self.multicast_group, self.discovery_port))
        print(f"Leader {self.id} announced.")

    def send_to_all_clients(self, message, sender):

        
        sender_name = self.clients[sender]["name"]
        message["sender_name"] = sender_name

        print(f"📨 [{sender_name}]: {message['text']}")
        print(f"   └─ Sending to {len(self.clients) - 1} other clients")

        for client_id, info in self.clients.items():
            if client_id != sender:
                try:
                    self.server_socket.sendto(json.dumps(
                        message).encode(), (info["ip"], info["port"]))
                except Exception as e:
                    print(f"❌ Send error to {client_id}: {e}")

    def send_system_message(self, message, exclude=None):

        
        target_count = len(self.clients) - (1 if exclude else 0)
        print(f"📢 System message: {message['text']}")
        print(f"   └─ Sending to {target_count} clients")
        
        for client_id, info in self.clients.items():
            if client_id != exclude:
                try:
                    self.server_socket.sendto(json.dumps(
                        message).encode(), (info["ip"], info["port"]))
                except Exception as e:
                    print(f"❌ Send error to {client_id}: {e}")

    def display_client_list(self):

        if not self.clients:
            print("👥 No clients connected")
            return
            
        print(f"\n👥 Connected Clients ({len(self.clients)}):")
        print("─" * 50)
        for i, (client_id, info) in enumerate(self.clients.items(), 1):
            print(f"  {i}. {info['name']} ({info['ip']}:{info['port']})")
        print("─" * 50)

    def display_server_status(self):

        print(f"\n🖥️  Server Status:")
        print("─" * 50)
        print(f"  Server ID: {self.id}")
        print(f"  Leader: {'✅ Yes' if self.is_leader else '❌ No'}")
        print(f"  Connected Clients: {len(self.clients)}")
        print(f"  Known Servers: {len(self.servers)}")
        print("─" * 50)

    def initiate_server_leader_election(self):

        # Start leader election with own token
        print(f"Server {self.id} starting leader election...")
        self.forward_server_token(self.id)

    def remove_dead_server_nodes(self):

        # Remove servers that haven't sent heartbeats for too long
        while True:
            time.sleep(5) 
            now = time.time()
            to_remove = []
            for server_id, info in list(self.servers.items()):
                if server_id == self.id:
                    continue
                last_hb = info.get("last_heartbeat", 0)
                time_since_last = now - last_hb
                # Remove if no activity for 20 seconds
                if time_since_last > 20:
                    print(f"❌ Removing dead server {server_id} ({info['ip']}:{info['port']}) from servers.")
                    to_remove.append(server_id)
            for server_id in to_remove:
                self.servers.pop(server_id, None)
            
            # Display current status every health check
            self.display_server_status()
            self.display_client_list()

    def forward_server_token(self, token_id):

        # Forward the election token in the ring
        sorted_servers = sorted(
            self.servers.values(), key=lambda x: x["id"])
        my_index = next((i for i, s in enumerate(
            sorted_servers) if s["id"] == self.id), None)
        if my_index is None:
            return
        
        print(f"Forwarding token {token_id}. Known servers: {len(sorted_servers)}")
        for s in sorted_servers:
            print(f"  - {s['id']} ({s['ip']}:{s['port']}) Leader: {s['isLeader']}")
        
        # Check whether a leader already exists
        existing_leader = next((s for s in sorted_servers if s["isLeader"] and s["id"] != self.id), None)
        if existing_leader:
            print(f"Leader already exists: {existing_leader['id']}. Not becoming leader.")
            return
        
        # If only one server in the ring, become leader immediately
        if len(sorted_servers) == 1:
            print("Only one server in the ring. I will become leader.")
            self.is_leader = True
            self.multicast_server_leader()
            threading.Thread(target=self.multicast_server_heartbeat, daemon=True).start()
            self.voted = True
            return
        # Otherwise forward token to next server
        for offset in range(1, len(sorted_servers)):
            next_index = (my_index + offset) % len(sorted_servers)
            next_server = sorted_servers[next_index]
            next_address = (next_server["ip"], next_server["port"])
            if next_server["id"] == self.id:
                # Only this server remaining
                print("No other reachable server. I will become leader.")
                self.is_leader = True
                self.multicast_server_leader()
                threading.Thread(target=self.multicast_server_heartbeat, daemon=True).start()
                self.voted = True
                return
            try:
                election_msg = {
                    "type": "election",
                    "token": token_id
                }
                self.server_socket.sendto(json.dumps(
                    election_msg).encode(), next_address)
                print(f"Election token forwarded to {next_server['id']}")
                return
            except Exception as e:
                print(f"Removing unreachable server {next_server['id']}: {e}")
                self.servers.pop(next_server["id"], None)
        # If no server is reachable, become leader
        print("No reachable server in the ring. I will become leader.")
        self.is_leader = True
        self.multicast_server_leader()
        threading.Thread(target=self.multicast_server_heartbeat, daemon=True).start()
        self.voted = True

    def multicast_server_discovery(self):

        # Regular multicast messages for server discovery
        while True:
            msg = {
                "type": "discover",
                "id": self.id,
                "port": self.port,
                "isLeader": self.is_leader
            }
            self.discovery_socket.sendto(json.dumps(
                msg).encode(), (self.multicast_group, self.discovery_port))
            time.sleep(5) 

    def multicast_server_heartbeat(self):

        # Only the leader sends regular heartbeats via multicast
        while self.is_leader:
            msg = {
                "type": "heartbeat",
                "id": self.id,
                "port": self.port
            }
            self.discovery_socket.sendto(json.dumps(
                msg).encode(), (self.multicast_group, self.discovery_port))
            print("Heartbeat sent by the leader.")
            time.sleep(5)

    def monitor_server_heartbeat(self):

        # Check regularly if heartbeat from leader is still being received
        while True:
            time.sleep(5)  
            # Only initiate election if we're not the leader and haven't received heartbeats
            if not self.is_leader and (time.time() - self.last_heartbeat > 15):
                print(f"Leader unresponsive for {time.time() - self.last_heartbeat:.1f}s. Initiating leader election.")
                self.initiate_server_leader_election()

    def listen_on_discovery_port(self):
        # Receiving Discovery, Heartbeat or Leader messages
        while True:
            message, address = self.discovery_socket.recvfrom(1024)
            data = json.loads(message.decode())
            server_id = data['id']
            server_ip = address[0]
            server_port = data['port']

            if data["type"] == "discover":
                # Search for an existing server with the same IP:Port
                existing_server = None
                for sid, info in self.servers.items():
                    if info["ip"] == server_ip and info["port"] == server_port:
                        existing_server = sid
                        break
                
                if existing_server:
                    # Update existing server
                    self.servers[existing_server]["id"] = server_id
                    self.servers[existing_server]["isLeader"] = data['isLeader']
                    self.servers[existing_server]["last_heartbeat"] = time.time()
                    print(f"Updated existing server: {server_ip}:{server_port}")
                    
                    # If it is a leader, also update self.last_heartbeat
                    if data['isLeader'] and server_id != self.id:
                        self.last_heartbeat = time.time()
                        print(f"Leader discovery received from {server_ip}:{server_port}")
                else:
                    # New server discovered
                    self.servers[server_id] = {
                        "id": server_id,
                        "ip": server_ip,
                        "port": server_port,
                        "isLeader": data['isLeader'],
                        "last_heartbeat": time.time()
                    }
                    print(f"Discovered new server: {server_ip}:{server_port}")
                    # Only start new leader election if no leader exists
                    if not self.is_leader and not any(info["isLeader"] for info in self.servers.values()):
                        print("New server discovered and no leader exists. Initiating leader election...")
                        self.initiate_server_leader_election()

            # Leader message
            elif data["type"] == "leader":
                # Leader was announced
                leader_id = server_id
                self.is_leader = (leader_id == self.id)
                self.voted = False
                print(f"Server {leader_id} has been elected as leader.")

                if leader_id in self.servers:
                    self.servers[leader_id]["isLeader"] = True
                else:
                    self.servers[leader_id] = {
                        "id": leader_id,
                        "ip": address[0],
                        "port": data["port"],
                        "isLeader": True,
                        "last_heartbeat": time.time()
                    }

            # Heartbeat message
            elif data["type"] == "heartbeat":
                if server_id != self.id:
                    self.last_heartbeat = time.time()
                    # Update heartbeat time for this server
                    if server_id in self.servers:
                        self.servers[server_id]["last_heartbeat"] = time.time()
                    else:
                        # Search for servers with the same IP:Port
                        existing_server = None
                        for sid, info in self.servers.items():
                            if info["ip"] == server_ip and info["port"] == server_port:
                                existing_server = sid
                                break
                        
                        if existing_server:
                            # Update existing server
                            self.servers[existing_server]["id"] = server_id
                            self.servers[existing_server]["last_heartbeat"] = time.time()
                        else:
                            # New server
                            self.servers[server_id] = {
                                "id": server_id,
                                "ip": server_ip,
                                "port": server_port,
                                "isLeader": False,
                                "last_heartbeat": time.time()
                            }
                    print(
                        f"Heartbeat received from leader {server_ip}:{server_port}.")

    def listen_on_server_client_port(self):

        # Receive messages from clients or election tokens
        while True:
            try:
                message, address = self.server_socket.recvfrom(1024)
                data = json.loads(message.decode())

                if data["type"] == "join":
                    # Client wants to join
                    client_id = data["id"]
                    client_ip = address[0]
                    client_port = data["port"]

                    if client_id not in self.clients:
                        client_number = len(self.clients) + 1
                        self.clients[client_id] = {
                            "id": client_id,
                            "ip": client_ip,
                            "port": client_port,
                            "name": f"Client {client_number}"
                        }
                        print(f"\n✅ {self.clients[client_id]['name']} connected from {client_ip}:{client_port}")
                        self.display_client_list()

                        # Reply to client with their name
                        welcome = {
                            "type": "welcome",
                            "name": f"Client {client_number}"
                        }
                        self.server_socket.sendto(json.dumps(
                            welcome).encode(), (client_ip, client_port))

                        # Notify other clients about join
                        notice = {
                            "type": "notice",
                            "text": f"Client {client_number} has joined the chat."
                        }
                        self.send_system_message(notice, exclude=client_id)

                elif data["type"] == "message":
                    # Message received from client
                    sender_id = data["id"]
                    text = data["text"]
                    sender_name = self.clients[sender_id]["name"]
                    print(f"\n💬 Message from {sender_name}: {text}")
                    self.send_to_all_clients(data, sender_id)

                elif data["type"] == "leave":
                    # Client has left the chat
                    client_id = data["id"]
                    if client_id in self.clients:
                        name = self.clients[client_id]["name"]
                        print(f"\n👋 {name} has left the chat.")
                        self.clients.pop(client_id)
                        self.display_client_list()

                        notice = {
                            "type": "notice",
                            "text": f"{name} has left the chat."
                        }
                        self.send_system_message(notice)

                elif data["type"] == "election":
                    # Election token received and processed
                    token_id = data["token"]
                    if not self.voted:
                        if token_id > self.id:
                            self.forward_server_token(token_id)
                            self.voted = True
                        elif token_id < self.id:
                            self.forward_server_token(self.id)
                            self.voted = True
                        elif token_id == self.id:
                            print("🎉 I was elected as leader!")
                            self.is_leader = True
                            self.multicast_server_leader()
                            threading.Thread(
                                target=self.multicast_server_heartbeat, daemon=True).start()
                            self.voted = True
                    else:
                        # Already voted, no re-broadcast/thread-start
                        pass

            except Exception as e:
                print(f"❌ Server error: {e}")

    def start_server_system(self):

        # Server startup and start parallel threads
        print("🚀 Starting Distributed Chat Server...")
        print("=" * 60)
        print(f"🖥️  Server ID: {self.id}")
        print(f"🌐 Server running on port {self.port}")
        print(f"🔍 Listening for discovery messages on port {self.discovery_port}")
        print(f"📡 Multicast group: {self.multicast_group}")
        print("=" * 60)

        threading.Thread(target=self.listen_on_server_client_port, daemon=True).start()
        threading.Thread(target=self.listen_on_discovery_port, daemon=True).start()
        threading.Thread(target=self.monitor_server_heartbeat, daemon=True).start()
        threading.Thread(target=self.multicast_server_discovery, daemon=True).start()
        threading.Thread(target=self.remove_dead_server_nodes, daemon=True).start()

        time.sleep(10)  # Time for discovery of other servers
        
        # Check if leader election is needed at startup
        if not self.is_leader and not any(info["isLeader"] for info in self.servers.values()):
            print("No leader found at startup. Initiating leader election...")
            self.initiate_server_leader_election()
        elif any(info["isLeader"] for info in self.servers.values()):
            leader = next(s for s in self.servers.values() if s["isLeader"])
            print(f"Leader already exists: {leader['id']}")

        # Display server status and client list
        print("\n✅ Server system started successfully!")
        print("📊 Initial status:")
        self.display_server_status()
        self.display_client_list()

        # Keep main thread alive
        while True:
            time.sleep(1)


if __name__ == "__main__":

    # Start the server
    server = Server()
    server.start_server_system()
