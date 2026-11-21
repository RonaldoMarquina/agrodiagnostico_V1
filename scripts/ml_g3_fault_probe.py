"""Fault probes for an isolated G3 Compose project with the real CPU worker.

Uses only admitted VAL images. It never reads TEST, changes the pinned bundle,
or promotes a policy outside the temporary acceptance database.
"""

import json
from pathlib import Path
import subprocess
import time
import uuid

import jwt

from check_async_acceptance import request_json


QUERY = """
import json,sys
from sqlalchemy import text
from app.persistence import engine
with engine().connect() as db:
    row=db.execute(text(sys.argv[1]), {'id':sys.argv[2]}).mappings().first()
print(json.dumps(dict(row) if row else None, default=str))
"""

MONITOR = """
import json,sys,time
from sqlalchemy import text
from app.persistence import engine
seen=[]
deadline=time.monotonic()+90
while time.monotonic()<deadline:
    with engine().connect() as db:
        row=db.execute(text('SELECT status, lease_expires_at FROM diagnoses WHERE id=CAST(:id AS uuid)'),
                       {'id':sys.argv[1]}).mappings().first()
    if row:
        value=str(row['lease_expires_at']) if row['lease_expires_at'] else None
        if row['status']=='PROCESANDO' and value and (not seen or seen[-1]!=value):
            seen.append(value)
        if row['status'] in ('COMPLETADO','NO_CONCLUYENTE','FALLIDO'):
            break
    time.sleep(.08)
print(json.dumps({'lease_expirations_observed':len(seen),'terminal_status':row['status'] if row else None}))
"""

REDELIVER = """
import json,os,sys
from pathlib import Path
import pika
from sqlalchemy import text
from app.persistence import engine
with engine().connect() as db:
    envelope=db.execute(text("SELECT envelope FROM diagnosis_outbox WHERE diagnosis_id=CAST(:id AS uuid) AND event_type='DiagnosisRequested' ORDER BY created_at LIMIT 1"), {'id':sys.argv[1]}).scalar_one()
password=Path(os.environ['RABBITMQ_PASSWORD_FILE']).read_text().strip()
conn=pika.BlockingConnection(pika.ConnectionParameters(host=os.environ['RABBITMQ_HOST'],
    credentials=pika.PlainCredentials(os.environ['RABBITMQ_USER'],password)))
channel=conn.channel()
channel.confirm_delivery()
channel.basic_publish(exchange='agrodiagnostico.events',routing_key='diagnosis.requested.v2',
    body=json.dumps(envelope).encode(),mandatory=True,
    properties=pika.BasicProperties(delivery_mode=2,content_type='application/json'))
conn.close()
print(json.dumps({'published_confirmed':True,'event_id':envelope['event_id']}))
"""

QUEUE = """
import json,os
from pathlib import Path
import pika
password=Path(os.environ['RABBITMQ_PASSWORD_FILE']).read_text().strip()
conn=pika.BlockingConnection(pika.ConnectionParameters(host=os.environ['RABBITMQ_HOST'],
    credentials=pika.PlainCredentials(os.environ['RABBITMQ_USER'],password)))
state=conn.channel().queue_declare(queue='ai_inference.diagnosis-requested.v2',passive=True).method
conn.close()
print(json.dumps({'queue_messages_after':state.message_count,'queue_consumers_after':state.consumer_count}))
"""

INTERNAL = """
import json,sys,urllib.error,urllib.request
data=json.loads(sys.stdin.read())
base='http://127.0.0.1:8000/internal/diagnoses/'+data['diagnosis_id']
def call(suffix,payload):
    request=urllib.request.Request(base+suffix,method='POST',data=json.dumps(payload).encode(),
        headers={'Authorization':'Bearer '+data['token'],'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=10) as response:
            return response.status,json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code,json.loads(error.read())
claim_code,claim=call('/claim',{})
renew_code,renew=call('/lease/renew',{'lease_token':data['stale_token']}) if claim_code==200 else (None,{})
print(json.dumps({'claim_http':claim_code,'stale_renew_http':renew_code,
    'stale_renew_code':renew.get('code') or renew.get('detail',{}).get('code')}))
"""


def service_json(base: list[str], service: str, code: str, *args: str, input_data=None) -> dict:
    result = subprocess.run(base + ["exec", "-T", service, "python", "-c", code, *args],
                            input=input_data, capture_output=True, text=True, timeout=110)
    if result.returncode:
        raise RuntimeError("FAULT_PROBE_SERVICE_COMMAND_FAILED: " + service + " " + result.stderr[-400:])
    return json.loads(result.stdout.strip())


