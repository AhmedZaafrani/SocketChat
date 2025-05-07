import dearpygui.dearpygui as dpg
import socket
import threading
import cv2
import numpy as np
import pickle
import struct
import argparse
import time
import sys

"""AGX: Texture read/write assertion failed: bytes_per_row >= used_bytes_per_rowAGX: Texture read/write assertion failed: bytes_per_row >= used_bytes_per_rowAGX: Texture read/write assertion failed: bytes_per_row >= used_bytes_per_row"""


# Configurazione iniziale di DearPyGUI
dpg.create_context()
dpg.create_viewport(title="Applicazione Videochiamata", width=1280, height=720)

# Variabili globali
conn = None
addr = None
client_socket = None
server_socket = None
is_server = False
is_connected = False
camera = None
remote_frame = None
local_frame = None
running = True


def initialize_camera():
    global camera
    try:
        camera = cv2.VideoCapture(0)
        if not camera.isOpened():
            print("Errore: impossibile aprire la webcam")
            return False
        return True
    except Exception as e:
        print(f"Errore nell'inizializzazione della camera: {e}")
        return False


def capture_video():
    global running, camera, local_frame
    while running and camera is not None:
        ret, frame = camera.read()
        if not ret:
            print("Errore nella lettura del frame dalla webcam")
            time.sleep(0.1)
            continue

        # Ridimensiona il frame per ridurre la larghezza di banda
        frame = cv2.resize(frame, (640, 480))
        # Converti il frame in BGR (OpenCV) a RGB (DearPyGUI)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        local_frame = frame_rgb

        # Invia il frame se siamo connessi
        if is_connected:
            try:
                data = pickle.dumps(frame)
                message_size = struct.pack("L", len(data))
                if is_server and conn:
                    conn.sendall(message_size + data)
                elif client_socket:
                    client_socket.sendall(message_size + data)
            except Exception as e:
                print(f"Errore nell'invio del frame: {e}")

        time.sleep(0.033)  # Circa 30 FPS


def receive_video():
    global running, remote_frame, conn, client_socket, is_connected

    data = b""
    payload_size = struct.calcsize("L")

    while running and is_connected:
        try:
            # Determinare quale socket utilizzare per ricevere
            sock = conn if is_server else client_socket
            if sock is None:
                time.sleep(0.1)
                continue

            # Ricevi prima la dimensione del messaggio
            while len(data) < payload_size:
                packet = sock.recv(4096)
                if not packet:
                    is_connected = False
                    break
                data += packet

            if not is_connected:
                break

            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("L", packed_msg_size)[0]

            # Ricevi l'intero messaggio
            while len(data) < msg_size:
                packet = sock.recv(4096)
                if not packet:
                    is_connected = False
                    break
                data += packet

            if not is_connected:
                break

            frame_data = data[:msg_size]
            data = data[msg_size:]

            # Deserializza il frame e memorizzalo per la visualizzazione
            frame = pickle.loads(frame_data)
            remote_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        except Exception as e:
            print(f"Errore nella ricezione del video: {e}")
            is_connected = False
            time.sleep(0.1)


def start_server(host, port):
    global server_socket, conn, addr, is_server, is_connected

    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen(1)
        print(f"Server avviato su {host}:{port}")
        print("In attesa di connessione...")

        conn, addr = server_socket.accept()
        print(f"Connessione stabilita con {addr}")
        is_server = True
        is_connected = True

        # Avvia il thread per ricevere il video
        threading.Thread(target=receive_video, daemon=True).start()

    except Exception as e:
        print(f"Errore nell'avvio del server: {e}")


def connect_to_server(host, port):
    global client_socket, is_connected

    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print(f"Tentativo di connessione a {host}:{port}...")
        client_socket.connect((host, port))
        print(f"Connessione stabilita con {host}:{port}")
        is_connected = True

        # Avvia il thread per ricevere il video
        threading.Thread(target=receive_video, daemon=True).start()

    except Exception as e:
        print(f"Errore nella connessione al server: {e}")


