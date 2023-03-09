# Copyright 2013-2023 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from __future__ import print_function

import errno
import getpass
import glob
import hashlib
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict

import llnl.util.lang
import llnl.util.tty as tty
from llnl.util.filesystem import (
    can_access,
    get_owner_uid,
    getuid,
    install,
    install_tree,
    mkdirp,
    partition_path,
    remove_linked_tree,
)
from llnl.util.symlink import symlink

import spack.caches
import spack.config
import spack.error
import spack.fetch_strategy as fs
import spack.mirror
import spack.paths
import spack.util.lock
import spack.util.path as sup
import spack.util.pattern as pattern
import spack.util.url as url_util
from spack.util.crypto import bit_length, prefix_bits
from spack.util.web import FetchError

# The well-known stage source subdirectory name.
_source_path_subdir = "spack-src"

# The temporary stage name prefix.
stage_prefix = "spack-stage-"


def create_stage_root(path: str) -> None:
    """Create the stage root directory and ensure appropriate access perms."""
    assert os.path.isabs(path) and len(path.strip()) > 1

    err_msg = "Cannot create stage root {0}: Access to {1} is denied"

    user_uid = getuid()

    # Obtain lists of ancestor and descendant paths of the $user node, if any.
    group_paths, user_node, user_paths = partition_path(path, getpass.getuser())

    for p in group_paths:
        if not os.path.exists(p):
            # Ensure access controls of subdirs created above `$user` inherit
            # from the parent and share the group.
            par_stat = os.stat(os.path.dirname(p))
            mkdirp(p, group=par_stat.st_gid, mode=par_stat.st_mode)

            p_stat = os.stat(p)
            if par_stat.st_gid != p_stat.st_gid:
                tty.warn(
                    "Expected {0} to have group {1}, but it is {2}".format(
                        p, par_stat.st_gid, p_stat.st_gid
                    )
                )

            if par_stat.st_mode & p_stat.st_mode != par_stat.st_mode:
                tty.warn(
                    "Expected {0} to support mode {1}, but it is {2}".format(
                        p, par_stat.st_mode, p_stat.st_mode
                    )
                )

            if not can_access(p):
                raise OSError(errno.EACCES, err_msg.format(path, p))

    # Add the path ending with the $user node to the user paths to ensure paths
    # from $user (on down) meet the ownership and permission requirements.
    if user_node:
        user_paths.insert(0, user_node)

    for p in user_paths:
        # Ensure access controls of subdirs from `$user` on down are
        # restricted to the user.
        owner_uid = get_owner_uid(p)
        if user_uid != owner_uid:
            tty.warn(
                "Expected user {0} to own {1}, but it is owned by {2}".format(
                    user_uid, p, owner_uid
                )
            )

    spack_src_subdir = os.path.join(path, _source_path_subdir)
    # When staging into a user-specified directory with `spack stage -p <PATH>`, we need
    # to ensure the `spack-src` subdirectory exists, as we can't rely on it being
    # created automatically by spack. It's not clear why this is the case for `spack
    # stage -p`, but since `mkdirp()` is idempotent, this should not change the behavior
    # for any other code paths.
    if not os.path.isdir(spack_src_subdir):
        mkdirp(spack_src_subdir, mode=stat.S_IRWXU)


def _first_accessible_path(paths):
    """Find the first path that is accessible, creating it if necessary."""
    for path in paths:
        try:
            # Ensure the user has access, creating the directory if necessary.
            if os.path.exists(path):
                if can_access(path):
                    return path
            else:
                # Now create the stage root with the proper group/perms.
                create_stage_root(path)
                return path

        except OSError as e:
            tty.debug("OSError while checking stage path %s: %s" % (path, str(e)))

    return None


def _resolve_paths(candidates):
    """
    Resolve candidate paths and make user-related adjustments.

    Adjustments involve removing extra $user from $tempdir if $tempdir includes
    $user and appending $user if it is not present in the path.
    """
    temp_path = sup.canonicalize_path("$tempdir")
    user = getpass.getuser()
    tmp_has_usr = user in temp_path.split(os.path.sep)

    paths = []
    for path in candidates:
        # Remove the extra `$user` node from a `$tempdir/$user` entry for
        # hosts that automatically append `$user` to `$tempdir`.
        if path.startswith(os.path.join("$tempdir", "$user")) and tmp_has_usr:
            path = path.replace("/$user", "", 1)

        # Ensure the path is unique per user.
        can_path = sup.canonicalize_path(path)
        if user not in can_path:
            can_path = os.path.join(can_path, user)

        paths.append(can_path)

    return paths


