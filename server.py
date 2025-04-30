import threading
import socket
import datetime
import time
import json
import os
from ftplib import FTP
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

server_socket = None
clients = []
active_users = {}  # username -> socket
lock = threading.Lock()
USERS_FILE = "users.json"
SERVER_IP = "0.0.0.0"
PORT = 12345
MAX_CONNECTIONS = 10
authorizer = None
server_FTP = None


def setup_server_FTP():
    global authorizer, server_FTP
    dict = load_users()
    authorizer = DummyAuthorizer()

    # Itera sulle coppie chiave-valore (username, password)
    for username, password in dict.items():
        # Crea la directory home se non esiste
        home_dir = "/Users/simo/Documents/GitHub/Senza nome/SocketChat/file_directory_ftp"
        if not os.path.exists(home_dir):
            try:
                os.makedirs(home_dir)
                print(f"Directory creata: {home_dir}")
            except Exception as e:
                print(f"Errore nella creazione della directory: {e}")

        # Aggiungi l'utente
        try:
            authorizer.add_user(
                username=username,
                password=password,
                homedir=home_dir,
                perm="elradfmwMT"  # ogni lettera è un permesso
            )
            print(f"Utente FTP aggiunto: {username}")
        except Exception as e:
            print(f"Errore nell'aggiunta dell'utente FTP {username}: {e}")

    # Aggiungi utente anonimo per debug
    try:
        authorizer.add_anonymous("/Users/simo/Documents/GitHub/Senza nome/SocketChat/file_directory_ftp",
                                 perm="elr")  # Permessi di sola lettura
    except Exception as e:
        print(f"Errore nell'aggiunta dell'utente anonimo: {e}")

    handler = FTPHandler
    handler.authorizer = authorizer
    handler.banner = "FTP Server pronto"

    try:
        server_FTP = FTPServer((SERVER_IP, 12346), handler)
        print("Server FTP inizializzato correttamente")
        server_FTP.serve_forever()
    except Exception as e:
        print(f"Errore nell'avvio del server FTP: {e}")

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


def send_active_users_list():
    users_list = list(active_users.keys())
    users_data = json.dumps({"type": "users_list", "users": users_list})

    for client in clients:
        try:
            client.send(users_data.encode('utf-8'))
        except:
            print(f"Errore nell'invio periodico degli utenti (clients) attivi a {client}")


def handle_client_connection(client, address):
    try:
        # Ricevi il comando iniziale
        data = client.recv(1024).decode('utf-8').strip()
        if not data:
            return

        print(f"Comando ricevuto da {address}: {data}")  # Debug

        username = ""

        if data.startswith("REGISTER:"):
            _, username, password = data.split(":", 2)
            success, message = register_user(username, password)
            client.send(message.encode('utf-8'))
            print(f"Registrazione: {username} - {message}")  # Debug
            if not success:
                client.close()
                return

            # Aggiungi l'utente all'authorizer FTP
            try:
                home_dir = "/Users/simo/Documents/GitHub/Senza nome/SocketChat/file_directory_ftp"
                authorizer.add_user(
                    username=username,
                    password=password,
                    homedir=home_dir,
                    perm="elradfmwMT"  # ogni lettera è un permesso
                )
                print(f"Utente FTP aggiunto: {username}")
            except Exception as e:
                print(f"Errore nell'aggiunta dell'utente FTP {username}: {e}")

        elif data.startswith("LOGIN:"):
            _, username, password = data.split(":", 2)
            success, message = authenticate_user(username, password)
            print(f"message di login: {message}")
            client.send(message.encode('utf-8'))
            print(f"Login: {username} - {message}")  # Debug
            if not success:
                client.close()
                return
        else:
            client.send("Comando non valido".encode('utf-8'))
            client.close()
            return

        time.sleep(0.5)

        # Se arriviamo qui, l'utente è autenticato
        with lock:
            clients.append(client)
            active_users[username] = client

            send_active_users_list()
            time.sleep(0.5)
            
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

                if message == "sending_file":
                    # Ricevi il nome del file
                    try:
                        filename = client.recv(1024).decode('utf-8')
                        print(f"Ricevuta notifica di invio file: {filename} da {username}")

                        # Log dell'evento
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        print(f"{timestamp} - File {filename} ricevuto da {username}, avvio distribuzione...")

                        # Attendi un momento per dare tempo al file di completare il caricamento
                        time.sleep(0.5)

                        # Verifica che il file esista
                        file_path = os.path.join(
                            "/Users/simo/Documents/GitHub/Senza nome/SocketChat/file_directory_ftp", filename)
                        if os.path.exists(file_path):
                            print(
                                f"File {filename} trovato in {file_path}, dimensione: {os.path.getsize(file_path)} bytes")

                            # Avvia la distribuzione del file agli altri client in un thread separato
                            file_distributor(client, filename, username)

                            # Log del messaggio di condivisione file
                            messaggio_broadcast(f"{timestamp} - {username}: Ha condiviso il file {filename}", client)
                        else:
                            print(f"ERRORE: File {filename} non trovato in {file_path}")
                    except Exception as e:
                        print(f"Errore durante la gestione dell'invio file: {e}")
                    continue

                if message.startswith("PRIVATE:"):
                    if "sending_file:" in message:
                        try:
                            # Formato: PRIVATE:sending_file:destinatario:timestamp:nome_file
                            parts = message.split(":", 4)

                            if len(parts) >= 4:
                                # Estrai le informazioni dal messaggio
                                recipient = parts[2]
                                timestamp = parts[3]

                                # Se ci sono 5 parti, abbiamo anche il nome del file
                                filename = parts[4] if len(parts) == 5 else "file sconosciuto"

                                print(f"File privato da {username} a {recipient}: {filename}")

                                # Verifica che il destinatario sia connesso
                                if recipient in active_users:
                                    # Invia notifica al destinatario
                                    # Formato: PRIVATE:sending_file:mittente:timestamp:nome_file
                                    notification = f"PRIVATE:sending_file:{username}:{timestamp}:{filename}"
                                    active_users[recipient].send(notification.encode('utf-8'))
                                    print(f"Notifica di file inviata a {recipient}")
                                else:
                                    # Notifica al mittente che il destinatario non è online
                                    error_msg = f"ERROR: Impossibile inviare il file. L'utente {recipient} non è connesso"
                                    client.send(error_msg.encode('utf-8'))

                        except Exception as e:
                            print(f"Errore nella gestione del file privato: {e}")
                    elif "IP_REQUEST" in message: #FORMATO --> PRIVATE:IP_REQUEST:NOME:TYPE (TYPE BOOL) (type indica chiamata o no)
                        print(f"IP REQUEST MESSAGE {message}")
                        parts = message.split(":")
                        nome_utente_richiesto = parts[2]
                        if nome_utente_richiesto in active_users.keys():
                            recipient_socket = active_users[nome_utente_richiesto]
                            recipient_ip = recipient_socket.getpeername()[0]
                            if parts[3] == "False":
                                client.send(f"IP:CALL:{recipient_ip}".encode('utf-8'))
                            else:
                                client.send(f"IP:VIDEOCALL:{recipient_ip}".encode('utf-8'))
                        else:
                            client.send("Nessun client con quel nome disponibile".encode('utf-8'))
                    else:
                        try:
                            # Gestione messaggi privati normali
                            parts = message.split(":")
                            if len(parts) == 3:
                                _, recipient, content = parts
                                print(f"Etrato in modalit private con recipient {recipient}")

                                if recipient in active_users:
                                    # Formatta il messaggio privato

                                    print(f"{recipient} è in active users")
                                    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    private_msg = f"PRIVATE:{timestamp} - {username} --> {content}"

                                    active_users[recipient].send(private_msg.encode('utf-8'))
                                    print(f"messaggio ({private_msg}) inviato")

                                    # Il server non tiene conto della cronologia della chat per evitare problemi di sicurezza
                                else:
                                    client.send(f"ERROR: L'utente {recipient} non è connesso".encode('utf-8'))

                        except Exception as e:
                            print(f"Errore nell'invio del messaggio privato: {e}")
                else:
                    parts = message.split(" - ", 1)
                    if len(parts) == 2:
                        timestamp, message_content = parts
                        # Controlla se il messaggio è già formattato con username
                        if ":" in message_content:
                            messaggio_broadcast(message, client)
                        else:
                            messaggio_broadcast(f"{timestamp} - {username}: {message_content}", client)
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
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                messaggio_broadcast(f"{timestamp} - {username} ha lasciato la chat", None)
                print(f"{username} ha lasciato la chat")
                if username in active_users:
                    del active_users[username] ## elimina il client con chiave username grazie al termine "del"
                client.close()
                send_active_users_list()


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


