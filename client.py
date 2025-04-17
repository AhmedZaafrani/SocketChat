import os
import sys
import tempfile
import textwrap
import threading
import socket
import datetime
from string import whitespace
from ftplib import FTP
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
import platform
import subprocess
import time

import dearpygui.dearpygui as dpg
import tkinter as tk
from tkfilebrowser import askopendirname, askopenfilename
from dearpygui.dearpygui import configure_item

from server import server_socket

SERVER_IP = '127.0.0.1'
DEFAULT_PORT = 12345
BUFFER_SIZE = 1024

dpg.create_context()
dpg.create_viewport(title='Socket Chat', width=950, height=800)

chatlog_lock = threading.Lock()
chatlog = ""
client_socket = None
server_started = False
current_username = ""
ftp_server = None
ftp_client = None

# Variabile globale per tracciare lo stato
file_selection_in_progress = False

# Definisco dimensioni di base per gli elementi
BUTTON_HEIGHT = 40
INPUT_HEIGHT = 35
SPACING = 20
LOGIN_FORM_WIDTH_RATIO = 0.65  # 50% della larghezza della viewport


def setup_connection_server_FTP():
    global ftp_server
    global ftp_client

    try:
        # Chiudi qualsiasi connessione esistente
        if ftp_server:
            try:
                ftp_server.quit()
            except:
                pass

        # Crea una nuova connessione
        ftp_server = FTP()
        ftp_server.connect(SERVER_IP, 12346)

        # Debug: mostra credenziali
        username = current_username
        password = dpg.get_value("password")
        print(f"Tentativo login FTP con: {username}:{password}")

        # Login con metodo standard
        response = ftp_server.login(user=username, passwd=password)
        print(f"Risposta login FTP: {response}")

        # Verifica se siamo effettivamente loggati
        ftp_server.sendcmd("PWD")  # Questo comando dovrebbe funzionare solo se siamo loggati

        print(f"Connessione FTP stabilita come {username}")
        return True
    except Exception as e:
        print(f"Errore nella connessione FTP: {e}")

    try:
        authorizer = DummyAuthorizer()
        authorizer.add_user(
            username="Server",
            password="Server",
            homedir="/Users/simo/Documents/GitHub/Senza nome/SocketChat/file_directory_ftp",
            perm="elradfmwMT"  # ogni lettera è un permesso
        )

        handler = FTPHandler
        handler.authorizer = authorizer
        server_FTP = FTPServer(("0.0.0.0", 12347), handler)
        server_FTP.serve_forever()

    except Exception as e:
        print(f"Errore nella creazione del client FTP: {e}")


def register():
    username = dpg.get_value("username")
    password = dpg.get_value("password")

    if not username or not password:
        dpg.set_value("logerr", "Username e password sono obbligatori!")
        return

    try:
        temp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_socket.connect((SERVER_IP, DEFAULT_PORT))
        print("sending registered usernamen and password")
        temp_socket.send(f"REGISTER:{username}:{password}".encode("utf-8"))
        print("sent registered username and password")
        response = temp_socket.recv(BUFFER_SIZE).decode("utf-8")
        print(response)

        dpg.set_value("logerr", response)

        temp_socket.close()
    except Exception as e:
        dpg.set_value("logerr", f"Errore durante la registrazione: {str(e)}")


def login():
    global client_socket, server_started, current_username
    username = dpg.get_value("username")
    password = dpg.get_value("password")

    if not username or not password:
        dpg.set_value("logerr", "Username e password sono obbligatori!")
        return

    try:
        # Prima connettiti al server di chat e autenticati
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        client_socket.connect((SERVER_IP, DEFAULT_PORT))

        # Invia comando di login
        client_socket.send(f"LOGIN:{username}:{password}".encode("utf-8"))

        # Ricevi risposta
        response = client_socket.recv(1024).decode("utf-8")

        if response != "Autenticazione riuscita":
            dpg.set_value("logerr", response)
            client_socket.close()
            return

        # Solo dopo l'autenticazione riuscita, connettiti al server FTP
        try:
            setup_connection_server_FTP()
        except Exception as e:
            print(f"Errore nella connessione FTP: {e}")
            # Continua comunque con la chat anche se la connessione FTP fallisce

        current_username = username
        listen_thread = threading.Thread(target=listen_to_server)
        listen_thread.daemon = True
        listen_thread.start()

        dpg.configure_item("chat", show=True)
        dpg.set_value("tabbar", "chat")
        dpg.set_value("logerr", "")
        server_started = True

    except Exception as e:
        dpg.set_value("logerr", f"Errore durante il login: {str(e)}")
        if client_socket:
            client_socket.close()


