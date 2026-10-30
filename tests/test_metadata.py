"""Testes do módulo metadata/ — stdlib unittest, sem dependência de pytest.

    python -m unittest discover -s tests -v

O dataset de teste é gerado na hora pelo scripts/make_phantom_dataset.py, então
os testes não dependem de nenhum arquivo DICOM externo.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "scripts"))

import pydicom  # noqa: E402

from metadata.anonymize import (  # noqa: E402
    anonymize_dataset,
    anonymize_folder,
    pseudo_id,
)
from metadata.extract_metadata import (  # noqa: E402
    MODALITY_TAGS,
    acquisition_matrix_freq_phase,
    extract_metadata,
    group_by_series,
    image_plane,
    iter_dicom_files,
    parse_tag,
    phase_encoding_axis,
    scan_folder,
    tags_for_modality,
    write_records,
)
from metadata.thumbnails import thumbnails_for_folder  # noqa: E402

import check_ms_protocol  # noqa: E402
import make_phantom_dataset  # noqa: E402


class PhantomBase(unittest.TestCase):
    """Gera um estudo sintético pequeno, uma vez para toda a classe."""

    slices = 3
    size = 64

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="dicom-test-")
        cls.dataset_dir = os.path.join(cls.tmp, "phantom")
        make_phantom_dataset.main(
            ["--output", cls.dataset_dir, "--slices", str(cls.slices), "--size", str(cls.size)]
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestPhantomGenerator(PhantomBase):
    def test_gera_duas_series_no_mesmo_estudo(self):
        registros = scan_folder(self.dataset_dir)
        self.assertEqual(len(registros), self.slices * 2)
        self.assertEqual(len({r["StudyInstanceUID"] for r in registros}), 1)
        self.assertEqual(len({r["SeriesInstanceUID"] for r in registros}), 2)
        self.assertEqual({r["Modality"] for r in registros}, {"CT", "MR"})

    def test_arquivos_sao_dicom_legiveis(self):
        for path in iter_dicom_files(self.dataset_dir):
            ds = pydicom.dcmread(path)
            self.assertTrue(ds.pixel_array.shape == (self.size, self.size))


class TestExtractMetadata(PhantomBase):
    def test_tags_comuns_presentes(self):
        registro = scan_folder(self.dataset_dir)[0]
        for keyword in ("PatientID", "Modality", "SOPInstanceUID", "Rows", "Columns"):
            self.assertIn(keyword, registro)
        self.assertTrue(registro["HasImageData"])
        self.assertTrue(registro["FilePath"].endswith(".dcm"))

    def test_tags_especificas_por_modalidade(self):
        registros = scan_folder(self.dataset_dir)
        mr = next(r for r in registros if r["Modality"] == "MR")
        ct = next(r for r in registros if r["Modality"] == "CT")

        # MR traz parâmetros de RM e não traz os de TC
        self.assertEqual(mr["RepetitionTime"], 4500.0)
        self.assertEqual(mr["EchoTime"], 96.0)
        self.assertEqual(mr["MagneticFieldStrength"], 1.5)
        self.assertNotIn("KVP", mr)

        # TC traz parâmetros de TC e não traz os de RM
        self.assertEqual(ct["KVP"], 120.0)
        self.assertEqual(ct["ConvolutionKernel"], "B30f")
        self.assertNotIn("RepetitionTime", ct)

    def test_tipos_nativos_para_serializacao(self):
        registro = scan_folder(self.dataset_dir)[0]
        self.assertIsInstance(registro["SliceThickness"], float)
        self.assertIsInstance(registro["InstanceNumber"], int)
        self.assertIsInstance(registro["PixelSpacing"], list)
        self.assertIsInstance(registro["PatientID"], str)

    def test_tag_extra_sob_demanda(self):
        ds = pydicom.dcmread(next(iter_dicom_files(self.dataset_dir)))
        registro = extract_metadata(ds, extra_tags=["SoftwareVersions"])
        self.assertEqual(registro["SoftwareVersions"], "0.2.0")

    def test_escrita_csv_e_json(self):
        registros = scan_folder(self.dataset_dir)
        for nome in ("saida.csv", "saida.json"):
            destino = os.path.join(self.tmp, nome)
            write_records(registros, destino)
            self.assertTrue(os.path.getsize(destino) > 0)

        import csv
        with open(os.path.join(self.tmp, "saida.csv"), encoding="utf-8-sig") as fh:
            linhas = list(csv.DictReader(fh))
        self.assertEqual(len(linhas), len(registros))
        # União das colunas: linha de MR tem a coluna KVP (vazia), e vice-versa
        self.assertIn("KVP", linhas[0])
        self.assertIn("RepetitionTime", linhas[0])

    def test_extensao_de_saida_invalida(self):
        with self.assertRaises(ValueError):
            write_records([{"a": 1}], os.path.join(self.tmp, "saida.xyz"))

    def test_ignora_arquivo_nao_dicom(self):
        lixo = os.path.join(self.dataset_dir, "anotacao.bin")
        with open(lixo, "wb") as fh:
            fh.write(b"isto nao e dicom")
        try:
            registros = scan_folder(self.dataset_dir)
            self.assertEqual(len(registros), self.slices * 2)
        finally:
            os.remove(lixo)


class TestPlanoDeCorte(unittest.TestCase):
    """Plano deduzido da orientação — o DICOM não traz essa informação pronta."""

    def test_planos_ortogonais(self):
        self.assertEqual(image_plane([1, 0, 0, 0, 1, 0]), "AXIAL")
        self.assertEqual(image_plane([0, 1, 0, 0, 0, -1]), "SAGITAL")
        self.assertEqual(image_plane([1, 0, 0, 0, 0, -1]), "CORONAL")

    def test_obliquo_e_ausente(self):
        self.assertEqual(image_plane([0.7, 0.7, 0, 0, 0, -1]), "OBLIQUO")
        self.assertIsNone(image_plane(None))
        self.assertIsNone(image_plane([1, 0, 0]))  # incompleto
        self.assertIsNone(image_plane(["a", "b", "c", "d", "e", "f"]))


class TestDirecaoDeFase(unittest.TestCase):
    """ROW/COL do DICOM traduzido para o eixo do paciente."""

    def test_axial_row_e_latero_lateral(self):
        # Corte axial: a primeira direção da imagem aponta para a esquerda.
        registro = {
            "InPlanePhaseEncodingDirection": "ROW",
            "ImageOrientationPatient": [1, 0, 0, 0, 1, 0],
        }
        self.assertEqual(phase_encoding_axis(registro), "R-L")

    def test_axial_col_e_antero_posterior(self):
        registro = {
            "InPlanePhaseEncodingDirection": "COL",
            "ImageOrientationPatient": [1, 0, 0, 0, 1, 0],
        }
        self.assertEqual(phase_encoding_axis(registro), "A-P")

    def test_sagital_col_e_cranio_caudal(self):
        registro = {
            "InPlanePhaseEncodingDirection": "COL",
            "ImageOrientationPatient": [0, 1, 0, 0, 0, -1],
        }
        self.assertEqual(phase_encoding_axis(registro), "F-H")

    def test_mesmo_row_muda_de_eixo_conforme_o_plano(self):
        # É justamente isto que ROW/COL sozinho não diz.
        axial = {"InPlanePhaseEncodingDirection": "ROW",
                 "ImageOrientationPatient": [1, 0, 0, 0, 1, 0]}
        sagital = {"InPlanePhaseEncodingDirection": "ROW",
                   "ImageOrientationPatient": [0, 1, 0, 0, 0, -1]}
        self.assertNotEqual(phase_encoding_axis(axial), phase_encoding_axis(sagital))

    def test_obliquo_e_faltante(self):
        self.assertEqual(
            phase_encoding_axis({
                "InPlanePhaseEncodingDirection": "ROW",
                "ImageOrientationPatient": [0.7, 0.7, 0, 0, 0, -1],
            }),
            "OBLIQUO",
        )
        self.assertIsNone(phase_encoding_axis({}))
        self.assertIsNone(phase_encoding_axis({
            "InPlanePhaseEncodingDirection": "OTHER",
            "ImageOrientationPatient": [1, 0, 0, 0, 1, 0],
        }))
        self.assertIsNone(phase_encoding_axis({
            "InPlanePhaseEncodingDirection": "ROW",
            "ImageOrientationPatient": None,
        }))


class TestMatrizDeAquisicao(unittest.TestCase):
    """Os quatro valores do AcquisitionMatrix reduzidos a frequência x fase."""

    def test_fase_na_coluna(self):
        # (0, 384, 256, 0) — como vem dos equipamentos GE do serviço.
        self.assertEqual(acquisition_matrix_freq_phase([0, 384, 256, 0]), "384x256")

    def test_fase_na_linha(self):
        self.assertEqual(acquisition_matrix_freq_phase([256, 0, 0, 192]), "256x192")

    def test_strings_do_orthanc(self):
        # Pelo servidor os valores chegam como texto.
        self.assertEqual(acquisition_matrix_freq_phase(["0", "384", "256", "0"]), "384x256")

    def test_ausente_ou_invalido(self):
        self.assertIsNone(acquisition_matrix_freq_phase(None))
        self.assertIsNone(acquisition_matrix_freq_phase([0, 384, 256]))
        self.assertIsNone(acquisition_matrix_freq_phase([0, 0, 0, 0]))
        self.assertIsNone(acquisition_matrix_freq_phase(["a", "b", "c", "d"]))


class TestNivelSerie(PhantomBase):
    """Uma linha por série, em vez de uma por imagem."""

    def test_uma_linha_por_serie_com_contagem(self):
        series = group_by_series(scan_folder(self.dataset_dir))
        self.assertEqual(len(series), 2)  # CT + MR
        self.assertEqual({s["InstanceCount"] for s in series}, {self.slices})
        self.assertEqual({s["Modality"] for s in series}, {"CT", "MR"})

    def test_colunas_de_instancia_somem_e_faixa_aparece(self):
        linha = group_by_series(scan_folder(self.dataset_dir))[0]
        for coluna in ("SOPInstanceUID", "InstanceNumber", "FilePath", "SliceLocation"):
            self.assertNotIn(coluna, linha)
        self.assertLess(linha["SliceLocationMin"], linha["SliceLocationMax"])

    def test_parametros_da_serie_sao_preservados(self):
        series = group_by_series(scan_folder(self.dataset_dir))
        mr = next(s for s in series if s["Modality"] == "MR")
        ct = next(s for s in series if s["Modality"] == "CT")
        self.assertEqual(mr["RepetitionTime"], 4500.0)
        self.assertEqual(mr["ImagePlane"], "AXIAL")
        self.assertEqual(mr["MatrixRowsColumns"], f"{self.size}x{self.size}")
        self.assertEqual(ct["KVP"], 120.0)
        self.assertTrue(ct["ConvolutionKernel"])

    def test_valor_que_varia_na_serie_nao_e_escondido(self):
        registros = [
            {"SeriesInstanceUID": "s1", "ConvolutionKernel": "B30f"},
            {"SeriesInstanceUID": "s1", "ConvolutionKernel": "B70f"},
        ]
        linha = group_by_series(registros)[0]
        self.assertEqual(linha["ConvolutionKernel"], "B30f | B70f")
        self.assertEqual(linha["InstanceCount"], 2)


class TestTagsPorNumero(PhantomBase):
    """Tags sem keyword (privadas de fabricante) pedidas por número."""

    def test_formatos_aceitos(self):
        self.assertEqual(parse_tag("0021,1004"), 0x00211004)
        self.assertEqual(parse_tag("(0021,1004)"), 0x00211004)
        self.assertEqual(parse_tag("0x0021,0x1004"), 0x00211004)
        self.assertIsNone(parse_tag("PatientID"))
        self.assertIsNone(parse_tag("0021"))

    def test_le_tag_privada_do_arquivo(self):
        caminho = next(iter_dicom_files(self.dataset_dir))
        ds = pydicom.dcmread(caminho)
        bloco = ds.private_block(0x0021, "FABRICANTE TESTE", create=True)
        bloco.add_new(0x04, "DS", "4.7")

        # VR "DS" vira float nativo, como em qualquer outra tag decimal.
        registro = extract_metadata(ds, extra_tags=["0021,1004"])
        self.assertEqual(registro["0021,1004"], 4.7)

    def test_tag_privada_ausente_nao_quebra(self):
        ds = pydicom.dcmread(next(iter_dicom_files(self.dataset_dir)))
        self.assertIsNone(extract_metadata(ds, extra_tags=["0099,9999"])["0099,9999"])


class TestTagsDeFluoroscopia(unittest.TestCase):
    """RF/XA precisam de tempo de fluoro e número de disparos; CR/DX não."""

    def test_rf_e_xa_tem_tempo_de_fluoroscopia(self):
        for modalidade in ("RF", "XA"):
            tags = tags_for_modality(modalidade)
            self.assertIn("TotalTimeOfFluoroscopy", tags)
            self.assertIn("TotalNumberOfExposures", tags)
            self.assertIn("ImageAndFluoroscopyAreaDoseProduct", tags)

    def test_cr_e_dx_mantem_o_conjunto_de_radiografia(self):
        for modalidade in ("CR", "DX"):
            tags = tags_for_modality(modalidade)
            self.assertIn("ExposureIndex", tags)
            self.assertNotIn("TotalTimeOfFluoroscopy", tags)

    def test_keywords_existem_no_dicionario_dicom(self):
        from pydicom.datadict import tag_for_keyword

        for modalidade in MODALITY_TAGS:
            for keyword in tags_for_modality(modalidade):
                self.assertIsNotNone(
                    tag_for_keyword(keyword), f"{modalidade}: {keyword} não existe"
                )


class TestProtocoloEM(unittest.TestCase):
    """Conferência do protocolo mínimo de esclerose múltipla."""

    @staticmethod
    def _series(*descricoes, acquisition_type=""):
        return [
            {"MainDicomTags": {"SeriesDescription": d, "MRAcquisitionType": acquisition_type}}
            for d in descricoes
        ]

    def test_protocolo_completo_passa(self):
        series = self._series(
            "T2 FLAIR SPACE SAG", "T1 MPRAGE POS GD", "SWI VENOSO", "AX T2 ORBITAS"
        )
        self.assertTrue(check_ms_protocol.evaluate_ms_protocol(series, verbose=False))

    def test_falta_de_swi_alerta_mas_nao_bloqueia(self):
        series = self._series("3D FLAIR", "T1 +C")
        self.assertTrue(check_ms_protocol.evaluate_ms_protocol(series, verbose=False))

    def test_falta_de_flair_3d_bloqueia(self):
        series = self._series("AX FLAIR 2D", "T1 POS GD", "SWI")
        self.assertFalse(check_ms_protocol.evaluate_ms_protocol(series, verbose=False))

    def test_falta_de_t1_com_contraste_bloqueia(self):
        series = self._series("T2 FLAIR CUBE", "T1 SAG", "SWI")
        self.assertFalse(check_ms_protocol.evaluate_ms_protocol(series, verbose=False))

    def test_3d_vem_do_cabecalho_quando_o_nome_nao_diz(self):
        # Descrição sem marca de volumétrica, mas MRAcquisitionType=3D
        series = self._series("FLAIR DARK FLUID", acquisition_type="3D")
        series += self._series("T1 GD")
        self.assertTrue(check_ms_protocol.evaluate_ms_protocol(series, verbose=False))

    def test_protocolo_vazio_bloqueia(self):
        self.assertFalse(check_ms_protocol.evaluate_ms_protocol([], verbose=False))


class TestAnonymize(PhantomBase):
    def test_pseudonimo_estavel_e_dependente_do_sal(self):
        self.assertEqual(pseudo_id("PAC1", "sal"), pseudo_id("PAC1", "sal"))
        self.assertNotEqual(pseudo_id("PAC1", "sal"), pseudo_id("PAC1", "outro"))
        self.assertNotEqual(pseudo_id("PAC1", "sal"), pseudo_id("PAC2", "sal"))

    def test_remove_identificacao_e_marca_dataset(self):
        ds = pydicom.dcmread(next(iter_dicom_files(self.dataset_dir)))
        anonimizado = anonymize_dataset(ds, salt="sal-de-teste")
        self.assertTrue(str(anonimizado.PatientName).startswith("ANON-"))
        self.assertEqual(str(anonimizado.PatientID), str(anonimizado.PatientName))
        self.assertEqual(anonimizado.PatientBirthDate, "")
        self.assertEqual(anonimizado.InstitutionName, "")
        self.assertEqual(anonimizado.ReferringPhysicianName, "")
        self.assertEqual(anonimizado.PatientIdentityRemoved, "YES")
        self.assertLessEqual(len(anonimizado.DeidentificationMethod), 64)

    def test_politica_de_datas(self):
        caminho = next(iter_dicom_files(self.dataset_dir))

        ano = anonymize_dataset(pydicom.dcmread(caminho), salt="s", date_policy="year")
        self.assertEqual(ano.StudyDate, "20240101")

        removida = anonymize_dataset(pydicom.dcmread(caminho), salt="s", date_policy="remove")
        self.assertEqual(removida.StudyDate, "")

        deslocada = anonymize_dataset(
            pydicom.dcmread(caminho), salt="s", date_policy="shift", shift_days=10
        )
        self.assertEqual(deslocada.StudyDate, "20240125")

        mantida = anonymize_dataset(pydicom.dcmread(caminho), salt="s", date_policy="keep")
        self.assertEqual(mantida.StudyDate, "20240115")

    def test_uids_remapeados_preservam_agrupamento(self):
        destino = os.path.join(self.tmp, "anon")
        processados, _, _ = anonymize_folder(self.dataset_dir, destino, salt="sal-de-teste")
        self.assertEqual(processados, self.slices * 2)

        originais = scan_folder(self.dataset_dir)
        anonimizados = scan_folder(destino)

        # Mesma estrutura: 1 estudo, 2 séries, N instâncias distintas
        self.assertEqual(len({r["StudyInstanceUID"] for r in anonimizados}), 1)
        self.assertEqual(len({r["SeriesInstanceUID"] for r in anonimizados}), 2)
        self.assertEqual(
            len({r["SOPInstanceUID"] for r in anonimizados}), self.slices * 2
        )

        # ... mas nenhum UID igual ao original
        uids_originais = {r["StudyInstanceUID"] for r in originais}
        uids_anon = {r["StudyInstanceUID"] for r in anonimizados}
        self.assertTrue(uids_originais.isdisjoint(uids_anon))

        # SOPClassUID (identifica o tipo de objeto) deve ser preservado
        self.assertEqual(
            {r["SOPClassUID"] for r in originais}, {r["SOPClassUID"] for r in anonimizados}
        )

    def test_anonimizacao_e_deterministica_entre_execucoes(self):
        a = os.path.join(self.tmp, "anon-a")
        b = os.path.join(self.tmp, "anon-b")
        anonymize_folder(self.dataset_dir, a, salt="mesmo-sal")
        anonymize_folder(self.dataset_dir, b, salt="mesmo-sal")
        ra = sorted(scan_folder(a), key=lambda r: r["FileName"])
        rb = sorted(scan_folder(b), key=lambda r: r["FileName"])
        self.assertEqual(
            [r["SOPInstanceUID"] for r in ra], [r["SOPInstanceUID"] for r in rb]
        )
        self.assertEqual([r["PatientID"] for r in ra], [r["PatientID"] for r in rb])

    def test_pixels_intactos(self):
        destino = os.path.join(self.tmp, "anon-pixels")
        anonymize_folder(self.dataset_dir, destino, salt="s")
        original = pydicom.dcmread(os.path.join(self.dataset_dir, "CT", "CT_0001.dcm"))
        anonimizado = pydicom.dcmread(os.path.join(destino, "CT", "CT_0001.dcm"))
        self.assertTrue((original.pixel_array == anonimizado.pixel_array).all())


class TestThumbnails(PhantomBase):
    def test_uma_miniatura_por_serie(self):
        destino = os.path.join(self.tmp, "thumbs")
        gerados = thumbnails_for_folder(self.dataset_dir, destino, size=64, verbose=False)
        self.assertEqual(len(gerados), 2)

        from PIL import Image
        for caminho in gerados:
            with Image.open(caminho) as imagem:
                self.assertLessEqual(max(imagem.size), 64)

    def test_uma_miniatura_por_instancia(self):
        destino = os.path.join(self.tmp, "thumbs-inst")
        gerados = thumbnails_for_folder(
            self.dataset_dir, destino, size=32, per_instance=True, verbose=False
        )
        self.assertEqual(len(gerados), self.slices * 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
