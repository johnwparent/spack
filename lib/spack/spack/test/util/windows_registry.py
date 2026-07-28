# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""Tests for ``util/windows_registry.py``.

These exercise the module against a fake ``winreg`` rather than the real registry, so that
the concurrent-modification races and transient failures the module is built to absorb can
be reproduced deterministically.
"""

import sys

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only tests", allow_module_level=True)

import spack.util.windows_registry as wr
from spack.util.windows_registry import (
    ERROR_ACCESS_DENIED,
    ERROR_FILE_NOT_FOUND,
    ERROR_NO_MORE_ITEMS,
    HKEY,
    InvalidRegistryOperation,
    WindowsRegistryView,
)

#: An error code winreg reports for indeterminate, potentially transient conditions
ERROR_NO_SYSTEM_RESOURCES = 1450


def win_error(winerror, message="fake registry error"):
    """Build an OSError carrying a winerror, the way the winreg module does.

    CPython picks the OSError subclass from the winerror, so code 2 arrives as
    FileNotFoundError and code 5 as PermissionError, matching real winreg.
    """
    return OSError(0, message, None, winerror)


class FakeKey:
    def __init__(self, subkeys=None, values=None, denied=False):
        self.subkeys = dict(subkeys or {})
        self.values = dict(values or {})
        self.denied = denied


class FakeHandle:
    """Stands in for a winreg PyHKEY, so handle lifetime is observable from tests"""

    def __init__(self, registry, path):
        self.registry = registry
        self.path = path
        self.closed = False

    def Close(self):
        self.closed = True
        self.registry.open_handles.discard(self)


class FakeWinreg:
    """Minimal in-memory stand-in for the winreg module.

    Records every operation in ``calls`` and can be told to fail specific operations a set
    number of times via ``faults``, keyed by ``(op, path, arg)``.
    """

    KEY_READ = 0x20019
    HKEY_LOCAL_MACHINE = "HKEY_LOCAL_MACHINE"

    def __init__(self, root):
        self.root = root
        self.calls = []
        self.faults = {}
        self.open_handles = set()
        self.peak_open_handles = 0

    # -- test-facing helpers ------------------------------------------------------------

    def fail(self, op, path, arg, codes):
        """Make ``op`` raise each of ``codes`` in turn before behaving normally"""
        self.faults[(op, path, arg)] = list(codes)

    def call_count(self, op, path, arg):
        return self.calls.count((op, path, arg))

    # -- internals ----------------------------------------------------------------------

    def _path_of(self, handle):
        if handle == self.HKEY_LOCAL_MACHINE:
            return ()
        if handle.closed:
            raise win_error(wr.ERROR_INVALID_HANDLE, "handle is closed")
        return handle.path

    def _key_at(self, path):
        key = self.root
        for part in path:
            key = key.subkeys[part]
        return key

    def _record(self, op, path, arg):
        self.calls.append((op, path, arg))
        pending = self.faults.get((op, path, arg))
        if pending:
            raise win_error(pending.pop(0))

    def _new_handle(self, path):
        handle = FakeHandle(self, path)
        self.open_handles.add(handle)
        self.peak_open_handles = max(self.peak_open_handles, len(self.open_handles))
        return handle

    # -- winreg surface -----------------------------------------------------------------

    def OpenKeyEx(self, handle, subname, access=None):
        path = self._path_of(handle)
        self._record("OpenKeyEx", path, subname)
        parent = self._key_at(path)
        if subname not in parent.subkeys:
            raise win_error(ERROR_FILE_NOT_FOUND)
        if parent.subkeys[subname].denied:
            raise win_error(ERROR_ACCESS_DENIED)
        return self._new_handle(path + (subname,))

    def QueryInfoKey(self, handle):
        path = self._path_of(handle)
        self._record("QueryInfoKey", path, None)
        key = self._key_at(path)
        return (len(key.subkeys), len(key.values), 0)

    def EnumKey(self, handle, index):
        path = self._path_of(handle)
        self._record("EnumKey", path, index)
        names = list(self._key_at(path).subkeys)
        if index >= len(names):
            raise win_error(ERROR_NO_MORE_ITEMS)
        return names[index]

    def EnumValue(self, handle, index):
        path = self._path_of(handle)
        self._record("EnumValue", path, index)
        items = list(self._key_at(path).values.items())
        if index >= len(items):
            raise win_error(ERROR_NO_MORE_ITEMS)
        name, data = items[index]
        return (name, data, 1)

    def QueryValueEx(self, handle, name):
        path = self._path_of(handle)
        self._record("QueryValueEx", path, name)
        values = self._key_at(path).values
        if name not in values:
            raise win_error(ERROR_FILE_NOT_FOUND)
        return (values[name], 1)


def flat_tree(count=10, denied=()):
    """A single key "Base" holding ``count`` numbered subkeys, each with one value"""
    subkeys = {
        f"Sub{i}": FakeKey(values={"Where": f"C:\\{i}"}, denied=(f"Sub{i}" in denied))
        for i in range(count)
    }
    return FakeKey(subkeys={"Base": FakeKey(subkeys=subkeys)})


@pytest.fixture
def fake_winreg(monkeypatch):
    """Install a fake winreg and hand the test a factory for building registry contents"""

    def install(root):
        registry = FakeWinreg(root)
        monkeypatch.setattr(wr, "winreg", registry)
        # The HKEY constants are module-level singletons that cache their handle and any
        # enumerated children, so reset them between tests
        for constant in vars(HKEY).values():
            if isinstance(constant, wr._HKEY_CONSTANT):
                constant._handle = None
                constant._keys = None
                constant._values = None
        return registry

    # Backoff is already tiny, but sleeping at all makes the retry tests needlessly slow
    monkeypatch.setattr(wr.Retry, "sleep", lambda self: None)
    return install


def view(key="Base"):
    return WindowsRegistryView(key, root_key=HKEY.HKEY_LOCAL_MACHINE)


def test_enumeration_stops_when_subkeys_vanish_mid_walk(fake_winreg):
    """A key removed after enumeration starts ends the walk instead of failing it.

    QueryInfoKey's count is only a hint: this is the race the old count-driven loop turned
    into an InvalidRegistryOperation that discarded the whole lookup.
    """
    registry = fake_winreg(flat_tree(count=10))
    registry.fail("EnumKey", ("Base",), 3, [ERROR_NO_MORE_ITEMS])

    names = [k.name for k in view().get_subkeys()]

    assert names == ["Sub0", "Sub1", "Sub2"]


def test_enumeration_finds_values_added_after_a_count_would_have_been_taken(fake_winreg):
    """Enumerating to exhaustion also picks up entries a stale count would have missed"""
    registry = fake_winreg(FakeKey(subkeys={"Base": FakeKey(values={"A": "1", "B": "2"})}))

    values = view().get_values()

    assert sorted(values) == ["A", "B"]
    # No count was consulted; the walk is driven purely by the registry reporting exhaustion
    assert registry.call_count("QueryInfoKey", ("Base",), None) == 0


def test_transient_failure_retries_only_the_failed_operation(fake_winreg):
    """The core of this change: a flaky call costs one more call, not the whole lookup."""
    registry = fake_winreg(flat_tree(count=5))
    registry.fail("EnumKey", ("Base",), 2, [ERROR_NO_SYSTEM_RESOURCES, ERROR_NO_SYSTEM_RESOURCES])

    names = [k.name for k in view().get_subkeys()]

    assert names == [f"Sub{i}" for i in range(5)]
    # Three attempts at the operation that failed
    assert registry.call_count("EnumKey", ("Base",), 2) == 3
    # and the operations that already succeeded were not repeated
    assert registry.call_count("EnumKey", ("Base",), 0) == 1
    assert registry.call_count("EnumKey", ("Base",), 1) == 1


def test_retry_exhaustion_reports_a_readable_error(fake_winreg):
    """Once retries run out the error is wrapped, and building that message must not crash.

    EnumKey passes an int index, which the old reporting path tried to str.join directly.
    """
    registry = fake_winreg(flat_tree(count=3))
    registry.fail("EnumKey", ("Base",), 0, [ERROR_NO_SYSTEM_RESOURCES] * 5)

    with pytest.raises(InvalidRegistryOperation) as exc_info:
        view().get_subkeys()

    message = str(exc_info.value)
    assert "EnumKey" in message
    assert registry.call_count("EnumKey", ("Base",), 0) == 3


def test_access_denied_propagates_without_consuming_retries(fake_winreg):
    registry = fake_winreg(flat_tree(count=3))
    registry.fail("EnumKey", ("Base",), 0, [ERROR_ACCESS_DENIED] * 5)

    with pytest.raises(PermissionError):
        view().get_subkeys()

    assert registry.call_count("EnumKey", ("Base",), 0) == 1


def test_missing_item_does_not_consume_retries(fake_winreg):
    """The view swallows "does not exist" by design; the point here is that it is terminal"""
    registry = fake_winreg(flat_tree(count=3))
    registry.fail("EnumKey", ("Base",), 0, [ERROR_FILE_NOT_FOUND] * 5)

    assert view().get_subkeys() is None
    assert registry.call_count("EnumKey", ("Base",), 0) == 1


def test_unreadable_subkeys_are_dropped_from_enumeration(fake_winreg):
    """Access-denied keys stay silently omitted, as callers have always relied on"""
    fake_winreg(flat_tree(count=4, denied=("Sub1", "Sub2")))

    assert [k.name for k in view().get_subkeys()] == ["Sub0", "Sub3"]


def test_subkey_deleted_between_enumeration_and_open_is_dropped(fake_winreg):
    registry = fake_winreg(flat_tree(count=3))
    registry.fail("OpenKeyEx", ("Base",), "Sub1", [ERROR_FILE_NOT_FOUND])

    assert [k.name for k in view().get_subkeys()] == ["Sub0", "Sub2"]


def test_repeated_traversal_returns_the_same_result(fake_winreg):
    """Regression: the BFS used to extend the root key's own cached child list in place"""
    fake_winreg(
        FakeKey(
            subkeys={
                "Base": FakeKey(
                    subkeys={
                        "Alpha": FakeKey(subkeys={"Target": FakeKey()}),
                        "Beta": FakeKey(subkeys={"Target": FakeKey()}),
                    }
                )
            }
        )
    )
    reg = view()

    first = [k.path for k in reg.find_subkeys("Target")]
    second = [k.path for k in reg.find_subkeys("Target")]

    assert first == second
    assert len(first) == 2


