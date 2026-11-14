from pathlib import Path
import pytest
from silhouette_mcp import server

def test_find_studio_exe():
    exe = server._find_studio_exe()
    # No Windows do usuario, Silhouette Studio 5 esta instalado
    if Path(r"C:\Program Files\Silhouette America\Silhouette Studio\Silhouette Studio.exe").is_file():
        assert exe != ""
        assert "Silhouette Studio.exe" in exe

def test_open_in_studio_resolution(monkeypatch):
    # Mock do subprocess.Popen para nao abrir janelas reais durante o teste
    launched_cmd = []
    def mock_popen(args):
        launched_cmd.append(args)
    monkeypatch.setattr(server.subprocess, "Popen", mock_popen)

    # Cria e exporta um arquivo de teste
    server.silhouette_new_design("open_test", width_mm=100, height_mm=100)
    server.silhouette_add_circle("open_test", 50, 50, 10)
    exp = server.silhouette_export("open_test", formats="dxf")
    dxf_path = exp["files"]["dxf"]

    # 1. Abre passando o caminho absoluto
    res1 = server.silhouette_open_in_studio(dxf_path)
    assert "opened" in res1

    # 2. Abre passando apenas o nome do arquivo
    res2 = server.silhouette_open_in_studio("open_test.dxf")
    assert "opened" in res2

    # 3. Abre passando o slug do design (adiciona .dxf automaticamente)
    res3 = server.silhouette_open_in_studio("open_test")
    assert "opened" in res3

    # Verifica se Popen foi chamado com o executavel
    if server._find_studio_exe():
        studio_calls = [cmd for cmd in launched_cmd if "Silhouette Studio.exe" in cmd[0]]
        assert len(studio_calls) == 3

def test_open_in_studio_missing_file():
    with pytest.raises(ValueError, match="not found or is not a .dxf/.svg file"):
        server.silhouette_open_in_studio("non_existent_design_xyz")

def test_open_in_studio_slug_resolution(monkeypatch):
    launched_cmd = []
    monkeypatch.setattr(server.subprocess, "Popen", lambda args: launched_cmd.append(args))

    server.silhouette_new_design("Meu Projeto Teste", width_mm=100, height_mm=100)
    server.silhouette_add_circle("Meu Projeto Teste", 50, 50, 10)
    exp = server.silhouette_export("Meu Projeto Teste", formats="dxf")
    expected_dxf = Path(exp["files"]["dxf"]).resolve()

    res1 = server.silhouette_open_in_studio("Meu Projeto Teste")
    assert Path(res1["opened"]).resolve() == expected_dxf

    res2 = server.silhouette_open_in_studio("Meu Projeto Teste.dxf")
    assert Path(res2["opened"]).resolve() == expected_dxf

def test_open_in_studio_oserror_raises_runtime_error(monkeypatch):
    def fail_popen(args):
        raise OSError("Executable failed to start")

    monkeypatch.setattr(server, "_find_studio_exe", lambda: r"C:\fake\Silhouette Studio.exe")
    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)
    monkeypatch.setattr(server.sys, "platform", "win32")

    server.silhouette_new_design("err_open", width_mm=100, height_mm=100)
    server.silhouette_add_circle("err_open", 50, 50, 10)
    server.silhouette_export("err_open", formats="dxf")

    with pytest.raises(RuntimeError, match="Failed to open"):
        server.silhouette_open_in_studio("err_open")

