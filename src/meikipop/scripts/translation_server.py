"""Explicit, verified Hy-MT2 installation and an owned loopback llama.cpp server.

Assets: github.com/ggml-org/llama.cpp/releases/tag/b11146
Models: huggingface.co/tencent/Hy-MT2-7B-GGUF and Hy-MT2-1.8B-GGUF
The pinned release supports --sleep-idle-seconds; inference never downloads.
"""
import argparse
import atexit
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener, urlopen
import zipfile

DEFAULT_ENDPOINT = "http://127.0.0.1:8766/v1"
RELEASE = "b11146"
_RELEASE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/"
# SHA256 from GitHub's release-asset digest and Hugging Face's LFS oid.
RUNTIMES = {
    "win-x64": (
        ("llama-b11146-bin-win-cuda-13.4-x64.zip", "b1866c0ce76bc7bfb0c24b33e9a37e9669f1be18539b12c74ce361f81c41f047"),
        ("cudart-llama-bin-win-cuda-13.4-x64.zip", "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668")),
    "mac-arm64": (("llama-b11146-bin-macos-arm64.tar.gz", "1ad3f9eff80edb9dbef4259ad564d1720612ef7eea48fa4afed0e54f5f3d5711"),),
    "mac-x64": (("llama-b11146-bin-macos-x64.tar.gz", "305f0e3a17d2c01eb205cd0a62128357f1ec3b55329cb084d94e5ec0115d7a3b"),),
}
MODELS = {
    "quality": dict(repo="Hy-MT2-7B-GGUF", revision="ab8472660ac61fac25f1af43fac2599d52a8a775",
                    file="HY-MT2-7B-Q8_0.gguf", size=7981928896,
                    sha256="58b3ad55dd6f6fa08c695cddc34fb5f8f708a844f78ae10508071914b0ed67c0"),
    "lightweight": dict(repo="Hy-MT2-1.8B-GGUF", revision="a0c709d9fac510f2c807aa3af52872340dc37a4a",
                        file="Hy-MT2-1.8B-Q8_0.gguf", size=1908528192,
                        sha256="5c3fe0b1408a5ceb0143184ef247b11b579c525f4b02b060e6c851bb76fef1a4"),
}
_lock = threading.RLock()
_install_lock = threading.Lock()
_stop_requested = threading.Event()
_closed = threading.Event()
_process = None
_running_model = None


def translation_path(directory=None):
    if directory is None:
        from meikipop.utils.paths import paths
        directory = Path(paths.data_dir) / "translation"
    return Path(directory).resolve()


def _platform_key():
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in ("amd64", "x86_64"):
        return "win-x64"
    if sys.platform == "darwin":
        if machine in ("arm64", "aarch64"):
            return "mac-arm64"
        if machine in ("x86_64", "amd64"):
            return "mac-x64"
    raise RuntimeError("Automatic translation setup supports Windows x64 and macOS. Use a custom local server on this platform.")


def _cancelled(cancelled):
    if cancelled and (cancelled.is_set() if hasattr(cancelled, "is_set") else cancelled()):
        raise InterruptedError("Translation installation cancelled.")


