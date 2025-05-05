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
import re  # Aggiungi qui

#import per le chiamate e le videochiamate
import pyaudio # con questo modulo gestisco l'audio in input e in output
import numpy as np
import struct
import pickle
import cv2 # con questo modulo gestisco la videocamera e i frame ricevuti dall'altro client


import dearpygui.dearpygui as dpg
from tkfilebrowser import askopendirname, askopenfilename
from dearpygui.dearpygui import configure_item

# Variabili per il controllo della frequenza di aggiornamento della UI
UI_UPDATE_INTERVAL = 0.1  # Intervallo in secondi per aggiornare l'interfaccia utente
last_ui_update_time = 0  # Timestamp dell'ultimo aggiornamento UI

# Costanti per le chiamate e le videochiamate
# Miglioramento della qualità audio
CHUNK = 512  # Ridotto da 1024 per ridurre la latenza audio
FORMAT = pyaudio.paInt16
CHANNEL = 1
RATE = 44100 # valore che consiglia la documentazione
PORT_CHIAMATE = 12347
PORT_RICEZIONE_COMANDI = 12353
PORT_INVIO_COMANDI = 12354
PORT_INVIO_AUDIO = 12349
PORT_INVIO_VIDEO = 12350
PORT_RICEZIONE_AUDIO = 12351
PORT_RICEZIONE_VIDEO = 12352
PORT_ATTESA_CHIAMATE = 12348

# Altre costanti

SERVER_IP = "172.20.10.3" #ip server a cui collegarsi
DEFAULT_PORT = 12345
BUFFER_SIZE = 4096  # Aumentato da 1024 per migliorare la stabilità
call_requests_thread = None

dpg.create_context()
dpg.create_viewport(title='Socket Chat', width=950, height=800)

# variabili globali per le chiamate e le videochiamate

chiamata_in_corso = False
socket_chiamata = None
socket_chiamata_invio_audio = None
socket_chiamata_invio_video = None
socket_chiamata_ricezione_audio = None
socket_chiamata_ricezione_video = None
is_video = False
is_audio_on = True
is_video_on = True
audioStream = None
VideoCapture = None
p = None # istanza di pyaudio
utente_in_chiamata = ""
ip_chiamata_destinatario = ""

# altre variabili globali

chatlog_lock = threading.Lock()
lock_audio = threading.Lock()
lock_video = threading.Lock()
chatlog = ""
download_folders = {}  # username -> cartella di download per la chat
client_socket = None
server_started = False
nome_utente_personale = ""
ftp_server = None
ftp_client = None
termina_thread_listen_for_calls = True

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

if os.name == 'nt':  # Windows
    try:
        import win32api, win32process, win32con
    except ImportError:
        pass  # Gestiremo questo caso nella funzione set_thread_priority


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
    base_download_folder = 'client_chats_file_directory'
    if not base_download_folder:
        base_download_folder = os.path.join(os.path.expanduser("~"), "Downloads")  # Default

    # Crea una cartella con nome dell'utente
    safe_username = "".join(c for c in username if c.isalnum() or c in [' ', '_', '-']).strip()
    chat_folder = os.path.join(base_download_folder, f"Chat_{safe_username}")

    # Crea la directory se non esiste
    if not os.path.exists(chat_folder):
        os.makedirs(chat_folder)

    # Memorizza la cartella per uso futuro
    download_folders[username] = chat_folder

    return chat_folder


def set_thread_priority(thread_type="audio"):
    """Imposta la priorità del thread corrente in base al tipo.

    Args:
        thread_type: Tipo di thread ("audio", "video", o "ui")
    """
    # Solo su Windows possiamo impostare la priorità
    if os.name == 'nt':
        try:
            thread_id = win32api.GetCurrentThreadId()
            thread_handle = win32api.OpenThread(win32con.THREAD_SET_INFORMATION, False, thread_id)

            if thread_type == "audio":
                # Massima priorità per l'audio
                win32process.SetThreadPriority(thread_handle, win32process.THREAD_PRIORITY_TIME_CRITICAL)
            elif thread_type == "video":
                # Alta priorità per il video
                win32process.SetThreadPriority(thread_handle, win32process.THREAD_PRIORITY_HIGHEST)
            elif thread_type == "ui":
                # Priorità normale per l'UI
                win32process.SetThreadPriority(thread_handle, win32process.THREAD_PRIORITY_NORMAL)
        except Exception as e:
            print(f"Errore nell'impostazione della priorità del thread {thread_type}: {e}")

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
    global client_socket, server_started, nome_utente_personale, call_requests_thread, termina_thread_listen_for_calls
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
        response = client_socket.recv(BUFFER_SIZE).decode("utf-8")
        splittedResponse = response.split(':', 1)

        if splittedResponse[0] != "Autenticazione riuscita":
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

        # Configura socket per le chiamate in arrivo
        try:
            # Ferma qualsiasi thread di ascolto precedente
            termina_thread_listen_for_calls = True
            if call_requests_thread and call_requests_thread.is_alive():
                time.sleep(1.0)
            termina_thread_listen_for_calls = False

            # Crea il socket
            socket_attesa_chiamate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_attesa_chiamate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            socket_attesa_chiamate.settimeout(1.0)  # Socket non bloccante

            # Legati a PORT_CHIAMATE
            socket_attesa_chiamate.bind(("0.0.0.0", PORT_CHIAMATE))
            socket_attesa_chiamate.listen(1)

            print(f"Socket per richieste di chiamata configurato su porta {PORT_CHIAMATE}")

            # Avvia thread per ascoltare le chiamate
            call_requests_thread = threading.Thread(target=listen_for_call_request, args=(socket_attesa_chiamate,))
            call_requests_thread.daemon = True
            call_requests_thread.start()

        except Exception as e:
            print(f"Errore nella configurazione del socket per le chiamate: {e}")
            # Non fallire il login se il socket per le chiamate non può essere configurato

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