def update_textures():
    global local_frame, remote_frame

    if local_frame is not None:
        height, width, _ = local_frame.shape
        dpg.set_value("local_texture", local_frame.flatten())
        dpg.configure_item("local_texture", width=width, height=height)

    if remote_frame is not None:
        height, width, _ = remote_frame.shape
        dpg.set_value("remote_texture", remote_frame.flatten())
        dpg.configure_item("remote_texture", width=width, height=height)


def cleanup():
    global running, camera, server_socket, client_socket, conn

    running = False
    time.sleep(0.5)  # Aspetta che i thread si fermino

    if camera is not None:
        camera.release()

    if conn is not None:
        conn.close()

    if client_socket is not None:
        client_socket.close()

    if server_socket is not None:
        server_socket.close()

    dpg.destroy_context()
    print("Applicazione terminata.")


def create_gui():
    # Registra le texture per i video
    with dpg.texture_registry():
        dpg.add_raw_texture(
            width=640, height=480, default_value=np.zeros((640 * 480 * 3), dtype=np.float32),
            format=dpg.mvFormat_Float_rgb, tag="remote_texture"
        )
        dpg.add_raw_texture(
            width=640, height=480, default_value=np.zeros((640 * 480 * 3), dtype=np.float32),
            format=dpg.mvFormat_Float_rgb, tag="local_texture"
        )

    # Crea la finestra principale
    with dpg.window(label="Videochiamata", tag="main_window"):
        dpg.add_text("Video Remoto:")
        dpg.add_image("remote_texture", width=640, height=480)

        dpg.add_text("Video Locale:")
        dpg.add_image("local_texture", width=640, height=480)

        dpg.add_separator()

        # Aggiungi controlli per la connessione
        with dpg.group(horizontal=True):
            dpg.add_input_text(label="Host", default_value="localhost", tag="host_input")
            dpg.add_input_int(label="Porta", default_value=5000, tag="port_input")

        with dpg.group(horizontal=True):
            dpg.add_button(label="Avvia Server", callback=lambda: start_server_callback())
            dpg.add_button(label="Connetti", callback=lambda: connect_callback())
            dpg.add_button(label="Disconnetti", callback=lambda: disconnect_callback())
            dpg.add_button(label="Esci", callback=lambda: exit_callback())


def start_server_callback():
    host = dpg.get_value("host_input")
    port = dpg.get_value("port_input")
    threading.Thread(target=start_server, args=(host, port), daemon=True).start()


def connect_callback():
    host = dpg.get_value("host_input")
    port = dpg.get_value("port_input")
    threading.Thread(target=connect_to_server, args=(host, port), daemon=True).start()


def disconnect_callback():
    global is_connected, conn, client_socket
    is_connected = False
    if conn:
        conn.close()
        conn = None
    if client_socket:
        client_socket.close()
        client_socket = None
    print("Disconnesso")


def exit_callback():
    cleanup()
    sys.exit(0)


def main():
    # Parsing degli argomenti da linea di comando
    parser = argparse.ArgumentParser(description="Applicazione di Videochiamata con DearPyGUI")
    parser.add_argument("--server", action="store_true", help="Avvia in modalità server")
    parser.add_argument("--client", action="store_true", help="Avvia in modalità client")
    parser.add_argument("--host", default="localhost", help="Indirizzo host (default: localhost)")
    parser.add_argument("--port", type=int, default=5000, help="Porta (default: 5000)")

    args = parser.parse_args()

    # Inizializza la webcam
    if not initialize_camera():
        print("Impossibile avviare l'applicazione senza una webcam funzionante")
        return

    # Avvia il thread per la cattura video
    threading.Thread(target=capture_video, daemon=True).start()

    # Crea l'interfaccia grafica
    create_gui()

    # Configura la connessione in base agli argomenti
    if args.server:
        dpg.set_value("host_input", args.host)
        dpg.set_value("port_input", args.port)
        start_server_callback()
    elif args.client:
        dpg.set_value("host_input", args.host)
        dpg.set_value("port_input", args.port)
        connect_callback()

    # Configura il viewport e il callback per l'aggiornamento delle texture
    dpg.setup_dearpygui()
    dpg.show_viewport()

    # Loop principale
    while dpg.is_dearpygui_running():
        # Aggiorna le texture con i frame video
        update_textures()
        dpg.render_dearpygui_frame()

    # Pulizia finale
    cleanup()


if __name__ == "__main__":
    main()