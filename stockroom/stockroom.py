import json
import uuid
import base64
import requests
import os
import logging

import barcode

import datetime as dt

from time import sleep
from queue import Queue
from threading import Thread, Lock
from pathlib import Path
from slugify import slugify

from requests.exceptions import HTTPError

from notion.client import NotionClient
from stockroom.notion import upload_file_to_row_property

logger = logging.getLogger(__name__)

def scanner(queue, lock):
    while True:
        barcode = input()
        logger.info(f'Barcode scanned: {barcode}')
        item_id = str(uuid.UUID(base64.b64decode(barcode).hex()))
        queue.put(item_id)

def item_tracker(queue, client, lock):
    flag = -1
    while True: 
        item_id = queue.get()
        
        if item_id == 'd8701fa4-af0b-11eb-8529-0242ac130003':
            flag = -1
            continue
        elif item_id == '153a3d34-af0c-11eb-8529-0242ac130003':
            flag = 1
            continue
        
        lock.acquire()
        try:
            item = client.get_block(item_id)
            item.refresh()
            current = item.stock if item.stock is not None else 0
            item.stock = max(current + flag, 0)
            logger.info(f'Processing item: {item.title}')
        except Exception as e:
            logger.warning(f'{type(e).__name__} when scanning {item_id}.')
        lock.release()


def create_barcode(item, barcode_dir='barcodes', btype='code128', font='sans-serif'):
    code = base64.b64encode(uuid.UUID(hex=item.id).bytes).decode('utf-8')

    svg = barcode.get(btype, code).render(
        text=item.title,
        writer_options=dict(quiet_zone=15, module_height=20)
    )

    svg = b'\n'.join([
        line.replace(
            b'style=\"', f'style=\"font-family: {font};'.encode('utf-8')
        ) if b'<text' in line else line for line in svg.splitlines() 
    ])

    slug = slugify(item.title)
    filename = Path(barcode_dir)/f'{slug}.svg'
    with open(filename, 'wb') as f:
        f.write(svg)
    return filename

def barcode_updater(client, supply_db, lock):
    while True:
        lock.acquire()
        items = supply_db.collection.get_rows()
        
        for item in items:
            if not item.barcode:
                logger.info(f'Creating barcode for {item.title}')
                filename = create_barcode(item)
                upload_file_to_row_property(client, item, filename, 'Barcode')
        lock.release()
        sleep(60)

def status_updater(status, lock):
    while True:
        lock.acquire()
        status.refresh()
        lock.release()
        now = dt.datetime.utcnow().astimezone()
        now = now.tzinfo.fromutc(now)
        now = now.strftime('%A, %B %-d, %Y at %-I:%M %p')
        lock.acquire()
        status.title = f'__Barcode Scanner Status:__ _Last seen {now}_ '
        lock.release()
        sleep(60)

if __name__ == '__main__':
    with open('config.json') as f:
        config = json.load(f)

    lock = Lock()
    q = Queue()
    
    try:
        client = NotionClient(token_v2=config['token'])
        logger.info('Logged in with token')
    except HTTPError as e:
        if e.response.status_code in [401, 403]:
            client = NotionClient(email=config['email'], password=config['password'])
            config['token'] = client.session.cookies['token_v2']

            with open('config.json', 'w') as f:
                json.dump(config, f, indent=4)
            logger.info('Updated token')
            
    status = client.get_block(config['status'])
    supply_db = client.get_collection_view(config['supplies'])
    
    threads = [
        Thread(target=scanner, kwargs=dict(queue=q, lock=lock)),
        Thread(target=item_tracker, kwargs=dict(queue=q, client=client, lock=lock)),
        Thread(target=status_updater, kwargs=dict(status=status, lock=lock)),
        Thread(target=barcode_updater, kwargs=dict(client=client, supply_db=supply_db, lock=lock))
    ]

    for thread in threads:
        thread.start()