def accetta_chiamata(chiChiama, is_videochiamata, client):
    """
    Accetta una chiamata in arrivo e inizializza le risorse audio/video.
    """
    global socket_chiamata, chiamata_in_corso, p, audioStream, VideoCapture, is_video, utente_in_chiamata
    global socket_chiamata_invio_audio, socket_chiamata_invio_video, socket_chiamata_ricezione_audio, socket_chiamata_ricezione_video
    global socket_comandi_input, socket_comandi_output

    try:
        print(f"Accettando chiamata da {chiChiama}, video={is_videochiamata}")

        # Chiudi la finestra di richiesta PRIMA di tutto il resto
        if dpg.does_item_exist("finestra_richiesta_chiamata"):
            dpg.delete_item("finestra_richiesta_chiamata")

        # Invia l'accettazione
        client.send("CALLREQUEST:ACCEPT".encode('utf-8'))

        # Imposta le variabili globali
        socket_chiamata = client
        chiamata_in_corso = True
        is_video = is_videochiamata
        utente_in_chiamata = chiChiama

        # Crea tutti i socket necessari
        socket_chiamata_invio_audio = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_chiamata_invio_audio.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socket_chiamata_invio_audio.settimeout(1.0)

        socket_chiamata_ricezione_audio = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_chiamata_ricezione_audio.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socket_chiamata_ricezione_audio.settimeout(1.0)

        socket_comandi_input = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_comandi_input.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socket_comandi_input.settimeout(1.0)

        socket_comandi_output = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_comandi_output.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socket_comandi_output.settimeout(1.0)

        if is_videochiamata:
            socket_chiamata_invio_video = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_chiamata_invio_video.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            socket_chiamata_invio_video.settimeout(1.0)

            socket_chiamata_ricezione_video = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_chiamata_ricezione_video.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            socket_chiamata_ricezione_video.settimeout(1.0)

        # Configura i socket per attendere connessioni
        try:
            socket_chiamata_invio_audio.bind(("0.0.0.0", PORT_INVIO_AUDIO))
            socket_chiamata_invio_audio.listen(1)
            print(f"Socket invio audio in ascolto su porta {PORT_INVIO_AUDIO}")

            socket_chiamata_ricezione_audio.bind(("0.0.0.0", PORT_RICEZIONE_AUDIO))
            socket_chiamata_ricezione_audio.listen(1)
            print(f"Socket ricezione audio in ascolto su porta {PORT_RICEZIONE_AUDIO}")

            socket_comandi_input.bind(("0.0.0.0", PORT_RICEZIONE_COMANDI))
            socket_comandi_input.listen(1)
            print(f"Socket comandi input in ascolto su porta {PORT_RICEZIONE_COMANDI}")

            socket_comandi_output.bind(("0.0.0.0", PORT_INVIO_COMANDI))
            socket_comandi_output.listen(1)
            print(f"Socket comandi output in ascolto su porta {PORT_INVIO_COMANDI}")

            if is_videochiamata:
                socket_chiamata_invio_video.bind(("0.0.0.0", PORT_INVIO_VIDEO))
                socket_chiamata_invio_video.listen(1)
                print(f"Socket invio video in ascolto su porta {PORT_INVIO_VIDEO}")

                socket_chiamata_ricezione_video.bind(("0.0.0.0", PORT_RICEZIONE_VIDEO))
                socket_chiamata_ricezione_video.listen(1)
                print(f"Socket ricezione video in ascolto su porta {PORT_RICEZIONE_VIDEO}")
        except OSError as e:
            if e.errno == 48:  # Address already in use
                print(f"Errore: porta già in uso. Potrebbe esserci una chiamata attiva non terminata correttamente.")
                client.send("CALLREQUEST:ERROR".encode('utf-8'))
                return
            raise

        # Accetta connessioni per audio e comandi
        print("In attesa di connessioni dai socket...")

        # Utilizziamo un timeout per non bloccare indefinitamente
        start_time = time.time()
        max_wait_time = 10  # 10 secondi di timeout totale

        socket_invio_audio_conn = None
        socket_ricezione_audio_conn = None
        socket_comandi_input_conn = None
        socket_comandi_output_conn = None
        socket_invio_video_conn = None
        socket_ricezione_video_conn = None

        while time.time() - start_time < max_wait_time:
            try:
                # Prova a accettare connessioni per tutti i socket
                if socket_invio_audio_conn is None:
                    socket_chiamata_invio_audio.settimeout(0.1)
                    socket_invio_audio_conn, _ = socket_chiamata_invio_audio.accept()
                    print("Connessione accettata per invio audio")

                if socket_ricezione_audio_conn is None:
                    socket_chiamata_ricezione_audio.settimeout(0.1)
                    socket_ricezione_audio_conn, _ = socket_chiamata_ricezione_audio.accept()
                    print("Connessione accettata per ricezione audio")

                if socket_comandi_input_conn is None:
                    socket_comandi_input.settimeout(0.1)
                    socket_comandi_input_conn, _ = socket_comandi_input.accept()
                    print("Connessione accettata per comandi input")

                if socket_comandi_output_conn is None:
                    socket_comandi_output.settimeout(0.1)
                    socket_comandi_output_conn, _ = socket_comandi_output.accept()
                    print("Connessione accettata per comandi output")

                if is_videochiamata:
                    if socket_invio_video_conn is None:
                        socket_chiamata_invio_video.settimeout(0.1)
                        socket_invio_video_conn, _ = socket_chiamata_invio_video.accept()
                        print("Connessione accettata per invio video")

                    if socket_ricezione_video_conn is None:
                        socket_chiamata_ricezione_video.settimeout(0.1)
                        socket_ricezione_video_conn, _ = socket_chiamata_ricezione_video.accept()
                        print("Connessione accettata per ricezione video")

                # Verifica se tutte le connessioni necessarie sono state stabilite
                if socket_invio_audio_conn and socket_ricezione_audio_conn and socket_comandi_input_conn and socket_comandi_output_conn:
                    if not is_videochiamata or (socket_invio_video_conn and socket_ricezione_video_conn):
                        break  # Tutte le connessioni stabilite

            except socket.timeout:
                # Timeout normale per i socket non bloccanti
                pass

            except Exception as e:
                print(f"Errore durante l'accettazione delle connessioni: {e}")
                break

            # Breve pausa per evitare di sovraccaricare la CPU
            time.sleep(0.01)

        # Verifica se tutte le connessioni sono state stabilite
        if (
                not socket_invio_audio_conn or not socket_ricezione_audio_conn or not socket_comandi_input_conn or not socket_comandi_output_conn or
                (is_videochiamata and (not socket_invio_video_conn or not socket_ricezione_video_conn))):
            print("Timeout: non tutte le connessioni sono state stabilite")
            termina_chiamata(True)
            return

        # Inizializza PyAudio
        p = pyaudio.PyAudio()
        audioStream = p.open(
            format=FORMAT,
            rate=RATE,
            channels=CHANNEL,
            input=True,
            output=True,
            frames_per_buffer=CHUNK
        )

        print("Stream audio inizializzato correttamente")

        # Avvia thread invio audio
        audio_invio_thread = threading.Thread(target=gestisci_invio_audio)
        audio_invio_thread.daemon = True
        audio_invio_thread.start()

        # Avvia thread ricezione audio
        audio_ricezione_thread = threading.Thread(target=gestisci_ricezione_audio)
        audio_ricezione_thread.daemon = True
        audio_ricezione_thread.start()

        # Avvia thread gestione comandi input
        comandi_input_thread = threading.Thread(target=gestisci_comandi_input_chiamata)
        comandi_input_thread.daemon = True
        comandi_input_thread.start()

        # Se è una videochiamata, inizializza anche il video
        if is_videochiamata:
            print("Inizializzazione webcam...")
            VideoCapture = cv2.VideoCapture(0)  # 0 è l'indice della webcam predefinita

            # Verifica che la webcam sia stata inizializzata correttamente
            if not VideoCapture.isOpened():
                print("Errore: impossibile aprire la webcam")
            else:
                print("Webcam inizializzata con successo")

                # Avvia i thread con priorità
                video_invio_thread = threading.Thread(target=gestisci_invio_video)
                video_invio_thread.daemon = True
                video_invio_thread.start()

                video_ricezione_thread = threading.Thread(target=gestisci_ricezione_video)
                video_ricezione_thread.daemon = True
                video_ricezione_thread.start()

        # Utilizziamo un brevissimo timeout per dare tempo ai thread di avviarsi
        time.sleep(0.1)

        # Mostra la finestra di chiamata
        try:
            # Assicurati che non ci siano finestre di chiamata esistenti
            if dpg.does_item_exist("finestra_chiamata"):
                dpg.delete_item("finestra_chiamata")

            # Mostra la nuova finestra di chiamata
            mostra_finestra_chiamata("ACCEPTED")
            print("Finestra di chiamata mostrata con successo")
        except Exception as e:
            print(f"Errore nel mostrare la finestra di chiamata: {e}")
            # Tentiamo di nuovo dopo un breve ritardo
            time.sleep(0.5)
            try:
                mostra_finestra_chiamata("ACCEPTED")
                print("Secondo tentativo di mostrare la finestra riuscito")
            except Exception as e2:
                print(f"Fallito anche il secondo tentativo: {e2}")

    except Exception as e:
        print(f"Errore nell'accettazione della chiamata: {e}")
        if socket_chiamata:
            socket_chiamata.close()
            socket_chiamata = None

        # In caso di errore, termina immediatamente la chiamata
        termina_chiamata(True)


def rifiuta_chiamata(chiChiama, client):
    """
    Rifiuta una chiamata in arrivo e invia la notifica al mittente.
    """
    try:
        print(f"Rifiutando chiamata da {chiChiama}")
        client.send("CALLREQUEST:REFUSE".encode('utf-8'))

        # Chiudi il socket dopo aver inviato il rifiuto
        client.close()

        # Chiudi la finestra di notifica
        if dpg.does_item_exist("finestra_richiesta_chiamata"):
            dpg.delete_item("finestra_richiesta_chiamata")
    except Exception as e:
        print(f"Errore nel rifiuto della chiamata: {e}")


def notifica_chiamata(chiChiama, client):
    """
    Mostra una finestra di notifica per una chiamata in arrivo e
    gestisce l'accettazione o il rifiuto della chiamata.
    """
    global is_video

    # Chiudi eventuali notifiche esistenti prima di crearne una nuova
    if dpg.does_item_exist("finestra_richiesta_chiamata"):
        dpg.delete_item("finestra_richiesta_chiamata")

    # Determina il tipo di chiamata per mostrarlo nella notifica
    if is_video:
        call_type = "Videochiamata"
    else:
        call_type = "Chiamata audio"

    # Calcola la posizione della finestra per centrarla
    viewport_width = dpg.get_viewport_width()
    viewport_height = dpg.get_viewport_height()
    window_width = 350
    window_height = 140
    window_pos = [viewport_width // 2 - window_width // 2, viewport_height // 2 - window_height // 2]

    # Crea la finestra di notifica
    try:
        with dpg.window(label=f"{call_type} in arrivo", tag="finestra_richiesta_chiamata",
                        modal=True, no_collapse=True, no_resize=True, no_close=True,
                        width=window_width, height=window_height, pos=window_pos):

            # Aggiunge il messaggio della chiamata
            dpg.add_spacer(height=10)
            dpg.add_text(f"{chiChiama} ti sta chiamando", color=[255, 255, 255])
            dpg.add_text(f"Tipo: {call_type}", color=[200, 200, 200])
            dpg.add_separator()
            dpg.add_spacer(height=15)

            # Aggiungi pulsanti in riga orizzontale per accettare o rifiutare
            with dpg.group(horizontal=True):
                # Pulsante Accetta
                with dpg.theme() as accept_theme:
                    with dpg.theme_component(dpg.mvButton):
                        dpg.add_theme_color(dpg.mvThemeCol_Button, [46, 120, 50])  # Verde normale
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [66, 150, 70])  # Verde hover
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [36, 100, 40])  # Verde cliccato
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 255])  # Testo bianco

                dpg.add_button(label="Accetta", tag="btn_accetta_chiamata", width=150,
                               callback=lambda: accetta_chiamata(chiChiama, is_video, client))
                dpg.bind_item_theme(dpg.last_item(), accept_theme)

                dpg.add_spacer(width=10)

                # Pulsante Rifiuta
                with dpg.theme() as reject_theme:
                    with dpg.theme_component(dpg.mvButton):
                        dpg.add_theme_color(dpg.mvThemeCol_Button, [150, 40, 40])  # Rosso normale
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [180, 60, 60])  # Rosso hover
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [120, 30, 30])  # Rosso cliccato
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 255])  # Testo bianco

                dpg.add_button(label="Rifiuta", tag="btn_rifiuta_chiamata", width=150,
                               callback=lambda: rifiuta_chiamata(chiChiama, client))
                dpg.bind_item_theme(dpg.last_item(), reject_theme)

        print(f"Finestra di notifica chiamata creata per {chiChiama}, tipo={call_type}")

    except Exception as e:
        print(f"Errore nella creazione della finestra di notifica chiamata: {e}")


def listen_for_call_request(socket_attesa_chiamate):
    """
    Thread che ascolta le richieste di chiamata in arrivo.
    Gestisce le connessioni e notifica l'utente quando arriva una chiamata.
    """
    global termina_thread_listen_for_calls, chiamata_in_corso

    print(f"Avvio thread ascolto chiamate su porta {PORT_CHIAMATE}")

    # Per sicurezza, imposta il socket come non bloccante
    socket_attesa_chiamate.settimeout(1.0)

    try:
        while not termina_thread_listen_for_calls:
            # Se c'è già una chiamata in corso, metti in pausa
            if chiamata_in_corso:
                time.sleep(0.5)
                continue

            try:
                # Accetta connessioni con timeout breve
                client, address = socket_attesa_chiamate.accept()
                print(f"Nuova richiesta di connessione da {address}")

                # Resto del codice per gestire la richiesta di chiamata
                # ...

            except socket.timeout:
                # Timeout normale, continua
                continue
            except Exception as e:
                print(f"Errore accept socket: {e}")
                time.sleep(0.5)
                continue
    except Exception as e:
        print(f"Errore thread ascolto chiamate: {e}")
    finally:
        # Chiudi il socket in modo sicuro alla fine
        try:
            socket_attesa_chiamate.close()
        except:
            pass
        print("Thread ascolto chiamate terminato")