# Cached stage path root
_stage_root = None


def get_stage_root():
    global _stage_root

    if _stage_root is None:
        candidates = spack.config.get("config:build_stage")
        if isinstance(candidates, str):
            candidates = [candidates]

        resolved_candidates = _resolve_paths(candidates)
        path = _first_accessible_path(resolved_candidates)
        if not path:
            raise StageError("No accessible stage paths in:", " ".join(resolved_candidates))

        _stage_root = path

    return _stage_root


def _mirror_roots():
    mirrors = spack.config.get("mirrors")
    return [
        sup.substitute_path_variables(root)
        if root.endswith(os.sep)
        else sup.substitute_path_variables(root) + os.sep
        for root in mirrors.values()
    ]


class Stage(object):
    """Manages a temporary stage directory for building.

    A Stage object is a context manager that handles a directory where
    some source code is downloaded and built before being installed.
    It handles fetching the source code, either as an archive to be
    expanded or by checking it out of a repository.  A stage's
    lifecycle looks like this::

        with Stage() as stage:      # Context manager creates and destroys the
                                    # stage directory
            stage.fetch()           # Fetch a source archive into the stage.
            stage.expand_archive()  # Expand the archive into source_path.
            <install>               # Build and install the archive.
                                    # (handled by user of Stage)

    When used as a context manager, the stage is automatically
    destroyed if no exception is raised by the context. If an
    excpetion is raised, the stage is left in the filesystem and NOT
    destroyed, for potential reuse later.

    You can also use the stage's create/destroy functions manually,
    like this::

        stage = Stage()
        try:
            stage.create()          # Explicitly create the stage directory.
            stage.fetch()           # Fetch a source archive into the stage.
            stage.expand_archive()  # Expand the archive into source_path.
            <install>               # Build and install the archive.
                                    # (handled by user of Stage)
        finally:
            stage.destroy()         # Explicitly destroy the stage directory.

    There are two kinds of stages: named and unnamed.  Named stages
    can persist between runs of spack, e.g. if you fetched a tarball
    but didn't finish building it, you won't have to fetch it again.

    Unnamed stages are created using standard mkdtemp mechanisms or
    similar, and are intended to persist for only one run of spack.
    """

    """Shared dict of all stage locks."""
    stage_locks: Dict[str, spack.util.lock.Lock] = {}

    """Most staging is managed by Spack.  DIYStage is one exception."""
    managed_by_spack = True

    def __init__(
        self,
        url_or_fetch_strategy,
        name=None,
        mirror_paths=None,
        keep=False,
        path=None,
        lock=True,
        search_fn=None,
    ):
        """Create a stage object.
        Parameters:
          url_or_fetch_strategy
              URL of the archive to be downloaded into this stage, OR
              a valid FetchStrategy.

          name
              If a name is provided, then this stage is a named stage
              and will persist between runs (or if you construct another
              stage object later).  If name is not provided, then this
              stage will be given a unique name automatically.

          mirror_paths
              If provided, Stage will search Spack's mirrors for
              this archive at each of the provided relative mirror paths
              before using the default fetch strategy.

          keep
              By default, when used as a context manager, the Stage
              is deleted on exit when no exceptions are raised.
              Pass True to keep the stage intact even if no
              exceptions are raised.

         path
              If provided, the stage path to use for associated builds.

         lock
              True if the stage directory file lock is to be used, False
              otherwise.

         search_fn
              The search function that provides the fetch strategy
              instance.
        """
        # TODO: fetch/stage coupling needs to be reworked -- the logic
        # TODO: here is convoluted and not modular enough.
        if isinstance(url_or_fetch_strategy, str):
            self.fetcher = fs.from_url_scheme(url_or_fetch_strategy)
        elif isinstance(url_or_fetch_strategy, fs.FetchStrategy):
            self.fetcher = url_or_fetch_strategy
        else:
            raise ValueError("Can't construct Stage without url or fetch strategy")
        self.fetcher.stage = self
        # self.fetcher can change with mirrors.
        self.default_fetcher = self.fetcher
        self.search_fn = search_fn
        # used for mirrored archives of repositories.
        self.skip_checksum_for_mirror = True

        self.srcdir = None

        # TODO: This uses a protected member of tempfile, but seemed the only
        # TODO: way to get a temporary name.  It won't be the same as the
        # TODO: temporary stage area in _stage_root.
        self.name = name
        if name is None:
            self.name = stage_prefix + next(tempfile._get_candidate_names())
        self.mirror_paths = mirror_paths

        # Use the provided path or construct an optionally named stage path.
        if path is not None:
            self._path = Path(path)
        else:
            self._path = Path(get_stage_root(), self.name)

        # Flag to decide whether to delete the stage folder on exit or not
        self.keep = keep

        # File lock for the stage directory.  We use one file for all
        # stage locks. See spack.database.Database.prefix_lock for
        # details on this approach.
        self._lock = None
        if lock:
            if self.name not in Stage.stage_locks:
                sha1 = hashlib.sha1(self.name.encode("utf-8")).digest()
                lock_id = prefix_bits(sha1, bit_length(sys.maxsize))
                stage_lock_path = os.path.join(get_stage_root(), ".lock")

                tty.debug("Creating stage lock {0}".format(self.name))
                Stage.stage_locks[self.name] = spack.util.lock.Lock(
                    stage_lock_path, lock_id, 1, desc=self.name
                )

            self._lock = Stage.stage_locks[self.name]

        # When stages are reused, we need to know whether to re-create
        # it.  This marks whether it has been created/destroyed.
        self.created = False

    def __enter__(self):
        """
        Entering a stage context will create the stage directory

        Returns:
            self
        """
        if self._lock is not None:
            self._lock.acquire_write(timeout=60)
        self.create()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exiting from a stage context will delete the stage directory unless:
        - it was explicitly requested not to do so
        - an exception has been raised

        Args:
            exc_type: exception type
            exc_val: exception value
            exc_tb: exception traceback

        Returns:
            Boolean
        """
        # Delete when there are no exceptions, unless asked to keep.
        if exc_type is None and not self.keep:
            self.destroy()

        if self._lock is not None:
            self._lock.release_write()

    @property
    def expected_archive_files(self):
        """Possible archive file paths."""
        paths = []
        fnames = []
        expanded = True
        if isinstance(self.default_fetcher, fs.URLFetchStrategy):
            expanded = self.default_fetcher.expand_archive
            clean_url = os.path.basename(sup.sanitize_file_path(self.default_fetcher.url))
            fnames.append(clean_url)

        if self.mirror_paths:
            fnames.extend(os.path.basename(x) for x in self.mirror_paths)

        paths.extend(str(self._path / f) for f in fnames)
        if not expanded:
            # If the download file is not compressed, the "archive" is a
            # single file placed in Stage.source_path
            paths.extend(os.path.join(self.source_path, f) for f in fnames)

        return paths

    @property
    def save_filename(self):
        possible_filenames = self.expected_archive_files
        if possible_filenames:
            # This prefers using the URL associated with the default fetcher if
            # available, so that the fetched resource name matches the remote
            # name
            return possible_filenames[0]

    @property
    def archive_file(self):
        """Path to the source archive within this stage directory."""
        for path in self.expected_archive_files:
            if os.path.exists(path):
                return path
        else:
            return None

    @property
    def expanded(self):
        """Returns True if source path expanded; else False."""
        return os.path.exists(self.source_path)

    @property
    def path(self):
        return str(self._path)

    @property
    def source_path(self):
        """Returns the well-known source directory path."""
        return str(self._path / _source_path_subdir)

    def contains(self, file_path):
        return os.path.realpath(self.path) in file_path

    def path_rel_to_stage(self, glob_expr):
        return os.path.relpath(glob_expr, self.path)

    def fetch(self, mirror_only=False, err_msg=None):
        """Retrieves the code or archive

        Args:
            mirror_only (bool): only fetch from a mirror
            err_msg (str or None): the error message to display if all fetchers
                fail or ``None`` for the default fetch failure message
        """
        fetchers = []
        if not mirror_only:
            fetchers.append(self.default_fetcher)

        # TODO: move mirror logic out of here and clean it up!
        # TODO: Or @alalazo may have some ideas about how to use a
        # TODO: CompositeFetchStrategy here.
        self.skip_checksum_for_mirror = True
        if self.mirror_paths:
            # Join URLs of mirror roots with mirror paths. Because
            # urljoin() will strip everything past the final '/' in
            # the root, so we add a '/' if it is not present.
            mirror_urls = {}
            for mirror in spack.mirror.MirrorCollection().values():
                for rel_path in self.mirror_paths:
                    mirror_url = url_util.join(mirror.fetch_url, rel_path)
                    mirror_urls[mirror_url] = {}
                    if (
                        mirror.get_access_pair("fetch")
                        or mirror.get_access_token("fetch")
                        or mirror.get_profile("fetch")
                    ):
                        mirror_urls[mirror_url] = {
                            "access_token": mirror.get_access_token("fetch"),
                            "access_pair": mirror.get_access_pair("fetch"),
                            "access_profile": mirror.get_profile("fetch"),
                            "endpoint_url": mirror.get_endpoint_url("fetch"),
                        }

            # If this archive is normally fetched from a tarball URL,
            # then use the same digest.  `spack mirror` ensures that
            # the checksum will be the same.
            digest = None
            expand = True
            extension = None
            if isinstance(self.default_fetcher, fs.URLFetchStrategy):
                digest = self.default_fetcher.digest
                expand = self.default_fetcher.expand_archive
                extension = self.default_fetcher.extension

            # Have to skip the checksum for things archived from
            # repositories.  How can this be made safer?
            self.skip_checksum_for_mirror = not bool(digest)

            # Add URL strategies for all the mirrors with the digest
            # Insert fetchers in the order that the URLs are provided.
            for url in reversed(list(mirror_urls.keys())):
                fetchers.insert(
                    0,
                    fs.from_url_scheme(
                        url,
                        digest,
                        expand=expand,
                        extension=extension,
                        connection=mirror_urls[url],
                    ),
                )

            if self.default_fetcher.cachable:
                for rel_path in reversed(list(self.mirror_paths)):
                    cache_fetcher = spack.caches.fetch_cache.fetcher(
                        rel_path, digest, expand=expand, extension=extension
                    )
                    fetchers.insert(0, cache_fetcher)

        def generate_fetchers():
            for fetcher in fetchers:
                yield fetcher
            # The search function may be expensive, so wait until now to
            # call it so the user can stop if a prior fetcher succeeded
            if self.search_fn and not mirror_only:
                dynamic_fetchers = self.search_fn()
                for fetcher in dynamic_fetchers:
                    yield fetcher

        def print_errors(errors):
            for msg in errors:
                tty.debug(msg)

        errors = []
        for fetcher in generate_fetchers():
            try:
                fetcher.stage = self
                self.fetcher = fetcher
                self.fetcher.fetch()
                break
            except spack.fetch_strategy.NoCacheError:
                # Don't bother reporting when something is not cached.
                continue
            except spack.error.SpackError as e:
                errors.append("Fetching from {0} failed.".format(fetcher))
                tty.debug(e)
                continue
        else:
            print_errors(errors)

            self.fetcher = self.default_fetcher
            default_msg = "All fetchers failed for {0}".format(self.name)
            raise FetchError(err_msg or default_msg, None)

        print_errors(errors)

    def steal_source(self, dest):
        """Copy the source_path directory in its entirety to directory dest

        This operation creates/fetches/expands the stage if it is not already,
        and destroys the stage when it is done."""
        if not self.created:
            self.create()
        if not self.expanded and not self.archive_file:
            self.fetch()
        if not self.expanded:
            self.expand_archive()

        if not os.path.isdir(dest):
            mkdirp(dest)

        # glob all files and directories in the source path
        hidden_entries = glob.glob(os.path.join(self.source_path, ".*"))
        entries = glob.glob(os.path.join(self.source_path, "*"))

        # Move all files from stage to destination directory
        # Include hidden files for VCS repo history
        for entry in hidden_entries + entries:
            if os.path.isdir(entry):
                d = os.path.join(dest, os.path.basename(entry))
                shutil.copytree(entry, d, symlinks=True)
            else:
                shutil.copy2(entry, dest)

        # copy archive file if we downloaded from url -- replaces for vcs
        if self.archive_file and os.path.exists(self.archive_file):
            shutil.copy2(self.archive_file, dest)

        # remove leftover stage
        self.destroy()

    def check(self):
        """Check the downloaded archive against a checksum digest.
        No-op if this stage checks code out of a repository."""
        if self.fetcher is not self.default_fetcher and self.skip_checksum_for_mirror:
            tty.warn(
                "Fetching from mirror without a checksum!",
                "This package is normally checked out from a version "
                "control system, but it has been archived on a spack "
                "mirror.  This means we cannot know a checksum for the "
                "tarball in advance. Be sure that your connection to "
                "this mirror is secure!",
            )
        elif spack.config.get("config:checksum"):
            self.fetcher.check()

    def cache_local(self):
        spack.caches.fetch_cache.store(self.fetcher, self.mirror_paths.storage_path)

    def cache_mirror(self, mirror, stats):
        """Perform a fetch if the resource is not already cached

        Arguments:
            mirror (spack.caches.MirrorCache): the mirror to cache this Stage's
                resource in
            stats (spack.mirror.MirrorStats): this is updated depending on whether the
                caching operation succeeded or failed
        """
        if isinstance(self.default_fetcher, fs.BundleFetchStrategy):
            # BundleFetchStrategy has no source to fetch. The associated
            # fetcher does nothing but the associated stage may still exist.
            # There is currently no method available on the fetcher to
            # distinguish this ('cachable' refers to whether the fetcher
            # refers to a resource with a fixed ID, which is not the same
            # concept as whether there is anything to fetch at all) so we
            # must examine the type of the fetcher.
            return

        if mirror.skip_unstable_versions and not fs.stable_target(self.default_fetcher):
            return

        absolute_storage_path = os.path.join(mirror.root, self.mirror_paths.storage_path)

        if os.path.exists(absolute_storage_path):
            stats.already_existed(absolute_storage_path)
        else:
            self.fetch()
            self.check()
            mirror.store(self.fetcher, self.mirror_paths.storage_path)
            stats.added(absolute_storage_path)

        mirror.symlink(self.mirror_paths)

    def expand_archive(self):
        """Changes to the stage directory and attempt to expand the downloaded
        archive.  Fail if the stage is not set up or if the archive is not yet
        downloaded."""
        if not self.expanded:
            self.fetcher.expand()
            tty.debug("Created stage in {0}".format(self._path))
        else:
            tty.debug("Already staged {0} in {1}".format(self.name, self._path))

    def restage(self):
        """Removes the expanded archive path if it exists, then re-expands
        the archive.
        """
        self.fetcher.reset()

    def create(self):
        """
        Ensures the top-level (config:build_stage) directory exists.
        """
        # User has full permissions and group has only read permissions
        if not self._path.exists():
            mkdirp(self.path, mode=stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)
        elif not self._path.is_dir():
            self._path.unlink()
            mkdirp(self.path, mode=stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP)

        # Make sure we can actually do something with the stage we made.
        ensure_access(self._path)
        self.created = True

    def destroy(self):
        """Removes this stage directory."""
        remove_linked_tree(self.path)

        # Make sure we don't end up in a removed directory
        try:
            os.getcwd()
        except OSError as e:
            tty.debug(e)
            os.chdir(self._path.parent)

        # mark as destroyed
        self.created = False


class ResourceStage(Stage):
    def __init__(self, url_or_fetch_strategy, root, resource, **kwargs):
        super(ResourceStage, self).__init__(url_or_fetch_strategy, **kwargs)
        self.root_stage = root
        self.resource = resource

    def restage(self):
        super(ResourceStage, self).restage()
        self._add_to_root_stage()

    def expand_archive(self):
        super(ResourceStage, self).expand_archive()
        self._add_to_root_stage()

    def _add_to_root_stage(self):
        """
        Move the extracted resource to the root stage (according to placement).
        """
        root_stage = self.root_stage
        resource = self.resource

        if resource.placement:
            placement = resource.placement
        elif self.srcdir:
            placement = self.srcdir
        else:
            placement = self.source_path

        if not isinstance(placement, dict):
            placement = {"": placement}

        target_path = os.path.join(root_stage.source_path, resource.destination)

        try:
            os.makedirs(target_path)
        except OSError as err:
            tty.debug(err)
            if err.errno == errno.EEXIST and os.path.isdir(target_path):
                pass
            else:
                raise

        for key, value in placement.items():
            destination_path = os.path.join(target_path, value)
            source_path = os.path.join(self.source_path, key)

            if not os.path.exists(destination_path):
                tty.info(
                    "Moving resource stage\n\tsource: "
                    "{stage}\n\tdestination: {destination}".format(
                        stage=source_path, destination=destination_path
                    )
                )

                src = os.path.realpath(source_path)

                if os.path.isdir(src):
                    install_tree(src, destination_path)
                else:
                    install(src, destination_path)


class CMakeBuildStage(Stage):
    """Interface abstracting a CMake build tree at a location outside
    of a Spack stage directory but still managed by Spack.

    CMake's build tree can be located arbitrarily on a filesystem independent
    from a source directory. This class relocates that build directory out of the
    stage and to a path under a Users home directory or to a location of a users chosing set
    either by config or the command line via the --cmake-build-dir cl argument
    to the install command.
    Interactions with the stage expecting an in stage build tree will work as normal
    as this class serves to obfucscate the external stage and allow for all stage behavior
    to perform as normal.
    The external build tree is given the same lifespan as its stage dir, is spun up when the stage
    spins up, and destroyed when the stage is destroyed. After the build and installation are done,
    the build tree is first relocated to what would be its proper place in the stage.
    and a symlink is placed in place of the build tree pointing at the external directory

    Note: This is not, nor should it be, used on *nix platforms and is intended as a solution to
    reduce file path lengths on Windows during compilation/linking. This class should be removed
    when MSVC fully supports the LongPath feature on Windows.
    """


    def __init__(self, hash, fetcher, **kwargs):
        # Users can override external cmake build dir, default is %USERPROFILE%
        # overrides can come from command line or config, command line will override all
        super(CMakeBuildStage, self).__init__(fetcher, **kwargs)
        self._hash = hash
        self._remote_stage = None
        self._remote_root = Path(spack.config.get("config:cmake_ext_build"))

    @property
    def root_stage_context(self):
        return self._path / ("spack-build-%s" % self._hash)

    @property
    def build_directory(self):
        return self._remote_stage

    def _establish_context_link(self):
        symlink(str(self._remote_stage), str(self.root_stage_context))

    def _remove_context_link(self):
        self.root_stage_context.unlink()

    def _setup_remote_build_stage(self):
        # try to create root if it doesn't exist
        self._remote_root.mkdir(parents=True, exist_ok=True)
        sub_dir = self._compute_next_open_subdir()
        full_subdir = self._remote_root / sub_dir
        attempts = 0
        while True and attempts < 200:
            try:
                full_subdir.mkdir()
                break
            except FileExistsError:
                # another process must have created the same directory as us
                # try again
                attempts += 1

        return full_subdir

    def _compute_next_open_subdir(self, last=None):
        def inc(c):
            curr = ord(c[-1])
            over = curr // 122
            if over:
                return (inc(c[:-1]) if len(c[:-1]) else "a") + "a"
            return c[:-1] + chr(curr + 1)

        sort_key = lambda x: (len(x.name), x.name)
        current_ext_stages = list(self._remote_root.iterdir())
        if not current_ext_stages:
            # no currently extant external stages, start enumerating with 'a'
            return "a"
        last = sorted(current_ext_stages, key=sort_key)[-1]
        return inc(last.name)

    def _teardown_remote_stage(self):
        """Destroy external build tree if not keep-stage
        Otherwise this is kept as usual"""

        def teardown(pth: Path):
            for sub_item in pth.iterdir():
                if sub_item.is_dir():
                    teardown(sub_item)
                else:
                    sub_item.unlink()
            pth.rmdir()

        if self._remote_stage.exists():
            teardown(self._remote_stage)
        self._remote_stage = None

    def _return_destroy_remote(self):
        # copy back to stage may fail in event of error, make sure we clean up the
        # associated external build dir in that event unless we're keeping the
        # parent stage on cleanup
        # If remote stage is not set, we never created one, package is already
        # installed and we should do nothing here
        if self._remote_stage:
            try:
                self._remove_context_link()
            finally:
                self._teardown_remote_stage()

    def contains(self, file_path):
        cont = super(CMakeBuildStage, self).contains(file_path)
        if not cont:
            return str(self._remote_stage) in file_path
        return cont

    def create(self):
        if not self.created:
            # Establish typical root stage
            super(CMakeBuildStage, self).create()
            # Now establish remote build stage
            # or pick up extant stage
            if not self.root_stage_context.exists():
                try:
                    self._remote_stage = self._setup_remote_build_stage()
                    self._establish_context_link()
                except Exception:
                    self._teardown_remote_stage()
                    self.created = False
                    raise
            else:
                self._remote_stage = self.root_stage_context.resolve()

    def destroy(self):
        self._return_destroy_remote()
        super(CMakeBuildStage, self).destroy()

    def path_rel_to_stage(self, glob_expr):
        return os.path.relpath(glob_expr, self._remote_stage)

    def restage(self):
        self._return_destroy_remote()
        super(CMakeBuildStage, self).restage()
        self.create()


class StageComposite(pattern.Composite):
    """Composite for Stage type objects. The first item in this composite is
    considered to be the root package, and operations that return a value are
    forwarded to it."""

    #
    # __enter__ and __exit__ delegate to all stages in the composite.
    #

    def __init__(self):
        super(StageComposite, self).__init__(
            [
                "fetch",
                "create",
                "created",
                "check",
                "expand_archive",
                "restage",
                "destroy",
                "cache_local",
                "cache_mirror",
                "steal_source",
                "managed_by_spack",
            ]
        )

    def __enter__(self):
        for item in self:
            item.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for item in reversed(self):
            item.keep = getattr(self, "keep", False)
            item.__exit__(exc_type, exc_val, exc_tb)

    #
    # Below functions act only on the *first* stage in the composite.
    #
    @property
    def source_path(self):
        return self[0].source_path

    @property
    def expanded(self):
        return self[0].expanded

    @property
    def path(self):
        return self[0].path

    @property
    def archive_file(self):
        return self[0].archive_file

    @property
    def build_directory(self):
        return self[0].build_directory

    def contains(self, file_path):
        return self[0].contains(file_path)

    def path_rel_to_stage(self, glob_expr):
        return self[0].path_rel_to_stage(glob_expr)


class DIYStage(object):
    """
    Simple class that allows any directory to be a spack stage.  Consequently,
    it does not expect or require that the source path adhere to the standard
    directory naming convention.
    """

    """DIY staging is, by definition, not managed by Spack."""
    managed_by_spack = False

    def __init__(self, path):
        if path is None:
            raise ValueError("Cannot construct DIYStage without a path.")
        elif not os.path.isdir(path):
            raise StagePathError("The stage path directory does not exist:", path)

        self.archive_file = None
        self.path = path
        self.source_path = path
        self.created = True

    # DIY stages do nothing as context managers.
    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def fetch(self, *args, **kwargs):
        tty.debug("No need to fetch for DIY.")

    def check(self):
        tty.debug("No checksum needed for DIY.")

    def expand_archive(self):
        tty.debug("Using source directory: {0}".format(self.source_path))

    @property
    def expanded(self):
        """Returns True since the source_path must exist."""
        return True

    def restage(self):
        raise RestageError("Cannot restage a DIY stage.")

    def create(self):
        self.created = True

    def destroy(self):
        # No need to destroy DIY stage.
        pass

    def cache_local(self):
        tty.debug("Sources for DIY stages are not cached")


def ensure_access(file):
    """Ensure we can access a directory and die with an error if we can't."""
    if not can_access(file):
        tty.die("Insufficient permissions for %s" % file)