def listen_to_server():
    global client_socket, chatlog, ftp_server
    while True:
        try:
            msg = client_socket.recv(BUFFER_SIZE).decode("utf-8")
            if not msg:
                break
            elif msg == "sending_file":
                time_stamp_and_user_name = client_socket.recv(BUFFER_SIZE).decode("utf-8")

                download_path = "/Users/simo/Documents/GitHub/Senza nome/SocketChat/client_downloaded_file"  # Definisci un percorso dove verranno scaricati i file
                file_path = os.path.join(download_path, "nome_file_scaricato")
                file_path = os.path.abspath(file_path)

                # Controlla il sistema operativo e usa il comando appropriato
                system = platform.system()

                if system == 'Windows':
                    # Per Windows: usa explorer.exe
                    subprocess.Popen(f'explorer "{file_path}"')

                elif system == 'Sequoia':  # macOS
                    # Per macOS: usa il comando open
                    subprocess.Popen(['open', file_path])
                with chatlog_lock:
                    chatlog = chatlog + "\n" + time_stamp_and_user_name + ": Ha inviato un file"
                    dpg.set_value("chatlog_field", chatlog)
            else:
                with chatlog_lock:
                    chatlog = chatlog + "\n" + msg
                    dpg.set_value("chatlog_field", chatlog)
        except Exception as e:
            print(f"Error in listen_to_server: {e}")
            break


def send():
    global client_socket, chatlog, current_username, ftp_server
    msg = dpg.get_value("input_txt")
    file_field = dpg.get_value("file_field")

    # Verifica se sono entrambi vuoti
    if not msg and not file_field:
        print("Niente da inviare: sia messaggio che file sono vuoti")
        return

    timestamp = str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # Priorità all'invio del file
    if file_field:
        print(f"Tentativo di invio file: {file_field}")
        try:
            # Forza una riconnessione FTP
            print("Effettuo una nuova connessione FTP...")
            setup_connection_server_FTP()

            # Invia notifica al client
            client_socket.send("sending_file".encode("utf-8"))
            client_socket.send(f"{timestamp} - {current_username}".encode("utf-8"))

            # Invia il file
            with open(file_field, 'rb') as file:
                name_file = os.path.basename(file_field)
                print(f"Invio del file {name_file} in corso...")
                ftp_server.storbinary(f"STOR {name_file}", file)
                print(f"File {name_file} inviato con successo")

                # Aggiungi messaggio al log della chat
                with chatlog_lock:
                    chatlog = chatlog + f"\n{timestamp} - {current_username}: Ha inviato un file ({name_file})"
                    dpg.set_value("chatlog_field", chatlog)

                # Pulisci il campo file dopo l'invio
                dpg.set_value("file_field", "")
        except Exception as e:
            print(f"Errore nell'invio del file: {e}")
    elif msg:  # Solo se c'è un messaggio e non un file
        formatted_msg = f"{timestamp} - {current_username}: {msg}"
        try:
            client_socket.send(formatted_msg.encode("utf-8"))
            with chatlog_lock:
                chatlog = chatlog + "\n" + formatted_msg
            dpg.set_value("input_txt", "")
        except Exception as e:
            dpg.set_value("logerr", f"Errore durante l'invio del messaggio: {str(e)}")



def center_items():
    viewport_width = dpg.get_viewport_width()
    viewport_height = dpg.get_viewport_height()

    # Calcola dimensioni proporzionali al viewport
    form_width = int(viewport_width * LOGIN_FORM_WIDTH_RATIO)
    side_spacer = (viewport_width - form_width) / 2

    # Aumenta la dimensione dei testi
    dpg.set_value("login_title", "LOGIN")
    dpg.configure_item("login_title", color=[255, 255, 255])

    # Aggiorna dimensioni degli elementi di login
    dpg.set_item_width("left_spacer", side_spacer)
    dpg.set_item_width("right_spacer", side_spacer)

    # Ridimensiona i campi di input
    input_width = form_width - 40  # Un po' più piccolo del form per margini
    dpg.set_item_width("username", input_width)
    dpg.configure_item("username", height=INPUT_HEIGHT)
    dpg.set_item_width("password", input_width)
    dpg.configure_item("password", height=INPUT_HEIGHT)

    # Ridimensiona pulsanti
    button_width = (input_width - 20) / 2  # Dividi lo spazio disponibile per i due pulsanti con un piccolo gap
    dpg.set_item_width("login_button", button_width)
    dpg.configure_item("login_button", height=BUTTON_HEIGHT)
    dpg.set_item_width("register_button", button_width)
    dpg.configure_item("register_button", height=BUTTON_HEIGHT)

    # Aggiorna i componenti della chat
    chat_width = viewport_width - (SPACING * 2)  # Margine ai lati
    file_width = viewport_width - (SPACING * 2)  # Margine ai lati
    chat_height = viewport_height - 200  # Spazio per inp e altri elementi

    dpg.set_item_width("chatlog_field", chat_width)
    dpg.set_item_height("chatlog_field", chat_height)

    # Aggiorna l'input di testo della chat
    input_chat_width = chat_width - 120  # Spazio per il pulsante Invia
    dpg.set_item_width("input_txt", input_chat_width)
    dpg.configure_item("input_txt", height=INPUT_HEIGHT)

    # Aggiorna dimensione pulsante invio
    dpg.set_item_width("send_button", 100)
    dpg.configure_item("send_button", height=INPUT_HEIGHT)

    # Aggiorna l'input di testo della file select
    input_file_width = file_width - 120  # Spazio per il pulsante file
    dpg.set_item_width("file_field", input_file_width)
    dpg.configure_item("file_field", height=INPUT_HEIGHT)

    # Aggiorna dimensione pulsante file
    dpg.set_item_width("file_button", 100)
    dpg.configure_item("file_button", height=INPUT_HEIGHT)


