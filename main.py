# main.py - File di configurazione condiviso
import socket

# Configurazioni condivise
SERVER_IP = '172.20.10.13'  # Modifica questo con l'IP del server
SERVER_PORT = 12345
USERS_FILE = "users.json"
CHAT_LOG_FILE = "chat_log.txt"

# Configurazioni client
DEFAULT_IP = SERVER_IP  # Client userà lo stesso IP del server
DEFAULT_PORT = str(SERVER_PORT)  # Convertito a stringa per il client

# Configurazioni server
MAX_CONNECTIONS = 10
BUFFER_SIZE = 1024