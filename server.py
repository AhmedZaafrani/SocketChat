import threading
import socket

server_socket = None
clients = []
lock = threading.Lock

def ascolta_client(client, address):
    client.send("Inserisci il tuo nome: ".encode('utf-8'))
    nome = client.recv(1024).decode('utf-8').strip()

    with lock:
        clients.append(client)
        messaggio_broadcast(f"{nome} si è unito alla chat".encode('utf-8'), None)
        print(f"{nome} - {address} - si è unito alla chat") # log

    while True:
        try:
            message = client.recv(1024).decode('utf-8')
            if message:
                if message == "closed connection":
                    break
                messaggio_broadcast(f"{nome}: {message}", client)
                print(f"{nome}: {message}")

        except Exception as e:
            print(f"eccezione nella gestione del client {client}. Info aggiuntive: {e}")

    with lock:
        clients.remove(client)
        messaggio_broadcast(f"{nome} ha lasciato la chat", client)
        print(f"{nome} - {address} - ha lasciato la chat") # log
        client.close()


def listen_for_client():
    global server_socket
    while True:
        try:
            client, address = server_socket.accept()
            print(f"si è connesso al server: {address}") # log
            client_thread = threading.Thread(target=ascolta_client, args=(client, address))
            client_thread.daemon = True
            client_thread.start()
        except Exception as e:
            print(f"eccezione nella funzione listen_for_client: {e}")
            break

def start_server():
    global server_socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 12345))
    server_socket.listen(10)

def messaggio_broadcast(message, sender_client):
    with lock:
        for client in clients:
            if client != sender_client:
                try:
                    client.send(message)
                except Exception as e:
                    print(f"errore nella funzione broadcast. Info: {e}")
                    # Se c'è un errore, il thread del client è attivo stranamente ma il client probabilmente si è disconnesso
                    client.close()
                    if client in clients:
                        clients.remove(client)


if __name__ == "__main__":
    start_server()
    listening_thread = threading.Thread(target=listen_for_client,)
    listening_thread.daemon = True
    listening_thread.start()

