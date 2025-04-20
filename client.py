import json
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


#import per le chiamate e le videochiamate
import pyaudio # con questo modulo gestisco l'audio in input e in output
import numpy as np
import struct
import pickle
import cv2 # con questo modulo gestisco la videocamera e i frame ricevuti dall'altro client


import dearpygui.dearpygui as dpg
from tkfilebrowser import askopendirname, askopenfilename
from dearpygui.dearpygui import configure_item


# Costanti per le chiamate e le videochiamate
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNEL = 1
RATE = 44100 # valore che consiglia la documentazione
PORT_CHIAMATE = 12347

# Altre costanti

SERVER_IP = '127.0.0.1'
DEFAULT_PORT = 12345
BUFFER_SIZE = 1024

dpg.create_context()
dpg.create_viewport(title='Socket Chat', width=950, height=800)

# variabili globali per le chiamate e le videochiamate

chiamata_in_corso = False
socket_chiamata = None
is_video = False
audioStream = None
VideoCapture = None
p = None # istanza di pyaudio
utente_in_chiamata = ""

# altre variabili globali

chatlog_lock = threading.Lock()
chatlog = ""
download_folders = {}  # username -> cartella di download per la chat
client_socket = None
server_started = False
nome_utente_personale = ""
ftp_server = None
ftp_client = None

# Variabile globale per tracciare lo stato
file_selection_in_progress = False

# Definisco dimensioni di base per gli elementi
BUTTON_HEIGHT = 40
INPUT_HEIGHT = 35
SPACING = 20
LOGIN_FORM_WIDTH_RATIO = 0.65  # 50% della larghezza della viewport

utenti_disponibili = []  # Lista di utenti disponibili
chat_attive = {}  # username -> cronologia chat
username_client_chat_corrente = ""  # Username del contatto attualmente selezionato


def get_chat_download_folder(username):
    """Restituisce la cartella dedicata per i download di una specifica chat"""
    global download_folders

    # Se esiste già la cartella per questo utente, restituiscila
    if username in download_folders:
        folder = download_folders[username]
        # Verifica che la cartella esista ancora
        if os.path.exists(folder):
            return folder

    # Altrimenti, crea una nuova cartella nella directory principale di download
    base_download_folder = '/Users/simo/Documents/GitHub/Senza nome/SocketChat/client_chats_file_directory'
    if not base_download_folder:
        base_download_folder = os.path.expanduser("~/Downloads")

    # Crea una cartella con nome dell'utente
    safe_username = "".join(c for c in username if c.isalnum() or c in [' ', '_', '-']).strip()
    chat_folder = os.path.join(base_download_folder, f"Chat_{safe_username}")

    # Crea la directory se non esiste
    if not os.path.exists(chat_folder):
        os.makedirs(chat_folder)

    # Memorizza la cartella per uso futuro
    download_folders[username] = chat_folder

    return chat_folder


def setup_connection_server_FTP():
    global ftp_server
    global nome_utente_personale

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

        # Ottieni le credenziali
        username = nome_utente_personale
        password = dpg.get_value("password")

        # Debug: mostra credenziali
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
        return False


def registrati():
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
    global client_socket, server_started, nome_utente_personale
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
        splittedResponde = response.split(':', 1)

        if splittedResponde[0] != "Autenticazione riuscita":
            print("risposta non attesa")
            dpg.set_value("logerr", response)
            client_socket.close()
            return

        # Salva username prima di configurare FTP
        nome_utente_personale = username

        # Solo dopo l'autenticazione riuscita, connettiti al server FTP
        ftp_success = setup_connection_server_FTP()
        if not ftp_success:
            print("Avviso: La connessione FTP non è riuscita, ma la chat funzionerà comunque")
            # Non interrompere l'esecuzione, continua con la chat anche se FTP fallisce

        # Avvia thread di ascolto
        listen_thread = threading.Thread(target=listen_to_server)
        listen_thread.daemon = True
        listen_thread.start()

        # Mostra la scheda di chat e abilita visivamente
        dpg.configure_item("chat", show=True)
        dpg.configure_item("chat_private", show=True)
        dpg.set_value("tab_bar", "chat")  # Cambia tab
        dpg.configure_item("login", show=False)  # Nascondi login tab

        # Pulisci messaggio di errore
        dpg.set_value("logerr", "")

        # Aggiorna il flag di server
        server_started = True

        print(f"Login riuscito come {username}, GUI aggiornata")

    except Exception as e:
        dpg.set_value("logerr", f"Errore durante il login: {str(e)}")
        if client_socket:
            client_socket.close()


def notifica_messaggio_privato():
    pass


def notifica_messaggio():
    pass


