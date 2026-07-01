"""Genera version_info.txt per PyInstaller dalle variabili d'ambiente impostate
da Creatore_exe.bat (GIT_VERSION, LIBVER, DEBUG_SUFFIX, VERSION_INFO_OUT).

filevers/prodvers vogliono una tupla di 4 interi -> estratti da GIT_VERSION.
La stringa git completa va nei campi testuali (Proprieta' -> Dettagli dell'exe).
I flag VS_FF_DEBUG | VS_FF_PRERELEASE si attivano solo per le build debug.
"""
import os
import re

# ── Personalizza questi due ──────────────────────────────────────────────────
COMPANY   = "Elite srl"
COPYRIGHT = "Elite srl (c)"
# ─────────────────────────────────────────────────────────────────────────────

OUT      = os.environ.get("VERSION_INFO_OUT", "version_info.txt")
gitver   = os.environ.get("GIT_VERSION", "unknown").strip()
libver   = os.environ.get("LIBVER", "unknown").strip()
is_debug = bool(os.environ.get("DEBUG_SUFFIX", "").strip())

# major.minor.patch (+ eventuale "-N-gHASH" -> N come 4o numero)
m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(?:-(\d+)-g[0-9a-fA-F]+)?", gitver)
if m:
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    build = int(m.group(4)) if m.group(4) else 0
else:
    major = minor = patch = build = 0

filevers = (major, minor, patch, build)
flags    = 0x3 if is_debug else 0x0  # VS_FF_DEBUG | VS_FF_PRERELEASE

if is_debug:
    description  = "Total Commander - BUILD DI SVILUPPO (NON RILASCIATA)"
    product_name = "Total Commander [DEBUG]"
else:
    description  = "Total Commander"
    product_name = "Total Commander"

comments = f"git: {gitver} | shared_lib: {libver}"

template = f"""# Generato da make_version_info.py - non modificare a mano.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={filevers},
    mask=0x3f,
    flags={hex(flags)},
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', {COMPANY!r}),
        StringStruct('FileDescription', {description!r}),
        StringStruct('FileVersion', {gitver!r}),
        StringStruct('InternalName', 'TotalCommander'),
        StringStruct('OriginalFilename', 'TotalCommander.exe'),
        StringStruct('ProductName', {product_name!r}),
        StringStruct('ProductVersion', {gitver!r}),
        StringStruct('Comments', {comments!r}),
        StringStruct('LegalCopyright', {COPYRIGHT!r})
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

with open(OUT, "w", encoding="utf-8") as f:
    f.write(template)

print(f"[INFO] version_info scritto: {OUT}  filevers={filevers}  debug={is_debug}")