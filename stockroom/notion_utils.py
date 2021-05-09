import os
import requests
import mimetypes

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