def listen_to_server():
    global client_socket, chatlog, ftp_server, utenti_disponibili, chat_attive, username_client_chat_corrente

    while True:
        try:
            msg = client_socket.recv(BUFFER_SIZE).decode("utf-8")
            if not msg:
                break

            print(f"Messaggio ricevuto: {msg}")  # Debug

            # Gestione JSON per la lista utenti
            if msg.startswith("{"):
                try:
                    data = json.loads(msg)
                    if data.get("type") == "users_list":
                        utenti_disponibili = data.get("users", [])
                        print(f"Lista utenti aggiornata: {utenti_disponibili}")
                        continue  # Salta il resto del processing
                except Exception as e:
                    print(f"Errore nel parsing JSON: {e}")
                    # Se non è un JSON valido, procedi come messaggio normale

            # Gestione messaggi privati
            if msg.startswith("PRIVATE:"):
                if "sending_file:" in msg:
                    try:
                        # Formato: PRIVATE:sending_file:mittente:timestamp:nome_file
                        parts = msg.split(":", 4)
                        if len(parts) == 5:
                            sender = parts[2]  # chi ha inviato il file
                            timestamp = parts[3]  # quando è stato inviato
                            filename = parts[4]  # nome del file

                            print(f"Notifica di file privato: {sender} ha inviato {filename}")

                            # Assicurati che ci sia una chat con il mittente
                            if sender not in chat_attive:
                                chat_attive[sender] = ""
                                aggiorna_lista_contatti()

                            # Aggiungi messaggio di notifica alla chat
                            file_notification = f"\n{timestamp} - {sender} --> Ha inviato il file {filename}. Download in corso..."
                            chat_attive[sender] += file_notification

                            # Aggiorna la visualizzazione se è la chat corrente
                            if sender == username_client_chat_corrente:
                                dpg.set_value("chatlog_field_privata", chat_attive[sender])

                            # Avvia un thread per il download in background
                            download_thread = threading.Thread(
                                target=download_private_file,
                                args=(sender, filename, timestamp, file_notification),
                                daemon=True
                            )
                            download_thread.start()

                        # Non processare oltre questo messaggio
                        continue
                    except Exception as e:
                        print(f"Errore nell'elaborazione della notifica di file privato: {e}")

                else:
                    _, private_msg = msg.split(":", 1)

                    # Estrai mittente o destinatario
                    parts = private_msg.split(" - ", 1)
                    if len(parts) == 2:
                        timestamp, content = parts

                        if "-->" in content:  # Messaggio in arrivo da un altro utente
                            sender, message = content.split(" -->", 1)
                            print(f"sender: {sender} - message: {message}")

                            # Aggiungi alla chat con il mittente
                            if sender not in chat_attive:
                                print(f"entrato in sender not in chat_attive - chat attive: {chat_attive}")
                                chat_attive[sender] = ""
                                # Aggiorna la lista dei contatti
                                aggiorna_lista_contatti()

                            # Aggiungi il messaggio alla chat con formato standardizzato
                            chat_attive[sender] += f"\n{timestamp} - {sender} -->{message}"

                            # Se è la chat corrente, aggiorna la visualizzazione
                            if sender == username_client_chat_corrente:
                                dpg.set_value("chatlog_field_privata", chat_attive[sender])

                            notifica_messaggio_privato()

                    # Non mostrare il messaggio privato nella chat globale
                    continue

            # Gestione file in arrivo
            elif msg == "sending_file":
                print("Rilevata notifica di invio file")

                # Ricevi timestamp e nome utente
                time_stamp_and_user_name = client_socket.recv(BUFFER_SIZE).decode("utf-8")
                print(f"Ricevuto timestamp e utente: {time_stamp_and_user_name}")

                # Ricevi il nome del file
                filename = client_socket.recv(BUFFER_SIZE).decode("utf-8")
                print(f"Ricevuto nome file: {filename}")

                # Crea un thread separato per il download del file
                download_thread = threading.Thread(
                    target=download_file,
                    args=(time_stamp_and_user_name, filename),
                    daemon=True
                )
                download_thread.start()

            # Messaggi normali per la chat globale
            else:
                with chatlog_lock:
                    chatlog = chatlog + "\n" + msg
                    dpg.set_value("chatlog_field", chatlog)
                    notifica_messaggio()

        except Exception as e:
            print(f"Error in listen_to_server: {e}")
            break

    print("Thread di ascolto terminato")


def download_private_file(sender, filename, timestamp, notification_message):
    """Scarica un file inviato in una chat privata"""
    try:
        # Ottieni cartella dedicata per questa chat

        download_folder = get_chat_download_folder(sender)

        print(f"filename prima dello split = {filename}")
        parts = filename.split(":", 2)
        filename = parts[2]
        print(f"filename dopo lo split = {filename}")

        print(f"Download di {filename} da {sender} nella cartella {download_folder}")

        # Percorso completo del file
        file_path = os.path.join(download_folder, filename)

        # Effettua la connessione FTP e scarica il file
        ftp_success = setup_connection_server_FTP()
        if not ftp_success:
            error_msg = f"\n{timestamp} - {sender} --> Impossibile scaricare il file {filename}: errore connessione FTP"
            update_private_chat(sender, notification_message, error_msg)
            return

        # Tentativo di download
        max_attempts = 5
        download_successful = False

        for attempt in range(max_attempts):
            try:
                # Lista i file disponibili
                files = ftp_server.nlst()

                if filename not in files:
                    print(f"File {filename} non trovato, tentativo {attempt + 1}/{max_attempts}")
                    time.sleep(2)
                    continue

                # Scarica il file

                with open(file_path, 'wb') as local_file:
                    ftp_server.retrbinary(f"RETR {filename}", local_file.write)

                # Verifica che il file sia stato scaricato correttamente
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    download_successful = True
                    break

            except Exception as e:
                print(f"Errore tentativo {attempt + 1}: {e}")
                time.sleep(2)

        # Aggiorna la chat in base al risultato
        if download_successful:
            success_msg = f"\n{timestamp} - {sender} --> Ha inviato il file {filename}. Download completato."
            update_private_chat(sender, notification_message, success_msg)

            # Apri la cartella di download
            try:
                system = platform.system()
                if system == 'Windows':
                    subprocess.Popen(f'explorer /select,"{file_path}"')
                elif system == 'Darwin':  # macOS
                    subprocess.Popen(['open', '-R', file_path])
                else:  # Linux e altri sistemi
                    subprocess.Popen(['xdg-open', os.path.dirname(file_path)])
            except Exception as e:
                print(f"Errore nell'apertura del file explorer: {e}")
        else:
            error_msg = f"\n{timestamp} - {sender} --> Impossibile scaricare il file {filename} dopo {max_attempts} tentativi"
            update_private_chat(sender, notification_message, error_msg)

    except Exception as e:
        print(f"Errore globale durante il download del file privato: {e}")
        error_msg = f"\n{timestamp} - {sender} --> Errore durante il download di {filename}: {str(e)}"
        update_private_chat(sender, notification_message, error_msg)


