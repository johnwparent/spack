# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
Utility module for dealing with Windows Registry.
"""

import itertools
import os
import re
import sys
from contextlib import contextmanager

from spack.util import tty
from spack.util.lang import Retry

if sys.platform == "win32":
    import winreg

#: the system cannot find the file specified - lookup item does not exist
ERROR_FILE_NOT_FOUND = 2
#: Access is denied - user not in key's ACL
ERROR_ACCESS_DENIED = 5
#: The handle is invalid - a cached key handle has gone stale
ERROR_INVALID_HANDLE = 6
#: No more data is available - an enumeration has run out of items
ERROR_NO_MORE_ITEMS = 259

#: Errors that will never be resolved by repeating the operation. Everything else the
#: registry reports is treated as potentially transient, matching the fact that the registry
#: raises the same generic error for every atypical condition.
_TERMINAL_ERRORS = (ERROR_FILE_NOT_FOUND, ERROR_ACCESS_DENIED, ERROR_NO_MORE_ITEMS)


def _operation_retry() -> Retry:
    """Retry policy for a single registry operation.

    Registry contention clears more or less immediately, so the backoff is deliberately tiny:
    the point is to yield briefly to whichever process holds the key, not to wait out a remote
    service. Note that ``Retry`` rejects a ``backoff_max`` of zero, so this cannot be reduced
    to a pure busy-retry.
    """
    return Retry(total=3, backoff_factor=0.01, backoff_jitter=0.01, backoff_max=0.1)


class RegistryValue:
    """
    Class defining a Windows registry entry
    """

    def __init__(self, name, value, parent_key):
        self.path = name
        self.value = value
        self.key = parent_key


class RegistryKey:
    """
    Class wrapping a Windows registry key
    """

    def __init__(self, name, handle=None, parent=None):
        self.path = name
        self.name = os.path.split(name)[-1]
        self._handle = handle
        self._parent = parent
        # None rather than an empty container, so that a key which genuinely has no subkeys
        # or no values is enumerated once instead of on every access
        self._keys = None
        self._values = None

    @property
    def values(self):
        """Returns all subvalues of this key as RegistryValue objects in dictionary
        of value name : RegistryValue object
        """
        self._gather_value_info()
        return self._values

    @property
    def subkeys(self):
        """Returns list of all subkeys of this key as RegistryKey objects"""
        self._gather_subkey_info()
        return self._keys

    @property
    def hkey(self):
        if self._handle is None and self._parent is not None:
            # A key that was reached through its parent can always be reopened through it, so
            # traversals are free to release handles they are done with, and a caller that
            # holds on to a key and reads from it later still works.
            self._handle = self._parent.OpenKeyEx(self.name, access=winreg.KEY_READ)
        return self._handle

    def close(self):
        """Release this key's handle. Keys reached by enumeration reopen it on next use."""
        if self._handle is not None:
            self._handle.Close()
            self._handle = None

    def _invalidate_handle(self):
        """Drop a stale handle so the next access reopens the key through its parent"""
        if self._parent is not None:
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def _winreg_call(self, name, func, *args, **kwargs):
        """Invoke a single winreg function, retrying only that operation if it fails.

        The registry offers no locking, and other processes rewrite it while Spack reads it,
        so individual operations fail spuriously. Retrying at this level means a flaky call
        costs one more call, rather than discarding the search, query, or subkey traversal
        that contained it.

        ``func`` is called as ``func(self.hkey, *args, **kwargs)``; ``name`` and the logical
        arguments are used only for error reporting.
        """
        retry = _operation_retry()
        for _ in retry:
            try:
                return func(self.hkey, *args, **kwargs)
            except OSError as err:
                winerror = getattr(err, "winerror", None)
                # Expected errors that occur on occasion, these are easily
                # debug-able and have sufficiently verbose reporting and obvious cause
                if winerror in _TERMINAL_ERRORS:
                    raise
                if winerror == ERROR_INVALID_HANDLE:
                    self._invalidate_handle()
                if not retry.is_last_attempt():
                    tty.debug(f"[WINREG ACCESS] Retrying {name} on {self.path} after error: {err}")
                    continue
                # Other OS errors are more difficult to diagnose, so we wrap them in some extra
                # reporting
                raise InvalidRegistryOperation(name, err, *args, **kwargs) from err
        raise AssertionError("unreachable")

    def OpenKeyEx(self, subname, **kwargs):
        """Convenience wrapper around winreg.OpenKeyEx"""
        tty.debug(
            f"[WINREG ACCESS] Accessing Reg Key {self.path}/{subname} with"
            f" {kwargs.get('access', 'default')} access"
        )
        return self._winreg_call("OpenKeyEx", winreg.OpenKeyEx, subname, **kwargs)

    def QueryInfoKey(self):
        """Convenience wrapper around winreg.QueryInfoKey"""
        tty.debug(f"[WINREG ACCESS] Obtaining key,value information from key {self.path}")
        return self._winreg_call("QueryInfoKey", winreg.QueryInfoKey)

    def EnumKey(self, index):
        """Convenience wrapper around winreg.EnumKey"""
        tty.debug(
            "[WINREG ACCESS] Obtaining name of subkey at index "
            f"{index} from registry key {self.path}"
        )
        return self._winreg_call("EnumKey", winreg.EnumKey, index)

    def EnumValue(self, index):
        """Convenience wrapper around winreg.EnumValue"""
        tty.debug(
            f"[WINREG ACCESS] Obtaining value at index {index} from registry key {self.path}"
        )
        return self._winreg_call("EnumValue", winreg.EnumValue, index)

    def QueryValueEx(self, name, **kwargs):
        """Convenience wrapper around winreg.QueryValueEx"""
        tty.debug(f"[WINREG ACCESS] Obtaining value {name} from registry key {self.path}")
        return self._winreg_call("QueryValueEx", winreg.QueryValueEx, name, **kwargs)

    def __str__(self):
        return self.name

    def _gather_subkey_info(self):
        """Composes all subkeys into a list for access"""
        if self._keys is not None:
            return
        self._keys = []
        # The registry is live: installers, MSI, and Windows Update add and remove keys while
        # we walk them, so the subkey count reported by QueryInfoKey is only ever a hint.
        # Enumerate until the registry itself reports the end of the enumeration, which also
        # picks up keys added after a count would have been taken.
        for i in itertools.count():
            try:
                sub_name = self.EnumKey(i)
            except OSError as e:
                if getattr(e, "winerror", None) == ERROR_NO_MORE_ITEMS:
                    break
                raise
            try:
                # Opening here is what tells us whether the key is readable at all, so that
                # keys we cannot read are dropped as callers expect. Recording the parent
                # means the handle can be released once a traversal is done with the key and
                # transparently reopened if the caller reads from it later.
                sub_handle = self.OpenKeyEx(sub_name, access=winreg.KEY_READ)
            except OSError as e:
                if getattr(e, "winerror", None) in (ERROR_ACCESS_DENIED, ERROR_FILE_NOT_FOUND):
                    # Either a permission error, so we can't read this key, or the key was
                    # removed between being enumerated and being opened. Move on either way.
                    continue
                raise
            self._keys.append(
                RegistryKey(os.path.join(self.path, sub_name), sub_handle, parent=self)
            )

    def _gather_value_info(self):
        """Compose all values for this key into a dict of form value name: RegistryValue Object"""
        if self._values is not None:
            return
        self._values = {}
        # Value counts race against concurrent writers exactly as subkey counts do; see
        # _gather_subkey_info.
        for i in itertools.count():
            try:
                value_name, value_data, _ = self.EnumValue(i)
            except OSError as e:
                if getattr(e, "winerror", None) == ERROR_NO_MORE_ITEMS:
                    break
                raise
            self._values[value_name] = RegistryValue(value_name, value_data, self)

    def get_subkey(self, sub_key):
        """Returns subkey of name sub_key in a RegistryKey objects"""
        # Unlike enumeration, this open is deliberately eager: callers rely on a nonexistent
        # subkey raising FileNotFoundError here rather than at first use.
        return RegistryKey(
            os.path.join(self.path, sub_key),
            self.OpenKeyEx(sub_key, access=winreg.KEY_READ),
            parent=self,
        )

    def get_value(self, val_name):
        """Returns value associated with this key in RegistryValue object"""
        return RegistryValue(val_name, self.QueryValueEx(val_name)[0], self)


