"""Technical acceptance against actual containers. Synthetic data only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
from uuid import UUID
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import httpx
from jsonschema import Draft202012Validator
import pika
import psycopg

SERVICES = ['identity', 'diagnosis', 'ai_inference', 'notification']
BUCKET = os.environ['S3_BUCKET']
KEY = 'acceptance/group4-synthetic.txt'
BODY = b'agro-group4-persistence-only'
QUEUE = 'acceptance.group4.durable'


def http(url):
    return httpx.get(url, timeout=15, trust_env=False)


def health(degraded=None):
    for service in SERVICES:
        doc = json.loads(Path('contracts/openapi/' + service + '.openapi.json').read_text())
        actual = http('http://' + service + ':8000/openapi.json').json()
        assert set(actual['paths']) == {'/health/live', '/health/ready'}
        for kind in ['live', 'ready']:
            route = '/health/' + kind
            response = http('http://' + service + ':8000' + route)
            expected = 503 if kind == 'ready' and (degraded == 'postgres' or degraded == service or (degraded == 's3' and service == 'diagnosis')) else 200
            assert response.status_code == expected, (service, kind, response.status_code, expected)
            assert response.headers['cache-control'] == 'private, no-store'
            UUID(response.headers['x-correlation-id'])
            schema = doc['paths'][route]['get']['responses'][str(expected)]['content']['application/json']['schema']
            Draft202012Validator(schema).validate(response.json())
            generated = actual['paths'][route]['get']
            assert generated['operationId'] == doc['paths'][route]['get']['operationId']
            assert set(generated['responses']) == set(doc['paths'][route]['get']['responses'])
            for code, contracted in doc['paths'][route]['get']['responses'].items():
                gs = generated['responses'][code]['content']['application/json']['schema']
                if '$ref' in gs:
                    gs = actual['components']['schemas'][gs['$ref'].split('/')[-1]]
                cs = contracted['content']['application/json']['schema']
                assert set(gs['required']) == set(cs['required'])
                assert gs['additionalProperties'] is False
                assert set(gs['properties']) == set(cs['properties'])
                for prop in cs['properties']:
                    assert gs['properties'][prop]['const'] == cs['properties'][prop]['const']
        assert http('http://' + service + ':8000/api/v1/diagnoses').status_code == 404
    print('HTTP health/contracts PASS: ' + str(degraded or 'healthy'))


def s3(name):
    credentials = json.loads(Path('/run/secrets/s3_' + name).read_text())
    return boto3.client('s3', endpoint_url='http://s3:8333', region_name=os.environ['S3_REGION'],
                        aws_access_key_id=credentials['access_key'], aws_secret_access_key=credentials['secret_key'],
                        config=Config(connect_timeout=3, read_timeout=15, retries={'max_attempts': 0}, s3={'addressing_style': 'path'}))


def broker():
    return pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq',credentials=pika.PlainCredentials('agro_local',Path('/run/secrets/rabbit_password').read_text().strip()),socket_timeout=5,blocked_connection_timeout=5,connection_attempts=1))


def database():
    return psycopg.connect(host='postgres',dbname='identity',user='identity',password=Path('/run/secrets/identity_password').read_text().strip(),connect_timeout=3,autocommit=True)


def seed():
    with database() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('identity_0001',)
    client=s3('diagnosis')
    client.put_object(Bucket=BUCKET,Key=KEY,Body=BODY)
    assert client.get_object(Bucket=BUCKET,Key=KEY)['Body'].read() == BODY
    ai=s3('ai')
    assert ai.get_object(Bucket=BUCKET,Key=KEY)['Body'].read() == BODY
    try:
        ai.put_object(Bucket=BUCKET,Key='acceptance/forbidden.txt',Body=b'forbidden')
    except ClientError as exc:
        assert exc.response['ResponseMetadata']['HTTPStatusCode'] == 403
    else:
        raise AssertionError('AI write permitted')
    anon=http('http://s3:8333/'+BUCKET+'/'+KEY)
    assert anon.status_code in [401,403], anon.status_code
    # Filer/master/volume bypass interfaces must not be reachable over Docker network.
    for port in [8888,9333,8080]:
        try:
            with socket.create_connection(('s3',port),timeout=2):
                pass
        except OSError:
            continue
        raise AssertionError('S3 bypass interface reachable: '+str(port))
    with broker() as conn:
        channel=conn.channel()
        channel.queue_declare(queue=QUEUE,durable=True)
        channel.confirm_delivery()
        channel.basic_publish(exchange='',routing_key=QUEUE,body=BODY,properties=pika.BasicProperties(delivery_mode=2),mandatory=True)
    print('Authorized S3/read-only AI/anonymous denied and confirmed durable message PASS')


def recover():
    with database() as db:
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('identity_0001',)
    client=s3('diagnosis');data=client.get_object(Bucket=BUCKET,Key=KEY)['Body'].read()
    assert hashlib.sha256(data).digest() == hashlib.sha256(BODY).digest()
    with broker() as conn:
        channel=conn.channel();method,_,data=channel.basic_get(queue=QUEUE,auto_ack=False)
        assert method and data == BODY
        channel.basic_ack(method.delivery_tag)
        channel.queue_delete(queue=QUEUE)
    client.delete_object(Bucket=BUCKET,Key=KEY)
    print('Persisted PostgreSQL head / RabbitMQ message / private object checksum PASS')


def revision(mode):
    with database() as db:
        if mode=='revision-empty':db.execute('DELETE FROM alembic_version')
        elif mode=='revision-wrong':db.execute("UPDATE alembic_version SET version_num='wrong_head'")
        else:
            db.execute('DELETE FROM alembic_version')
            db.execute("INSERT INTO alembic_version VALUES ('identity_0001')")


parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['health','postgres','s3','identity','seed','recover','revision-empty','revision-wrong','revision-restore'])
mode=parser.parse_args().mode
if mode=='health':health()
elif mode in ['postgres','s3','identity']:health(mode)
elif mode=='seed':seed()
elif mode=='recover':recover()
else:revision(mode)