def update_private_chat(username, old_message, new_message):
    """Aggiorna un messaggio nella chat privata"""
    global chat_attive

    if username in chat_attive:
        # Sostituisci il vecchio messaggio con il nuovo
        chat_attive[username] = chat_attive[username].replace(old_message, new_message)

        # Aggiorna la visualizzazione se è la chat attiva
        if username == username_client_chat_corrente:
            dpg.set_value("chatlog_field_privata", chat_attive[username])


def download_file(time_stamp_and_user_name, filename):
    """Thread separato per gestire il download di un file"""
    global ftp_server, chatlog

    try:
        # Controlla se esiste una cartella di download configurata
        download_folder = dpg.get_value("cartella_download")
        if not download_folder:
            download_folder = os.path.expanduser("~/Downloads")  # Default
            print(f"Usando cartella di download predefinita: {download_folder}")

        # Assicurati che la cartella esista
        if not os.path.exists(download_folder):
            os.makedirs(download_folder)
            print(f"Creata cartella di download: {download_folder}")

        # Percorso completo del file da scaricare
        file_path = os.path.join(download_folder, filename)
        print(f"Percorso completo del file: {file_path}")

        # Attendi un po' prima di iniziare il download
        # Questo dà tempo al server FTP di completare il caricamento
        time.sleep(1)

        # Tenta di riconnettersi all'FTP per diverse volte
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                print(f"Tentativo di connessione FTP {attempt + 1}/{max_attempts}...")
                ftp_success = setup_connection_server_FTP()

                if not ftp_success:
                    print(f"Tentativo {attempt + 1} fallito, riprovo...")
                    time.sleep(2)  # Attesa tra i tentativi
                    continue

                # Lista i file disponibili (debug)
                print("File disponibili sul server:")
                files = ftp_server.nlst()
                print(files)

                if filename not in files:
                    print(f"File {filename} non trovato sul server, riprovo...")
                    time.sleep(2)
                    continue

                # Scarica il file
                with open(file_path, 'wb') as local_file:
                    print(f"Tentativo di download di {filename}...")
                    ftp_server.retrbinary(f"RETR {filename}", local_file.write)

                print(f"File scaricato con successo in: {file_path}")

                # Se siamo arrivati qui, il download è riuscito
                break

            except Exception as e:
                print(f"Errore durante il tentativo {attempt + 1} di download: {e}")
                time.sleep(2)  # Attesa tra i tentativi

        # Verifica se il file esiste e ha dimensione > 0
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            # Apri la cartella di download nel file explorer
            system = platform.system()
            print(f"Sistema operativo rilevato: {system}")

            try:
                if system == 'Windows':
                    # Per Windows: usa explorer.exe
                    subprocess.Popen(f'explorer /select,"{file_path}"')
                elif system == 'Darwin':  # macOS o Sequoia
                    # Per macOS: usa il comando open
                    subprocess.Popen(['open', '-R', file_path])
                else:  # Linux e altri sistemi
                    subprocess.Popen(['xdg-open', os.path.dirname(file_path)])

                print("File explorer aperto correttamente")

                # Aggiorna il log della chat per indicare download completato
                with chatlog_lock:
                    chatlog = chatlog + "\n" + time_stamp_and_user_name + f": Ha inviato un file ({filename}) - Download completato"
                    dpg.set_value("chatlog_field", chatlog)

            except Exception as e:
                print(f"Errore nell'apertura del file explorer: {e}")
        else:
            print(f"Download fallito: file {filename} non trovato o vuoto")
            # Aggiorna comunque il log della chat
            with chatlog_lock:
                chatlog = chatlog + "\n" + time_stamp_and_user_name + f": Ha inviato un file ({filename}) - Download fallito"
                dpg.set_value("chatlog_field", chatlog)

    except Exception as e:
        print(f"Errore durante il download del file: {e}")
        # Aggiorna il log della chat anche in caso di errore
        with chatlog_lock:
            chatlog = chatlog + "\n" + time_stamp_and_user_name + f": Ha inviato un file ({filename}) - Errore nel download"
            dpg.set_value("chatlog_field", chatlog)