class _HKEY_CONSTANT(RegistryKey):
    """Subclass of RegistryKey to represent the prebaked, always open registry HKEY constants"""

    def __init__(self, hkey_constant):
        hkey_name = hkey_constant
        # This class is instantiated at module import time
        # on non Windows platforms, winreg would not have been
        # imported. For this reason we can't reference winreg yet,
        # so handle is none for now to avoid invalid references to a module.
        # _handle provides a workaround to prevent null references to self.handle
        # when coupled with the handle property.
        super(_HKEY_CONSTANT, self).__init__(hkey_name, None)

    def _get_hkey(self, key):
        return getattr(winreg, key)

    @property
    def hkey(self):
        if not self._handle:
            self._handle = self._get_hkey(self.path)
        return self._handle

    def close(self):
        """The predefined HKEY constants are always open and must never be closed"""


class HKEY:
    """
    Predefined, open registry HKEYs
    From the Microsoft docs:
    An application must open a key before it can read data from the registry.
    To open a key, an application must supply a handle to another key in
    the registry that is already open. The system defines predefined keys
    that are always open. Predefined keys help an application navigate in
    the registry."""

    HKEY_CLASSES_ROOT = _HKEY_CONSTANT("HKEY_CLASSES_ROOT")
    HKEY_CURRENT_USER = _HKEY_CONSTANT("HKEY_CURRENT_USER")
    HKEY_USERS = _HKEY_CONSTANT("HKEY_USERS")
    HKEY_LOCAL_MACHINE = _HKEY_CONSTANT("HKEY_LOCAL_MACHINE")
    HKEY_CURRENT_CONFIG = _HKEY_CONSTANT("HKEY_CURRENT_CONFIG")
    HKEY_PERFORMANCE_DATA = _HKEY_CONSTANT("HKEY_PERFORMANCE_DATA")


