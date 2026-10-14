# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import io
import os
import pathlib
import shutil
import tarfile
from itertools import product

import pytest

import spack.util.filesystem
import spack.util.url
from spack.error import SpackError
from spack.paths import spack_root
from spack.util import compression
from spack.util.executable import CommandNotFoundError
from spack.util.filesystem import working_dir

datadir = os.path.join(spack_root, "lib", "spack", "spack", "test", "data", "compression")

ext_archive = {
    ext: f"Foo.{ext}" for ext in spack.util.url.ALLOWED_ARCHIVE_TYPES if "TAR" not in ext
}
# Spack does not use Python native handling for tarballs or zip
# Don't test tarballs or zip in native test
native_archive_list = [
    key for key in ext_archive.keys() if "tar" not in key and "zip" not in key and "whl" not in key
]


@pytest.fixture
def compr_support_check(monkeypatch):
    monkeypatch.setattr(compression, "LZMA_SUPPORTED", False)
    monkeypatch.setattr(compression, "GZIP_SUPPORTED", False)
    monkeypatch.setattr(compression, "BZ2_SUPPORTED", False)


@pytest.fixture
def archive_file_and_extension(tmp_path_factory: pytest.TempPathFactory, request):
    """Copy example archive to temp directory into an extension-less file for test"""
    archive_file_stub = os.path.join(datadir, "Foo")
    extension, add_extension = request.param
    tmpdir = tmp_path_factory.mktemp("compression")
    tmp_archive_file = os.path.join(
        str(tmpdir), "Foo" + (("." + extension) if add_extension else "")
    )
    shutil.copy(archive_file_stub + "." + extension, tmp_archive_file)
    return (tmp_archive_file, extension)


@pytest.mark.parametrize(
    "archive_file_and_extension", product(native_archive_list, [True, False]), indirect=True
)
def test_native_unpacking(tmp_path_factory: pytest.TempPathFactory, archive_file_and_extension):
    archive_file, extension = archive_file_and_extension
    util = compression.decompressor_for(archive_file, extension)
    tmpdir = tmp_path_factory.mktemp("comp_test")
    with working_dir(str(tmpdir)):
        assert not os.listdir(os.getcwd())
        util(archive_file)
        files = os.listdir(os.getcwd())
        assert len(files) == 1
        with open(files[0], "r", encoding="utf-8") as f:
            contents = f.read()
        assert "TEST" in contents


@pytest.mark.not_on_windows("Only Python unpacking available on Windows")
@pytest.mark.parametrize(
    "archive_file_and_extension",
    [(ext, True) for ext in ext_archive.keys() if "whl" not in ext],
    indirect=True,
)
def test_system_unpacking(
    tmp_path_factory: pytest.TempPathFactory, archive_file_and_extension, compr_support_check
):
    # actually run test
    archive_file, _ = archive_file_and_extension
    util = compression.decompressor_for(archive_file)
    tmpdir = tmp_path_factory.mktemp("system_comp_test")
    with working_dir(str(tmpdir)):
        assert not os.listdir(os.getcwd())
        util(archive_file)
        files = os.listdir(os.getcwd())
        assert len(files) == 1
        with open(files[0], "r", encoding="utf-8") as f:
            contents = f.read()
        assert "TEST" in contents


def test_unallowed_extension():
    # use a cxx file as python files included for the test
    # are picked up by the linter and break style checks
    bad_ext_archive = "Foo.cxx"
    with pytest.raises(CommandNotFoundError):
        compression.decompressor_for(bad_ext_archive)


@pytest.mark.parametrize("ext", ["gz", "bz2", "xz"])
def test_file_type_check_does_not_advance_stream(tmp_path: pathlib.Path, ext):
    # Create a tarball compressed with the given format
    path = str(tmp_path / "compressed_tarball")

    try:
        if ext == "gz":
            tar = tarfile.open(path, "w:gz")
        elif ext == "bz2":
            tar = tarfile.open(path, "w:bz2")
        elif ext == "xz":
            tar = tarfile.open(path, "w:xz")
        else:
            assert False, f"Unsupported extension: {ext}"
    except tarfile.CompressionError:
        pytest.skip(f"Cannot create tar.{ext} files")

    with tar:
        tar.addfile(tarfile.TarInfo("test.txt"), fileobj=io.BytesIO(b"test"))

    # Classify the file from its magic bytes, and check that the stream is not advanced
    with open(path, "rb") as f:
        computed_ext = compression.extension_from_magic_numbers_by_stream(f, decompress=False)
        assert computed_ext == ext
        assert f.tell() == 0
        computed_ext = compression.extension_from_magic_numbers_by_stream(f, decompress=True)
        assert computed_ext == f"tar.{ext}"
        assert f.tell() == 0