def invia():
    global client_socket, chatlog, nome_utente_personale, ftp_server
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
            # Verifica che il file esista
            if not os.path.exists(file_field):
                error_msg = f"Errore: il file {file_field} non esiste"
                print(error_msg)
                dpg.set_value("logerr", error_msg)
                return

            # Verifica che il file non sia vuoto
            if os.path.getsize(file_field) == 0:
                error_msg = "Errore: il file è vuoto"
                print(error_msg)
                dpg.set_value("logerr", error_msg)
                return

            # Ottieni il nome del file dal percorso
            name_file = os.path.basename(file_field)

            # Forza una riconnessione FTP
            print("Effettuo una nuova connessione FTP...")
            ftp_success = setup_connection_server_FTP()

            if not ftp_success:
                dpg.set_value("logerr", "Errore nella connessione FTP. Impossibile inviare il file.")
                return

            # Aggiungi messaggio al log della chat (prima dell'invio)
            with chatlog_lock:
                chatlog = chatlog + f"\n{timestamp} - {nome_utente_personale}: Invio del file {name_file} in corso..."
                dpg.set_value("chatlog_field", chatlog)

            # Invia il file tramite FTP
            with open(file_field, 'rb') as file:
                print(f"Invio del file {name_file} in corso...")
                ftp_server.storbinary(f"STOR {name_file}", file)
                print(f"File {name_file} inviato con successo")

            # Dopo il caricamento FTP, notifica il server
            client_socket.send("sending_file".encode("utf-8"))
            time.sleep(0.1)  # Piccola pausa per assicurarsi che i messaggi non si sovrappongano
            client_socket.send(name_file.encode("utf-8"))

            # Aggiorna il messaggio nel log della chat
            with chatlog_lock:
                chatlog = chatlog + f"\n{timestamp} - {nome_utente_personale}: File {name_file} inviato con successo"
                dpg.set_value("chatlog_field", chatlog)

            # Pulisci il campo file dopo l'invio
            dpg.set_value("file_field", "")

            # Pulisci eventuali messaggi di errore
            dpg.set_value("logerr", "")

        except Exception as e:
            error_msg = f"Errore nell'invio del file: {e}"
            print(error_msg)
            dpg.set_value("logerr", error_msg)

            # Aggiorna il log con l'errore
            with chatlog_lock:
                chatlog = chatlog + f"\n{timestamp} - {nome_utente_personale}: Errore nell'invio del file {os.path.basename(file_field)}"
                dpg.set_value("chatlog_field", chatlog)

    elif msg:  # Solo se c'è un messaggio e non un file
        try:
            # Invia il messaggio con timestamp
            formatted_msg = f"{timestamp} - {nome_utente_personale}: {msg}"
            client_socket.send(formatted_msg.encode("utf-8"))

            with chatlog_lock:
                chatlog = chatlog + "\n" + formatted_msg
                dpg.set_value("chatlog_field", chatlog)

            dpg.set_value("input_txt", "")

        except Exception as e:
            error_msg = f"Errore durante l'invio del messaggio: {str(e)}"
            print(error_msg)
            dpg.set_value("logerr", error_msg)


