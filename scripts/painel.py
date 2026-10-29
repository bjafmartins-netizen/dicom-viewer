#!/usr/bin/env python3
"""Painel do miniPACS — o fluxo inteiro numa janela, sem linha de comando.

    python scripts/painel.py

Cada botão monta e roda o mesmo comando documentado em `docs/COMANDOS.md`, num
subprocesso, com a saída aparecendo no log da própria janela. O painel não
reimplementa nada: se um comando funciona no terminal, funciona aqui, e
vice-versa.

Usa só Tkinter, que vem com o Python — nada a instalar.
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from typing import Any, Dict, List, Optional, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACS = os.path.join(RAIZ, "pacs")
ORTHANC_EXE = os.path.join(PACS, "Orthanc.exe")
SAL = os.path.join(RAIZ, ".salt")

# 127.0.0.1 em vez de localhost: no Windows o localhost resolve primeiro para
# ::1 e cada requisição perde ~2 s até cair no IPv4 (ver orthanc_client.py).
URL = "http://127.0.0.1:8042"
URLS_NAVEGADOR = (
    ("Orthanc Explorer", URL),
    ("Stone Web Viewer", URL + "/stone-webviewer/index.html"),
    ("OHIF Viewer", URL + "/ohif/"),
)

# Evita o piscar de uma janela de console a cada subprocesso (só no Windows).
SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ambiente() -> Dict[str, str]:
    """Ambiente dos subprocessos, com saída em UTF-8.

    Sem isto, um acento no log mata o filho com UnicodeEncodeError quando o
    console está em cp1252.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    return env


