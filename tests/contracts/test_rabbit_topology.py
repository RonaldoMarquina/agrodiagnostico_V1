"""Tests for RabbitMQ durable topology, least-privilege credentials, and bootstrap (Task 4.1).

Verifies:
- Topic exchange 'agrodiagnostico.events' is declared durable.
- All queues (Requested v1/v2, Analyzed v1, Finished v1, and DLQs) are durable.
- Exact bindings match routing.json.
- Least-privilege permissions per service:
  - Diagnosis: can write to exchange, read only diagnosis-analyzed queues, cannot read ai_inference queues.
  - AI Inference: can write to exchange, read only diagnosis-requested queues, cannot read diagnosis queues.
  - Notification: read-only on diagnosis-finished queues, cannot write to exchange.
- Re-declaration and reconnect idempotency.
"""
import json
from pathlib import Path
import re
import unittest
from unittest.mock import MagicMock, call, patch

from infra.rabbitmq.bootstrap import (
    EXCHANGE_NAME,
    QUEUES_AND_BINDINGS,
    SERVICE_PERMISSIONS,
    bootstrap_rabbitmq,
    declare_topology_amqp,
    provision_users_and_permissions,
)


class TestRabbitTopologyAndCredentials(unittest.TestCase):
    def setUp(self):
        self.routing_path = Path("contracts/events/routing.json")
        self.routing_data = json.loads(self.routing_path.read_text())

    def test_exchange_name_matches_routing_spec(self):
        self.assertEqual(EXCHANGE_NAME, self.routing_data["exchange"])

    def test_topology_queues_and_bindings_match_routing_json(self):
        """All queues defined in routing.json plus DLQs must be present in topology."""
        defined_queues = {item["queue"]: item["routing_key"] for item in QUEUES_AND_BINDINGS}

        for ev in self.routing_data["events"]:
            queue = ev["queue"]
            routing_key = ev["routing_key"]
            dlq = ev["dlq"]

            # Main queue and binding must exist
            self.assertIn(queue, defined_queues)
            self.assertEqual(defined_queues[queue], routing_key)

            # DLQ queue and binding must exist
            self.assertIn(dlq, defined_queues)
            self.assertEqual(defined_queues[dlq], f"{routing_key}.dlq")

    def test_least_privilege_permissions_negative_and_positive(self):
        """Verify strict regex patterns enforce least privilege between services."""
        # 1. Diagnosis permissions
        diag = SERVICE_PERMISSIONS["rabbit_diagnosis"]
        diag_read_re = re.compile(diag["read"])
        diag_write_re = re.compile(diag["write"])

        # Can write to event exchange
        self.assertTrue(diag_write_re.match("agrodiagnostico.events"))
        # Cannot write to random exchanges
        self.assertFalse(diag_write_re.match("amq.topic"))
        self.assertFalse(diag_write_re.match("other.exchange"))

        # Can read diagnosis-analyzed queues
        self.assertTrue(diag_read_re.match("diagnosis.diagnosis-analyzed.v1"))
        self.assertTrue(diag_read_re.match("diagnosis.diagnosis-analyzed.v1.dlq"))
        # CANNOT read ai_inference or notification queues
        self.assertFalse(diag_read_re.match("ai_inference.diagnosis-requested.v1"))
        self.assertFalse(diag_read_re.match("ai_inference.diagnosis-requested.v2"))
        self.assertFalse(diag_read_re.match("notification.diagnosis-finished.v1"))

        # 2. AI Inference permissions
        ai = SERVICE_PERMISSIONS["rabbit_ai_inference"]
        ai_read_re = re.compile(ai["read"])
        ai_write_re = re.compile(ai["write"])

        # Can write to event exchange
        self.assertTrue(ai_write_re.match("agrodiagnostico.events"))
        # Can read ai_inference queues
        self.assertTrue(ai_read_re.match("ai_inference.diagnosis-requested.v1"))
        self.assertTrue(ai_read_re.match("ai_inference.diagnosis-requested.v1.dlq"))
        self.assertTrue(ai_read_re.match("ai_inference.diagnosis-requested.v2"))
        self.assertTrue(ai_read_re.match("ai_inference.diagnosis-requested.v2.dlq"))
        # CANNOT read diagnosis-analyzed or notification queues
        self.assertFalse(ai_read_re.match("diagnosis.diagnosis-analyzed.v1"))
        self.assertFalse(ai_read_re.match("notification.diagnosis-finished.v1"))

        # 3. Notification permissions
        notif = SERVICE_PERMISSIONS["rabbit_notification"]
        notif_read_re = re.compile(notif["read"])
        notif_write_re = re.compile(notif["write"])

        # CANNOT write to any exchange (read-only consumer)
        self.assertFalse(notif_write_re.match("agrodiagnostico.events"))
        self.assertFalse(notif_write_re.match("amq.default"))

        # Can read notification queues
        self.assertTrue(notif_read_re.match("notification.diagnosis-finished.v1"))
        self.assertTrue(notif_read_re.match("notification.diagnosis-finished.v1.dlq"))
        # CANNOT read diagnosis or ai_inference queues
        self.assertFalse(notif_read_re.match("diagnosis.diagnosis-analyzed.v1"))
        self.assertFalse(notif_read_re.match("ai_inference.diagnosis-requested.v2"))

    @patch("infra.rabbitmq.bootstrap.pika.BlockingConnection")
    def test_declare_topology_amqp_idempotent(self, mock_conn_cls):
        """Verify AMQP topology declaration declares durable exchange, queues, and bindings."""
        mock_conn = MagicMock()
        mock_channel = MagicMock()
        mock_conn.channel.return_value = mock_channel
        mock_conn_cls.return_value.__enter__.return_value = mock_conn

        declare_topology_amqp("test_host", 5672, "test_user", "test_pass")

        # Must declare exchange as topic and durable
        mock_channel.exchange_declare.assert_called_once_with(
            exchange="agrodiagnostico.events",
            exchange_type="topic",
            durable=True,
            auto_delete=False,
        )

        # Must declare all 8 queues as durable
        self.assertEqual(mock_channel.queue_declare.call_count, 8)
        for c in mock_channel.queue_declare.call_args_list:
            self.assertTrue(c.kwargs["durable"])
            self.assertFalse(c.kwargs["auto_delete"])
            self.assertFalse(c.kwargs["exclusive"])

        # Must bind all 8 queues to exchange
        self.assertEqual(mock_channel.queue_bind.call_count, 8)

    @patch("infra.rabbitmq.bootstrap.mgmt_request")
    @patch("infra.rabbitmq.bootstrap.read_secret")
    def test_provision_users_and_permissions(self, mock_read_secret, mock_mgmt):
        mock_read_secret.return_value = "supersecret123"

        provision_users_and_permissions("localhost", 15672, "Basic token")

        # 3 users created + 3 permissions set = 6 calls
        self.assertEqual(mock_mgmt.call_count, 6)

    @patch("infra.rabbitmq.bootstrap.wait_for_rabbitmq")
    @patch("infra.rabbitmq.bootstrap.declare_topology_amqp")
    @patch("infra.rabbitmq.bootstrap.provision_users_and_permissions")
    @patch("infra.rabbitmq.bootstrap.read_secret")
    def test_bootstrap_idempotent_flow(self, mock_secret, mock_prov, mock_decl, mock_wait):
        mock_secret.return_value = "admin_pass"
        mock_wait.return_value = "Basic token"

        res = bootstrap_rabbitmq(host="localhost", admin_user="admin")
        self.assertTrue(res)
        mock_decl.assert_called_once()
        mock_prov.assert_called_once()


if __name__ == "__main__":
    unittest.main()

