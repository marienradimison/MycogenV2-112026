"""Service de connexion aux automates (à laisser tourner en permanence sur le serveur).

    python manage.py instruments_listen

Lance un fil d'écoute par automate actif (TCP serveur/client, port série, dossier).
La configuration se fait dans Mycogen → Automates. Relancer le service après modification.
"""
import logging
import os
import shutil
import socket
import socketserver
import threading
import time

from django.core.management.base import BaseCommand

from apps.instruments import astm
from apps.instruments.handlers import handle_astm, handle_file
from apps.instruments.models import Instrument

log = logging.getLogger("mycogen.instruments")


def run_session(instrument, link, peer):
    log.info("%s : connexion %s", instrument.name, peer)
    session = astm.Session(link, lambda text: handle_astm(instrument, text), name=instrument.name)
    try:
        session.run()
    except (ConnectionError, OSError) as exc:
        log.info("%s : déconnexion %s (%s)", instrument.name, peer, exc)


def tcp_server(instrument):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            run_session(instrument, astm.SocketLink(self.request), self.client_address)

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("0.0.0.0", instrument.port), Handler) as server:
        log.info("%s : écoute sur le port %s", instrument.name, instrument.port)
        server.serve_forever()


def tcp_client(instrument):
    while True:
        try:
            sock = socket.create_connection((instrument.host, instrument.port), timeout=10)
            run_session(instrument, astm.SocketLink(sock), f"{instrument.host}:{instrument.port}")
        except OSError as exc:
            log.warning("%s : connexion impossible à %s:%s (%s)", instrument.name, instrument.host,
                        instrument.port, exc)
        time.sleep(15)


def serial_port(instrument):
    try:
        import serial
    except ImportError:
        log.error("%s : pyserial non installé (pip install pyserial)", instrument.name)
        return
    while True:
        try:
            with serial.Serial(instrument.serial_port, instrument.baudrate, timeout=15) as port:
                run_session(instrument, astm.SerialLink(port), instrument.serial_port)
        except Exception as exc:
            log.warning("%s : port %s indisponible (%s)", instrument.name, instrument.serial_port, exc)
        time.sleep(15)


def watch_folder(instrument):
    done = os.path.join(instrument.folder, "importes")
    os.makedirs(done, exist_ok=True)
    log.info("%s : surveillance du dossier %s", instrument.name, instrument.folder)
    while True:
        for name in sorted(os.listdir(instrument.folder)):
            path = os.path.join(instrument.folder, name)
            if not os.path.isfile(path) or time.time() - os.path.getmtime(path) < 5:
                continue  # fichier en cours d'écriture
            with open(path, "rb") as fh:
                content = fh.read().decode("utf-8", "replace")
            handle_file(instrument, name, content)
            shutil.move(path, os.path.join(done, f"{int(time.time())}_{name}"))
        time.sleep(10)


RUNNERS = {"TCP_SERVER": tcp_server, "TCP_CLIENT": tcp_client, "SERIAL": serial_port, "FOLDER": watch_folder}


class Command(BaseCommand):
    help = "Écoute les automates (GeneXpert, MGIT, Pluslife) et importe leurs résultats."

    def handle(self, *args, **opts):
        threads = []
        for inst in Instrument.objects.filter(active=True):
            missing = {"TCP_SERVER": not inst.port, "TCP_CLIENT": not (inst.host and inst.port),
                       "SERIAL": not inst.serial_port, "FOLDER": not inst.folder}[inst.connection]
            if missing:
                self.stderr.write(f"{inst.name} : configuration de connexion incomplète, ignoré.")
                continue
            t = threading.Thread(target=self.guard, args=(RUNNERS[inst.connection], inst), daemon=True,
                                 name=inst.name)
            t.start()
            threads.append(t)
            self.stdout.write(f"→ {inst.name} ({inst.get_connection_display()})")
        if not threads:
            self.stderr.write("Aucun automate actif configuré.")
            return
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            self.stdout.write("Arrêt.")

    @staticmethod
    def guard(runner, instrument):
        while True:  # un plantage ne doit jamais arrêter l'écoute
            try:
                runner(instrument)
            except Exception:
                log.exception("%s : erreur, redémarrage dans 30 s", instrument.name)
            time.sleep(30)
