# Copyright 2013-2021 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import os
import re
from itertools import product

from spack.util.executable import which

# Supported archive extensions.
PRE_EXTS   = ["tar", "TAR"]
EXTS       = ["gz", "bz2", "xz", "Z"]
NOTAR_EXTS = ["zip", "tgz", "tbz", "tbz2", "txz"]

# Add PRE_EXTS and EXTS last so that .tar.gz is matched *before* .tar or .gz
ALLOWED_ARCHIVE_TYPES = [".".join(ext) for ext in product(
    PRE_EXTS, EXTS)] + PRE_EXTS + EXTS + NOTAR_EXTS


def allowed_archive(path):
    return any(path.endswith(t) for t in ALLOWED_ARCHIVE_TYPES)


def _bunzip2(archive_file):
    """ Use Python's bz2 module to decompress bz2 compressed archives

    Args:
        archive_file (str): absolute path to the bz2 archive to be decompressed
    """
    try:
        import bz2
        decompressed_file = os.path.basename(archive_file.strip(".bz2"))
        archive_out = os.path.join(os.getcwd(),decompressed_file)
        with bz2.open(archive_file,mode='rb') as bzf:
            with open(archive_out,'wb') as ar:
                ar.write(bzf.read())
    except ImportError:
        bunzip2 = which('bunzip2', required=True)
        bunzip2.add_default_arg('-q')
        return bunzip2


def _gunzip(archive_file):
    """Like gunzip, but extracts in the current working directory
    instead of in-place.

    Args:
        archive_file (str): absolute path of the file to be decompressed
    """
    import gzip
    decompressed_file = os.path.basename(archive_file.strip('.gz'))
    working_dir = os.getcwd()
    destination_abspath = os.path.join(working_dir, decompressed_file)
    with gzip.open(archive_file, "rb") as f_in:
        with open(destination_abspath, "wb") as f_out:
            f_out.write(f_in.read())


def decompressor_for(path, extension=None):
    """Get the appropriate decompressor for a path."""
    if ((extension and re.match(r'\.?zip$', extension)) or
            path.endswith('.zip')):
        unzip = which('unzip', required=True)
        unzip.add_default_arg('-q')
        return unzip
    if extension and re.match(r'gz', extension):
        return _gunzip
    if extension and re.match(r'bz2', extension):
        return _bunzip2
    tar = which('tar', required=True)
    tar.add_default_arg('-oxf')
    return tar


def strip_extension(path):
    """Get the part of a path that does not include its compressed
       type extension."""
    for type in ALLOWED_ARCHIVE_TYPES:
        suffix = r'\.%s$' % type
        if re.search(suffix, path):
            return re.sub(suffix, "", path)
    return path


def extension(path):
    """Get the archive extension for a path."""
    if path is None:
        raise ValueError("Can't call extension() on None")

    # Strip sourceforge suffix.
    if re.search(r'((?:sourceforge.net|sf.net)/.*)/download$', path):
        path = os.path.dirname(path)

    for t in ALLOWED_ARCHIVE_TYPES:
        suffix = r'\.%s$' % t
        if re.search(suffix, path):
            return t
    return None