def seleziona_cartella_download():
    #Apre un dialog per selezionare la cartella di download dei file, usando AppleScript per macOS
    if getattr(seleziona_cartella_download, 'in_progress', False):
        return

    seleziona_cartella_download.in_progress = True
    dpg.configure_item("btn_selezione_cartella_download", enabled=False)

    # Crea un file temporaneo per comunicare il risultato
    temp_file = tempfile.mktemp()

    # Determina il sistema operativo
    system = platform.system()

    if system == 'Darwin':  # macOS o Sequoia
        # Usa AppleScript direttamente per un dialogo di selezione cartella nativo
        # che sarà sempre in primo piano
        applescript = f'''
        tell application "System Events"
            activate
        end tell
        set selectedFolder to choose folder with prompt "Seleziona cartella per i file scaricati"
        set folderPath to POSIX path of selectedFolder
        do shell script "echo " & quoted form of folderPath & " > {temp_file}"
        '''

        try:
            # Esegui AppleScript
            subprocess.run(["osascript", "-e", applescript], check=False)
        except Exception as e:
            print(f"Errore nell'esecuzione di AppleScript: {e}")
    else:
        # Per Windows e altri sistemi, usa il metodo Tkinter come prima
        script_file = tempfile.mktemp(suffix='.py')
        with open(script_file, 'w') as f:
            f.write("""
import tkinter as tk
from tkinter import filedialog
import sys

root = tk.Tk()
root.attributes('-topmost', True)
root.withdraw()
folder_path = filedialog.askdirectory(
    title="Seleziona cartella per i file scaricati"
)

if folder_path:
    with open(sys.argv[1], 'w') as f:
        f.write(folder_path)
""")

        # Esegui lo script in un processo separato
        subprocess.run([sys.executable, script_file, temp_file], check=False)

        # Pulisci il file dello script
        try:
            if os.path.exists(script_file):
                os.remove(script_file)
        except:
            pass

    try:
        # Leggi il risultato
        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            with open(temp_file, 'r') as f:
                folder_path = f.read().strip()
                if folder_path:
                    # Salva il percorso
                    dpg.set_value("cartella_download", folder_path)
                    print(f"Cartella di download impostata: {folder_path}")
    finally:
        # Pulisci il file temporaneo
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass

        dpg.configure_item("btn_selezione_cartella_download", enabled=True)
        seleziona_cartella_download.in_progress = False


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
    dpg.set_item_width("spaziatore_sinistro", side_spacer)
    dpg.set_item_width("spaziatore_destro", side_spacer)

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
    download_width = viewport_width - (SPACING * 2)  # Margine ai lati
    chat_height = viewport_height - 250  # Spazio per input e altri elementi

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

    # Aggiorna l'input della cartella di download
    input_download_width = download_width - 180  # Spazio per il pulsante
    dpg.set_item_width("cartella_download", input_download_width)
    dpg.configure_item("cartella_download", height=INPUT_HEIGHT)

    # Aggiorna dimensione pulsante cartella
    dpg.set_item_width("btn_selezione_cartella_download", 160)
    dpg.configure_item("btn_selezione_cartella_download", height=INPUT_HEIGHT)

    if dpg.does_item_exist("pannello_contatti"):
        # Imposta dimensioni per il pannello dei contatti
        contacts_width = 250
        dpg.set_item_width("pannello_contatti", contacts_width)

        # Imposta dimensioni per il pannello di chat attiva
        chat_panel_width = viewport_width - contacts_width - 25  # Margine
        dpg.set_item_width("chat_attiva", chat_panel_width)

        # Configura altri elementi nella chat privata
        if dpg.does_item_exist("private_chatlog_field"):
            dpg.set_item_width("chatlog_field_privata", chat_panel_width - 20)
            chat_height = viewport_height - 200  # Spazio per input e header
            dpg.set_item_height("chatlog_field_privata", chat_height)

        # Input text e pulsante
        if dpg.does_item_exist("input_txt_chat_privata"):
            input_width = chat_panel_width - 120  # Spazio per pulsante
            dpg.set_item_width("input_txt_chat_privata", input_width)
            dpg.configure_item("input_txt_chat_privata", height=INPUT_HEIGHT)

        # File field e pulsante
        if dpg.does_item_exist("file_field_privata"):
            dpg.set_item_width("file_field_privata", input_width)
            dpg.configure_item("file_field_privata", height=INPUT_HEIGHT)


def carica_file():
    """Apre un dialog per selezionare un file da inviare, usando AppleScript per macOS"""
    if getattr(carica_file, 'in_progress', False):
        return

    carica_file.in_progress = True
    dpg.configure_item("file_button", enabled=False)

    # Crea un file temporaneo per comunicare il risultato
    temp_file = tempfile.mktemp()

    # Determina il sistema operativo
    system = platform.system()

    if system == 'Darwin':  # macOS
        # Usa AppleScript direttamente per un dialogo di selezione file nativo
        # che sarà sempre in primo piano
        applescript = f'''
        tell application "System Events"
            activate
        end tell
        set selectedFile to choose file with prompt "Seleziona un file da inviare"
        set filePath to POSIX path of selectedFile
        do shell script "echo " & quoted form of filePath & " > {temp_file}"
        '''

        try:
            # Esegui AppleScript
            subprocess.run(["osascript", "-e", applescript], check=False)
        except Exception as e:
            print(f"Errore nell'esecuzione di AppleScript: {e}")
    else:
        # Per Windows e altri sistemi, usa il metodo Tkinter come prima
        script_file = tempfile.mktemp(suffix='.py')
        with open(script_file, 'w') as f:
            f.write("""
import tkinter as tk
from tkinter import filedialog
import sys

root = tk.Tk()
root.attributes('-topmost', True)
root.withdraw()
file_path = filedialog.askopenfilename(
    title="Seleziona un file da inviare",
    filetypes=[("Tutti i file", "*"), ("File di testo", "*.txt")]
)

if file_path:
    with open(sys.argv[1], 'w') as f:
        f.write(file_path)
""")

        # Esegui lo script in un processo separato
        subprocess.run([sys.executable, script_file, temp_file], check=False)

        # Pulisci il file dello script
        try:
            if os.path.exists(script_file):
                os.remove(script_file)
        except:
            pass

    try:
        # Leggi il risultato
        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            with open(temp_file, 'r') as f:
                file_path = f.read().strip()
                if file_path:
                    dpg.set_value("file_field", file_path)
                    print(f"File selezionato: {file_path}")
    finally:
        # Pulisci il file temporaneo
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass

        dpg.configure_item("file_button", enabled=True)
        carica_file.in_progress = False


