import os
import sys

# Tratamento de erro amigável caso a biblioteca pydicom não esteja instalada
try:
    import pydicom
except ImportError:
    print("ERRO: A biblioteca 'pydicom' não foi encontrada.")
    print("Por favor, abra o terminal do seu WinPython e digite: pip install pydicom")
    sys.exit(1)

# Importando a biblioteca tkinter para a interface gráfica
import tkinter as tk
from tkinter import filedialog, messagebox

# Importando o matplotlib para a visualização da imagem e integração com o tkinter
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


def open_and_show_dicom(file_path: str, canvas_frame: tk.Frame) -> None:
    """
    Lê um arquivo DICOM e exibe sua imagem na interface gráfica.

    Args:
        file_path (str): Caminho absoluto para o arquivo DICOM.
        canvas_frame (tk.Frame): O frame do Tkinter onde a imagem será renderizada.
    """
    # Verifica se o arquivo realmente existe no sistema antes de tentar abrir
    if not os.path.exists(file_path):
        messagebox.showerror("Erro", f"O arquivo '{file_path}' não foi encontrado.")
        return

    try:
        # Lê o arquivo DICOM
        dataset = pydicom.dcmread(file_path)

        # Verifica se o arquivo DICOM possui a tag de Pixel Data.
        if not hasattr(dataset, 'pixel_array'):
            messagebox.showwarning("Aviso", "Este arquivo DICOM não contém dados de imagem (Pixel Data).\nPode ser um DICOM de Relatório Estruturado (SR) ou arquivo corrompido.")
            return

        # Extrai a matriz matemática da imagem
        image_array = dataset.pixel_array

        # Limpa qualquer imagem anterior do frame
        for widget in canvas_frame.winfo_children():
            widget.destroy()

        # Cria uma figura para exibir a imagem (tamanho ajustado para a janela)
        fig, ax = plt.subplots(figsize=(6, 6))

        # Exibe a imagem usando um mapa de cores em escala de cinza (padrão radiológico)
        ax.imshow(image_array, cmap='gray')

        # Removemos os eixos numéricos (x, y) para focar apenas na anatomia
        ax.axis('off')

        # Extrai algumas informações básicas para o título (se existirem)
        modality = dataset.Modality if 'Modality' in dataset else 'Desconhecida'
        patient_name = dataset.PatientName if 'PatientName' in dataset else 'Anonimizado'

        ax.set_title(f"Modalidade: {modality} | Paciente: {patient_name}")

        # Integra a figura do matplotlib no tkinter
        canvas = FigureCanvasTkAgg(fig, master=canvas_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    except pydicom.errors.InvalidDicomError:
        messagebox.showerror("Erro", "O arquivo selecionado não é um arquivo DICOM válido.")
    except Exception as e:
        messagebox.showerror("Erro Inesperado", f"Ocorreu uma falha ao processar a imagem.\nDetalhes: {e}")


def main_gui():
    """Configura e inicia a interface gráfica principal."""
    # Cria a janela principal
    root = tk.Tk()
    root.title("Visualizador DICOM Básico")
    root.geometry("700x800")

    # Adiciona um pequeno padding geral
    root.configure(padx=10, pady=10)

    # Função chamada quando o botão "Selecionar Arquivo" é clicado
    def select_file():
        file_path = filedialog.askopenfilename(
            title="Selecione uma imagem DICOM",
            # Filtro básico, embora arquivos DICOM muitas vezes não tenham extensão
            filetypes=[("Arquivos DICOM", "*.dcm"), ("Todos os Arquivos", "*.*")]
        )
        if file_path:
            # Mostra o caminho do arquivo selecionado (opcional, para feedback)
            path_label.config(text=f"Arquivo: {os.path.basename(file_path)}")
            # Tenta abrir e mostrar a imagem
            open_and_show_dicom(file_path, image_frame)

    # --- Elementos da Interface ---

    # 1. Botão de Seleção
    btn_select = tk.Button(
        root,
        text="Selecionar Imagem DICOM",
        command=select_file,
        font=("Arial", 12, "bold"),
        bg="#4CAF50",  # Um verde amigável
        fg="white",
        padx=10, pady=5
    )
    btn_select.pack(pady=(0, 10))

    # 2. Label para mostrar o nome do arquivo selecionado
    path_label = tk.Label(root, text="Nenhum arquivo selecionado", fg="gray")
    path_label.pack(pady=(0, 10))

    # 3. Frame (quadro) onde a imagem será renderizada
    # Usamos um frame com borda para demarcar a área da imagem
    image_frame = tk.Frame(root, bg="black", bd=2, relief=tk.SUNKEN)
    image_frame.pack(fill=tk.BOTH, expand=True)

    # Texto inicial dentro do quadro preto
    initial_label = tk.Label(image_frame, text="A imagem aparecerá aqui", bg="black", fg="white")
    initial_label.pack(expand=True)

    # Inicia o loop da interface gráfica
    root.mainloop()


if __name__ == "__main__":
    main_gui()
