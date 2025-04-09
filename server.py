import socket as sc
import threading
from socket import socket

server_socket
clients = []
lock = threading.Lock

def listen_for_client():
    global server_socket
    while True:
        with lock:
            server_socket.


def start_server():
    global server_socket
    server_socket = sc.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind("127.0.0.1", 12345)
    server_socket.listen(10)


if __name__ == "__main__":
    start_server()