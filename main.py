import socket
import os

# Configurazioni condivise
SERVER_IP = '127.0.0.1'
SERVER_PORT = 12345
CHAT_LOG_FILE = "chat_log.txt"

script_dir = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(script_dir, "users.json")

# Configurazioni client
DEFAULT_PORT = SERVER_PORT  # Convertito a stringa per il client

# Configurazioni server
MAX_CONNECTIONS = 10
BUFFER_SIZE = 1024