@pytest.fixture
def symlinks_available():
    if not spack.util.filesystem._windows_can_symlink():
        pytest.skip("Requires permission to create symlinks")


@pytest.fixture
def symlinks_unavailable(monkeypatch):
    monkeypatch.setattr(spack.util.filesystem, "_windows_can_symlink", lambda: False)


def _untar(archive: str, tmp_path: pathlib.Path, extension: str = "tar") -> pathlib.Path:
    """Extracts the archive into a new directory, and returns the directory"""
    dest = tmp_path / "extract"
    dest.mkdir()
    with working_dir(str(dest)):
        compression.decompressor_for(archive, extension)(archive)
    return dest


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.parametrize("extension", ["tar", "tar.gz"])
def test_windows_untar_does_not_use_system_tar(tmp_path, tarball, monkeypatch, extension):
    """Tarballs, compressed or not, are extracted with Python rather than system tar."""

    def _fail(*args, **kwargs):
        raise AssertionError("system tar should not be used")

    monkeypatch.setattr(compression, "_system_untar", _fail)
    archive = tarball(f"Foo.{extension}").file("foo/bar.txt").create()
    dest = _untar(archive, tmp_path, extension)
    assert (dest / "foo" / "bar.txt").exists()


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.usefixtures("symlinks_available")
def test_windows_untar_symlink_target_with_forward_slashes(tmp_path, tarball):
    """Symlink targets are stored with forward slashes, which Windows does not resolve in a
    relative symlink, so they are converted. System tar converts them too."""
    archive = tarball("Foo.tar").file("foo/data/bar.txt").symlink("foo/link", "data/bar.txt")
    dest = _untar(archive.create(), tmp_path)
    assert os.readlink(dest / "foo" / "link") == os.path.join("data", "bar.txt")


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.usefixtures("symlinks_available")
def test_windows_untar_symlink_listed_before_target(tmp_path, tarball):
    """A symlink listed before its target is created once its target is extracted. System tar
    fails to create it with "Invalid argument", as it requires the target to exist."""
    archive = tarball("Foo.tar").symlink("foo/link", "bar.txt").file("foo/bar.txt", "bar")
    dest = _untar(archive.create(), tmp_path)
    assert (dest / "foo" / "link").read_text() == "bar"


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.usefixtures("symlinks_available")
def test_windows_untar_directory_symlink_listed_before_target(tmp_path, tarball):
    """A symlink to a directory listed before the directory is created as a directory symlink,
    rather than as a file symlink, which cannot be traversed. System tar fails to create it with
    "Invalid argument", as it requires the target to exist."""
    archive = tarball("Foo.tar").symlink("foo/link", "data").file("foo/data/bar.txt")
    dest = _untar(archive.create(), tmp_path)
    assert (dest / "foo" / "link" / "bar.txt").exists()


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.usefixtures("symlinks_available")
def test_windows_untar_dangling_symlink(tmp_path, tarball):
    """A symlink to a missing target is created, as tar does on other platforms. System tar
    fails to create it with "Invalid argument"."""
    archive = tarball("Foo.tar").symlink("foo/link", "missing.txt").create()
    dest = _untar(archive, tmp_path)
    assert os.path.islink(dest / "foo" / "link")


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.usefixtures("symlinks_unavailable")
def test_windows_untar_without_symlinks_file_symlink_is_hard_link(tmp_path, tarball):
    """Without permission to create symlinks, a symlink to a file becomes a hard link. System
    tar fails the extraction."""
    archive = tarball("Foo.tar").file("foo/bar.txt").symlink("foo/link", "bar.txt").create()
    foo = _untar(archive, tmp_path) / "foo"
    assert os.path.samefile(foo / "link", foo / "bar.txt")


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.usefixtures("symlinks_unavailable")
def test_windows_untar_without_symlinks_symlink_to_symlink(tmp_path, tarball):
    """Without permission to create symlinks, a symlink to another symlink listed after it is
    replaced once the other symlink is. System tar fails the extraction."""
    archive = (
        tarball("Foo.tar")
        .symlink("foo/second", "first")
        .symlink("foo/first", "bar.txt")
        .file("foo/bar.txt")
    )
    foo = _untar(archive.create(), tmp_path) / "foo"
    assert os.path.samefile(foo / "second", foo / "bar.txt")


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.usefixtures("symlinks_unavailable")
def test_windows_untar_without_symlinks_directory_symlink_is_copied(tmp_path, tarball):
    """Without permission to create symlinks, a symlink to a directory becomes a copy, made once
    the symlinks inside the directory are replaced, so the copy includes them. System tar fails
    the extraction."""
    archive = (
        tarball("Foo.tar")
        .symlink("foo/link", "data")
        .symlink("foo/data/inner_link", "bar.txt")
        .file("foo/data/bar.txt")
    )
    foo = _untar(archive.create(), tmp_path) / "foo"
    assert (foo / "link" / "inner_link").exists()


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.usefixtures("symlinks_unavailable")
@pytest.mark.parametrize("target", ["missing.txt", "."], ids=["dangling", "own-directory"])
def test_windows_untar_without_symlinks_skips_uncopyable_symlinks(tmp_path, tarball, target):
    """Without permission to create symlinks, a symlink to a missing target, or to the directory
    containing it, cannot be replaced by a hard link or copy, so it is skipped. System tar fails
    the extraction."""
    archive = tarball("Foo.tar").directory("foo/").symlink("foo/link", target).create()
    dest = _untar(archive, tmp_path)
    assert not os.path.lexists(dest / "foo" / "link")


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.parametrize("target", ["../../outside.txt", "/etc/passwd"])
def test_windows_untar_skips_symlinks_outside_destination(tmp_path, tarball, target):
    """A symlink pointing outside of the destination is skipped, rather than failing the
    extraction, as some source tarballs contain such links, e.g. to automake's files under
    /usr/share. System tar fails to create it, as the target does not exist."""
    archive = tarball("Foo.tar").directory("foo/").symlink("foo/link", target).create()
    dest = _untar(archive, tmp_path)
    assert not os.path.lexists(dest / "foo" / "link")


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
@pytest.mark.parametrize(
    "add_member",
    [
        lambda t: t.file("../evil.txt"),
        lambda t: t.file("foo/../../evil.txt"),
        lambda t: t.hardlink("foo/hard_link", "../outside.txt"),
    ],
    ids=["parent", "nested-parent", "hard-link"],
)
def test_windows_untar_rejects_members_outside_destination(tmp_path, tarball, add_member):
    """A member written outside of the destination, or hard linking to a file outside of it,
    fails the extraction before anything is extracted. System tar skips such members with
    "Path contains '..'", but extracts the other members."""
    archive = add_member(tarball("Foo.tar").file("foo/bar.txt")).create()
    dest = tmp_path / "extract"
    dest.mkdir()
    with working_dir(str(dest)):
        with pytest.raises(SpackError, match="Refusing to extract"):
            compression.decompressor_for(archive, "tar")(archive)
    assert not os.listdir(dest)


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
def test_windows_untar_dot_prefixed_members(tmp_path, tarball):
    """Members prefixed with "./", as in tarballs created with ``tar -C dir .``, are extracted,
    though extraction uses extended-length paths, which Windows does not normalize."""
    archive = tarball("Foo.tar").directory("./").file("./foo/bar.txt").create()
    dest = _untar(archive, tmp_path)
    assert (dest / "foo" / "bar.txt").exists()


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
def test_windows_untar_hard_link(tmp_path, tarball):
    """A hard link's target, stored with forward slashes, is converted so the link is created
    as a hard link rather than as a copy. System tar creates the hard link."""
    archive = tarball("Foo.tar").file("foo/data/bar.txt").hardlink("foo/link", "foo/data/bar.txt")
    foo = _untar(archive.create(), tmp_path) / "foo"
    assert os.path.samefile(foo / "link", foo / "data" / "bar.txt")


@pytest.mark.only_windows("Python tarball extraction is only used on Windows")
def test_windows_untar_long_path(tmp_path, tarball):
    """Members whose path exceeds MAX_PATH are extracted, even when long paths are not enabled
    on the system. System tar uses extended-length paths too."""
    name = "/".join(["foo"] + ["d" * 50] * 6 + ["bar.txt"])
    archive = tarball("Foo.tar").file(name).create()
    path = str(_untar(archive, tmp_path) / name)
    assert len(path) > 260
    assert os.path.exists(compression._windows_extended_length_path(path))