def carica_file():
    if getattr(carica_file, 'in_progress', False):
        return

    carica_file.in_progress = True
    dpg.configure_item("file_button", enabled=False)

    # Crea un file temporaneo per comunicare il risultato
    temp_file = tempfile.mktemp()

    # Crea un piccolo script Python da eseguire
    script_file = tempfile.mktemp(suffix='.py')
    with open(script_file, 'w') as f:
        f.write("""
import tkinter as tk
from tkinter import filedialog
import sys

root = tk.Tk()
root.withdraw()
file_path = filedialog.askopenfilename(
    title="Seleziona un file",
    filetypes=[("Tutti i file", "*"), ("File di testo", "*.txt")]
)

if file_path:
    with open(sys.argv[1], 'w') as f:
        f.write(file_path)
""")

    # Esegui lo script in un processo separato
    subprocess.run([sys.executable, script_file, temp_file], check=False)

    try:
        # Leggi il risultato
        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            with open(temp_file, 'r') as f:
                file_path = f.read().strip()
                if file_path:
                    dpg.set_value("file_field", file_path)
    finally:
        # Pulisci i file temporanei
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            if os.path.exists(script_file):
                os.remove(script_file)
        except:
            pass

        dpg.configure_item("file_button", enabled=True)
        carica_file.in_progress = False

def create_gui():
    with dpg.window(label="Chat", tag="window"):
        with dpg.tab_bar(tag="tabbar"):
            # Tab Login
            with dpg.tab(label="Login", tag="login"):
                with dpg.group(horizontal=True):
                    dpg.add_spacer(tag="left_spacer", width=300)  # Spaziatore a sinistra

                    with dpg.group():  # Gruppo verticale per gli elementi di login
                        dpg.add_spacer(height=SPACING * 13)  # Spaziatore in alto
                        dpg.add_text("LOGIN", tag="login_title", color=[255, 255, 255])
                        dpg.add_spacer(height=SPACING)
                        dpg.add_input_text(label="Username", tag="username")
                        dpg.add_spacer(height=SPACING)
                        dpg.add_input_text(label="Password", tag="password", password=True)
                        dpg.add_spacer(height=SPACING * 2)

                        # Gruppo orizzontale per i pulsanti, centrato
                        with dpg.group(horizontal=True):
                            dpg.add_button(label="Login", tag="login_button", callback=login)
                            dpg.add_spacer(width=SPACING)
                            dpg.add_button(label="Register", tag="register_button", callback=register)

                        dpg.add_spacer(height=SPACING)
                        dpg.add_text("", tag="logerr", color=(255, 0, 0))  # Colore rosso per errori
                        dpg.add_spacer(height=SPACING * 2)  # Spaziatore in basso

                    dpg.add_spacer(tag="right_spacer", width=300)  # Spaziatore a destra

            # Tab Chat
            with dpg.tab(label="Chat", tag="chat", show=False):
                dpg.add_text("CHAT", tag="chat_title", color=[255, 255, 255])
                dpg.add_input_text(
                    tag="chatlog_field", multiline=True, readonly=True, tracked=True,
                    track_offset=1)
                dpg.add_spacer(height=SPACING)
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="input_txt", multiline=True)
                    dpg.add_spacer(width=SPACING)  # Spaziatore a destra
                    dpg.add_button(label="Invia", tag="send_button", callback=send)

                dpg.add_spacer(height=5)

                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="file_field", multiline=True, readonly=True)
                    dpg.add_spacer(width=SPACING)  # Spaziatore a destra
                    dpg.add_button(label="File", tag="file_button", callback=carica_file)



# Creazione dell'interfaccia
create_gui()

# Aggiungi la callback per il ridimensionamento della viewport
dpg.set_viewport_resize_callback(center_items)

dpg.set_primary_window("window", True)
dpg.setup_dearpygui()
dpg.show_viewport()

# Esegui il centering iniziale dopo aver mostrato la viewport
center_items()

while dpg.is_dearpygui_running():
    if server_started:
        with chatlog_lock:
            if dpg.get_value("chatlog_field") != chatlog:
                dpg.set_value("chatlog_field", chatlog)
    dpg.render_dearpygui_frame()

if server_started:
    try:
        client_socket.send("closed connection")
        client_socket.close()
    except:
        pass

dpg.destroy_context()