def notifica_messaggio_privato(daChi):
    viewport_width = dpg.get_viewport_width()
    viewport_height = dpg.get_viewport_height()
    window_width = 280
    window_height = 100
    margin = 10  # margine in pixel

    # Controlla quale tab è attualmente visibile/selezionata
    current_tab = dpg.get_value("tab_bar")
    # Non mostrare notifiche se l'utente è già nella chat privata
    if not dpg.is_item_visible(
            "chat_private") or current_tab != 2:  # Assumo che "chat_private" sia la terza tab (indice 2)
        if dpg.does_item_exist("notifica_messaggio_privato"):
            dpg.delete_item("notifica_messaggio_privato")

        with dpg.window(label="Nuovo messaggio privato", tag="notifica_messaggio_privato",
                        modal=False, no_collapse=True, no_resize=True,
                        width=window_width, height=window_height,
                        pos=[viewport_width - window_width - margin,
                             viewport_height - window_height - margin]):
            dpg.add_spacer(height=5)
            dpg.add_text(f"{daChi} ti ha mandato un messaggio", color=[255, 255, 255])
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Apri", tag="btn_notifica_privata", width=125,
                               callback=lambda: apri_chat_con(daChi))
                dpg.add_spacer(width=10)
                dpg.add_button(label="Chiudi", tag="btn_destroy_privato", width=125,
                               callback=destroy_notifica)


def notifica_messaggio():
    print("notifica")
    viewport_width = dpg.get_viewport_width()
    viewport_height = dpg.get_viewport_height()
    window_width = 250
    window_height = 100
    margin = 10  # margine in pixel

    # Controlla quale tab è attualmente visibile/selezionata
    current_tab = dpg.get_value("tab_bar")
    # Non mostrare notifiche se l'utente è già nella chat globale
    if not dpg.is_item_visible("chat") or current_tab != 1:  # Assumo che "chat" sia la seconda tab (indice 1)
        if dpg.does_item_exist("notifica_messaggio_globale"):
            dpg.show_item("notifica_messaggio_globale")
            dpg.set_item_pos("notifica_messaggio_globale",
                             [viewport_width - window_width - margin,
                              viewport_height - window_height - margin])
        else:
            with dpg.window(label="Nuovo messaggio", tag="notifica_messaggio_globale",
                            modal=False, no_collapse=True, no_resize=True,
                            width=window_width, height=window_height,
                            pos=[viewport_width - window_width - margin,
                                 viewport_height - window_height - margin]):
                dpg.add_spacer(height=5)
                dpg.add_text("Hai ricevuto un messaggio globale", color=[255, 255, 255])
                dpg.add_spacer(height=10)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Apri", tag="btn_notifica_globale", width=110, callback=apri_globale)
                    dpg.add_spacer(width=10)
                    dpg.add_button(label="Chiudi", tag="btn_destroy_globale", width=110, callback=destroy_notifica)


def apri_globale():
    if dpg.get_value("tab_bar") != 1:
        dpg.set_value("tab_bar", "chat")  # Cambia tab

def destroy_notifica():
    print("entrato distuggi notifica")
    if dpg.does_item_exist("notifica_messaggio_globale"):
        dpg.delete_item("notifica_messaggio_globale")
        print("distrutto privato")
    else:
        dpg.delete_item("notifica_messaggio_privato")


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
                        utenti_disponibili.remove(nome_utente_personale)
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
                        parts = msg.split(":")
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
                            sender, message = content.split(" -->")
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

                            notifica_messaggio_privato(sender)

                    # Non mostrare il messaggio privato nella chat globale
                    continue

            if msg.startswith("IP:CALL:"): # risolto
                keys = msg.split(':')
                # risposta != "Nessun client con quel nome disponibile"
                ip_utente_da_chiamare = keys[2]
                print(ip_utente_da_chiamare)
                dpg.configure_item("btn_videochiama_privato", enabled=False)
                dpg.configure_item("btn_chiama_privato", enabled=False)
                thread_chiama = threading.Thread(target=call, args=(ip_utente_da_chiamare,))
                thread_chiama.start()

            elif msg.startswith("IP:VIDEOCALL:"):
                keys = msg.split(':')
                # risposta != "Nessun client con quel nome disponibile"
                ip_utente_da_chiamare = keys[2]
                print(ip_utente_da_chiamare)
                dpg.configure_item("btn_videochiama_privato", enabled=False)
                dpg.configure_item("btn_chiama_privato", enabled=False)
                thread_chiama = threading.Thread(target=videocall, args=(ip_utente_da_chiamare,))
                thread_chiama.start()

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


def call(ip):
    """
    Inizia una chiamata audio con l'utente all'IP specificato.
    Gestisce correttamente gli errori e mantiene lo stato dell'interfaccia.
    """
    global chiamata_in_corso, socket_chiamata, is_video, audioStream, VideoCapture, p, utente_in_chiamata
    global socket_chiamata_invio_audio, socket_chiamata_ricezione_audio, socket_comandi_input, socket_comandi_output

    # Disabilita immediatamente i pulsanti per evitare chiamate multiple
    dpg.configure_item("btn_videochiama_privato", enabled=False)
    dpg.configure_item("btn_chiama_privato", enabled=False)

    # Prima di iniziare, verifica che non ci sia già una chiamata in corso
    if chiamata_in_corso:
        print("C'è già una chiamata in corso, impossibile avviarne un'altra")
        mostra_finestra_chiamata("ERROR")
        dpg.configure_item("btn_videochiama_privato", enabled=True)
        dpg.configure_item("btn_chiama_privato", enabled=True)
        return

    try:
        is_video = False  # Chiamata normale (solo audio)
        utente_in_chiamata = username_client_chat_corrente

        # Verifica preliminare della connettività
        if not verifica_connettivita(ip, PORT_CHIAMATE, timeout=1):
            print(f"L'utente {utente_in_chiamata} non è raggiungibile sulla porta {PORT_CHIAMATE}")
            mostra_finestra_chiamata("UNREACHABLE")
            dpg.configure_item("btn_videochiama_privato", enabled=True)
            dpg.configure_item("btn_chiama_privato", enabled=True)
            return

        print(f"Chiamata in corso verso IP: {ip}, porta: {PORT_CHIAMATE}")

        # Inizializza il socket principale
        socket_chiamata = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_chiamata.settimeout(5)  # Timeout più breve di 5 secondi
        socket_chiamata.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socket_chiamata.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # Buffer di ricezione più grande
        socket_chiamata.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)  # Buffer di invio più grande
        socket_chiamata.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # Disattiva Nagle's algorithm

        # Tenta la connessione
        try:
            socket_chiamata.connect((ip, PORT_CHIAMATE))
            print(f"Connessione stabilita con {ip}:{PORT_CHIAMATE}")
        except ConnectionRefusedError:
            print(f"Connessione rifiutata da {ip}:{PORT_CHIAMATE}")
            mostra_finestra_chiamata("UNREACHABLE")
            termina_chiamata()
            return
        except socket.timeout:
            print(f"Timeout nella connessione a {ip}:{PORT_CHIAMATE}")
            mostra_finestra_chiamata("TIMEOUT")
            termina_chiamata()
            return
        except Exception as e:
            print(f"Errore di connessione: {e}")
            mostra_finestra_chiamata("ERROR")
            termina_chiamata()
            return

        # Invia richiesta di chiamata - IMPORTANTE: Nome mittente
        request = f"CALLREQUEST:{nome_utente_personale}:{is_video}"
        print(f"Invio richiesta: {request}")
        socket_chiamata.send(request.encode('utf-8'))

        # Attendi risposta
        try:
            response = socket_chiamata.recv(BUFFER_SIZE).decode('utf-8')
            print(f"Risposta ricevuta: {response}")
        except socket.timeout:
            print("Timeout in attesa di risposta alla richiesta di chiamata")
            mostra_finestra_chiamata("TIMEOUT")
            termina_chiamata()
            return
        except Exception as e:
            print(f"Errore nella ricezione della risposta: {e}")
            mostra_finestra_chiamata("ERROR")
            termina_chiamata()
            return

        if response == "CALLREQUEST:ACCEPT":
            # Inizializza i socket ausiliari solo dopo l'accettazione
            socket_chiamata_invio_audio = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_chiamata_invio_audio.settimeout(5)
            socket_chiamata_invio_audio.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            socket_chiamata_invio_audio.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            socket_chiamata_invio_audio.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            socket_chiamata_invio_audio.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            socket_chiamata_ricezione_audio = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_chiamata_ricezione_audio.settimeout(5)
            socket_chiamata_ricezione_audio.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            socket_chiamata_ricezione_audio.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            socket_chiamata_ricezione_audio.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            socket_chiamata_ricezione_audio.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            socket_comandi_input = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_comandi_input.settimeout(5)
            socket_comandi_input.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            socket_comandi_input.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            socket_comandi_input.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            socket_comandi_input.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            socket_comandi_output = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_comandi_output.settimeout(5)
            socket_comandi_output.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            socket_comandi_output.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            socket_comandi_output.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            socket_comandi_output.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            # Connessione ai socket
            try:
                socket_chiamata_invio_audio.connect((ip, PORT_INVIO_AUDIO))
                print(f"Connessione audio invio stabilita con {ip}:{PORT_INVIO_AUDIO}")

                socket_chiamata_ricezione_audio.connect((ip, PORT_RICEZIONE_AUDIO))
                print(f"Connessione audio ricezione stabilita con {ip}:{PORT_RICEZIONE_AUDIO}")

                socket_comandi_input.connect((ip, PORT_RICEZIONE_COMANDI))
                print(f"Connessione comandi input stabilita con {ip}:{PORT_RICEZIONE_COMANDI}")

                socket_comandi_output.connect((ip, PORT_INVIO_COMANDI))
                print(f"Connessione comandi output stabilita con {ip}:{PORT_INVIO_COMANDI}")
            except Exception as e:
                print(f"Errore nella connessione dei socket ausiliari: {e}")
                mostra_finestra_chiamata("ERROR")
                termina_chiamata()
                return

            chiamata_in_corso = True

            # Inizializza PyAudio con impostazioni ottimizzate per la latenza
            p = pyaudio.PyAudio()

            # Cerca di ottenere il buffer size più piccolo possibile supportato dal sistema
            min_buffer = CHUNK

            # Apre lo stream audio con impostazioni ottimizzate per bassa latenza
            audioStream = p.open(
                format=FORMAT,
                rate=RATE,
                channels=CHANNEL,
                input=True,
                output=True,
                frames_per_buffer=min_buffer,
                input_host_api_specific_stream_info=get_low_latency_settings(),
                output_host_api_specific_stream_info=get_low_latency_settings()
            )

            print("Stream audio inizializzato con impostazioni a bassa latenza")

            # Avvia thread invio audio
            audio_invio_thread = threading.Thread(target=gestisci_invio_audio)
            audio_invio_thread.daemon = True
            audio_invio_thread.start()

            # Avvia thread ricezione audio
            audio_ricezione_thread = threading.Thread(target=gestisci_ricezione_audio)
            audio_ricezione_thread.daemon = True
            audio_ricezione_thread.start()

            # Avvia thread gestione comandi input
            comandi_input_thread = threading.Thread(target=gestisci_comandi_input_chiamata)
            comandi_input_thread.daemon = True
            comandi_input_thread.start()

            # Piccolo timeout per dare tempo ai thread di avviarsi
            time.sleep(0.05)

            # Mostra finestra di chiamata
            mostra_finestra_chiamata("ACCEPTED")

        else:
            print(f"Chiamata rifiutata: {response}")
            mostra_finestra_chiamata("REFUSED")
            termina_chiamata()

    except Exception as e:
        print(f"Errore generale durante la chiamata: {e}")
        mostra_finestra_chiamata("ERROR")
        termina_chiamata()