class Painel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("miniPACS — painel")
        self.geometry("1000x700")
        self.minsize(860, 580)

        self._fila: "queue.Queue[tuple]" = queue.Queue()
        self._tarefa: Optional[threading.Thread] = None
        self._orthanc: Optional[subprocess.Popen] = None

        self.var_entrada = tk.StringVar(value=os.path.join(RAIZ, "data", "phantom"))
        self.var_saida = tk.StringVar(value=os.path.join(RAIZ, "metadados.csv"))
        self.var_nivel = tk.StringVar(value="serie")
        self.var_tags = tk.StringVar()
        self.var_anonimizar = tk.BooleanVar(value=True)
        self.var_estudo = tk.StringVar()
        self.var_servidor = tk.StringVar(value="Servidor: verificando...")
        self.var_tarefa = tk.StringVar(value="pronto")

        self._montar()
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.after(100, self._drenar)
        threading.Thread(target=self._vigiar_servidor, daemon=True).start()

    # -- interface ---------------------------------------------------------

    def _montar(self) -> None:
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)

        topo = ttk.Frame(self, padding=(10, 8, 10, 0))
        topo.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._montar_servidor(topo)

        esquerda = ttk.Frame(self, padding=(10, 8, 5, 10))
        esquerda.grid(row=1, column=0, sticky="nsw")
        self._montar_acoes(esquerda)

        direita = ttk.Frame(self, padding=(5, 8, 10, 10))
        direita.grid(row=1, column=1, sticky="nsew")
        self._montar_log(direita)

    def _montar_servidor(self, pai: ttk.Frame) -> None:
        caixa = ttk.LabelFrame(pai, text="Servidor", padding=8)
        caixa.pack(fill="x")

        linha = ttk.Frame(caixa)
        linha.pack(fill="x")
        ttk.Label(linha, textvariable=self.var_servidor,
                  font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(linha, text="Parar", command=self._parar_servidor).pack(side="right", padx=2)
        ttk.Button(linha, text="Subir servidor",
                   command=self._subir_servidor).pack(side="right", padx=2)

        atalhos = ttk.Frame(caixa)
        atalhos.pack(fill="x", pady=(8, 0))
        for nome, endereco in URLS_NAVEGADOR:
            ttk.Button(atalhos, text=nome, width=18,
                       command=lambda e=endereco: webbrowser.open(e)).pack(side="left", padx=(0, 6))

    def _montar_acoes(self, pai: ttk.Frame) -> None:
        pastas = ttk.LabelFrame(pai, text="Pastas", padding=8)
        pastas.pack(fill="x")
        pastas.columnconfigure(0, weight=1)

        ttk.Label(pastas, text="Exames (entrada):").grid(row=0, column=0, sticky="w")
        ttk.Entry(pastas, textvariable=self.var_entrada, width=38).grid(row=1, column=0, sticky="ew")
        ttk.Button(pastas, text="...", width=3,
                   command=self._escolher_entrada).grid(row=1, column=1, padx=(4, 0))

        ttk.Label(pastas, text="Planilha de saída:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(pastas, textvariable=self.var_saida, width=38).grid(row=3, column=0, sticky="ew")
        ttk.Button(pastas, text="...", width=3,
                   command=self._escolher_saida).grid(row=3, column=1, padx=(4, 0))

        importar = ttk.LabelFrame(pai, text="Importar", padding=8)
        importar.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(importar, text="Anonimizar antes de enviar",
                        variable=self.var_anonimizar).pack(anchor="w")
        ttk.Button(importar, text="Importar pasta para o servidor",
                   command=self._importar).pack(fill="x", pady=(6, 0))
        ttk.Button(importar, text="Só anonimizar (sem enviar)",
                   command=self._anonimizar).pack(fill="x", pady=(4, 0))

        extrair = ttk.LabelFrame(pai, text="Metadados", padding=8)
        extrair.pack(fill="x", pady=(10, 0))
        nivel = ttk.Frame(extrair)
        nivel.pack(fill="x")
        ttk.Label(nivel, text="Uma linha por:").pack(side="left")
        ttk.Radiobutton(nivel, text="série", value="serie",
                        variable=self.var_nivel).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(nivel, text="imagem", value="instancia",
                        variable=self.var_nivel).pack(side="left")

        ttk.Label(extrair, text="Tags extras (nome ou 0021,1004):").pack(anchor="w", pady=(6, 0))
        ttk.Entry(extrair, textvariable=self.var_tags).pack(fill="x")
        ttk.Button(extrair, text="Exportar da pasta",
                   command=self._extrair_pasta).pack(fill="x", pady=(6, 0))
        ttk.Button(extrair, text="Exportar do servidor",
                   command=self._extrair_servidor).pack(fill="x", pady=(4, 0))
        ttk.Button(extrair, text="Miniaturas (PNG) da pasta",
                   command=self._miniaturas).pack(fill="x", pady=(4, 0))

        protocolo = ttk.LabelFrame(pai, text="Protocolo de esclerose múltipla", padding=8)
        protocolo.pack(fill="x", pady=(10, 0))
        ttk.Label(protocolo, text="Estudo (UID ou ID do Orthanc):").pack(anchor="w")
        ttk.Entry(protocolo, textvariable=self.var_estudo).pack(fill="x")
        ttk.Button(protocolo, text="Conferir esse estudo",
                   command=self._protocolo_estudo).pack(fill="x", pady=(6, 0))
        ttk.Button(protocolo, text="Conferir todos no servidor",
                   command=self._protocolo_todos).pack(fill="x", pady=(4, 0))
        ttk.Button(protocolo, text="Conferir a pasta de entrada",
                   command=self._protocolo_pasta).pack(fill="x", pady=(4, 0))

        manutencao = ttk.LabelFrame(pai, text="Manutenção", padding=8)
        manutencao.pack(fill="x", pady=(10, 0))
        ttk.Button(manutencao, text="Gerar exame de teste (phantom)",
                   command=self._phantom).pack(fill="x")
        ttk.Button(manutencao, text="Rodar os testes", command=self._testes).pack(fill="x", pady=(4, 0))

    def _montar_log(self, pai: ttk.Frame) -> None:
        cabecalho = ttk.Frame(pai)
        cabecalho.pack(fill="x")
        ttk.Label(cabecalho, textvariable=self.var_tarefa).pack(side="left")
        ttk.Button(cabecalho, text="Limpar", command=self._limpar_log).pack(side="right")

        moldura = ttk.Frame(pai)
        moldura.pack(fill="both", expand=True, pady=(6, 0))
        self.log = tk.Text(
            moldura, wrap="none", font=("Consolas", 9), background="#11151c",
            foreground="#d8dee9", insertbackground="#d8dee9",
        )
        vertical = ttk.Scrollbar(moldura, orient="vertical", command=self.log.yview)
        horizontal = ttk.Scrollbar(pai, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.log.pack(side="left", fill="both", expand=True)
        vertical.pack(side="right", fill="y")
        horizontal.pack(fill="x")

        self.log.tag_configure("comando", foreground="#88c0d0")
        self.log.tag_configure("erro", foreground="#f08080")
        self.log.tag_configure("fim", foreground="#a3be8c")
        self.log.configure(state="disabled")

    # -- log e fila --------------------------------------------------------

    def _escrever(self, texto: str, tag: str = "") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _limpar_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _drenar(self) -> None:
        """Passa para a janela o que as threads produziram.

        Tkinter não é thread-safe: só esta função, rodando no laço de eventos,
        toca nos widgets.
        """
        try:
            while True:
                tipo, carga = self._fila.get_nowait()
                if tipo == "servidor":
                    self.var_servidor.set(carga)
                elif tipo == "fim":
                    if carga:
                        self._escrever(carga, "fim")
                    self.var_tarefa.set("pronto")
                else:
                    self._escrever(carga, tipo if tipo != "linha" else "")
        except queue.Empty:
            pass
        self.after(100, self._drenar)

    # -- execução ----------------------------------------------------------

    def _ocupado(self) -> bool:
        if self._tarefa is not None and self._tarefa.is_alive():
            messagebox.showinfo("Aguarde", "Já há uma tarefa rodando. Espere ela terminar.")
            return True
        return False

    def _rodar(self, argv: Sequence[str], titulo: str) -> None:
        """Dispara um comando numa thread, jogando a saída no log."""
        if self._ocupado():
            return
        self.var_tarefa.set(titulo + "...")
        self._tarefa = threading.Thread(
            target=self._trabalhar, args=(list(argv), titulo), daemon=True
        )
        self._tarefa.start()

    def _trabalhar(self, argv: List[str], titulo: str) -> None:
        self._fila.put(("comando", "\n$ " + " ".join(argv)))
        try:
            processo = subprocess.Popen(
                argv, cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=_ambiente(), creationflags=SEM_JANELA,
            )
        except OSError as exc:
            self._fila.put(("erro", "não consegui executar: " + str(exc)))
            self._fila.put(("fim", ""))
            return

        for linha in processo.stdout or ():
            self._fila.put(("linha", linha.rstrip("\n")))
        codigo = processo.wait()
        if codigo == 0:
            self._fila.put(("fim", "[" + titulo + "] concluído."))
        else:
            self._fila.put(("erro", f"[{titulo}] terminou com código {codigo}."))
            self._fila.put(("fim", ""))

    def _py(self, *resto: str) -> List[str]:
        return [sys.executable, *resto]

    # -- servidor ----------------------------------------------------------

    def _vigiar_servidor(self) -> None:
        """Pergunta ao Orthanc, de 3 em 3 segundos, se ele está de pé."""
        while True:
            self._fila.put(("servidor", _estado_servidor()))
            time.sleep(3)

    def _subir_servidor(self) -> None:
        if _consultar("/system") is not None:
            self._escrever("O servidor já está no ar.", "fim")
            return
        if not os.path.exists(ORTHANC_EXE):
            messagebox.showerror(
                "Orthanc não encontrado",
                "Não achei " + ORTHANC_EXE + ".\n\n"
                "Baixe a versão portátil e extraia em pacs\\ (veja pacs/README.md).",
            )
            return
        self._escrever("\n$ Orthanc.exe orthanc.json", "comando")
        self._orthanc = subprocess.Popen(
            [ORTHANC_EXE, "orthanc.json"], cwd=PACS, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=SEM_JANELA,
        )
        threading.Thread(target=self._ler_orthanc, args=(self._orthanc,), daemon=True).start()

    def _ler_orthanc(self, processo: subprocess.Popen) -> None:
        for linha in processo.stdout or ():
            self._fila.put(("linha", linha.rstrip("\n")))
        self._fila.put(("erro", f"Orthanc encerrou (código {processo.wait()})."))

    def _parar_servidor(self) -> None:
        if self._orthanc is None or self._orthanc.poll() is not None:
            self._escrever(
                "Este painel não subiu o servidor — se há um Orthanc rodando, "
                "feche a janela dele.", "erro",
            )
            return
        self._orthanc.terminate()
        self._escrever("Pedido de encerramento enviado ao Orthanc.", "fim")

    # -- ações -------------------------------------------------------------

    def _escolher_entrada(self) -> None:
        escolhida = filedialog.askdirectory(
            title="Pasta com os exames", initialdir=self.var_entrada.get() or RAIZ
        )
        if escolhida:
            self.var_entrada.set(os.path.normpath(escolhida))

    def _escolher_saida(self) -> None:
        escolhido = filedialog.asksaveasfilename(
            title="Salvar metadados como", defaultextension=".csv",
            initialfile=os.path.basename(self.var_saida.get() or "metadados.csv"),
            initialdir=os.path.dirname(self.var_saida.get()) or RAIZ,
            filetypes=[("CSV", "*.csv"), ("JSON", "*.json"), ("Parquet", "*.parquet")],
        )
        if escolhido:
            self.var_saida.set(os.path.normpath(escolhido))

    def _entrada(self) -> Optional[str]:
        caminho = self.var_entrada.get().strip()
        if not caminho or not os.path.exists(caminho):
            messagebox.showwarning("Pasta de entrada", "Escolha uma pasta que exista.")
            return None
        return caminho

    def _saida(self) -> str:
        return self.var_saida.get().strip() or os.path.join(RAIZ, "metadados.csv")

    def _tags(self) -> List[str]:
        return argumentos_de_tags(self.var_tags.get())

    def _importar(self) -> None:
        entrada = self._entrada()
        if not entrada:
            return
        argv = self._py("scripts/import_folder.py", "--input", entrada, "--url", URL)
        if self.var_anonimizar.get():
            argv += ["--anonymize", "--salt-file", SAL]
        self._rodar(argv, "importar")

    def _anonimizar(self) -> None:
        entrada = self._entrada()
        if not entrada:
            return
        destino = filedialog.askdirectory(
            title="Pasta de destino (anonimizada)", initialdir=os.path.join(RAIZ, "data")
        )
        if not destino:
            return
        self._rodar(
            self._py("-m", "metadata.anonymize", "--input", entrada,
                     "--output", os.path.normpath(destino), "--salt-file", SAL),
            "anonimizar",
        )

    def _extrair_pasta(self) -> None:
        entrada = self._entrada()
        if not entrada:
            return
        self._rodar(
            self._py("-m", "metadata.extract_metadata", "--input", entrada,
                     "--output", self._saida(), "--nivel", self.var_nivel.get()) + self._tags(),
            "extrair da pasta",
        )

    def _extrair_servidor(self) -> None:
        self._rodar(
            self._py("-m", "metadata.extract_metadata", "--orthanc", URL,
                     "--output", self._saida(), "--nivel", self.var_nivel.get()) + self._tags(),
            "extrair do servidor",
        )

    def _miniaturas(self) -> None:
        entrada = self._entrada()
        if not entrada:
            return
        self._rodar(
            self._py("-m", "metadata.thumbnails", "--input", entrada,
                     "--output", os.path.join(RAIZ, "thumbs")),
            "miniaturas",
        )

    def _protocolo_estudo(self) -> None:
        estudo = self.var_estudo.get().strip()
        if not estudo:
            messagebox.showwarning(
                "Estudo",
                "Informe o StudyInstanceUID ou o ID do Orthanc.\n\n"
                "Sem um estudo em mãos, use \"Conferir todos no servidor\".",
            )
            return
        self._rodar(
            self._py("scripts/check_ms_protocol.py", "--study", estudo, "--url", URL),
            "protocolo EM",
        )

    def _protocolo_todos(self) -> None:
        self._rodar(
            self._py("scripts/check_ms_protocol.py", "--todos", "--url", URL),
            "protocolo EM (todos)",
        )

    def _protocolo_pasta(self) -> None:
        entrada = self._entrada()
        if not entrada:
            return
        self._rodar(
            self._py("scripts/check_ms_protocol.py", "--input", entrada),
            "protocolo EM (pasta)",
        )

    def _phantom(self) -> None:
        destino = os.path.join(RAIZ, "data", "phantom")
        self._rodar(self._py("scripts/make_phantom_dataset.py", "--output", destino), "phantom")
        self.var_entrada.set(destino)

    def _testes(self) -> None:
        self._rodar(self._py("-m", "unittest", "discover", "-s", "tests"), "testes")

    # -- encerramento ------------------------------------------------------

    def _ao_fechar(self) -> None:
        if self._orthanc is not None and self._orthanc.poll() is None:
            if not messagebox.askokcancel(
                "Fechar",
                "O servidor foi subido por este painel e vai parar junto. Fechar?",
            ):
                return
            self._orthanc.terminate()
        self.destroy()


def argumentos_de_tags(bruto: str) -> List[str]:
    """Transforma o campo de tags extras em uma lista de ``--tag X``.

    Aceita separação por espaço, vírgula ou ponto-e-vírgula. A vírgula também
    separa grupo e elemento de uma tag privada (``0021,1004``), então não
    quebra em vírgula seguida de quatro dígitos hexadecimais.
    """
    argumentos: List[str] = []
    for pedaco in re.split(r"[;\s]+|,(?![0-9A-Fa-f]{4}\b)", bruto.strip()):
        pedaco = pedaco.strip()
        if pedaco:
            argumentos += ["--tag", pedaco]
    return argumentos


def _consultar(caminho: str, timeout: float = 1.5) -> Optional[Dict[str, Any]]:
    """GET no Orthanc; devolve None se ele não responder."""
    try:
        with urllib.request.urlopen(URL + caminho, timeout=timeout) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _estado_servidor() -> str:
    dados = _consultar("/statistics")
    if dados is None:
        return "Servidor: fora do ar"
    return (
        f"Servidor: no ar — {dados.get('CountStudies')} estudo(s), "
        f"{dados.get('CountSeries')} série(s), {dados.get('CountInstances')} imagem(ns)"
    )


def main() -> int:
    Painel().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
