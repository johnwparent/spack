# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Utilities for interacting with files,
like those in spack.llnl.util.filesystem, but which require logic from spack.util
"""

import glob
import os
import re

from spack.llnl.util.filesystem import edit_in_place_through_temporary_file
from spack.util.executable import Executable

import llnl.util.tty as tty
from llnl.util.lang import memoized

from spack.util.environment import EnvironmentModifications
from spack.util.executable import Executable, ProcessError, which


def fix_darwin_install_name(path: str) -> None:
    """Fix install name of dynamic libraries on Darwin to have full path.

    There are two parts of this task:

    1. Use ``install_name -id  ...`` to change install name of a single lib
    2. Use ``install_name -change  ...`` to change the cross linking between libs.
       The function assumes that all libraries are in one folder and currently won't follow
       subfolders.

    Parameters:
        path: directory in which ``.dylib`` files are located
    """
    libs = glob.glob(os.path.join(path, "*.dylib"))
    install_name_tool = Executable("install_name_tool")
    otool = Executable("otool")
    for lib in libs:
        args = ["-id", lib]
        long_deps = otool("-L", lib, output=str).split("\n")
        deps = [dep.partition(" ")[0][1::] for dep in long_deps[2:-1]]
        # fix all dependencies:
        for dep in deps:
            for loc in libs:
                # We really want to check for either
                #     dep == os.path.basename(loc)   or
                #     dep == join_path(builddir, os.path.basename(loc)),
                # but we don't know builddir (nor how symbolic links look
                # in builddir). We thus only compare the basenames.
                if os.path.basename(dep) == os.path.basename(loc):
                    args.extend(("-change", dep, loc))
                    break

        with edit_in_place_through_temporary_file(lib) as tmp:
            install_name_tool(*args, tmp)


@memoized
def relocate(package=None) -> Executable:
    if package:
        return Executable(str(package.spec["compiler-wrapper"].package.bin_dir() / "relocate.exe"))
    import spack.bootstrap

    with spack.bootstrap.ensure_bootstrap_configuration():
        return spack.bootstrap.ensure_msvc_relocate_or_raise()  # type: ignore


@memoized
def dumpbin(pkg) -> Executable:
    # TODO: actually find path to this
    db_bin_dir = os.path.dirname(pkg["msvc"].cc)
    dumpbin = which("dumpbin", path=db_bin_dir)
    if not dumpbin:
        raise RuntimeError("dumpbin required, but not found")
    return dumpbin


def relocate_win_rpath(package):
    # populate environment with required paths to perform relocation
    # relocate relies on finding the dll an import library
    # links to and re-writing the path to the dll
    # in the import lib
    ev = EnvironmentModifications()
    dirs_to_relocate = [package.prefix]
    for search_dir in dirs_to_relocate:
        for entry in os.scandir(search_dir):
            if not (entry.is_symlink() or entry.is_junction()) and entry.is_dir():
                dirs_to_relocate.append(entry.path)
    ev.set_path("SPACK_RELOCATE_PATH", dirs_to_relocate)
    lib_map = {}
    for lib in glob.glob(os.path.join(package.spec.prefix, "**\\*.lib"), recursive=True):
        if verify_import_lib(lib, package=package):
            # we have an import lib, determine symbols
            dll_name = get_importlib_target(lib, package=package)
            if dll_name:
                dll_name = os.path.basename(dll_name)
            lib_map[dll_name] = lib
    for dll in glob.glob(os.path.join(package.spec.prefix, "**\\*.dll"), recursive=True):
        name = os.path.basename(dll)
        if name in lib_map and is_imp_lib_for_dll(package, lib_map[name], dll):
            relocate(package)(
                "--pe",
                dll,
                "--coff",
                lib_map[name],
                "--export",
                "--full",
                extra_env=ev,
                fail_on_error=True,
            )


def get_importlib_target(lib, package=None):
    reloc = relocate(package)
    info = reloc("--coff", lib, "--report", output=str)
    regex = re.compile("DLL: (.*)")
    match = regex.search(info)
    if match:
        dll_name = match.group(1).strip("\r")
        return dll_name
    raise RuntimeError(f"Ill formed coff file: {lib}, unable to determine corresponding DLL")


def verify_import_lib(lib: str, package=None) -> bool:
    relocate_exe = relocate(package)
    try:
        relocate_exe("--coff", lib, "--verify", ignore_errors=[1])
    except ProcessError:
        tty.debug(f"Cannot verify library {lib} as COFF.")
    if relocate_exe.returncode == 0:
        return True
    return False


def collect_import_exports(pkg, lib):
    db = dumpbin(pkg)
    raw_exports = db("/NOLOGO", "/EXPORTS", lib, output=str).split("\n")
    # first 8 lines are boilerplate and not useful
    raw_exports = raw_exports[8:]
    exports = []
    for export_line in raw_exports:
        if export_line == "  Summary\r":
            # exports end just before this section, terminate
            break
        sanitized_line = export_line.strip("\r").strip(" ")
        if not sanitized_line:
            # there are a couple blank lines, just skip them
            continue
        exports.append(sanitized_line)
    return exports


def collect_dll_api(pkg, dll):
    regex = re.compile(".*? ([a-zA-Z_][a-zA-Z0-9_]*)(?: = ([a-zA-Z_][a-zA-Z0-9_]*))?\r$")
    db = dumpbin(pkg)
    raw_exports = db("/NOLOGO", "/EXPORTS", dll, output=str).split("\n")
    raw_exports = raw_exports[16:]
    exports = []
    for export_line in raw_exports:
        if export_line == "  Summary\r":
            # exports end just before this section, terminate
            break
        match = regex.search(export_line)
        if match:
            symbol_export = match.group(1)
            if match.group(2):
                symbol_export += f" = {match.group(2)}"
            exports.append(symbol_export)
    return exports


def is_imp_lib_for_dll(pkg, imp_lib, dll):
    lib_exports = collect_import_exports(pkg, imp_lib)
    dll_exports = collect_dll_api(pkg, dll)
    assert lib_exports, f"Lib exports in {imp_lib} should not be empty"
    assert dll_exports, f"Dll exports in {dll} should not be empty"
    # values should be ordered already, no need for sorting
    for lib_line, dll_line in zip(lib_exports, dll_exports):
        if lib_line not in dll_line:
            return False
    return True