def gestisci_comandi_input_chiamata():
    """
    Gestisce i comandi in ingresso durante una chiamata in modo robusto.
    Utilizza un meccanismo di timeout avanzato per evitare blocchi.
    """
    global socket_comandi_input, chiamata_in_corso

    print("Avvio thread gestione comandi input")

    # Loop principale con controllo attivo della chiamata
    while chiamata_in_corso and socket_comandi_input:
        try:
            # Verifica che il socket sia ancora valido
            if not socket_comandi_input:
                break

            # Imposta timeout breve per evitare blocchi
            socket_comandi_input.settimeout(0.5)

            try:
                # Prova a ricevere un comando
                comando = socket_comandi_input.recv(BUFFER_SIZE).decode('utf-8')

                # Gestisci il comando se presente
                if comando:
                    print(f"Comando ricevuto: {comando}")
                    if comando == "TERMINA":
                        print("Comando di terminazione ricevuto")
                        termina_chiamata()
                        break
            except socket.timeout:
                # Timeout normale, verifichiamo se la chiamata è ancora attiva
                if not chiamata_in_corso:
                    break
                continue
            except ConnectionResetError:
                print("Connessione reset dal peer")
                termina_chiamata()
                break
            except Exception as e:
                print(f"Errore ricezione comando: {e}")
                # Non terminiamo immediatamente per errori temporanei
                time.sleep(0.1)
                continue

        except Exception as e:
            print(f"Errore gestione comandi input: {e}")
            if not chiamata_in_corso:
                break
            time.sleep(0.1)

        # Breve pausa per ridurre l'utilizzo della CPU
        time.sleep(0.01)

    print("Thread gestione comandi input terminato")

def debug_richiesta_ip(destinatario, is_video):
    """
    Funzione di supporto per debuggare la richiesta IP
    Utile per verificare che la richiesta al server sia formattata correttamente
    """
    print("\n--- Debug richiesta IP ---")
    print(f"Destinatario: {destinatario}")
    print(f"Is video: {is_video}")

    # Costruisci il comando corretto
    is_video_str = "True" if is_video else "False"
    comando = f"PRIVATE:IP_REQUEST:{destinatario}:{is_video_str}"
    print(f"Comando da inviare: {comando}")

    # Ritorna il comando per uso immediato
    return comando


def get_low_latency_settings():
    """
    Crea impostazioni a bassa latenza specifiche per l'host API
    """
    try:
        # Su Windows, utilizziamo le impostazioni WASAPI per la bassa latenza
        if os.name == 'nt':
            if not hasattr(pyaudio.PaMacCoreStreamInfo, 'kAudioLowLatencyMode'):
                # Creazione di strutture dati per le API WASAPI
                # (questo è uno stub, pyaudio non fornisce direttamente queste API)
                return None

        # Su macOS, utilizziamo Core Audio per la bassa latenza
        elif sys.platform == 'darwin':
            # Richiede pyaudio compilato con supporto Core Audio
            if hasattr(pyaudio, 'paMacCoreStreamInfo'):
                stream_info = pyaudio.PaMacCoreStreamInfo(
                    flags=pyaudio.PaMacCoreStreamInfo.kAudioLowLatencyMode
                )
                return stream_info

        # Su Linux, utilizziamo ALSA o PulseAudio
        else:
            # Impostazioni specifiche per ALSA/PulseAudio
            # (questo è uno stub perché pyaudio non fornisce un'API specifica)
            return None
    except Exception as e:
        print(f"Avviso: Impossibile creare impostazioni a bassa latenza: {e}")

    return None


def get_low_latency_settings():
    """
    Crea impostazioni a bassa latenza specifiche per l'host API
    """
    try:
        # Su Windows, utilizziamo le impostazioni WASAPI per la bassa latenza
        if os.name == 'nt':
            if not hasattr(pyaudio.PaMacCoreStreamInfo, 'kAudioLowLatencyMode'):
                # Creazione di strutture dati per le API WASAPI
                # (questo è uno stub, pyaudio non fornisce direttamente queste API)
                return None

        # Su macOS, utilizziamo Core Audio per la bassa latenza
        elif sys.platform == 'darwin':
            # Richiede pyaudio compilato con supporto Core Audio
            if hasattr(pyaudio, 'paMacCoreStreamInfo'):
                stream_info = pyaudio.PaMacCoreStreamInfo(
                    flags=pyaudio.PaMacCoreStreamInfo.kAudioLowLatencyMode
                )
                return stream_info

        # Su Linux, utilizziamo ALSA o PulseAudio
        else:
            # Impostazioni specifiche per ALSA/PulseAudio
            # (questo è uno stub perché pyaudio non fornisce un'API specifica)
            return None
    except Exception as e:
        print(f"Avviso: Impossibile creare impostazioni a bassa latenza: {e}")

    return None


def detect_mobile_hotspot(ip):
    """
    Tenta di rilevare se la connessione è su un hotspot mobile
    basandosi sul ping e sul pattern dell'indirizzo IP
    """
    try:
        # Fai un test di ping per verificare latenza e jitter
        ping_count = 3
        if os.name == 'nt':  # Windows
            ping_cmd = f"ping -n {ping_count} {ip}"
        else:  # Linux/Mac
            ping_cmd = f"ping -c {ping_count} {ip}"

        ping_result = subprocess.run(ping_cmd, shell=True, capture_output=True, text=True)

        if ping_result.returncode == 0:
            output = ping_result.stdout

            # Estrai i tempi di ping
            ping_times = []
            if os.name == 'nt':  # Windows
                pattern = r'tempo=(\d+)ms'
            else:  # Linux/Mac
                pattern = r'time=(\d+\.\d+) ms'

            matches = re.findall(pattern, output)
            for match in matches:
                ping_times.append(float(match))

            # Calcola il ping medio e jitter
            if ping_times:
                avg_ping = sum(ping_times) / len(ping_times)

                # Calcola il jitter (variazione del ping)
                if len(ping_times) > 1:
                    jitter = sum(abs(ping_times[i] - ping_times[i - 1]) for i in range(1, len(ping_times))) / (
                                len(ping_times) - 1)
                else:
                    jitter = 0

                print(f"Test connessione: ping={avg_ping:.1f}ms, jitter={jitter:.1f}ms")

                # Indicatori di hotspot mobile:
                # 1. Ping elevato (>50ms) per connessioni locali
                # 2. Jitter elevato (>10ms)
                if avg_ping > 50 or jitter > 10:
                    print("Rilevamento automatico: probabile hotspot mobile")
                    return True

        # Verifica range IP tipici degli hotspot
        hotspot_patterns = [
            r'^192\.168\.43\.',  # Tipico di hotspot Android
            r'^172\.20\.10\.',  # Tipico di hotspot iOS
            r'^10\.0\.0\.'  # Alcuni hotspot
        ]

        for pattern in hotspot_patterns:
            if re.match(pattern, ip):
                print(f"Rilevato IP tipico di hotspot mobile: {ip}")
                return True

    except Exception as e:
        print(f"Errore nel rilevamento hotspot: {e}")

    return False