def probe(base, run, report, base_url: str, owner_token: str, sample: dict,
          secrets: Path, multipart) -> None:
    """Exercise durable restart, renewals, stale fencing and broker redelivery."""
    run(base + ["--profile", "ml-real", "stop", "ai_inference-worker-real"])
    body, content_type = multipart(sample["path"].read_bytes(), "POTATO")
    code, created, _ = request_json(base_url + "/api/v1/diagnoses", "POST", body,
                                    {"Authorization": "Bearer " + owner_token,
                                     "Content-Type": content_type,
                                     "Idempotency-Key": str(uuid.uuid4())})
    if code != 202:
        raise AssertionError("RESTART_UPLOAD_NOT_ACCEPTED")
    diagnosis_id = created["id"]
    before = service_json(base, "diagnosis", QUERY,
                          "SELECT status FROM diagnoses WHERE id=CAST(:id AS uuid)", diagnosis_id)
    if before["status"] != "PENDIENTE":
        raise AssertionError("RESTART_JOB_NOT_DURABLE_PENDING")
    monitor = subprocess.Popen(base + ["exec", "-T", "diagnosis", "python", "-c", MONITOR,
                                       diagnosis_id], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    run(base + ["--profile", "ml-real", "up", "-d", "--wait", "--wait-timeout", "180",
                "ai_inference-worker-real"], timeout=300)
    deadline = time.monotonic() + 90
    detail = {}
    while time.monotonic() < deadline:
        status_code, detail, _ = request_json(base_url + "/api/v1/diagnoses/" + diagnosis_id,
                                              headers={"Authorization": "Bearer " + owner_token})
        if status_code == 200 and detail["status"] in {"COMPLETADO", "NO_CONCLUYENTE", "FALLIDO"}:
            break
        time.sleep(.2)
    else:
        monitor.kill()
        raise AssertionError("RESTART_TERMINAL_TIMEOUT")
    output, errors = monitor.communicate(timeout=15)
    if monitor.returncode:
        raise RuntimeError("HEARTBEAT_MONITOR_FAILED: " + errors[-400:])
    monitored = json.loads(output.strip())
    report["fault_restart_heartbeat"] = {"diagnosis_id": diagnosis_id,
                                         "pending_before_restart": before["status"] == "PENDIENTE",
                                         "terminal_status": detail["status"], **monitored}

    redelivered = service_json(base, "diagnosis", REDELIVER, diagnosis_id)
    time.sleep(2)
    queue = service_json(base, "ai_inference", QUEUE)
    ai_counts = service_json(base, "ai_inference", QUERY,
        "SELECT (SELECT count(*) FROM inference_inbox WHERE diagnosis_id=CAST(:id AS uuid)) AS inbox, "
        "(SELECT count(*) FROM inference_results WHERE diagnosis_id=CAST(:id AS uuid)) AS results, "
        "(SELECT count(*) FROM inference_outbox WHERE diagnosis_id=CAST(:id AS uuid)) AS outbox", diagnosis_id)
    diag_counts = service_json(base, "diagnosis", QUERY,
        "SELECT count(*) AS finished FROM diagnosis_outbox WHERE diagnosis_id=CAST(:id AS uuid) AND event_type='DiagnosisFinished'",
        diagnosis_id)
    report["fault_redelivery"] = {**redelivered, **queue, **ai_counts, **diag_counts}

    run(base + ["--profile", "ml-real", "stop", "ai_inference-worker-real"])
    body, content_type = multipart(sample["path"].read_bytes(), "POTATO")
    code, new_created, _ = request_json(base_url + "/api/v1/diagnoses", "POST", body,
                                        {"Authorization": "Bearer " + owner_token,
                                         "Content-Type": content_type,
                                         "Idempotency-Key": str(uuid.uuid4())})
    if code != 202:
        raise AssertionError("STALE_PROBE_UPLOAD_NOT_ACCEPTED")
    key = Path(secrets / "internal_worker_1_private_key.pem").read_text()
    now = int(time.time())
    internal_token = jwt.encode({"iss": "agrodiagnostico-internal", "aud": "diagnosis-internal",
                                 "sub": "ai_inference", "instance_id": "worker-1",
                                 "jti": str(uuid.uuid4()), "iat": now, "exp": now + 60},
                                key, algorithm="EdDSA", headers={"kid": "worker-1-key"})
    stale = service_json(base, "diagnosis", INTERNAL,
        input_data=json.dumps({"diagnosis_id": new_created["id"], "token": internal_token,
                               "stale_token": str(uuid.uuid4())}))
    report["fault_stale_lease"] = stale
    report["fault_matrix_pass"] = (
        report["fault_restart_heartbeat"]["pending_before_restart"]
        and report["fault_restart_heartbeat"]["terminal_status"] in {"COMPLETADO", "NO_CONCLUYENTE"}
        and report["fault_restart_heartbeat"]["lease_expirations_observed"] >= 2
        and redelivered["published_confirmed"] and queue["queue_messages_after"] == 0
        and queue["queue_consumers_after"] >= 1
        and ai_counts == {"inbox": 1, "results": 1, "outbox": 1}
        and diag_counts == {"finished": 1}
        and stale == {"claim_http": 200, "stale_renew_http": 409, "stale_renew_code": "STALE_LEASE"})
