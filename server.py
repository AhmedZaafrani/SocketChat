import threading
import socket

server_socket = None
clients = []
nomi = {}
lock = threading.Lock

def ascolta_client(client):
    client.send("Inserisci il tuo nome: ".encode('utf-8'))
    nome = client.recv(1024).decode('utf-8').strip()

    with lock:
        clients.append(client)
        nomi[client] = nome
        messaggio_broadcast(f"{nome} si è unito alla chat".encode('utf-8'), None)
        print(f"{nome} si è unito alla chat")

    while True:
        try:
            message = client.recv(1024).decode('utf-8')
            messaggio_broadcast(message, client)
            print(f"{nomi[client]}: {message}")

        except Exception as e:
            print(f"eccezione nella gestione del client {client}. Info aggiuntive: {e}")

    with lock:
        clients.remove(client)
        del nomi[client]
        messaggio_broadcast(f"{nome} ha lasciato la chat", client, address)


def listen_for_client():
    global server_socket
    while True:
        try:
            client, address = server_socket.accept()
            print(f"si è connesso al server: {address}")
            client_thread = threading.Thread(ascolta_client, args=(client))
            client_thread.daemon = True
            client_thread.start()
        except Exception as e:
            print(f"eccezzione nella funzione listen_for_client: {e}")
            break

def start_server():
    global server_socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind("127.0.0.1", 12345)
    server_socket.listen(10)

def messaggio_broadcast(messagge, sender_client):
    with lock:
        for client in clients:
            if client != sender_client:
                client.send(messagge.encode('utf-8'))


if __name__ == "__main__":
    start_server()
    listening_thread = threading.Thread(listen_for_client,)

