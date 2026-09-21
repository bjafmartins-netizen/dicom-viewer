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
    extract_metadata,
    iter_dicom_files,
    scan_folder,
    write_records,
)
from metadata.thumbnails import thumbnails_for_folder  # noqa: E402

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
