import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrations.brasilapi import BrasilAPIError, consultar, endpoint
from integrations.brasilapi_panel import CATEGORIES


class BrasilAPITests(unittest.TestCase):
    def test_normalization(self):
        for resource, value, expected in [
            ("cep", "01001-000", "cep/v2/01001000"),
            ("cnpj", "19.131.243/0001-97", "cnpj/v1/19131243000197"),
            ("cnpj", "AB.CDE.FGH/0001-12", "cnpj/v1/ABCDEFGH000112"),
            ("cpf", "107.235.550-79", "cpf/v1/10723555079"),
            ("ddd", "11", "ddd/v2/11"),
            ("ncm", "3305.10.00", "ncm/v1/33051000"),
            ("cnae", "01.113", "ibge/cnae/v1/classes/01113"),
            ("ibpt_versao", "", "ibpt/versao/v1"),
            ("municipios", "sp", "ibge/municipios/v1/SP"),
        ]:
            with self.subTest(resource=resource, value=value):
                self.assertEqual(endpoint(resource, value), expected)

    @patch("integrations.brasilapi.requests.get")
    def test_invalid_inputs_never_send_request(self, get):
        for resource, value in [("cep", "abcdefgh"), ("cep", "123"), ("cnpj", "12"), ("cpf", "00000000000"), ("ddd", "01"), ("ncm", "123"), ("cnae", "1234"), ("ibpt_versao", "x"), ("municipios", "XX"), ("url", "https://example.com")]:
            with self.subTest(resource=resource), self.assertRaises(BrasilAPIError):
                consultar(resource, value)
        get.assert_not_called()

    @patch("integrations.brasilapi.requests.get")
    def test_success_and_request_isolation(self, get):
        get.return_value = Mock(status_code=200, json=Mock(return_value={"cep": "01001000"}))
        self.assertEqual(consultar("cep", "01001-000"), {"cep": "01001000"})
        args, kwargs = get.call_args
        self.assertEqual(args[0], "https://brasilapi.com.br/api/cep/v2/01001000")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (5, 20))
        self.assertNotIn("Authorization", kwargs["headers"])

    @patch("integrations.brasilapi.requests.get")
    def test_new_response_formats(self, get):
        cases = [("ddd", "11", [{"state": "SP", "cities": []}]), ("ncm", "33051000", {"codigo": "3305.10.00"}), ("cnae", "01113", {"id": "01113"}), ("ibpt_versao", "", {"versao": "24.2.A"})]
        for resource, value, payload in cases:
            get.return_value = Mock(status_code=200, json=Mock(return_value=payload))
            with self.subTest(resource=resource):
                self.assertEqual(consultar(resource, value), payload)

    @patch("integrations.brasilapi.requests.get")
    def test_upstream_errors(self, get):
        for status in (301, 400, 404, 422, 429, 500, 503):
            get.return_value = Mock(status_code=status)
            with self.subTest(status=status), self.assertRaises(BrasilAPIError):
                consultar("municipios", "SP")

    @patch("integrations.brasilapi.requests.get")
    def test_transport_errors(self, get):
        for error in (requests.Timeout(), requests.ConnectionError()):
            get.side_effect = error
            with self.subTest(error=error), self.assertRaises(BrasilAPIError):
                consultar("municipios", "SP")

    @patch("integrations.brasilapi.requests.get")
    def test_malformed_payload(self, get):
        for payload in (None, "bad", {}, ["bad"]):
            get.return_value = Mock(status_code=200, json=Mock(return_value=payload))
            with self.subTest(payload=payload), self.assertRaises(BrasilAPIError):
                consultar("municipios", "SP")
        get.return_value = Mock(status_code=200, json=Mock(side_effect=ValueError()))
        with self.assertRaises(BrasilAPIError):
            consultar("municipios", "SP")

    def test_panel_submit_error_and_switch(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string("from integrations.brasilapi_panel import render\nrender()")
        app.run()
        self.assertFalse(app.exception)
        with patch("integrations.brasilapi_panel.consultar", return_value={"cep": "01001000", "city": "São Paulo"}) as call:
            app.text_input[0].set_value("01001-000")
            app.button[0].click().run()
            call.assert_called_once_with("cep", "01001000")
            self.assertEqual(len(app.dataframe), 1)
            app.text_input[0].set_value("invalid")
            app.button[0].click().run()
            self.assertEqual(len(app.error), 1)
            self.assertEqual(len(app.dataframe), 0)
            app.selectbox[0].select("Municípios").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox[1].value, "SP")

    def test_removed_categories_are_not_available(self):
        self.assertEqual(set(CATEGORIES), {"⌖  Endereço e Localização", "◈  Empresas e Pessoas", "▤  Fiscal e Comércio"})
        resources = {resource for options in CATEGORIES.values() for resource in options.values()}
        self.assertFalse(resources & {"moedas", "taxas", "banks", "feriados"})


if __name__ == "__main__":
    unittest.main()