def file_distributor(sender_client, filename, username):
    """
    Crea un thread separato per distribuire un file ricevuto da un client a tutti gli altri client

    Args:
        sender_client: Socket del client che ha inviato il file
        filename: Nome del file da distribuire
        username: Username del client che ha inviato il file
    """
    # Crea un thread per la distribuzione del file
    distributor_thread = threading.Thread(
        target=distribute_file_to_clients,
        args=(sender_client, filename, username),
        daemon=False  # Impostato a False per assicurarsi che termini completamente
    )
    distributor_thread.start()
    print(f"Thread di distribuzione avviato per il file: {filename}")


def distribute_file_to_clients(sender_client, filename, username):
    """
    Funzione eseguita in un thread separato per distribuire un file a tutti i client

    Args:
        sender_client: Socket del client che ha inviato il file
        filename: Nome del file da distribuire
        username: Username del client che ha inviato il file
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Path al file sul server
    file_path = os.path.join("/Users/simo/Documents/GitHub/Senza nome/SocketChat/file_directory_ftp", filename)

    if not os.path.exists(file_path):
        print(f"File {filename} non trovato per la distribuzione")
        return

    # Ottieni una copia della lista dei client per evitare modifiche durante l'iterazione
    client_list = []
    with lock:
        client_list = clients.copy()

    # Conta quanti client devono ricevere il file
    client_count = sum(1 for client in client_list if client != sender_client)
    print(f"Distribuzione del file {filename} da {username} a {client_count} client")

    success_count = 0
    fail_count = 0

    for client in client_list:
        if client == sender_client:
            continue  # Salta il client che ha inviato il file

        try:
            # Invia notifica di file in arrivo
            client.send("sending_file".encode('utf-8'))

            # Breve pausa per assicurarsi che il client processi il messaggio
            time.sleep(0.1)

            # Invia timestamp e username del mittente
            client.send(f"{timestamp} - {username}".encode('utf-8'))

            # Breve pausa per assicurarsi che il client processi il messaggio
            time.sleep(0.5)

            # Invia nome del file
            client.send(filename.encode('utf-8'))

            print(f"Notifica di file inviata a un client: {filename} da {username}")
            success_count += 1

        except Exception as e:
            print(f"Errore nell'invio della notifica file a un client: {e}")
            fail_count += 1
            try:
                client.close()
            except:
                pass
            with lock:
                if client in clients:
                    clients.remove(client)

    print(f"Distribuzione file completata: {success_count} successi, {fail_count} fallimenti")

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