def _sha256(path, cancelled=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            _cancelled(cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def _download(url, destination, digest, progress=None, cancelled=None, local=None, size=None):
    """Publish only a verified complete file; cancellation leaves no partial model."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _cancelled(cancelled)
    if destination.is_file() and _sha256(destination, cancelled) == digest:
        return destination
    fd, name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as output:
            request = Request(url, headers={"User-Agent": "Meikipop-setup/2.0.5"})
            with Path(local).open("rb") if local and Path(local).is_file() else urlopen(request, timeout=30) as source:
                digest_state, received, last_report = hashlib.sha256(), 0, -1
                while chunk := source.read(4 * 1024 * 1024):
                    _cancelled(cancelled)
                    digest_state.update(chunk)
                    output.write(chunk)
                    received += len(chunk)
                    report = int(received * 100 / size) if size else received // (16 * 1024 * 1024)
                    if progress and report != last_report:
                        progress(f"{destination.name}: {report}%" if size else f"{destination.name}: {received // (1024 * 1024)} MB")
                        last_report = report
            if digest_state.hexdigest() != digest or size is not None and received != size:
                raise ValueError(f"Download verification failed: {destination.name}")
        _cancelled(cancelled)
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def _archive_target(root, name):
    relative = PurePosixPath(name)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe path in translation runtime archive.")
    target = root.joinpath(*relative.parts).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Unsafe path in translation runtime archive.")
    return target


def _extract_archive(archive_path, destination, cancelled=None):
    """Support internal macOS dylib links, reject traversal/devices/external links."""
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                _cancelled(cancelled)
                target = _archive_target(root, member.filename)
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ValueError("Unexpected link in translation ZIP.")
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
    else:
        with tarfile.open(archive_path, "r:gz") as archive:
            links = []
            for member in archive:
                _cancelled(cancelled)
                target = _archive_target(root, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    target.chmod(member.mode & 0o777)
                elif member.issym() or member.islnk():
                    links.append((target, member))
                else:
                    raise ValueError("Unexpected member in translation runtime archive.")
            while links:
                pending = []
                for target, member in links:
                    link = PurePosixPath(member.linkname)
                    source = (target.parent if member.issym() else root).joinpath(*link.parts).resolve()
                    if link.is_absolute() or not source.is_relative_to(root) or "\\" in member.linkname or ":" in member.linkname:
                        raise ValueError("Unsafe link in translation runtime archive.")
                    if not source.is_file():
                        pending.append((target, member))
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if member.issym():
                        target.symlink_to(os.path.relpath(source, target.parent))
                    else:
                        os.link(source, target)
                if len(pending) == len(links):
                    raise ValueError("Broken link in translation runtime archive.")
                links = pending


def installation(directory=None):
    try:
        result = json.loads((translation_path(directory) / "installation.json").read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_installation(root, registry):
    fd, temporary = tempfile.mkstemp(prefix=".manifest-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(registry, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, root / "installation.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def install_model(profile="quality", directory=None, progress=None, cancelled=None, downloads=None):
    """Explicit setup only. Optional bootstrap files are copied and hash-checked."""
    if profile not in MODELS:
        raise ValueError("Choose quality or lightweight translation.")
    root, platform_key = translation_path(directory), _platform_key()
    root.mkdir(parents=True, exist_ok=True)
    with _install_lock:
        registry = installation(root)
        runtime_path = root / f"runtime-{RELEASE}-{platform_key}"
        executable_name = "llama-server.exe" if platform_key.startswith("win-") else "llama-server"
        if not runtime_path.is_dir():
            temporary = Path(tempfile.mkdtemp(prefix=".runtime-", dir=root)).resolve()
            try:
                for name, digest in RUNTIMES[platform_key]:
                    archive = _download(_RELEASE_URL + name, root / "downloads" / name, digest,
                                        progress, cancelled, Path(downloads) / name if downloads else None)
                    _extract_archive(archive, temporary, cancelled)
                executables = list(temporary.rglob(executable_name))
                if len(executables) != 1:
                    raise ValueError("Translation runtime has no unique server executable.")
                if platform_key.startswith("win-"):
                    for dll in temporary.rglob("*.dll"):
                        target = executables[0].parent / dll.name
                        if dll != target and not target.exists():
                            shutil.copy2(dll, target)
                _cancelled(cancelled)
                temporary.rename(runtime_path)
            finally:
                if temporary.exists() and temporary.parent == root:
                    shutil.rmtree(temporary)
        executables = list(runtime_path.rglob(executable_name))
        if len(executables) != 1:
            raise RuntimeError("Translation runtime is incomplete. Reinstall its runtime folder.")
        model = MODELS[profile]
        url = f'https://huggingface.co/tencent/{model["repo"]}/resolve/{model["revision"]}/{model["file"]}'
        model_path = _download(url, root / "models" / model["file"], model["sha256"], progress,
                               cancelled, Path(downloads) / model["file"] if downloads else None, model["size"])
        registry.update(release=RELEASE, platform=platform_key,
                        executable=executables[0].relative_to(root).as_posix())
        if not isinstance(registry.get("models"), dict):
            registry["models"] = {}
        registry["models"][profile] = dict(path=model_path.relative_to(root).as_posix(),
                                          sha256=model["sha256"], size=model["size"], url=url)
        _write_installation(root, registry)
        if progress:
            progress("Translation installed")
        return registry


def _local_json(path, timeout=1):
    # Never proxy local requests or follow a redirect to another machine.
    from urllib.request import HTTPRedirectHandler

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise RuntimeError("Unexpected redirect from local translation server.")

    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open("http://127.0.0.1:8766" + path, timeout=timeout) as response:
        return json.loads(response.read(1024 * 1024))


def _ready():
    try:
        return _local_json("/health").get("status") == "ok"
    except (OSError, ValueError, URLError):
        return False


def _installed_paths(profile, directory):
    root, registry = translation_path(directory), installation(directory)
    try:
        models = registry.get("models", {})
        model = models.get(profile, {}) if isinstance(models, dict) else {}
        # Older Windows installs used native separators. Normalize only local
        # manifest fields; archive member names remain strictly validated.
        executable = _archive_target(root, registry["executable"].replace("\\", "/"))
        model_path = _archive_target(root, model["path"].replace("\\", "/"))
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Install the selected translation model in Settings first.") from error
    if not executable.is_file() or not model_path.is_file() or model_path.stat().st_size != model.get("size"):
        raise RuntimeError("Install the selected translation model in Settings first.")
    return executable, model_path


def server_command(executable, model):
    return [str(executable), "--model", str(model), "--alias", "hy-mt2", "--host", "127.0.0.1",
            "--port", "8766", "-ngl", "99", "--ctx-size", "8192", "--parallel", "1",
            "--sleep-idle-seconds", "60", "--cache-ram", "0", "--no-context-shift", "--jinja",
            "--no-webui", "--no-agent", "--log-disable"]


def _terminate_owned():
    global _process, _running_model
    process, _process, _running_model = _process, None, None
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def shutdown_server(permanent=False):
    """Stop only the process created by this application, never a custom server."""
    if permanent:
        _closed.set()
    _stop_requested.set()
    with _lock:
        _terminate_owned()


def ensure_server(endpoint=DEFAULT_ENDPOINT, profile="quality", timeout=120, directory=None):
    """Start an installed model. This function has no download or setup path."""
    global _process, _running_model
    parsed = urlsplit(endpoint.rstrip("/"))
    if (parsed.scheme, parsed.hostname, parsed.port, parsed.path) != ("http", "127.0.0.1", 8766, "/v1") \
            or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Managed translation uses http://127.0.0.1:8766/v1 only.")
    if profile not in MODELS:
        raise ValueError("Choose quality or lightweight translation.")
    executable, model = _installed_paths(profile, directory)
    with _lock:
        if _closed.is_set():
            raise RuntimeError("Translation server is shutting down.")
        _stop_requested.clear()
        if _process is not None and (_process.poll() is not None or _running_model != model):
            _terminate_owned()
        if _ready():
            if _process is None:
                props = _local_json("/props")
                if Path(props.get("model_path", "")).resolve() != model:
                    raise RuntimeError("Port 8766 is used by another model. Stop that server or choose Custom in Settings.")
            return
        if _process is None:
            options = dict(cwd=str(executable.parent), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           env={key: value for key, value in os.environ.items() if not key.startswith("LLAMA_")})
            if sys.platform == "win32":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            _process = subprocess.Popen(server_command(executable, model), **options)
            _running_model = model
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if _stop_requested.wait(0.1):
                    raise RuntimeError("Translation startup cancelled.")
                if _process.poll() is not None:
                    raise RuntimeError("Local translation could not start. Check GPU drivers and available memory, or select Lightweight.")
                if _ready():
                    return
            raise RuntimeError("Local translation took too long to start. Try Lightweight in Settings.")
        except BaseException:
            _terminate_owned()
            raise


atexit.register(shutdown_server, permanent=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Install or run local Hy-MT2 translation")
    parser.add_argument("--install", choices=tuple(MODELS), nargs="?", const="quality")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--profile", choices=tuple(MODELS), default="quality")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--downloads", type=Path, help="Reuse already-downloaded official files")
    args = parser.parse_args(argv)
    if not args.install and not args.serve:
        parser.error("Choose --install or --serve")
    if args.install:
        install_model(args.install, args.directory, progress=print, downloads=args.downloads)
    if args.serve:
        try:
            ensure_server(profile=args.install or args.profile, directory=args.directory)
            while _process is not None and _process.poll() is None:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            shutdown_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