def gestisci_comandi_chiamata():
    """
    Gestisce i comandi durante una chiamata.
    Versione robusta che gestisce meglio i timeout.
    """
    global chiamata_in_corso, socket_comandi_input

    print("Avvio thread gestione comandi")

    try:
        while chiamata_in_corso:
            try:
                # Verifica che il socket sia valido
                if socket_comandi_input:
                    socket_comandi_input.settimeout(0.5)  # Timeout più lungo
                else:
                    # Socket non valido, esci dal ciclo
                    break

                try:
                    # Ricevi comandi
                    comando = socket_comandi_input.recv(BUFFER_SIZE).decode('utf-8')

                    # Gestisci comando se presente
                    if comando:
                        if comando == "TERMINA":
                            print("Ricevuto comando di terminazione")
                            termina_chiamata(True)
                            break
                except socket.timeout:
                    # Timeout normale, continua
                    continue
                except Exception as e:
                    # Ignora altri errori di rete
                    print(f"Errore ricezione comando: {e}")
                    if not chiamata_in_corso:
                        break
                    time.sleep(0.1)
                    continue

            except Exception as e:
                print(f"Errore gestione comandi: {e}")
                if not chiamata_in_corso:
                    break
                time.sleep(0.1)

            # Pausa per ridurre utilizzo CPU
            time.sleep(0.05)

    except Exception as e:
        print(f"Errore critico thread comandi: {e}")
    finally:
        print("Thread comandi terminato")


def videocall(ip):
    """
    Inizia una videochiamata con l'utente all'IP specificato.
    """
    global chiamata_in_corso, socket_chiamata, is_video, audioStream, VideoCapture, p, utente_in_chiamata
    global socket_chiamata_invio_audio, socket_chiamata_invio_video, socket_chiamata_ricezione_audio, socket_chiamata_ricezione_video
    global socket_comandi_input, socket_comandi_output

    # Disabilita i pulsanti
    dpg.configure_item("btn_videochiama_privato", enabled=False)
    dpg.configure_item("btn_chiama_privato", enabled=False)

    # Verifica se c'è già una chiamata
    if chiamata_in_corso:
        print("C'è già una chiamata in corso")
        mostra_finestra_chiamata("ERROR")
        dpg.configure_item("btn_videochiama_privato", enabled=True)
        dpg.configure_item("btn_chiama_privato", enabled=True)
        return

    # Chiudi eventuali socket esistenti
    termina_chiamata(True)

    try:
        is_video = True
        utente_in_chiamata = username_client_chat_corrente

        # Crea socket principale
        socket_chiamata = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_chiamata.settimeout(5)
        socket_chiamata.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Connettiti al socket principale
        try:
            socket_chiamata.connect((ip, PORT_CHIAMATE))
        except:
            print("Impossibile connettersi all'utente")
            mostra_finestra_chiamata("UNREACHABLE")
            termina_chiamata()
            return

        # Invia richiesta
        request = f"CALLREQUEST:{nome_utente_personale}:{is_video}"
        socket_chiamata.send(request.encode('utf-8'))

        # Attendi risposta
        try:
            response = socket_chiamata.recv(BUFFER_SIZE).decode('utf-8')
        except:
            print("Timeout o errore nella risposta")
            mostra_finestra_chiamata("TIMEOUT")
            termina_chiamata()
            return

        if response == "CALLREQUEST:ACCEPT":
            # Crea socket audio
            socket_chiamata_invio_audio = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_chiamata_ricezione_audio = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            # Crea socket video
            socket_chiamata_invio_video = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_chiamata_ricezione_video = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            # Crea socket comandi
            socket_comandi_input = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socket_comandi_output = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            # Imposta timeout e opzioni
            for s in [socket_chiamata_invio_audio, socket_chiamata_ricezione_audio,
                      socket_chiamata_invio_video, socket_chiamata_ricezione_video,
                      socket_comandi_input, socket_comandi_output]:
                s.settimeout(5)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Connetti i socket ausiliari
            try:
                socket_chiamata_invio_audio.connect((ip, PORT_INVIO_AUDIO))
                socket_chiamata_ricezione_audio.connect((ip, PORT_RICEZIONE_AUDIO))
                socket_chiamata_invio_video.connect((ip, PORT_INVIO_VIDEO))
                socket_chiamata_ricezione_video.connect((ip, PORT_RICEZIONE_VIDEO))
                socket_comandi_input.connect((ip, PORT_RICEZIONE_COMANDI))
                socket_comandi_output.connect((ip, PORT_INVIO_COMANDI))
            except Exception as e:
                print(f"Errore nella connessione dei socket: {e}")
                mostra_finestra_chiamata("ERROR")
                termina_chiamata()
                return

            # Imposta stato chiamata
            chiamata_in_corso = True

            # Inizializza audio
            p = pyaudio.PyAudio()
            audioStream = p.open(
                format=FORMAT,
                rate=RATE,
                channels=CHANNEL,
                input=True,
                output=True,
                frames_per_buffer=CHUNK
            )

            # Inizializza video
            VideoCapture = cv2.VideoCapture(0)
            VideoCapture.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
            VideoCapture.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)

            # Avvia thread
            if VideoCapture.isOpened():
                # Thread video
                threading.Thread(target=gestisci_invio_video, daemon=True).start()
                threading.Thread(target=gestisci_ricezione_video, daemon=True).start()

            # Thread audio
            threading.Thread(target=gestisci_invio_audio, daemon=True).start()
            threading.Thread(target=gestisci_ricezione_audio, daemon=True).start()

            # Thread comandi
            threading.Thread(target=gestisci_comandi_chiamata, daemon=True).start()

            # Mostra finestra chiamata
            time.sleep(0.1)  # Pausa per stabilizzare
            mostra_finestra_chiamata("ACCEPTED")

        else:
            print("Chiamata rifiutata")
            mostra_finestra_chiamata("REFUSED")
            termina_chiamata()

    except Exception as e:
        print(f"Errore nella videochiamata: {e}")
        mostra_finestra_chiamata("ERROR")
        termina_chiamata()


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
        print(time_stamp_and_user_name)
        print(filename)
        # Controlla se esiste una cartella di download configurata
        download_folder = dpg.get_value("cartella_download")
        if not download_folder:
            download_folder = os.path.join(os.path.expanduser("~"), "Downloads")  # Default
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
                                       default_value=os.path.join(os.path.expanduser("~"), "Downloads"))
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
                            dpg.add_spacer(width=355)
                            dpg.add_button(label="Chiama", tag="btn_chiama_privato", callback=lambda:chiama_privato(True), width=70)
                            dpg.add_button(label="Videochiama", tag="btn_videochiama_privato", callback=lambda:videochiama_privato(True), width=90)

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


def chiama_privato(is_you_calling):
    global chiamata_in_corso, socket_chiamata, is_video, audioStream, VideoCapture, p, utente_in_chiamata

    try:
        if is_you_calling:
            dpg.configure_item("btn_chiama_privato", enabled=False)
            dpg.configure_item("btn_videochiama_privato", enabled=False)
            utente_da_chiamare = username_client_chat_corrente
            utente_in_chiamata = utente_da_chiamare  # Salva il nome utente

            # Verifica che ci sia un utente selezionato
            if not utente_da_chiamare:
                print("Errore: nessun contatto selezionato per la chiamata")
                dpg.configure_item("btn_chiama_privato", enabled=True)
                dpg.configure_item("btn_videochiama_privato", enabled=True)
                return

            # Invia richiesta IP al server con debug
            is_video = False
            comando = debug_richiesta_ip(utente_da_chiamare, is_video)
            print(f"Richiedo IP per chiamare {utente_da_chiamare}")
            client_socket.send(comando.encode('utf-8'))

    except Exception as e:
        print(f"Errore nella richiesta di chiamata: {e}")
        dpg.configure_item("btn_chiama_privato", enabled=True)
        dpg.configure_item("btn_videochiama_privato", enabled=True)


def videochiama_privato(is_you_calling):  # se sei tu a chiamare allora t aspetti una risposta
    global chiamata_in_corso, socket_chiamata, is_video, audioStream, VideoCapture, p, utente_in_chiamata
    try:
        if is_you_calling:
            dpg.configure_item("btn_chiama_privato", enabled=False)
            dpg.configure_item("btn_videochiama_privato", enabled=False)
            utente_da_chiamare = username_client_chat_corrente
            utente_in_chiamata = utente_da_chiamare  # Salva il nome utente

            # Verifica che ci sia un utente selezionato
            if not utente_da_chiamare:
                print("Errore: nessun contatto selezionato per la videochiamata")
                dpg.configure_item("btn_chiama_privato", enabled=True)
                dpg.configure_item("btn_videochiama_privato", enabled=True)

            is_video = True
            comando = debug_richiesta_ip(utente_da_chiamare, is_video)
            print(f"Richiedo IP per videochiamare {utente_da_chiamare}")
            client_socket.send(comando.encode('utf-8'))
    except Exception as e:
        print(f"Errore nella richiesta di videochiamata: {e}")
        dpg.configure_item("btn_chiama_privato", enabled=True)
        dpg.configure_item("btn_videochiama_privato", enabled=True)