def test_empty_key_is_enumerated_once(fake_winreg):
    """A key with no subkeys must cache that fact rather than re-enumerating every access"""
    registry = fake_winreg(FakeKey(subkeys={"Base": FakeKey()}))
    reg = view()

    assert reg.get_subkeys() == []
    assert reg.get_subkeys() == []

    assert registry.call_count("EnumKey", ("Base",), 0) == 1


def test_recursive_search_releases_handles_as_it_goes(fake_winreg):
    """A recursive walk must not end up holding a handle for every key in the subtree.

    Keys are opened once each, which is the floor while unreadable keys are dropped during
    enumeration, but a key's handle is released as soon as the walk is done with it.
    """
    depth_three = FakeKey(
        subkeys={
            "Base": FakeKey(
                subkeys={
                    f"Mid{i}": FakeKey(subkeys={f"Leaf{i}{j}": FakeKey() for j in range(4)})
                    for i in range(4)
                }
            )
        }
    )
    registry = fake_winreg(depth_three)

    found = view().find_subkeys(r"Leaf1.*")

    assert sorted(k.name for k in found) == ["Leaf10", "Leaf11", "Leaf12", "Leaf13"]
    # 20 keys in the subtree, opened once each: no key is opened twice
    assert len([c for c in registry.calls if c[0] == "OpenKeyEx"]) == 21
    # Only the four matches, plus the view's own root key, are still holding a handle
    assert len(registry.open_handles) == 5
    # and the walk never held one per key in the subtree
    assert registry.peak_open_handles < 20


def test_released_key_reopens_transparently_on_use(fake_winreg):
    """A key whose handle was released is still usable; it reopens through its parent"""
    registry = fake_winreg(flat_tree(count=3))

    key = view().find_subkey("Sub1")
    key.close()
    opens_before_use = registry.call_count("OpenKeyEx", ("Base",), "Sub1")

    assert key.values["Where"].value == "C:\\1"
    assert registry.call_count("OpenKeyEx", ("Base",), "Sub1") == opens_before_use + 1


def test_get_subkey_raises_immediately_for_a_missing_key(fake_winreg):
    """Explicit lookups stay eager: _load_key and the VS scan both depend on this"""
    fake_winreg(flat_tree(count=2))

    with pytest.raises(FileNotFoundError):
        view().reg.get_subkey("Nope")

    # _load_key builds the view's validity on that eager raise
    assert not WindowsRegistryView("Absent", root_key=HKEY.HKEY_LOCAL_MACHINE)


def test_get_matching_subkeys_returns_matches(fake_winreg):
    """Regression: this used to compute its result and then discard it"""
    fake_winreg(flat_tree(count=12))

    matched = view().get_matching_subkeys(r"Sub1[0-9]")

    assert sorted(k.name for k in matched) == ["Sub10", "Sub11"]
