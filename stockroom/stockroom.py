import json
import uuid
import base64
import mimetypes
import requests
import os

import barcode
# from barcode.writer import SVGWriter

import datetime as dt

from time import sleep
from queue import Queue
from threading import Thread, Lock
from pathlib import Path
from slugify import slugify


from requests.exceptions import HTTPError

from notion.client import NotionClient
from notion.operations import build_operation

def upload_file_to_row_property(client, row, path, prop):
    mimetype = mimetypes.guess_type(path)[0] or 'text/plain'
    filename = os.path.split(path)[-1]
    data = client.post(
        'getUploadFileUrl',
        {'bucket': 'secure', 'name': filename, 'contentType': mimetype}
    ).json()
    
    ids = {p['name']: p['id'] for p in row.schema}

    with open(path, "rb") as f:
        response = requests.put(data['signedPutUrl'], data=f, headers={'Content-type': mimetype})
        response.raise_for_status()
    
    simpleurl = data['signedGetUrl'].split('?')[0]
    file_id = simpleurl.split('/')[-2]
    client.submit_transaction([
        build_operation(
            id=row.id,
            path=['properties', ids[prop]],
            args=[[filename, [['a', simpleurl]]]],
            table='block',
            command='set'
        ),
        build_operation(
            id=row.id,
            path=['file_ids'],
            args={'id': file_id},
            table='block',
            command='listAfter'
        )
    ])

def scanner(queue, lock):
    while True:
        barcode = input()
        print(f'Barcode scanned: {barcode}')
        item_id = str(uuid.UUID(base64.b64decode(barcode).hex()))
        queue.put(item_id)

def item_tracker(queue, client, lock):
    while True: 
        item_id = queue.get()
        lock.acquire()
        try:
            item = client.get_block(item_id)
            item.refresh()
            current = item.stock
            item.stock = current - 1 if current else 0
            print(f'Processing item: {item.title}')
        except Exception as e:
            print(f'{type(e).__name__} when scanning {item_id}.')
        lock.release()


def create_barcode(item, barcode_dir='barcodes', btype='code128', font='Roboto'):
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
    filename = Path(barcode_dir)/f'{slug}-b64.svg'
    with open(filename, 'wb') as f:
        f.write(svg)
    return filename

def barcode_updater(client, supply_db, lock):
    while True:
        lock.acquire()
        items = supply_db.collection.get_rows()
        
        for item in items:
            if not item.barcode:
                print(f'Creating barcode for {item.title}')
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
        print('Logged in with token')
    except HTTPError as e:
        if e.response.status_code in [401, 403]:
            client = NotionClient(email=config['email'], password=config['password'])
            config['token'] = client.session.cookies['token_v2']

            with open('config.json', 'w') as f:
                json.dump(config, f, indent=4)
            print('Updated token')
            
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