def mostra_finestra_chiamata(risposta):
    """
    Mostra la finestra di chiamata in base alla risposta ricevuta.
    Layout migliorato con frame video affiancati orizzontalmente e pulsanti ingranditi.

    Risposte possibili:
    - "ACCEPTED": Chiamata accettata, mostra finestra completa
    - "REFUSED": Chiamata rifiutata
    - "UNREACHABLE", "TIMEOUT", "ERROR": Problemi di connessione
    """
    global utente_in_chiamata, call_requests_thread

    # Debug per verificare che la funzione venga chiamata
    print(f"mostra_finestra_chiamata chiamata con risposta: {risposta}, utente: {utente_in_chiamata}")

    # Se esiste già una finestra di chiamata, eliminiamola prima
    if dpg.does_item_exist("finestra_chiamata"):
        dpg.delete_item("finestra_chiamata")

    # Se esiste già un registro texture, eliminiamolo
    if dpg.does_item_exist("registro_chiamata"):
        dpg.delete_item("registro_chiamata")

    # Calcola dimensioni in base al testo e alla viewport
    viewport_width = dpg.get_viewport_width()
    viewport_height = dpg.get_viewport_height()

    # Per gli stati di errore, mostriamo solo un messaggio semplice
    if risposta in ["UNREACHABLE", "TIMEOUT", "ERROR", "REFUSED"]:
        window_width = 330
        window_height = 170
        window_pos = [viewport_width // 2 - window_width // 2, viewport_height // 2 - window_height // 2]

        # Costruisci il messaggio in base alla risposta
        if risposta == "UNREACHABLE":
            title = "Utente non raggiungibile"
            message = f"Impossibile raggiungere {utente_in_chiamata}."
            details = "L'utente potrebbe essere offline o non disponibile."
        elif risposta == "TIMEOUT":
            title = "Timeout connessione"
            message = f"Timeout della connessione con {utente_in_chiamata}."
            details = "La rete potrebbe essere instabile."
        elif risposta == "ERROR":
            title = "Errore chiamata"
            message = f"Errore durante la chiamata a {utente_in_chiamata}."
            details = "Si è verificato un problema imprevisto."
        elif risposta == "REFUSED":
            title = "Chiamata rifiutata"
            message = f"Chiamata rifiutata da {utente_in_chiamata}."
            details = "L'utente ha rifiutato la chiamata."

        try:
            with dpg.window(label=title, tag="finestra_chiamata",
                            modal=True, width=window_width, height=window_height,
                            pos=window_pos, no_resize=True, no_close=True):
                dpg.add_spacer(height=10)
                dpg.add_text(message, color=[255, 100, 100])
                dpg.add_text(details, wrap=280)
                dpg.add_spacer(height=20)

                # Centra il pulsante
                button_width = 100
                dpg.add_spacer(width=(window_width - button_width) // 2)
                dpg.add_button(label="OK", width=button_width, callback=lambda: dpg.delete_item("finestra_chiamata"))

            print(f"Finestra di errore creata: {title}")
        except Exception as e:
            print(f"Errore nella creazione della finestra di errore: {e}")

        # Riabilitiamo i pulsanti di chiamata
        dpg.configure_item("btn_videochiama_privato", enabled=True)
        dpg.configure_item("btn_chiama_privato", enabled=True)
        return

    if call_requests_thread:
        termina_thread_listen_for_calls = True
        call_requests_thread = None

    # Per chiamate accettate, mostra la finestra completa con layout migliorato
    try:
        # Nuove dimensioni per avere i video affiancati
        # Per videochiamate: finestra più larga per contenere i due video affiancati
        # Per chiamate solo audio: finestra più piccola
        if is_video:
            call_window_width = 700  # Sufficiente per 2 video affiancati (320*2 + margini)
            call_window_height = 430  # Altezza singolo video + controlli + margini
        else:
            call_window_width = 400  # Finestra più piccola per solo audio
            call_window_height = 180  # Altezza ridotta per solo audio

        call_window_pos = [viewport_width // 2 - call_window_width // 2, viewport_height // 2 - call_window_height // 2]

        with dpg.window(label=f"Chiamata con {utente_in_chiamata}", tag="finestra_chiamata",
                        modal=True, width=call_window_width, height=call_window_height,
                        pos=call_window_pos, no_resize=True, no_close=True):

            # Crea le texture solo se si tratta di una videochiamata
            if is_video:
                with dpg.texture_registry(tag="registro_chiamata"):
                    # Texture per il video del mittente (tu)
                    dpg.add_raw_texture(
                        width=320, height=240,
                        default_value=np.zeros(320 * 240 * 3, dtype=np.float32),
                        format=dpg.mvFormat_Float_rgb,
                        tag="texture_mittente"
                    )

                    # Texture per il video del destinatario
                    dpg.add_raw_texture(
                        width=320, height=240,
                        default_value=np.zeros(320 * 240 * 3, dtype=np.float32),
                        format=dpg.mvFormat_Float_rgb,
                        tag="texture_destinatario"
                    )

                # Gruppo orizzontale per i video affiancati
                with dpg.group(horizontal=True):
                    # Video locale
                    with dpg.group():
                        dpg.add_text("Tu", color=[200, 200, 200])
                        dpg.add_image(texture_tag="texture_mittente", tag="video_mittente", width=320, height=240)

                    # Piccolo spazio tra i video
                    dpg.add_spacer(width=10)

                    # Video remoto
                    with dpg.group():
                        dpg.add_text(f"{utente_in_chiamata}", color=[200, 200, 200])
                        dpg.add_image(texture_tag="texture_destinatario", tag="video_destinatario", width=320,
                                      height=240)

            # Aggiungi informazioni sulla chiamata
            dpg.add_text(f"In chiamata con: {utente_in_chiamata}", color=[255, 255, 255])
            dpg.add_text("Stato: Connesso", color=[100, 255, 100])
            dpg.add_separator()

            # Controlli della chiamata con pulsanti più grandi e proporzionati
            dpg.add_spacer(height=10)

            # Calcola dimensioni pulsanti in base alla finestra
            if is_video:
                button_count = 3  # Termina, Video, Audio
                button_width = 190  # Pulsanti più grandi
                button_height = 50  # Altezza aumentata
                spacing = 20
                total_width = button_count * button_width + (button_count - 1) * spacing
                left_margin = (call_window_width - total_width) // 2
            else:
                button_count = 2  # Termina, Audio
                button_width = 190  # Pulsanti più grandi
                button_height = 50  # Altezza aumentata
                spacing = 20
                total_width = button_count * button_width + (button_count - 1) * spacing
                left_margin = (call_window_width - total_width) // 2

            # Centra i pulsanti orizzontalmente
            with dpg.group(horizontal=True):
                # Aggiungi margine a sinistra per centrare
                dpg.add_spacer(width=left_margin)

                # Pulsante Termina (rosso)
                with dpg.theme() as termina_theme:
                    with dpg.theme_component(dpg.mvButton):
                        dpg.add_theme_color(dpg.mvThemeCol_Button, [150, 40, 40])  # Rosso normale
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [180, 60, 60])  # Rosso hover
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [120, 30, 30])  # Rosso cliccato
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 255])  # Testo bianco

                dpg.add_button(label="Termina", tag="btn_termina_chiamata", width=button_width, height=button_height,
                               callback=termina_chiamata)
                dpg.bind_item_theme(dpg.last_item(), termina_theme)

                # Spazio tra i pulsanti
                dpg.add_spacer(width=spacing)

                # Pulsante Video (blu) - solo per videochiamate
                if is_video:
                    with dpg.theme() as video_theme:
                        with dpg.theme_component(dpg.mvButton):
                            dpg.add_theme_color(dpg.mvThemeCol_Button, [40, 80, 150])  # Blu normale
                            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [60, 100, 180])  # Blu hover
                            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [30, 60, 120])  # Blu cliccato
                            dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 255])  # Testo bianco

                    video_label = "Disattiva Video" if is_video_on else "Attiva Video"
                    dpg.add_button(label=video_label, tag="btn_video", width=button_width, height=button_height,
                                   callback=attiva_disattiva_video)
                    dpg.bind_item_theme(dpg.last_item(), video_theme)

                    # Spazio tra i pulsanti
                    dpg.add_spacer(width=spacing)

                # Pulsante Audio (verde)
                with dpg.theme() as audio_theme:
                    with dpg.theme_component(dpg.mvButton):
                        dpg.add_theme_color(dpg.mvThemeCol_Button, [46, 120, 50])  # Verde normale
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, [66, 150, 70])  # Verde hover
                        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, [36, 100, 40])  # Verde cliccato
                        dpg.add_theme_color(dpg.mvThemeCol_Text, [255, 255, 255])  # Testo bianco

                audio_label = "Disattiva Audio" if is_audio_on else "Attiva Audio"
                dpg.add_button(label=audio_label, tag="btn_audio", width=button_width, height=button_height,
                               callback=attiva_disattiva_audio)
                dpg.bind_item_theme(dpg.last_item(), audio_theme)

        print(f"Finestra di chiamata creata per {utente_in_chiamata}, tipo: {risposta}")
    except Exception as e:
        print(f"Errore nella creazione della finestra di chiamata: {e}")
        # In caso di errore, riabilitiamo comunque i pulsanti
        dpg.configure_item("btn_videochiama_privato", enabled=True)
        dpg.configure_item("btn_chiama_privato", enabled=True)


# Funzioni complementari che devono essere aggiornate per mantenere la coerenza

def attiva_disattiva_video():
    """Attiva o disattiva la webcam durante una videochiamata."""
    global is_video_on

    # Inverti lo stato del video
    is_video_on = not is_video_on

    # Aggiorna l'etichetta del pulsante
    if dpg.does_item_exist("btn_video"):
        new_label = "Disattiva Video" if is_video_on else "Attiva Video"
        dpg.set_item_label("btn_video", new_label)

    print(f"Video {'attivato' if is_video_on else 'disattivato'}")


def attiva_disattiva_audio():
    """Attiva o disattiva il microfono durante una chiamata."""
    global is_audio_on

    # Inverti lo stato dell'audio
    is_audio_on = not is_audio_on

    # Aggiorna l'etichetta del pulsante
    if dpg.does_item_exist("btn_audio"):
        new_label = "Disattiva Audio" if is_audio_on else "Attiva Audio"
        dpg.set_item_label("btn_audio", new_label)

    print(f"Audio {'attivato' if is_audio_on else 'disattivato'}")


def aggiorna_video_remoto(frame_remoto):
    """Aggiorna la texture remota con il nuovo frame."""
    if not dpg.does_item_exist("texture_destinatario") or frame_remoto is None:
        return

    try:
        # Converti e formatta il frame
        frame_rgb = cv2.cvtColor(frame_remoto, cv2.COLOR_BGR2RGB)
        frame_resized = cv2.resize(frame_rgb, (320, 240))
        frame_float = frame_resized.astype(np.float32) / 255.0  # Normalizza a [0,1]

        # Aggiorna la texture solo se l'interfaccia è visibile e la finestra esiste
        if dpg.does_item_exist("finestra_chiamata") and dpg.is_item_visible("finestra_chiamata"):
            dpg.set_value("texture_destinatario", frame_float.ravel())
    except Exception as e:
        # Ignora errori di aggiornamento UI per non bloccare il thread video
        pass

