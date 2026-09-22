"""Testes do cliente Orthanc contra um servidor HTTP de mentira.

Não requer um Orthanc rodando: um `http.server` mínimo imita as poucas rotas
que o cliente usa (/system, /instances, /dicom-web/studies).

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

from metadata.orthanc_client import OrthancClient, OrthancError, _clean  # noqa: E402

import make_phantom_dataset  # noqa: E402

ESTADO = {"instancias": [], "stow_calls": 0, "ultimo_content_type": ""}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencia o log do servidor nos testes
        pass

    def _responder(self, objeto, codigo=200):
        corpo = json.dumps(objeto).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path == "/system":
            self._responder({"Version": "1.12.3", "Name": "fake-orthanc"})
        elif self.path == "/statistics":
            self._responder({"CountInstances": len(ESTADO["instancias"])})
        elif self.path == "/instances":
            self._responder([i["ID"] for i in ESTADO["instancias"]])
        elif re.fullmatch(r"/instances/[^/]+/simplified-tags", self.path):
            indice = int(self.path.split("/")[2].split("-")[1])
            self._responder(ESTADO["instancias"][indice]["tags"])
        else:
            self._responder({"erro": self.path}, 404)

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        dados = self.rfile.read(tamanho)
        if self.path == "/instances":
            import io

            import pydicom

            ds = pydicom.dcmread(io.BytesIO(dados))
            indice = len(ESTADO["instancias"])
            ESTADO["instancias"].append(
                {
                    "ID": f"inst-{indice}",
                    "tags": {
                        "Modality": str(ds.Modality),
                        "PatientID": str(ds.PatientID),
                        "StudyInstanceUID": str(ds.StudyInstanceUID),
                        "SeriesInstanceUID": str(ds.SeriesInstanceUID),
                        "SOPInstanceUID": str(ds.SOPInstanceUID),
                        "KVP": str(getattr(ds, "KVP", "")),
                        "RepetitionTime": str(getattr(ds, "RepetitionTime", "")),
                    },
                }
            )
            self._responder({"ID": f"inst-{indice}", "Status": "Success"})
        elif self.path == "/dicom-web/studies":
            ESTADO["stow_calls"] += 1
            ESTADO["ultimo_content_type"] = self.headers.get("Content-Type", "")
            self._responder({"00081190": {"vr": "UR", "Value": ["http://fake/studies/1"]}})
        else:
            self._responder({"erro": self.path}, 404)


class TestOrthancClient(unittest.TestCase):
    slices = 2

    @classmethod
    def setUpClass(cls):
        cls.servidor = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.porta = cls.servidor.server_address[1]
        cls.thread = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.thread.start()

        cls.tmp = tempfile.mkdtemp(prefix="dicom-orthanc-test-")
        cls.dataset_dir = os.path.join(cls.tmp, "phantom")
        make_phantom_dataset.main(
            ["--output", cls.dataset_dir, "--slices", str(cls.slices), "--size", "32"]
        )
        cls.client = OrthancClient(f"http://127.0.0.1:{cls.porta}")

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        ESTADO["instancias"].clear()
        ESTADO["stow_calls"] = 0

    def test_system(self):
        self.assertEqual(self.client.system()["Name"], "fake-orthanc")

    def test_upload_rest(self):
        enviados, falhas = self.client.upload_folder(self.dataset_dir, verbose=False)
        self.assertEqual((enviados, falhas), (self.slices * 2, 0))
        self.assertEqual(len(self.client.list_instances()), self.slices * 2)

    def test_upload_stow_em_lotes(self):
        enviados, falhas = self.client.upload_folder(
            self.dataset_dir, use_stow=True, batch_size=3, verbose=False
        )
        self.assertEqual((enviados, falhas), (self.slices * 2, 0))
        # 4 arquivos em lotes de 3 => 2 POSTs
        self.assertEqual(ESTADO["stow_calls"], 2)
        self.assertIn("multipart/related", ESTADO["ultimo_content_type"])
        self.assertIn("boundary=", ESTADO["ultimo_content_type"])

    def test_scan_metadata_via_api(self):
        self.client.upload_folder(self.dataset_dir, verbose=False)
        registros = self.client.scan_metadata(verbose=False)
        self.assertEqual(len(registros), self.slices * 2)
        self.assertEqual({r["Modality"] for r in registros}, {"CT", "MR"})
        # tags específicas de modalidade também vêm pela API
        mr = next(r for r in registros if r["Modality"] == "MR")
        self.assertEqual(mr["RepetitionTime"], "4500.0")
        self.assertIn("OrthancInstanceID", mr)

    def test_erro_de_conexao_tem_mensagem_util(self):
        offline = OrthancClient("http://127.0.0.1:9", timeout=2)
        with self.assertRaises(OrthancError) as contexto:
            offline.system()
        self.assertIn("Orthanc está rodando", str(contexto.exception))


class TestNormalizacao(unittest.TestCase):
    """Valores da API precisam sair iguais aos lidos direto do arquivo."""

    def test_localhost_vira_ipv4(self):
        self.assertEqual(
            OrthancClient("http://localhost:8042/").base_url, "http://127.0.0.1:8042"
        )
        self.assertEqual(
            OrthancClient("http://orthanc:8042").base_url, "http://orthanc:8042"
        )

    def test_valores_multiplos_viram_lista(self):
        self.assertEqual(_clean("0.5\\0.5"), ["0.5", "0.5"])
        self.assertEqual(_clean("ORIGINAL\\PRIMARY"), ["ORIGINAL", "PRIMARY"])

    def test_float_longo_do_orthanc_encurta(self):
        self.assertEqual(_clean("0.90000000000000002"), "0.9")
        self.assertEqual(_clean("38.399999999999999"), "38.4")
        # UID e decimal curto ficam como estão
        self.assertEqual(_clean("1.2.840.10008.1.2.1"), "1.2.840.10008.1.2.1")
        self.assertEqual(_clean("4500.0"), "4500.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