def purge():
    """Remove all build directories in the top-level stage path."""
    root = get_stage_root()
    if os.path.isdir(root):
        for stage_dir in os.listdir(root):
            if stage_dir.startswith(stage_prefix) or stage_dir == ".lock":
                stage_path = os.path.join(root, stage_dir)
                if os.path.isdir(stage_path):
                    remove_linked_tree(stage_path)
                else:
                    os.remove(stage_path)
    # Remove all external build directories spack is aware of as well
    ext_build_dir = spack.config.get("config:cmake_ext_build", None)
    if ext_build_dir and os.path.exists(ext_build_dir):
        for ext_build in os.listdir(ext_build_dir):
            if os.path.isdir(ext_build):
                remove_linked_tree(ext_build)
            else:
                os.remove(ext_build)


def get_checksums_for_versions(url_dict, name, **kwargs):
    """Fetches and checksums archives from URLs.

    This function is called by both ``spack checksum`` and ``spack
    create``.  The ``first_stage_function`` argument allows the caller to
    inspect the first downloaded archive, e.g., to determine the build
    system.

    Args:
        url_dict (dict): A dictionary of the form: version -> URL
        name (str): The name of the package
        first_stage_function (typing.Callable): function that takes a Stage and a URL;
            this is run on the stage of the first URL downloaded
        keep_stage (bool): whether to keep staging area when command completes
        batch (bool): whether to ask user how many versions to fetch (false)
            or fetch all versions (true)
        latest (bool): whether to take the latest version (true) or all (false)
        fetch_options (dict): Options used for the fetcher (such as timeout
            or cookies)

    Returns:
        (str): A multi-line string containing versions and corresponding hashes

    """
    batch = kwargs.get("batch", False)
    fetch_options = kwargs.get("fetch_options", None)
    first_stage_function = kwargs.get("first_stage_function", None)
    keep_stage = kwargs.get("keep_stage", False)
    latest = kwargs.get("latest", False)

    sorted_versions = sorted(url_dict.keys(), reverse=True)
    if latest:
        sorted_versions = sorted_versions[:1]

    # Find length of longest string in the list for padding
    max_len = max(len(str(v)) for v in sorted_versions)
    num_ver = len(sorted_versions)

    tty.msg(
        "Found {0} version{1} of {2}:".format(num_ver, "" if num_ver == 1 else "s", name),
        "",
        *llnl.util.lang.elide_list(
            ["{0:{1}}  {2}".format(str(v), max_len, url_dict[v]) for v in sorted_versions]
        ),
    )
    print()

    if batch or latest:
        archives_to_fetch = len(sorted_versions)
    else:
        archives_to_fetch = tty.get_number(
            "How many would you like to checksum?", default=1, abort="q"
        )

    if not archives_to_fetch:
        tty.die("Aborted.")

    versions = sorted_versions[:archives_to_fetch]
    urls = [url_dict[v] for v in versions]

    tty.debug("Downloading...")
    version_hashes = []
    i = 0
    errors = []
    for url, version in zip(urls, versions):
        # Wheels should not be expanded during staging
        expand_arg = ""
        if url.endswith(".whl") or ".whl#" in url:
            expand_arg = ", expand=False"
        try:
            if fetch_options:
                url_or_fs = fs.URLFetchStrategy(url, fetch_options=fetch_options)
            else:
                url_or_fs = url
            with Stage(url_or_fs, keep=keep_stage) as stage:
                # Fetch the archive
                stage.fetch()
                if i == 0 and first_stage_function:
                    # Only run first_stage_function the first time,
                    # no need to run it every time
                    first_stage_function(stage, url)

                # Checksum the archive and add it to the list
                version_hashes.append(
                    (version, spack.util.crypto.checksum(hashlib.sha256, stage.archive_file))
                )
                i += 1
        except FailedDownloadError:
            errors.append("Failed to fetch {0}".format(url))
        except Exception as e:
            tty.msg("Something failed on {0}, skipping.  ({1})".format(url, e))

    for msg in errors:
        tty.debug(msg)

    if not version_hashes:
        tty.die("Could not fetch any versions for {0}".format(name))

    # Generate the version directives to put in a package.py
    version_lines = "\n".join(
        ['    version("{0}", sha256="{1}"{2})'.format(v, h, expand_arg) for v, h in version_hashes]
    )

    num_hash = len(version_hashes)
    tty.debug(
        "Checksummed {0} version{1} of {2}:".format(num_hash, "" if num_hash == 1 else "s", name)
    )

    return version_lines


class StageError(spack.error.SpackError):
    """ "Superclass for all errors encountered during staging."""


class StagePathError(StageError):
    """ "Error encountered with stage path."""


class RestageError(StageError):
    """ "Error encountered during restaging."""


class VersionFetchError(StageError):
    """Raised when we can't determine a URL to fetch a package."""


# Keep this in namespace for convenience
FailedDownloadError = fs.FailedDownloadError