def aggiorna_video_locale(frame):
    """Aggiorna la texture locale con il nuovo frame."""
    if not dpg.does_item_exist("texture_mittente") or frame is None:
        return

    try:
        # Converti e formatta il frame in modo efficiente
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_resized = frame_rgb  # Il frame è già stato ridimensionato nella funzione chiamante
        frame_float = frame_resized.astype(np.float32) / 255.0  # Normalizza a [0,1]

        # Aggiorna la texture solo se l'interfaccia è visibile e la finestra esiste
        if dpg.does_item_exist("finestra_chiamata") and dpg.is_item_visible("finestra_chiamata"):
            dpg.set_value("texture_mittente", frame_float.ravel())
    except Exception as e:
        # Ignora errori di aggiornamento UI per non bloccare il thread video
        pass


def gestisci_invio_video():
    global is_video, is_video_on, socket_chiamata, socket_chiamata_invio_video

    # Imposta alta priorità per questo thread
    set_thread_priority("video")

    # Utilizzato per limitare la frequenza di aggiornamento del frame
    last_frame_time = time.time()
    frame_interval = 0.033  # Circa 30 FPS

    try:
        while is_video_on and socket_chiamata and chiamata_in_corso and socket_chiamata_invio_video:
            current_time = time.time()

            # Limitazione frame rate per ridurre carico CPU e rete
            if current_time - last_frame_time < frame_interval:
                time.sleep(0.001)  # Piccola pausa se non è il momento di un nuovo frame
                continue

            last_frame_time = current_time

            # Cattura frame dalla webcam
            ret, frame = VideoCapture.read()
            if not ret:
                time.sleep(0.005)  # Piccola pausa in caso di errore lettura webcam
                continue

            # Ridimensiona e comprimi il frame
            frame = cv2.resize(frame, (320, 240))

            # Aggiorna l'anteprima locale solo se l'interfaccia è visibile
            # Utilizziamo una variabile wrapper per thread safety
            try:
                if dpg.does_item_exist("texture_mittente"):
                    aggiorna_video_locale(frame)
            except:
                pass  # Ignora errori di aggiornamento UI

            # Comprimi il frame con qualità ridotta per migliorare le prestazioni di rete
            _, encoded_frame = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 30])
            data = encoded_frame.tobytes()

            # Invia dimensione e dati del frame
            try:
                size = len(data)
                socket_chiamata_invio_video.settimeout(0.1)  # Timeout breve per l'invio
                socket_chiamata_invio_video.send(struct.pack('!I', size) + data)
            except Exception as e:
                print(f"Errore nell'invio del frame: {e}")
                # Non interrompere il ciclo per un singolo errore

    except Exception as e:
        print(f"Errore nella gestione video: {e}")
        # Non terminare la chiamata, potrebbe essere solo audio

def gestisci_ricezione_video():
    global is_video, is_video_on, socket_chiamata, socket_chiamata_invio_audio, socket_chiamata_invio_video, socket_chiamata_ricezione_audio, socket_chiamata_ricezione_video

    # Imposta alta priorità per questo thread
    set_thread_priority("video")

    # Utilizzato per limitare la frequenza di aggiornamento del frame
    last_frame_time = time.time()
    frame_interval = 0.033  # Circa 30 FPS
    try:
        while is_video_on and socket_chiamata and chiamata_in_corso and socket_chiamata_ricezione_video:
            socket_chiamata_ricezione_video.settimeout(0.05)  # Timeout molto breve per non bloccare
            size_data = socket_chiamata_ricezione_video.recv(4)
            if size_data:
                size = struct.unpack('!I', size_data)[0]

                # Limita la dimensione massima per sicurezza
                if size > 10000000:  # 1MB max
                    continue

                frame_data = b''
                remaining = size

                # Loop di ricezione con timeout
                start_time = time.time()
                while len(frame_data) < size and time.time() - start_time < 0.1:  # Max 100ms per frame
                    try:
                        pacchetto = socket_chiamata_ricezione_video.recv(min(remaining, 4096))
                        if not pacchetto:
                            break
                        frame_data += pacchetto
                        remaining -= len(pacchetto)
                    except socket.timeout:
                        # Se il timeout scade, passiamo al frame successivo
                        break

                # Se abbiamo ricevuto tutti i dati, decodifica e mostra
                if len(frame_data) == size:
                    try:
                        # Decodifica il frame
                        frame_remoto = cv2.imdecode(np.frombuffer(frame_data, dtype=np.uint8), cv2.IMREAD_COLOR)

                        # Aggiorna UI solo se l'elemento esiste
                        if dpg.does_item_exist("texture_destinatario"):
                            aggiorna_video_remoto(frame_remoto)
                    except Exception as e:
                        print(f"Errore nella decodifica del frame: {e}")
    except socket.timeout:
        # Nessun dato disponibile, continua al frame successivo
        pass
    except Exception as e:
        print(f"Errore nella ricezione video: {e}")

def gestisci_invio_audio():
    """
    Gestisce l'invio dell'audio durante una chiamata.
    Migliorata la gestione degli errori e dei timeout.
    """
    global chiamata_in_corso, audioStream, is_audio_on, socket_chiamata_invio_audio

    print("Avvio thread invio audio")

    # Contatori per gestire errori consecutivi
    consecutive_errors = 0
    max_errors = 10  # Massimo numero di errori prima di terminare la chiamata

    try:
        while chiamata_in_corso and socket_chiamata_invio_audio:
            # Verifica se l'audio è attivo
            if not is_audio_on:
                time.sleep(0.01)
                continue

            try:
                # Verifica che il socket sia ancora valido
                if not socket_chiamata_invio_audio:
                    print("Socket invio audio non valido, termino thread")
                    break

                try:
                    # Leggi dati audio con gestione overflow migliore
                    with lock_audio:
                        audio_data = audioStream.read(CHUNK, exception_on_overflow=False)
                except IOError as e:
                    print(f"Errore lettura audio: {e}")
                    time.sleep(0.01)
                    continue

                # Invia dati audio con timeout
                try:
                    socket_chiamata_invio_audio.settimeout(0.5)
                    socket_chiamata_invio_audio.send(audio_data)
                    # Reset errori dopo invio riuscito
                    consecutive_errors = 0
                except (BrokenPipeError, ConnectionResetError) as e:
                    # Connessione interrotta, aumenta contatore errori
                    consecutive_errors += 1
                    print(f"Errore di connessione audio ({consecutive_errors}/{max_errors}): {e}")

                    # Se troppi errori consecutivi, termina la chiamata
                    if consecutive_errors >= max_errors:
                        print("Troppe connessioni fallite, termino chiamata in modo controllato")
                        # Termina in un thread separato per evitare deadlock
                        threading.Thread(target=termina_chiamata, args=(True,), daemon=True).start()
                        break

                    time.sleep(0.1)  # Pausa prima di riprovare
                    continue

            except Exception as e:
                # Gestione generica errori
                print(f"Errore gestione audio: {e}")
                consecutive_errors += 1

                if consecutive_errors >= max_errors:
                    print("Troppi errori generici, termino chiamata")
                    threading.Thread(target=termina_chiamata, args=(True,), daemon=True).start()
                    break

                time.sleep(0.1)

            # Breve pausa per evitare utilizzo elevato CPU
            time.sleep(0.001)

    except Exception as e:
        print(f"Errore critico thread audio: {e}")
    finally:
        print("Thread invio audio terminato")
        if chiamata_in_corso:
            # Se stiamo terminando ma la chiamata è ancora attiva, terminiamola
            threading.Thread(target=termina_chiamata, args=(True,), daemon=True).start()


def is_socket_connected(sock):
    """
    Verifica se un socket è ancora connesso.
    Restituisce True se il socket è attivo, False altrimenti.
    """
    if sock is None:
        return False

    try:
        # Prova a inviare un dato vuoto (heartbeat)
        # Se genera errore, il socket è disconnesso
        sock.settimeout(0.5)

        # Tenta di effettuare un'operazione non bloccante
        # che rivela lo stato della connessione
        errno = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if errno != 0:
            return False

        # In alternativa, per alcuni socket:
        # sock.send(b'', socket.MSG_DONTWAIT)
        return True
    except Exception:
        return False

def gestisci_ricezione_audio():
    """
    Gestisce la ricezione dell'audio durante una chiamata con gestione robusta errori.
    """
    global chiamata_in_corso, audioStream, socket_chiamata_ricezione_audio

    print("Avvio thread ricezione audio")

    # Contatori per gestire errori consecutivi
    consecutive_errors = 0
    max_errors = 15  # Più permissivo nella ricezione

    try:
        while chiamata_in_corso and socket_chiamata_ricezione_audio:
            try:
                # Verifica che il socket sia ancora valido
                if not socket_chiamata_ricezione_audio:
                    print("Socket ricezione audio non valido, termino thread")
                    break

                # Imposta timeout breve ma non troppo
                socket_chiamata_ricezione_audio.settimeout(0.3)

                try:
                    # Ricevi i dati audio
                    audio_data = socket_chiamata_ricezione_audio.recv(CHUNK * 4)

                    # Reset errori dopo ricezione riuscita
                    if audio_data:
                        consecutive_errors = 0

                        # Verifica che ci siano dati e che lo stream sia valido
                        if audioStream:
                            try:
                                with lock_audio:
                                    audioStream.write(audio_data)
                            except IOError as e:
                                print(f"Errore scrittura audio: {e}")
                                if "closed" in str(e).lower():
                                    break
                    else:
                        # Nessun dato ricevuto, potrebbe essere una disconnessione
                        consecutive_errors += 1
                        print(f"Nessun dato audio ricevuto: {consecutive_errors}/{max_errors}")
                        time.sleep(0.1)

                except socket.timeout:
                    # Timeout normale, continua
                    continue

                except (ConnectionResetError, BrokenPipeError) as e:
                    # Connessione interrotta
                    consecutive_errors += 1
                    print(f"Connessione audio interrotta ({consecutive_errors}/{max_errors}): {e}")

                    if consecutive_errors >= max_errors:
                        print("Troppe interruzioni di connessione, termino chiamata")
                        threading.Thread(target=termina_chiamata, args=(True,), daemon=True).start()
                        break

                    time.sleep(0.1)  # Pausa prima di riprovare
                    continue

            except Exception as e:
                print(f"Errore generale ricezione audio: {e}")
                consecutive_errors += 1

                if consecutive_errors >= max_errors:
                    print("Troppi errori generici in ricezione, termino chiamata")
                    threading.Thread(target=termina_chiamata, args=(True,), daemon=True).start()
                    break

                time.sleep(0.1)

            # Pausa minima
            time.sleep(0.001)

    except Exception as e:
        print(f"Errore critico thread ricezione: {e}")
    finally:
        print("Thread ricezione audio terminato")
        if chiamata_in_corso:
            # Se stiamo terminando ma la chiamata è ancora attiva, terminiamola
            threading.Thread(target=termina_chiamata, args=(True,), daemon=True).start()