def create_gui():
    with dpg.window(label="Chat", tag="window"):
        with dpg.tab_bar(tag="tab_bar"):
            # Tab Login
            with dpg.tab(label="Login", tag="login"):
                with dpg.group(horizontal=True):
                    dpg.add_spacer(tag="spaziatore_sinistro", width=300)  # Spaziatore a sinistra

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
                            dpg.add_button(label="Register", tag="register_button", callback=registrati)

                        dpg.add_spacer(height=SPACING)
                        dpg.add_text("", tag="logerr", color=(255, 0, 0))  # Colore rosso per errori
                        dpg.add_spacer(height=SPACING * 2)  # Spaziatore in basso

                    dpg.add_spacer(tag="spaziatore_destro", width=300)  # Spaziatore a destra

            # Tab Chat
            with dpg.tab(label="chat_globale", tag="chat", show=False):
                dpg.add_spacer(height=5)
                dpg.add_text("CHAT GLOBALE", tag="chat_title", color=[255, 255, 255])
                dpg.add_input_text(
                    tag="chatlog_field", multiline=True, readonly=True, tracked=True,
                    track_offset=1)
                dpg.add_spacer(height=SPACING)

                # Gruppo per il messaggio di testo
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="input_txt", multiline=True)
                    dpg.add_spacer(width=SPACING)  # Spaziatore a destra
                    dpg.add_button(label="Invia", tag="send_button", callback=invia)

                dpg.add_spacer(height=5)

                # Gruppo per la selezione del file
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="file_field", multiline=True, readonly=True)
                    dpg.add_spacer(width=SPACING)  # Spaziatore a destra
                    dpg.add_button(label="File", tag="file_button", callback=carica_file)

                dpg.add_spacer(height=5)

                # Gruppo per la cartella di download
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag="cartella_download", multiline=True, readonly=True,
                                       default_value=os.path.expanduser("~/Downloads"))
                    dpg.add_spacer(width=SPACING)
                    dpg.add_button(label="Set Download Folder", tag="btn_selezione_cartella_download",
                                   callback=seleziona_cartella_download)

            with dpg.tab(label="Chat private", tag="chat_private", show=False):
                dpg.add_spacer(height=5)
                with dpg.group(horizontal=True):
                    # finestra a sinistra con la lista dei contatti
                    with dpg.child_window(tag="pannello_contatti", width=250, border=True):
                        dpg.add_text("Contatti", color=[255, 255, 255])
                        dpg.add_separator()

                        # finestra con la lista dei contatti
                        with dpg.child_window(tag="lista_contatti", height=-35, border=False):
                            # I contatti saranno aggiunti in runtime nella lista (col pulsante apposito)
                            pass

                        # Pulsante per aggiungere nuovi contatti
                        dpg.add_button(label="Aggiungi contatto", tag="btn_aggiungi_contatto",
                                       callback=mostra_aggiungi_contatti, width=-1)

                    # finestra a destra con la chat selezionata da visualizzare
                    with dpg.child_window(tag="chat_attiva", width=-1, border=True):
                        # titolo/nome della chat
                        with dpg.group(horizontal=True, tag="Nome_chat"):
                            dpg.add_text("Seleziona una chat", tag="titolo_chat_attiva")
                            dpg.add_spacer(width=348)
                            dpg.add_button(label="Chiama", tag="btn_chiama_privato", callback=chiama_privato, width=70)
                            dpg.add_button(label="Videochiama", tag="btn_videochiama_privato", callback=videochiama_privato, width=90)

                        dpg.add_separator()

                        # Chat log privata
                        dpg.add_input_text(tag="chatlog_field_privata", multiline=True,
                                           readonly=True, height=-70, width=-1)

                        # Area di input
                        with dpg.group(horizontal=True):
                            dpg.add_input_text(tag="input_txt_chat_privata", multiline=False, width=-100)
                            dpg.add_button(label="Invia", tag="btn_invia_messaggio_privato",
                                           callback=invia_messaggio_privato, width=80)

                        with dpg.group(horizontal=True):
                            dpg.add_input_text(tag="file_field_privata", multiline=False, readonly=True, width=-120)
                            dpg.add_button(label="File", tag="btn_file_chat_privata", callback=select_private_file,
                                           width=100)


def chiama_privato():
    global chiamata_in_corso, socket_chiamata, is_video, audioStream, VideoCapture, p, utente_in_chiamata
    try:
        dpg.configure_item("btn_chiama_privato", enabled=False)
        dpg.configure_item("btn_videochiama_privato", enabled=False)
        utente_da_chiamare = username_client_chat_corrente
        client_socket.send(f"CALLREQUEST:{utente_da_chiamare}".encode('utf-8'))
        ip_utente_da_chiamare = client_socket.recv(BUFFER_SIZE).decode('utf-8')
        socket_chiamata = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_chiamata.connect((ip_utente_da_chiamare, PORT_CHIAMATE))
        socket_chiamata.send(f"CALLREQUEST:{dpg.get_value("username")}:{is_video}".encode('utf-8'))  # is_video è False siccome stiamo chiamando normalmente, sennò True
        response = socket_chiamata.recv(BUFFER_SIZE).decode('utf-8')
        if response is "CALLREQUEST:ACCEPTED":
            chiamata_in_corso = True
            p = pyaudio.PyAudio()
            audioStream = p.open(
                format=FORMAT,
                rate=RATE,
                channels=CHANNEL,
                input=True,
                output=True,
                frames_per_buffer=CHUNK
            )

            audio_thread = threading.Thread(target=gestisci_audio)
            audio_thread.start()
            mostra_finestra_chiamata()
    except Exception as e:
        print(f"Errore nell'inizializzazione della chiamata: {e}")
        termina_chiamata()


