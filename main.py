import socket

# Configurazioni condivise
SERVER_IP = '172.20.10.9'
SERVER_PORT = 12345
USERS_FILE = "users.json"
CHAT_LOG_FILE = "chat_log.txt"

# Configurazioni client
DEFAULT_PORT = SERVER_PORT  # Convertito a stringa per il client

# Configurazioni server
MAX_CONNECTIONS = 10
BUFFER_SIZE = 1024