def verifica_connettivita(ip, porta, timeout=2):
    """
    Verifica se è possibile stabilire una connessione TCP all'indirizzo e porta specificati.
    Restituisce True se la connessione è possibile, False altrimenti.
    """
    try:
        # Crea un socket temporaneo
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        # Tenta la connessione
        result = sock.connect_ex((ip, porta))

        # Chiudi subito il socket
        sock.close()

        # Se result è 0, la connessione è riuscita
        return result == 0

    except Exception as e:
        print(f"Errore nel test di connettività: {e}")
        return False


def termina_chiamata(from_error=False):
    """
    Termina la chiamata attiva e rilascia le risorse in modo controllato.
    """
    global chiamata_in_corso, socket_chiamata, is_video, audioStream, VideoCapture, p, utente_in_chiamata
    global socket_chiamata_invio_audio, socket_chiamata_invio_video, socket_chiamata_ricezione_audio, socket_chiamata_ricezione_video
    global socket_comandi_input, socket_comandi_output, call_requests_thread, termina_thread_listen_for_calls

    # Previeni chiamate multiple con un flag
    if not chiamata_in_corso and socket_chiamata is None:
        return

    print("Terminazione chiamata...")

    # Prima di tutto, imposta stato chiamata terminata
    chiamata_in_corso = False

    # Prova a inviare un comando di terminazione all'altro client
    try:
        if socket_comandi_output:
            socket_comandi_output.settimeout(1.0)
            try:
                socket_comandi_output.send("TERMINA".encode('utf-8'))
            except:
                pass  # Ignora errori di invio durante la terminazione
    except Exception as e:
        print(f"Errore invio comando terminazione: {e}")

    # Attendi un momento per permettere ai thread di terminare
    time.sleep(0.5)  # Aumentato per maggiore stabilità

    # Funzione helper per chiudere un socket in modo sicuro
    def safe_close_socket(socket_obj, socket_name):
        if socket_obj:
            try:
                socket_obj.shutdown(socket.SHUT_RDWR)
            except:
                pass  # Ignora errori di shutdown

            try:
                socket_obj.close()
                print(f"Socket {socket_name} chiuso correttamente")
            except Exception as e:
                print(f"Errore chiusura socket {socket_name}: {e}")

            return None
        return None  # Ritorna sempre None anche se socket_obj è None

    # Chiudi i socket in modo sicuro - riassegnando alle variabili globali
    socket_chiamata = safe_close_socket(socket_chiamata, "chiamata")
    socket_comandi_output = safe_close_socket(socket_comandi_output, "comandi_output")
    socket_comandi_input = safe_close_socket(socket_comandi_input, "comandi_input")
    socket_chiamata_invio_audio = safe_close_socket(socket_chiamata_invio_audio, "invio_audio")
    socket_chiamata_ricezione_audio = safe_close_socket(socket_chiamata_ricezione_audio, "ricezione_audio")
    socket_chiamata_invio_video = safe_close_socket(socket_chiamata_invio_video, "invio_video")
    socket_chiamata_ricezione_video = safe_close_socket(socket_chiamata_ricezione_video, "ricezione_video")

    # Chiusura ordinata risorse PyAudio e VideoCapture
    if VideoCapture:
        try:
            VideoCapture.release()
            print("VideoCapture rilasciato correttamente")
        except:
            pass  # Ignora errori
        VideoCapture = None

    # Chiudi stream audio e PyAudio
    if audioStream:
        try:
            audioStream.stop_stream()
            audioStream.close()
            print("Stream audio chiuso correttamente")
        except:
            pass  # Ignora errori
        audioStream = None

    if p:
        try:
            p.terminate()
            print("PyAudio terminato correttamente")
        except:
            pass  # Ignora errori
        p = None

    # Reimposta le variabili
    is_video = False
    utente_in_chiamata = ""

    # Chiudi la finestra di chiamata nell'UI
    try:
        if dpg.does_item_exist("finestra_chiamata"):
            dpg.delete_item("finestra_chiamata")

        if dpg.does_item_exist("registro_chiamata"):
            dpg.delete_item("registro_chiamata")
    except:
        pass  # Ignora errori UI

    # Riattiva i pulsanti di chiamata
    try:
        if dpg.does_item_exist("btn_videochiama_privato"):
            dpg.configure_item("btn_videochiama_privato", enabled=True)

        if dpg.does_item_exist("btn_chiama_privato"):
            dpg.configure_item("btn_chiama_privato", enabled=True)
    except:
        pass  # Ignora errori UI

    # Gestione socket di ascolto chiamate
    # Usa un approccio più semplice che eviti problemi
    try:
        # Crea un nuovo socket di ascolto dopo un timeout più lungo
        time.sleep(3.0)  # Attesa più lunga per garantire il rilascio della porta

        socket_attesa_chiamate = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        socket_attesa_chiamate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socket_attesa_chiamate.settimeout(1.0)

        # Tenta binding con retry
        try:
            socket_attesa_chiamate.bind(("0.0.0.0", PORT_CHIAMATE))
            socket_attesa_chiamate.listen(1)
            print(f"Socket di ascolto chiamate ricreato con successo su porta {PORT_CHIAMATE}")

            # Avvia nuovo thread
            call_thread = threading.Thread(target=listen_for_call_request, args=(socket_attesa_chiamate,), daemon=True)
            call_thread.start()
            call_requests_thread = call_thread
        except OSError as e:
            print(f"Impossibile ricreare socket di ascolto: {e}")
    except Exception as e:
        print(f"Errore nel riavvio del socket di ascolto: {e}")

    print("Terminazione chiamata completata")

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

    if dpg.does_item_exist("notifica_messaggio_privato"):
        dpg.delete_item("notifica_messaggio_privato")

    # Imposta l'utente corrente
    username_client_chat_corrente = utente

    if dpg.get_value("tab_bar") != 2:
        dpg.set_value("tab_bar", "chat_private")

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
                callback=lambda:apri_chat_con(username), #funzione lambda senza nome
                width=-1,
                parent="lista_contatti"
            )


def inizia_chat_con(utente):
    """Inizia una nuova chat con un utente"""
    print(f"Inizializzazione chat con utente: {utente}")

    if utente not in chat_attive:
        chat_attive[utente] = ""
        aggiorna_lista_contatti()
        base_dir = os.path.dirname(os.path.abspath(__file__))  # directory corrente dello script
        private_chat_download_directory = os.path.join(base_dir, "client_chats_file_directory", utente)
        if not os.path.exists(private_chat_download_directory):
            os.makedirs(private_chat_download_directory)
            print(f"Creata cartella di download: {private_chat_download_directory}")

    print(f"Apertura chat con {utente}")

    # Apre la chat con l'utente scelto
    apri_chat_con(utente)

    # Chiude la finestra dell'aggiungi contatti
    if dpg.does_item_exist("finestra_aggiungi_contatto"):
        dpg.delete_item("finestra_aggiungi_contatto")


def create_callback_for_user(username):
    """
    Factory function che crea una funzione di callback specifica per un utente.
    Questa funzione evita il problema delle closure nelle lambda in Python.

    Args:
        username: Il nome dell'utente per cui creare la callback

    Returns:
        Una funzione di callback che chiamerà inizia_chat_con con l'username corretto
    """

    def callback():
        print(f"Callback eseguita per l'utente: {username}")
        inizia_chat_con(username)

    return callback

def mostra_aggiungi_contatti():
    """
    Mostra la finestra di dialogo per aggiungere nuovi contatti.
    Corretto il problema con la callback lambda che usava sempre l'ultimo utente.
    """
    global utenti_disponibili

    # Se la finestra esiste già, rimuovila prima di ricrearla
    if dpg.does_item_exist("finestra_aggiungi_contatto"):
        dpg.delete_item("finestra_aggiungi_contatto")

    with dpg.window(label="Aggiungi contatto", tag="finestra_aggiungi_contatto",
                    modal=True, width=300, height=400):
        dpg.add_text("Utenti disponibili:")
        dpg.add_separator()

        with dpg.child_window(tag="lista_utenti_disponibili", height=300, width=-1):
            for user in utenti_disponibili:
                print(f"Creazione pulsante per utente: {user}")

                # utilizzando una factory function per creare la callback
                callback_fn = create_callback_for_user(user)

                # Creiamo un tag univoco per ogni pulsante basato sull'username
                button_tag = f"add_user_{user}"

                # Aggiungiamo il pulsante con la callback corretta
                dpg.add_button(
                    label=user,
                    tag=button_tag,
                    callback=callback_fn,
                    width=-1
                )

        # Pulsante per chiudere la finestra
        dpg.add_button(
            label="Chiudi",
            callback=lambda: dpg.delete_item("finestra_aggiungi_contatto"),
            width=-1
        )


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