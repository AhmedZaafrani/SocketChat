import threading
import socket
import datetime
import json
import os
from ftplib import FTP
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer


server_socket = None
clients = []
lock = threading.Lock()
USERS_FILE = "users.json"
SERVER_IP = '172.20.10.2'
PORT = 12345
MAX_CONNECTIONS = 10
authorizer = None

def setup_server_FTP():
    global authorizer
    dict = load_users()
    authorizer = DummyAuthorizer()
    # Itera sulle coppie chiave-valore (username, password)
    for username, password in dict.items():
        authorizer.add_user(
            username=username,
            password=password,
            homedir="/Users/simo/Documents/GitHub/Senza nome/SocketChat/file_directory_ftp",
            perm="elradfmwMT"  # ogni lettera è un permesso
        )

    handler = FTPHandler
    handler.authorizer = authorizer

    server_FTP = FTPServer(("0.0.0.0", 12346), handler)
    server_FTP.serve_forever()

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)


def register_user(username, password):
    users = load_users()
    if username in users:
        return False, "Username già esistente"
    users[username] = password
    save_users(users)
    return True, "Registrazione completata"


def authenticate_user(username, password):
    users = load_users()
    if username not in users:
        return False, "Username non trovato"
    if users[username] != password:
        return False, "Password errata"
    return True, "Autenticazione riuscita"


def handle_client_connection(client, address):
    try:
        # Ricevi il comando iniziale
        data = client.recv(1024).decode('utf-8').strip()
        if not data:
            return

        print(f"Comando ricevuto da {address}: {data}")  # Debug

        if data.startswith("REGISTER:"):
            _, username, password = data.split(":", 2)
            success, message = register_user(username, password)
            client.send(message.encode('utf-8'))
            print(f"Registrazione: {username} - {message}")  # Debug
            if not success:
                client.close()
                return

            authorizer.add_user(
                username=username,
                password=password,
                homedir="/Users/simo/Documents/GitHub/Senza nome/SocketChat/file_directory_ftp",
                perm="elradfmwMT"  # ogni lettera è un permesso
            )

        elif data.startswith("LOGIN:"):
            _, username, password = data.split(":", 2)
            success, message = authenticate_user(username, password)
            client.send(message.encode('utf-8'))
            print(f"Login: {username} - {message}")  # Debug
            if not success:
                client.close()
                return
        else:
            client.send("Comando non valido".encode('utf-8'))
            client.close()
            return

        # Se arriviamo qui, l'utente è autenticato
        with lock:
            clients.append(client)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            messaggio_broadcast(f"{timestamp} - {username} si è unito alla chat", None)
            print(f"{username} si è unito alla chat")

        # Gestione normale della chat
        while True:
            try:
                message = client.recv(1024).decode('utf-8')
                if not message:
                    break
                if message == "closed connection":
                    break

                parts = message.split(" - ", 1)
                if len(parts) == 2:
                    timestamp, text = parts
                    messaggio_broadcast(f"{timestamp} - {username}: {text}", client)
                else:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    messaggio_broadcast(f"{timestamp} - {username}: {message}", client)

            except Exception as e:
                print(f"Errore con client {username}: {e}")
                break

    except Exception as e:
        print(f"Errore durante l'autenticazione: {e}")
    finally:
        with lock:
            if client in clients:
                clients.remove(client)
                messaggio_broadcast(f"{username} ha lasciato la chat", client)
                print(f"{username} ha lasciato la chat")
                client.close()


def listen_for_clients():
    while True:
        try:
            client, address = server_socket.accept()
            print(f"Nuova connessione da: {address}")
            client_thread = threading.Thread(target=handle_client_connection, args=(client, address))
            client_thread.start()
        except Exception as e:
            print(f"Errore nell'accettare connessioni: {e}")
            break


def messaggio_broadcast(message, sender_client):
    with open("chat_log.txt", "a", encoding="utf-8") as log_file:
        log_file.write(f"{message}\n")


    for client in clients:
        if client != sender_client:
            try:
                client.send(message.encode('utf-8'))
            except Exception as e:
                print(f"Errore nell'invio a un client: {e}")
                client.close()
                if client in clients:
                    clients.remove(client)


def start_server():
    global server_socket
    global authorizer

    # Crea il file users.json se non esiste
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w") as f:
            json.dump({}, f)

    # Avvia il server FTP in un thread separato
    server_ftp_thread = threading.Thread(target=setup_server_FTP)
    server_ftp_thread.daemon = True
    server_ftp_thread.start()

    # Avvia il distributore di file in un altro thread
    #distributor_thread = threading.Thread(target=file_distributor)
    #distributor_thread.daemon = True
    #distributor_thread.start()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((SERVER_IP, PORT))
    server_socket.listen(MAX_CONNECTIONS)
    print(f"Server in ascolto su {SERVER_IP}:{PORT}")

    listening_thread = threading.Thread(target=listen_for_clients)
    listening_thread.daemon = True
    listening_thread.start()

    try:
        while True:
            cmd = input("Server command (quit per uscire - send per inviare un messaggio globale a tutti i client collegati): ")
            if cmd.lower() == "quit":
                break
            elif cmd.lower() == "send":
                msg = input("Inserisci il messaggio da inviare (exit per uscire dalla modalità invio messaggio): ")
                if msg.lower() == ("exit"):
                   pass
                else:
                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    messaggio_broadcast(f"{timestamp} - Server: {msg}", None)
                    print("messaggio inviato!")

    except KeyboardInterrupt:
        pass
    finally:
        print("Chiusura server...")
        messaggio_broadcast("Server in chiusura...", None)
        server_socket.close()


if __name__ == "__main__":
    start_server()