"""Instalador e desinstalador da LadderIDE para Windows (por usuario, sem administrador).

Empacotado por scripts/build_installer.py em dois executaveis:
  LadderIDE-Setup-<versao>.exe  este programa + payload.zip (a IDE completa)
  Desinstalar.exe               este programa sem payload, copiado para a pasta instalada

Instalar: extrai a IDE em %LOCALAPPDATA%\\Programs\\LadderIDE (ou outra pasta),
cria atalhos no menu Iniciar (e, se marcado, na area de trabalho), associa os
arquivos .ladproj e registra o desinstalador em "Aplicativos instalados".
Tudo fica em HKEY_CURRENT_USER e na pasta do usuario.

Linha de comando (testes e instalacao automatica):
  --silent  --dir <pasta>  --no-shortcuts  --no-registry  --no-launch
  --uninstall [--silent] [--dir <pasta>]
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

APP = "LadderIDE"
EXE = "LadderIDE.exe"
MARKER = "ladderide-install.json"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\LadderIDE"
PROG_ID = "LadderIDE.Projeto"


def resource(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def default_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs" / APP


def start_menu_dir() -> Path:
    return Path(os.environ.get("APPDATA", Path.home())) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP


def desktop_dir() -> Path:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=20, creationflags=_NO_WINDOW)
        if out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def payload_info() -> dict:
    with zipfile.ZipFile(resource("payload.zip")) as z:
        return json.loads(z.read("LadderIDE/ladderide-version.json"))


# ------------------------------------------------------------------ atalhos
def make_shortcut(lnk: Path, target: Path, description: str) -> None:
    lnk.parent.mkdir(parents=True, exist_ok=True)
    script = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
              f"$s.TargetPath='{target}';$s.WorkingDirectory='{target.parent}';"
              f"$s.IconLocation='{target},0';$s.Description='{description}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   check=True, capture_output=True, timeout=60, creationflags=_NO_WINDOW)


# ----------------------------------------------------------------- registro
def register(install_dir: Path, version: str, size_kb: int, associate: bool) -> None:
    import winreg
    exe = install_dir / EXE
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        values = {"DisplayName": APP, "DisplayVersion": version, "InstallLocation": str(install_dir),
                  "DisplayIcon": str(exe), "UninstallString": f'"{install_dir / "Desinstalar.exe"}"',
                  "QuietUninstallString": f'"{install_dir / "Desinstalar.exe"}" --silent',
                  "Comments": "IDE LADDER para CLP com ESP32"}
        for name, value in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        for name, value in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", size_kb)):
            winreg.SetValueEx(k, name, 0, winreg.REG_DWORD, value)
    if associate:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.ladproj") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, PROG_ID)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Projeto LadderIDE")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\DefaultIcon") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{exe}",0')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\open\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{exe}" "%1"')
        _notify_shell()


def unregister() -> None:
    import winreg

    def delete_tree(root, path: str) -> None:
        try:
            with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        delete_tree(root, f"{path}\\{winreg.EnumKey(k, 0)}")
                    except OSError:
                        break
            winreg.DeleteKey(root, path)
        except FileNotFoundError:
            pass

    delete_tree(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    delete_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}")
    try:                                         # so remove a associacao se ainda for nossa
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.ladproj") as k:
            ours = winreg.QueryValueEx(k, "")[0] == PROG_ID
        if ours:
            delete_tree(winreg.HKEY_CURRENT_USER, r"Software\Classes\.ladproj")
    except FileNotFoundError:
        pass
    _notify_shell()


def _notify_shell() -> None:
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)   # SHCNE_ASSOCCHANGED
    except (OSError, AttributeError):
        pass


# ---------------------------------------------------------------- instalar
def is_running(install_dir: Path) -> bool:
    """A IDE aberta trava o executavel: tenta renomear para saber."""
    exe = install_dir / EXE
    if not exe.exists():
        return False
    probe = exe.with_suffix(".exe.verifica")
    try:
        exe.rename(probe)
        probe.rename(exe)
        return False
    except OSError:
        return True


def install(install_dir: Path, *, shortcuts: bool, desktop: bool, registry: bool, associate: bool,
            progress=lambda pct, text: None) -> dict:
    info = payload_info()
    if is_running(install_dir):
        raise RuntimeError("A LadderIDE esta aberta. Feche todas as janelas dela e tente de novo.")
    marker = install_dir / MARKER
    if install_dir.exists() and any(install_dir.iterdir()) and not marker.exists():
        raise RuntimeError(f"A pasta {install_dir} ja existe e nao e uma instalacao da LadderIDE. "
                           "Escolha uma pasta vazia.")
    if marker.exists():
        progress(2, "Removendo a versao anterior...")
        _remove_files(install_dir, keep_self=False)
    install_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(resource("payload.zip")) as z:
        members = [m for m in z.infolist() if m.filename.startswith("LadderIDE/") and not m.is_dir()]
        total = sum(m.file_size for m in members) or 1
        done = 0
        files = []
        for m in members:
            rel = m.filename[len("LadderIDE/"):]
            dest = install_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(m) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            files.append(rel)
            done += m.file_size
            progress(5 + int(85 * done / total), f"Copiando {rel}")
    links = []
    if shortcuts:
        progress(92, "Criando atalhos...")
        for lnk, target, text in ((start_menu_dir() / f"{APP}.lnk", install_dir / EXE, "IDE LADDER para CLP com ESP32"),
                                  (start_menu_dir() / f"Desinstalar {APP}.lnk", install_dir / "Desinstalar.exe",
                                   "Remove a LadderIDE")):
            make_shortcut(lnk, target, text)
            links.append(str(lnk))
        if desktop:
            lnk = desktop_dir() / f"{APP}.lnk"
            make_shortcut(lnk, install_dir / EXE, "IDE LADDER para CLP com ESP32")
            links.append(str(lnk))
    if registry:
        progress(96, "Registrando no Windows...")
        register(install_dir, info["version"], total // 1024, associate)
    manifest = {"app": APP, "version": info["version"], "files": files, "shortcuts": links,
                "registry": registry}
    marker.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    progress(100, "Instalacao concluida.")
    return manifest


# ------------------------------------------------------------- desinstalar
def _remove_files(install_dir: Path, keep_self: bool) -> None:
    me = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
    for item in list(install_dir.iterdir()):
        if keep_self and me is not None and item.resolve() == me:
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except OSError:
                pass


def uninstall(install_dir: Path) -> None:
    marker = install_dir / MARKER
    if not marker.exists():
        raise RuntimeError(f"{install_dir} nao e uma instalacao da LadderIDE.")
    if is_running(install_dir):
        raise RuntimeError("A LadderIDE esta aberta. Feche todas as janelas dela e tente de novo.")
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    for link in manifest.get("shortcuts", []):
        try:
            Path(link).unlink()
        except OSError:
            pass
    try:
        start_menu_dir().rmdir()
    except OSError:
        pass
    if manifest.get("registry"):
        unregister()
    _remove_files(install_dir, keep_self=True)
    me = Path(sys.executable)
    if getattr(sys, "frozen", False) and me.parent.resolve() == install_dir.resolve():
        # o proprio desinstalador so pode ser apagado depois de terminar
        subprocess.Popen(f'cmd /c ping 127.0.0.1 -n 3 >nul & del /f /q "{me}" & rmdir /s /q "{install_dir}"',
                         creationflags=_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0), close_fds=True)
    else:
        shutil.rmtree(install_dir, ignore_errors=True)


# ---------------------------------------------------------------- interface
def run_gui(uninstall_mode: bool, install_dir: Path) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    try:                                       # texto nitido com escala de tela do Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (OSError, AttributeError):
        pass
    root = tk.Tk()
    root.title(f"Desinstalar {APP}" if uninstall_mode else f"Instalar {APP}")
    root.resizable(False, False)
    try:
        root.iconbitmap(str(resource("ladderide.ico")))
    except tk.TclError:
        pass
    if uninstall_mode:
        root.withdraw()
        if not messagebox.askyesno(f"Desinstalar {APP}",
                                   f"Remover a {APP} de {install_dir}?\n\nSeus projetos (.ladproj) e a pasta "
                                   "~/.ladderide (controladores e ambientes do usuario) nao sao apagados."):
            return 1
        try:
            uninstall(install_dir)
        except Exception as exc:  # noqa: BLE001 - mostrado ao usuario
            messagebox.showerror(f"Desinstalar {APP}", str(exc))
            return 2
        messagebox.showinfo(f"Desinstalar {APP}", f"A {APP} foi removida.")
        return 0

    info = payload_info()
    frame = ttk.Frame(root, padding=18)
    frame.grid()
    ttk.Label(frame, text=f"{APP} {info['version']}", font=("Segoe UI", 15, "bold")).grid(columnspan=3, sticky="w")
    ttk.Label(frame, wraplength=470, justify="left", text=(
        "IDE LADDER para o CLP com ESP32: editor, simulador com ambientes, simulador da placa, "
        "blocos de comparacao e matematica, transferencia e monitor online, e gravacao do firmware "
        "na placa (Dispositivo > Gravar firmware na placa).\n\n"
        "A instalacao e so para o seu usuario e nao pede administrador.")).grid(columnspan=3, sticky="w",
                                                                                pady=(6, 12))
    ttk.Label(frame, text="Pasta de instalacao:").grid(row=2, column=0, sticky="w")
    dir_var = tk.StringVar(value=str(install_dir))
    ttk.Entry(frame, textvariable=dir_var, width=52).grid(row=3, column=0, columnspan=2, sticky="we")

    def browse() -> None:
        chosen = filedialog.askdirectory(initialdir=dir_var.get())
        if chosen:
            dir_var.set(str(Path(chosen) / APP) if not chosen.rstrip("\\/").endswith(APP) else chosen)
    ttk.Button(frame, text="Procurar...", command=browse).grid(row=3, column=2, padx=(6, 0))
    desktop_var, assoc_var, launch_var = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    ttk.Checkbutton(frame, text="Atalho na area de trabalho", variable=desktop_var).grid(row=4, columnspan=3,
                                                                                          sticky="w", pady=(10, 0))
    ttk.Checkbutton(frame, text="Abrir arquivos .ladproj com a LadderIDE", variable=assoc_var).grid(
        row=5, columnspan=3, sticky="w")
    ttk.Checkbutton(frame, text="Abrir a LadderIDE ao terminar", variable=launch_var).grid(row=6, columnspan=3,
                                                                                            sticky="w")
    bar = ttk.Progressbar(frame, length=470, maximum=100)
    bar.grid(row=7, columnspan=3, pady=(14, 4), sticky="we")
    status = ttk.Label(frame, text="", width=70)
    status.grid(row=8, columnspan=3, sticky="w")
    buttons = ttk.Frame(frame)
    buttons.grid(row=9, columnspan=3, sticky="e", pady=(10, 0))
    install_btn = ttk.Button(buttons, text="Instalar")
    close_btn = ttk.Button(buttons, text="Cancelar", command=root.destroy)
    install_btn.grid(row=0, column=0, padx=4)
    close_btn.grid(row=0, column=1)

    def report(pct: int, text: str) -> None:
        root.after(0, lambda: (bar.configure(value=pct), status.configure(text=text[-80:])))

    def worker(target: Path) -> None:
        try:
            install(target, shortcuts=True, desktop=desktop_var.get(), registry=True, associate=assoc_var.get(),
                    progress=report)
        except Exception as exc:  # noqa: BLE001 - mostrado ao usuario
            root.after(0, lambda e=exc: (messagebox.showerror(f"Instalar {APP}", str(e)),
                                         install_btn.configure(state="normal"), close_btn.configure(state="normal")))
            return

        def finish() -> None:
            close_btn.configure(text="Fechar", state="normal")
            status.configure(text=f"Instalada em {target}")
            if launch_var.get():
                subprocess.Popen([str(target / EXE)], cwd=str(target), close_fds=True)
                root.after(800, root.destroy)
        root.after(0, finish)

    def start() -> None:
        install_btn.configure(state="disabled")
        close_btn.configure(state="disabled")
        threading.Thread(target=worker, args=(Path(dir_var.get()),), daemon=True).start()
    install_btn.configure(command=start)
    root.mainloop()
    return 0


def main(argv: list[str]) -> int:
    def option(name: str) -> str | None:
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None

    uninstall_mode = "--uninstall" in argv or not resource("payload.zip").exists()
    here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    install_dir = Path(option("--dir") or (here if uninstall_mode and here and (here / MARKER).exists()
                                           else default_dir()))
    if "--silent" in argv:
        try:
            if uninstall_mode:
                uninstall(install_dir)
            else:
                install(install_dir, shortcuts="--no-shortcuts" not in argv, desktop=False,
                        registry="--no-registry" not in argv, associate="--no-registry" not in argv)
                if "--no-launch" not in argv:
                    subprocess.Popen([str(install_dir / EXE)], cwd=str(install_dir), close_fds=True)
        except Exception as exc:  # noqa: BLE001 - codigo de saida para scripts
            log = Path(tempfile.gettempdir()) / "ladderide-setup.log"
            log.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            return 2
        return 0
    return run_gui(uninstall_mode, install_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