class WindowsRegistryView:
    """
    Interface to provide access, querying, and searching to Windows registry entries.
    This class represents a single key entrypoint into the Windows registry
    and provides an interface to this key's values, its subkeys, and those subkey's values.
    This class cannot be used to move freely about the registry, only subkeys/values of
    the root key used to instantiate this class.
    """

    def __init__(self, key, root_key=HKEY.HKEY_CURRENT_USER):
        """Constructs a Windows Registry entrypoint to key provided
        root_key should be an already open root key or an hkey constant if provided

        Args:
            key (str): registry key to provide root for registry key for this clas
            root_key: Already open registry key or HKEY constant to provide access into
                         the Windows registry. Registry access requires an already open key
                         to get an entrypoint, the HKEY constants are always open, or an already
                         open key can be used instead.
        """
        if sys.platform != "win32":
            raise RuntimeError(
                "Cannot instantiate Windows Registry class on non Windows platforms"
            )
        self.key = key
        self.root = root_key
        self._reg = None

    class KeyMatchConditions:
        @staticmethod
        def regex_matcher(subkey_name):
            return lambda x: re.match(subkey_name, x.name)

        @staticmethod
        def name_matcher(subkey_name):
            return lambda x: subkey_name == x.name

    @contextmanager
    def invalid_reg_ref_error_handler(self):
        try:
            yield
        except FileNotFoundError as e:
            if sys.platform == "win32" and e.winerror == 2:
                tty.debug("Key %s at position %s does not exist" % (self.key, str(self.root)))
            else:
                raise e

    def __bool__(self):
        return self.reg != -1

    def _load_key(self):
        try:
            self._reg = self.root.get_subkey(self.key)
        except FileNotFoundError as e:
            if sys.platform == "win32" and e.winerror == 2:
                self._reg = -1
                tty.debug("Key %s at position %s does not exist" % (self.key, str(self.root)))
            else:
                raise e

    def _valid_reg_check(self):
        if self.reg == -1:
            tty.debug(f"[WINREG ACCESS] Cannot perform operation for nonexistent key {self.key}")
            return False
        return True

    def _regex_match_subkeys(self, subkey):
        r_subkey = re.compile(subkey)
        return [key for key in self.get_subkeys() if r_subkey.match(key.name)]

    @property
    def reg(self):
        if not self._reg:
            self._load_key()
        return self._reg

    def get_value(self, value_name):
        """Return registry value corresponding to provided argument (if it exists)"""
        if not self._valid_reg_check():
            raise RegistryError(f"Cannot query value from invalid key {self.key}")
        with self.invalid_reg_ref_error_handler():
            return self.reg.get_value(value_name)

    def get_subkey(self, subkey_name):
        if not self._valid_reg_check():
            raise RegistryError(f"Cannot query subkey from invalid key {self.key}")
        with self.invalid_reg_ref_error_handler():
            return self.reg.get_subkey(subkey_name)

    def get_subkeys(self):
        if not self._valid_reg_check():
            raise RegistryError(f"Cannot query subkeys from invalid key {self.key}")
        with self.invalid_reg_ref_error_handler():
            return self.reg.subkeys

    def get_matching_subkeys(self, subkey_name):
        """Returns all subkeys regex matching subkey name

        Note: this method obtains only direct subkeys of the given key and does not
        descend to transitive subkeys. For this behavior, see ``find_matching_subkeys``"""
        return self._regex_match_subkeys(subkey_name)

    def get_values(self):
        if not self._valid_reg_check():
            raise RegistryError(f"Cannot query values from invalid key {self.key}")
        with self.invalid_reg_ref_error_handler():
            return self.reg.values

    def _traverse_subkeys(self, stop_condition, collect_all_matching=False, recursive=True):
        """Perform simple BFS of subkeys, returning the key
        that successfully triggers the stop condition.
        Args:
            stop_condition: lambda or function pointer that takes a single argument
                            a key and returns a boolean value based on that key
            collect_all_matching: boolean value, if True, the traversal collects and returns
                            all keys meeting stop condition. If false, once stop
                            condition is met, the key that triggered the condition '
                            is returned.
            recursive: boolean value, if True perform a recursive search of subkeys
        Return:
            the key if stop_condition is triggered, or None if not
        """
        collection = []
        if not self._valid_reg_check():
            raise InvalidKeyError(self.key)
        with self.invalid_reg_ref_error_handler():
            # Copy: self.reg.subkeys is the key's own cached child list, and extending it
            # below would append grandchildren into that cache
            queue = list(self.reg.subkeys)
            for key in queue:
                matched = stop_condition(key)
                if matched and not collect_all_matching:
                    return key
                if matched:
                    collection.append(key)
                if recursive:
                    queue.extend(key.subkeys)
                if not matched:
                    # Release the handle now that this key has been matched against and
                    # descended into. Without this a recursive walk holds one open handle
                    # for every key in the subtree at once. Keys we return keep theirs, and
                    # any key reopens through its parent if it is read from later.
                    key.close()
            return collection if collection else None

    def find_subkey(self, subkey_name: str, recursive: bool = True):
        """Perform a BFS of subkeys until desired key is found
        Returns None or RegistryKey object corresponding to requested key name

        Args:
            subkey_name: subkey to be searched for
            recursive:  perform a recursive search
        Return:
            the desired subkey as a RegistryKey object, or none
        """
        return self._traverse_subkeys(
            WindowsRegistryView.KeyMatchConditions.name_matcher(subkey_name), recursive=recursive
        )

    def find_matching_subkey(self, subkey_name: str, recursive: bool = True):
        """Perform a BFS of subkeys until a key matching subkey name regex is found
        Returns None or the first RegistryKey object corresponding to requested key name

        Args:
            subkey_name: subkey to be searched for
            recursive:  perform a recursive search
        Return:
            the desired subkey as a RegistryKey object, or none
        """
        return self._traverse_subkeys(
            WindowsRegistryView.KeyMatchConditions.regex_matcher(subkey_name), recursive=recursive
        )

    def find_subkeys(self, subkey_name: str, recursive: bool = True):
        """Exactly the same as find_subkey, except this function tries to match
        a regex to multiple keys

        Args:
            subkey_name: subkey to be searched for
        Return:
            the desired subkeys as a list of RegistryKey object, or none
        """
        kwargs = {"collect_all_matching": True, "recursive": recursive}
        return self._traverse_subkeys(
            WindowsRegistryView.KeyMatchConditions.regex_matcher(subkey_name), **kwargs
        )

    def find_value(self, val_name: str, recursive: bool = True):
        """
        If non recursive, return RegistryValue object corresponding to name

        Args:
            val_name: name of value desired from registry
            recursive: optional argument, if True, the registry is searched recursively
                       for the value of name val_name, else only the current key is searched
        Return:
            The desired registry value as a RegistryValue object if it exists, otherwise, None
        """
        if not recursive:
            return self.get_value(val_name)

        else:
            key = self._traverse_subkeys(lambda x: val_name in x.values)
            if not key:
                return None
            else:
                return key.values[val_name]


class RegistryError(Exception):
    """RunTime Error concerning the Windows Registry"""


class InvalidKeyError(RegistryError):
    """Runtime Error describing issue with invalid key access to Windows registry"""

    def __init__(self, key):
        message = f"Cannot query invalid key: {key}"
        super().__init__(message)


class InvalidRegistryOperation(RegistryError):
    """A Runtime Error encountered when a registry operation is invalid for
    an indeterminate reason"""

    def __init__(self, name, e, *args, **kwargs):
        message = (
            f"Windows registry operations: {name} encountered error: {str(e)}"
            "\nMethod invoked with parameters:\n"
        )
        message += "\n\t".join([f"{k}:{v}" for k, v in kwargs.items()])
        message += "\n"
        # str(): positional arguments are not always strings, e.g. the index passed by
        # EnumKey and EnumValue
        message += "\n\t".join(str(arg) for arg in args)
        super().__init__(message)
