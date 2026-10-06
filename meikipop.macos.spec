# -*- mode: python ; coding: utf-8 -*-

import re
from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_all, copy_metadata


def _get_build_version() -> str:
    config_path = Path(CONF['specpath']) / 'src' / 'meikipop' / 'config' / 'config.py'
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', config_path.read_text(encoding='utf-8'), re.M)
    if not match:
        return '0.0.0'

    version = match.group(1)
    if version.startswith('v.'):
        return version[2:]
    if version.startswith('v'):
        return version[1:]
    return version


BUILD_VERSION = _get_build_version()
model_data, model_binaries, model_imports = collect_all('stanza')
model_data += copy_metadata('stanza', recursive=True)

a = Analysis(
    ['src/meikipop/scripts/quick_lookup.py'],
    pathex=['src'],
    binaries=model_binaries,
    datas=model_data + [
        ('src/meikipop/resources/icon.ico', 'meikipop/resources'),
        ('src/meikipop/resources/icon.inactive.ico', 'meikipop/resources'),
        ('src/meikipop/scripts/deconjugator.json', 'meikipop/scripts'),
        ('src/meikipop/resources/turkish/*.json', 'meikipop/resources/turkish'),
    ],
    hiddenimports=model_imports + ['PyQt6.QtTextToSpeech', 'Vision', 'Foundation', 'Quartz', 'AppKit', 'pynput.keyboard._darwin', 'pynput.mouse._darwin'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['packaging/runtime.py'],
    excludes=['paddleocr', 'paddlex', 'paddle', 'meikiocr', 'onnxruntime', 'tkinter', 'IPython', 'pytest'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='meikipop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='meikipop',
)

app = BUNDLE(
    coll,
    name='meikipop.app',
    icon='src/meikipop/resources/icon.ico',
    bundle_identifier='io.github.rtr46.meikipop',
    version=BUILD_VERSION,
    info_plist={
        'CFBundleVersion': BUILD_VERSION,
        'CFBundleDisplayName': 'Meikipop',
        'NSHighResolutionCapable': True,
        'NSScreenCaptureUsageDescription': 'Recognize text under the pointer for dictionary lookup.',
        'NSAppleEventsUsageDescription': 'Look up text selected in another app when you use its shortcut.',
    },
)
