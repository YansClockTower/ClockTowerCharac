
RUN = 'python3 main.py'

from datetime import datetime
import sqlite3
from pysrc.fetch_json import import_from_json

import shutil
import os
import sys

def clean_folder(folder):
    if os.path.exists(folder):
        try:
            shutil.rmtree(folder)
            print(f"Deleted folder: {folder}")
        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Folder does not exist.")
    pass
    os.makedirs(folder, exist_ok=True)

def help():
    print("Help: ")
    print(f"{RUN} clean         \t\t clean the output.")
    print(f"{RUN} gen           \t\t generate HTML and json.")
    print(f"{RUN} fetch <json>  \t\t import edition from json.")


if len(sys.argv) <= 1:
    help()
    exit()

para = sys.argv[1]

if para == 'fetch':
    if len(sys.argv) <= 2:
        help()
        exit()
    shutil.copy2("database/edition_latest.sqlite", f'database/history/{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}_edition.sqlite')
    shutil.copy2("database/character_latest.sqlite", f'database/history/{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}_character.sqlite')
    
    edition = sqlite3.connect("database/edition_latest.sqlite")
    character = sqlite3.connect("database/character_latest.sqlite")
    import_from_json(sys.argv[2], edition, character)
    edition.commit()
    edition.close()
    character.commit()
    character.close()

elif para == 'clean':
    clean_folder('config')
    clean_folder('data')
    clean_folder('output')

else:
    help()