def videochiama_privato():
    global chiamata_in_corso, socket_chiamata, is_video, audioStream, VideoCapture, p, utente_in_chiamata
    pass

def mostra_finestra_chiamata():
    global utente_in_chiamata
    dpg.window()

def gestisci_audio():
    global chiamata_in_corso, socket_chiamata, audioStream
    try:
        while chiamata_in_corso and socket_chiamata:
            #invio audio
            audio_data = audioStream.read(CHUNK, exception_on_overlfow=False)
            socket_chiamata.send(audio_data)

            #ricevo audio
            try:
                socket_chiamata.settimeout(0.1) #diamo un minimo di tempo al destinatario di inviare l'audio
                audio_ricevuto = socket_chiamata.recv(CHUNK * 4) # inserisco il buffer che consiglia la documentazione
                if audio_ricevuto:
                    audioStream.write(audio_ricevuto)
            except socket_chiamata.timeout:
                pass # vuol dire che non abbiamo ricevuto nessun audio quindi semplicemente continua
    except Exception as e:
        print(f"Errore nella gestione dell'audio: {e}")

def termina_chiamata():
    global chiamata_in_corso, socket_chiamata, is_video, audioStream, VideoCapture, p, utente_in_chiamata
    pass

def select_private_file():
    #Apre un dialog per selezionare un file da inviare in chat privata
    if not username_client_chat_corrente:
        dpg.set_value("logerr", "Seleziona prima un contatto")
        return

    if getattr(select_private_file, 'in_progress', False):
        return

    select_private_file.in_progress = True
    dpg.configure_item("btn_file_chat_privata", enabled=False)

    # Usa la stessa logica di selezione file che hai già implementato
    temp_file = tempfile.mktemp()
    system = platform.system()

    if system == 'Darwin':  # macOS
        # Usa AppleScript direttamente per un dialogo di selezione file nativo
        # che sarà sempre in primo piano
        applescript = f'''
            tell application "System Events"
                activate
            end tell
            set selectedFile to choose file with prompt "Seleziona un file da inviare"
            set filePath to POSIX path of selectedFile
            do shell script "echo " & quoted form of filePath & " > {temp_file}"
            '''

        try:
            # Esegui AppleScript
            subprocess.run(["osascript", "-e", applescript], check=False)
        except Exception as e:
            print(f"Errore nell'esecuzione di AppleScript: {e}")
    else:
        # Per Windows e altri sistemi, usa il metodo Tkinter come prima
        script_file = tempfile.mktemp(suffix='.py')
        with open(script_file, 'w') as f:
            f.write("""
    import tkinter as tk
    from tkinter import filedialog
    import sys

    root = tk.Tk()
    root.attributes('-topmost', True)
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Seleziona un file da inviare",
        filetypes=[("Tutti i file", "*"), ("File di testo", "*.txt")]
    )

    if file_path:
        with open(sys.argv[1], 'w') as f:
            f.write(file_path)
    """)

        # Esegui lo script in un processo separato
        subprocess.run([sys.executable, script_file, temp_file], check=False)

        # Pulisci il file dello script
        try:
            if os.path.exists(script_file):
                os.remove(script_file)
        except:
            pass

    try:
        # Leggi il risultato
        if os.path.exists(temp_file) and os.path.getsize(temp_file) > 0:
            with open(temp_file, 'r') as f:
                file_path = f.read().strip()
                if file_path:
                    dpg.set_value("file_field_privata", file_path)
                    print(f"File selezionato per chat privata: {file_path}")
    finally:
        # Pulisci il file temporaneo
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except:
            pass

        dpg.configure_item("btn_file_chat_privata", enabled=True)
        select_private_file.in_progress = False

