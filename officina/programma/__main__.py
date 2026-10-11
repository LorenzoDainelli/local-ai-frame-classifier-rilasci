import os
import sys

from officina.programma.avvio import principale

if __name__ == "__main__":
    codice = principale()
    sys.stdout and sys.stdout.flush()
    sys.stderr and sys.stderr.flush()
    os._exit(codice)
