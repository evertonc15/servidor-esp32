"""Ciclo de vida do anúncio: troca de IP, desconexão e recuperação."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import text
from network_discovery import ServerDiscovery, lan_addresses
from storage import Store


class DiscoveryTest(unittest.TestCase):
    def test_direct_http_notice_works_even_when_mdns_is_unavailable(self):
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200, read=Mock(return_value=b'DESCOBERTA_ACEITA'))
        factory = Mock(return_value=connection)
        zc = Mock()
        zc.register_service.side_effect = OSError('multicast indisponivel')
        d = ServerDiscovery(addresses=lambda: ['192.168.2.7'], factory=Mock(return_value=zc), http_factory=factory)
        d.refresh()
        d.notify_esp()
        self.assertFalse(d.status()['ativo'])
        self.assertTrue(d.status()['aviso_http']['aceito'])
        factory.assert_called_once_with('192.168.2.5', 80, timeout=2, source_address=('192.168.2.7', 0))
        connection.request.assert_called_once_with('GET', '/servidor')
        connection.close.assert_called_once()
        d.stop()

    def test_notice_has_backoff_but_ip_change_is_announced_immediately(self):
        current = ['192.168.2.7']
        connection = Mock()
        connection.getresponse.return_value = Mock(status=200, read=Mock(return_value=b'DESCOBERTA_ACEITA'))
        factory = Mock(return_value=connection)
        d = ServerDiscovery(addresses=lambda: current, http_factory=factory)
        with patch('network_discovery.time.monotonic', side_effect=[0, 10, 11, 42]):
            d.notify_esp()
            d.notify_esp()
            self.assertEqual(factory.call_count, 1)
            current[:] = ['192.168.2.8']
            d.notify_esp()
            self.assertEqual(d.status()['aviso_http']['ip_servidor'], '192.168.2.8')
            d.notify_esp()
            self.assertEqual(factory.call_count, 3)
        d.stop()

    def test_timeout_closes_notice_and_next_attempt_recovers(self):
        first, second = Mock(), Mock()
        first.getresponse.side_effect = TimeoutError('ESP ocupada')
        second.getresponse.return_value = Mock(status=200, read=Mock(return_value=b'DESCOBERTA_ACEITA'))
        d = ServerDiscovery(addresses=lambda: ['192.168.2.7'], http_factory=Mock(side_effect=[first, second]))
        with patch('network_discovery.time.monotonic', side_effect=[0, 31]):
            d.notify_esp()
            self.assertFalse(d.status()['aviso_http']['aceito'])
            first.close.assert_called_once()
            d.notify_esp()
            self.assertTrue(d.status()['aviso_http']['aceito'])
        d.stop()

    def test_old_firmware_reply_is_not_treated_as_registration(self):
        connection = Mock()
        connection.getresponse.return_value = Mock(status=404, read=Mock(return_value=b'Not found'))
        d = ServerDiscovery(addresses=lambda: ['192.168.2.7'], http_factory=Mock(return_value=connection))
        d.notify_esp()
        self.assertFalse(d.status()['aviso_http']['aceito'])
        self.assertIn('firmware', d.status()['aviso_http']['erro'])
        connection.request.assert_called_once_with('GET', '/servidor')
        d.stop()

    def test_http_server_port_string_can_be_published(self):
        zc = Mock()
        d = ServerDiscovery(port='5050', addresses=lambda: ['192.168.2.7'], factory=Mock(return_value=zc))
        d.refresh()
        self.assertTrue(d.status()['ativo'])
        self.assertEqual(zc.register_service.call_args.args[0].port, 5050)
        d.stop()

    def test_change_of_ip_replaces_advertisement_and_same_ip_keeps_it(self):
        current = ['192.168.2.6']
        first, second = Mock(), Mock()
        factory = Mock(side_effect=[first, second])
        d = ServerDiscovery(addresses=lambda: current, factory=factory)
        d.refresh()
        d.refresh()
        self.assertEqual(factory.call_count, 1)
        current[:] = ['192.168.2.7']
        d.refresh()
        first.unregister_service.assert_called_once()
        first.close.assert_called_once()
        self.assertEqual(d.status()['enderecos'], ['192.168.2.7'])
        self.assertEqual(second.register_service.call_args.args[0].parsed_addresses(), ['192.168.2.7'])
        d.stop()
        second.close.assert_called_once()

    def test_interface_disappearance_cancels_old_ip_and_return_recovers(self):
        current = ['192.168.2.6']
        first, second = Mock(), Mock()
        d = ServerDiscovery(addresses=lambda: current, factory=Mock(side_effect=[first, second]))
        d.refresh()
        current.clear()
        d.refresh()
        self.assertFalse(d.status()['ativo'])
        first.close.assert_called_once()
        current.append('192.168.2.7')
        d.refresh()
        self.assertTrue(d.status()['ativo'])
        self.assertIsNone(d.status()['erro'])
        d.stop()

    def test_registration_failure_closes_socket_and_retries(self):
        first, second = Mock(), Mock()
        first.register_service.side_effect = OSError('rede indisponivel')
        d = ServerDiscovery(addresses=lambda: ['192.168.2.7'], factory=Mock(side_effect=[first, second]))
        d.refresh()
        self.assertFalse(d.status()['ativo'])
        first.close.assert_called_once()
        d.refresh()
        self.assertTrue(d.status()['ativo'])
        d.stop()

    def test_goodbye_failure_does_not_prevent_new_announcement(self):
        current = ['192.168.2.6']
        first, second = Mock(), Mock()
        first.unregister_service.side_effect = OSError('interface removida')
        d = ServerDiscovery(addresses=lambda: current, factory=Mock(side_effect=[first, second]))
        d.refresh()
        current[:] = ['192.168.2.7']
        d.refresh()
        self.assertEqual(d.status()['enderecos'], ['192.168.2.7'])
        first.close.assert_called_once()
        d.stop()

    def test_only_ipv4_in_selected_network_is_published(self):
        addresses = ['127.0.0.1', '10.0.0.5', '192.168.2.7', '192.168.2.7', ('::1', 0, 0)]
        adapters = [SimpleNamespace(ips=[SimpleNamespace(ip=ip) for ip in addresses])]
        with patch('network_discovery.ifaddr.get_adapters', return_value=adapters):
            self.assertEqual(lan_addresses(), ('192.168.2.7',))

    def test_previous_database_gets_static_ip_metadata_without_losing_plate(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            s = Store('sqlite:///' + str(Path(temp) / 'old.sqlite3').replace('\\', '/'))
            try:
                with s.engine.begin() as c:
                    c.execute(text('CREATE TABLE esp_placas (name VARCHAR(64) PRIMARY KEY, ip VARCHAR(15), updated DATETIME, automatic BOOLEAN, mode VARCHAR(16))'))
                    c.execute(text("INSERT INTO esp_placas VALUES ('anterior', '192.168.2.5', '2026-10-09', 0, 'cognitivo')"))
                s.initialize()
                s.initialize()
                with s.engine.connect() as c:
                    row = c.execute(text('SELECT name, ip, static_ip FROM esp_placas')).one()
                    self.assertEqual(tuple(row), ('anterior', '192.168.2.5', 0))
            finally:
                s.engine.dispose()


if __name__ == '__main__':
    unittest.main()