def invia_messaggio_privato():
    #Invia un messaggio privato o un file al contatto attuale
    global client_socket, username_client_chat_corrente, chat_attive

    if not username_client_chat_corrente:
        dpg.set_value("logerr", "Seleziona prima un contatto")
        return

    msg = dpg.get_value("input_txt_chat_privata")
    file_field = dpg.get_value("file_field_privata")

    # Verifica se sono entrambi vuoti
    if not msg and not file_field:
        return

    timestamp = str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # Priorità all'invio del file
    if file_field:
        try:
            # Verifica che il file esista
            if not os.path.exists(file_field):
                dpg.set_value("logerr", f"Errore: il file {file_field} non esiste")
                return

            # Verifica che il file non sia vuoto
            if os.path.getsize(file_field) == 0:
                dpg.set_value("logerr", "Errore: il file è vuoto")
                return

            # Ottieni il nome del file dal percorso
            name_file = os.path.basename(file_field)

            # Forza una riconnessione FTP
            ftp_success = setup_connection_server_FTP()
            if not ftp_success:
                dpg.set_value("logerr", "Errore nella connessione FTP. Impossibile inviare il file.")
                return

            # Aggiungi messaggio alla chat (prima dell'invio)
            message = f"\n{timestamp} - Tu -> Invio del file {name_file} in corso..."
            chat_attive[username_client_chat_corrente] += message
            dpg.set_value("chatlog_field_privata", chat_attive[username_client_chat_corrente])

            # Invia il file tramite FTP
            with open(file_field, 'rb') as file:
                print(f"Invio del file {name_file} in chat privata con {username_client_chat_corrente}...")
                ftp_server.storbinary(f"STOR {name_file}", file)
                print(f"File {name_file} inviato con successo")

            # Dopo il caricamento FTP, notifica il server
            # Formato: PRIVATE:sending_file:destinatario:timestamp:nome_file
            file_notification = f"PRIVATE:sending_file:{username_client_chat_corrente}:{timestamp}:{name_file}"
            client_socket.send(file_notification.encode('utf-8'))

            # Aggiorna il messaggio nella chat
            sent_message = f"\n{timestamp} - Tu -> File {name_file} inviato con successo"
            chat_attive[username_client_chat_corrente] = chat_attive[username_client_chat_corrente].replace(message,sent_message)
            dpg.set_value("chatlog_field_privata", chat_attive[username_client_chat_corrente])

            # Pulisci il campo file dopo l'invio
            dpg.set_value("file_field_privata", "")

        except Exception as e:
            error_msg = f"Errore nell'invio del file: {e}"
            dpg.set_value("logerr", error_msg)

            # Aggiorna il log con l'errore
            error_message = f"\n{timestamp} - Tu -> Errore nell'invio del file {os.path.basename(file_field)}"
            chat_attive[username_client_chat_corrente] += error_message
            dpg.set_value("chatlog_field_privata", chat_attive[username_client_chat_corrente])

    elif msg:  # Solo se c'è un messaggio e non un file
        try:
            # Invia il messaggio privato - MODIFICATO IL FORMATO
            client_socket.send(f"PRIVATE:{username_client_chat_corrente}:{msg}".encode("utf-8"))

            # Aggiungi il messaggio alla chat locale con formato standardizzato
            formatted_msg = f"\n{timestamp} - Tu --> {msg}"
            chat_attive[username_client_chat_corrente] += formatted_msg
            dpg.set_value("chatlog_field_privata", chat_attive[username_client_chat_corrente])

            # Pulisci il campo di input
            dpg.set_value("input_txt_chat_privata", "")

        except Exception as e:
            error_msg = f"Errore durante l'invio del messaggio: {str(e)}"
            dpg.set_value("logerr", error_msg)


def apri_chat_con(utente):
    global username_client_chat_corrente
    print(f"Aprendo chat con {utente}")

    # Imposta l'utente corrente
    username_client_chat_corrente = utente

    # Assicurati che esista una cartella per i download di questa chat
    download_folder = get_chat_download_folder(utente)
    print(f"Cartella download per chat con {utente}: {download_folder}")

    # Aggiorna l'intestazione della chat
    dpg.set_value("titolo_chat_attiva", f"Chat con {username_client_chat_corrente}")

    # Mostra la cronologia dei messaggi
    if utente in chat_attive:
        dpg.set_value("chatlog_field_privata", chat_attive[utente])
    else:
        dpg.set_value("chatlog_field_privata", "")
        chat_attive[utente] = ""


def aggiorna_lista_contatti():
    #Aggiorna la lista dei contatti nella finestra laterale

    # Pulisci la lista precedente

    if dpg.does_item_exist("lista_contatti"):
        dpg.delete_item("lista_contatti", children_only=True)

        # Aggiungi i contatti con cui abbiamo una chat attiva
        for username in chat_attive.keys():
            dpg.add_button(
                label=username,
                tag=f"contact_{username}",
                callback=apri_chat_con(username), #funzione lambda senza nome
                width=-1,
                parent="lista_contatti"
            )


def inizia_chat_con(utente):
    #Inizia una nuova chat con un utente
    if utente not in chat_attive:
        chat_attive[utente] = ""
        aggiorna_lista_contatti()
        private_chat_download_directory = f"/Users/simo/Documents/GitHub/Senza nome/SocketChat/client_chats_file_directory/{utente}"
        if not os.path.exists(private_chat_download_directory):
            os.makedirs(private_chat_download_directory)
            print(f"Creata cartella di download: {private_chat_download_directory}")

    print(f"funzione inizia chat con {utente}")

    # Apre la chat con l'utente scelto
    apri_chat_con(utente)

    # Chiude la finestra dell'aggiungi contatti
    if dpg.does_item_exist("finestra_aggiungi_contatto"):
        dpg.delete_item("finestra_aggiungi_contatto")


def mostra_aggiungi_contatti():
    global utenti_disponibili

    if dpg.does_item_exist("finestra_aggiungi_contatto"):
        dpg.delete_item("finestra_aggiungi_contatto")

    with dpg.window(label="Aggiungi contatto", tag="finestra_aggiungi_contatto",
                    modal=True, width=300, height=400):
        dpg.add_text("Utenti disponibili:")
        dpg.add_separator()

        with dpg.child_window(tag="lista_utenti_disponibili", height=300, width=-1):
            for user in utenti_disponibili:
                print(user)
                #if user != nome_utente_personale:  Non mostrare l'utente corrente
                dpg.add_button(label=user, tag=f"add_user_{user}",
                                   callback=lambda:inizia_chat_con(user), width=-1) #lambda è una funzione senza nome. Se non facessi così non potrei passare nulla come argomento o mi eseguirebbe subito la funzione con le parentesi

        dpg.add_button(label="Chiudi", callback=lambda:dpg.delete_item("finestra_aggiungi_contatto"), width=-1)


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