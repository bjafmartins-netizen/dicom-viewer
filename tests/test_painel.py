"""Testes do painel (`scripts/painel.py`) que não precisam abrir janela."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import painel  # noqa: E402


class TestArgumentosDeTags(unittest.TestCase):
    def test_vazio_nao_gera_argumento(self):
        self.assertEqual(painel.argumentos_de_tags("   "), [])

    def test_nomes_separados_por_espaco_e_ponto_e_virgula(self):
        self.assertEqual(
            painel.argumentos_de_tags("BodyPartExamined; ContrastBolusAgent"),
            ["--tag", "BodyPartExamined", "--tag", "ContrastBolusAgent"],
        )

    def test_tag_privada_nao_e_quebrada_na_virgula(self):
        # A vírgula de 0021,1004 separa grupo e elemento, não duas tags.
        self.assertEqual(painel.argumentos_de_tags("0021,1004"), ["--tag", "0021,1004"])

    def test_mistura_de_nome_e_numero(self):
        self.assertEqual(
            painel.argumentos_de_tags("BodyPartExamined, 0021,1004"),
            ["--tag", "BodyPartExamined", "--tag", "0021,1004"],
        )


class TestEnderecos(unittest.TestCase):
    def test_usa_ipv4_para_nao_esperar_o_fallback(self):
        self.assertIn("127.0.0.1", painel.URL)
        self.assertNotIn("localhost", painel.URL)

    def test_atalhos_do_navegador_apontam_para_o_mesmo_servidor(self):
        for _, endereco in painel.URLS_NAVEGADOR:
            self.assertTrue(endereco.startswith(painel.URL))

    def test_estado_do_servidor_nao_levanta_sem_orthanc(self):
        # Mesmo sem servidor no ar, a vigilância não pode derrubar a janela.
        texto = painel._estado_servidor()
        self.assertTrue(texto.startswith("Servidor:"))


class TestAmbienteDosSubprocessos(unittest.TestCase):
    def test_forca_utf8_na_saida(self):
        # Sem isto, um acento no log mata o filho em console cp1252.
        self.assertEqual(painel._ambiente()["PYTHONIOENCODING"], "utf-8")


if __name__ == "__main__":
    unittest.main()
