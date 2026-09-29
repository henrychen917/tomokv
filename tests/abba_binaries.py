#!/usr/bin/env python3
"""Campaign-owned binary snapshots, hard-link aliases and disk-space preflight.

Copy external inputs once with a fresh mtime. Never fall back to copying a cell
alias: all phases must live on the campaign filesystem. The digest is recorded
in one immutable manifest; every cell verifies both inode identity and bytes.
This is independent of external retention policy (mtime is not run liveness).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys


DISK_GUARD_FLOOR = 40 * 1024**3  # /home/user/Projects/{ops/,}disk-guard.sh
# Controls + calibration + null + holdout, including retained receipt copies.
# A budget, not a claim to have measured the new campaign. Check free space
# again before every cell because other writers can consume this reservation.
ARTIFACT_RESERVE = 1536 * 1024**2
MANIFEST = "binaries.json"


class BinaryGuardError(RuntimeError):
    pass


def fail(path, reason):
    raise BinaryGuardError(
        f"ABBA binary guard: {reason}: {path}; external prune/disk guard must preserve "
        "live campaign files, regardless of source mtime. Retain this failed run; "
        "do not recreate a missing snapshot or retry it into a pass.")


def executable(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(path, "missing executable")
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        fail(path, "not a regular executable")
    return info


def identity(info):
    return dict(device=info.st_dev, inode=info.st_ino, size=info.st_size,
                mode=stat.S_IMODE(info.st_mode), mtime_ns=info.st_mtime_ns)


def digest(path):
    value = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
    except FileNotFoundError:
        fail(path, "missing executable")
    return value.hexdigest()


def space_check(directory, sources=(), *, artifacts=ARTIFACT_RESERVE):
    """Require the *remaining* free bytes to be strictly above the guard floor."""
    unique = {}
    for source in sources:
        info = executable(Path(source).resolve())
        unique[info.st_dev, info.st_ino] = info.st_size
    footprint = sum(unique.values()) + artifacts
    usage = shutil.disk_usage(directory)
    result = dict(path=str(Path(directory).resolve()), free_bytes=usage.free,
                  binary_bytes=sum(unique.values()), artifact_reserve_bytes=artifacts,
                  footprint_bytes=footprint, disk_guard_floor_bytes=DISK_GUARD_FLOOR,
                  remaining_bytes=usage.free - footprint)
    if result["remaining_bytes"] <= DISK_GUARD_FLOOR:
        raise BinaryGuardError(
            f"ABBA disk-space guard: {directory}: free={usage.free} bytes, "
            f"campaign footprint={footprint} bytes (binaries={sum(unique.values())}, "
            f"artifacts={artifacts}); remaining={result['remaining_bytes']} bytes "
            f"would reach the disk guard floor={DISK_GUARD_FLOOR} bytes (40 GiB). "
            "No binary staging or measurement may start; free space outside live runs first.")
    return result


class BinaryStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / MANIFEST
        try:
            self.raw = self.path.read_bytes()
        except FileNotFoundError:
            fail(self.path, "missing campaign manifest")
        self.manifest = json.loads(self.raw)
        if self.manifest.get("schema") != 1 or not self.manifest.get("arms"):
            fail(self.path, "invalid campaign manifest")

    @classmethod
    def create(cls, root, sources):
        root = Path(root).resolve()
        # Existing files are never refreshed: a disappeared snapshot is a failure.
        if (root / MANIFEST).exists() or any((root / f"binary-{arm}").exists() for arm in sources):
            raise FileExistsError(f"campaign snapshots already exist in {root}")
        rows, copied = {}, {}
        for arm, source in sources.items():
            if arm not in ("A", "B"):
                raise ValueError(f"unknown binary arm: {arm}")
            source = Path(source).resolve()
            before = executable(source)
            dest = root / f"binary-{arm}"
            key = before.st_dev, before.st_ino
            if key in copied:
                first = copied[key]
                os.link(root / f"binary-{first}", dest)
                checksum = rows[first]["sha256"]
            else:
                # Deliberately do not preserve timestamps or link an external
                # build output that a later linker/in-place writer could mutate.
                checksum = hashlib.sha256()
                with source.open("rb") as src, dest.open("xb") as dst:
                    for block in iter(lambda: src.read(1024 * 1024), b""):
                        dst.write(block)
                        checksum.update(block)
                after = executable(source)
                if identity(before) != identity(after) or before.st_ctime_ns != after.st_ctime_ns:
                    fail(source, "source changed while freezing")
                dest.chmod(stat.S_IMODE(before.st_mode))
                checksum = checksum.hexdigest()
                copied[key] = arm
            rows[arm] = dict(source=str(source), sha256=checksum, **identity(executable(dest)))
        with (root / MANIFEST).open("x") as stream:
            json.dump(dict(schema=1, arms=rows), stream, indent=2)
            stream.write("\n")
        return cls(root)

    def verify(self, arm, alias=None, *, full=True):
        try:
            if self.path.read_bytes() != self.raw:
                fail(self.path, "campaign manifest changed")
        except FileNotFoundError:
            fail(self.path, "missing campaign manifest")
        path = self.root / f"binary-{arm}"
        row = self.manifest["arms"].get(arm)
        if row is None:
            fail(path, "arm absent from campaign manifest")
        info = executable(path)
        if identity(info) != {key: row[key] for key in identity(info)}:
            fail(path, "snapshot inode/metadata differs from frozen manifest")
        if alias is not None:
            other = executable(Path(alias))
            if (other.st_dev, other.st_ino) != (info.st_dev, info.st_ino):
                fail(alias, "alias is not a hard link to the campaign snapshot")
        if full and digest(path) != row["sha256"]:
            fail(path, "snapshot digest differs from frozen manifest")
        if identity(executable(path)) != identity(info):
            fail(path, "snapshot changed during verification")
        return row["sha256"]

    def aliases(self, out, sources):
        binaries = {}
        for arm, source in sources.items():
            checksum = self.verify(arm)
            if digest(Path(source).resolve()) != checksum:
                fail(source, f"requested {arm} bytes differ from campaign snapshot")
            path, alias = self.root / f"binary-{arm}", Path(out) / f"binary-{arm}"
            if alias != path:
                try:
                    os.link(path, alias)
                except OSError as error:
                    fail(alias, f"cannot hard-link campaign snapshot ({error}); copying is forbidden")
            self.verify(arm, alias, full=False)
            binaries[arm] = alias
        return binaries

    def binding(self):
        return dict(path=str(self.path), sha256=hashlib.sha256(self.raw).hexdigest())

    def start(self, children, argv, log, folder, arm):
        """Pin the checked inode across taskset's exec: an unlink cannot yield 127.

        The caller records the logical argv with the retained binary path. Only
        launch substitutes an inherited descriptor; no server bytes/options change.
        The normal post-window check still fails a cell if a name was pruned.
        """
        alias = Path(argv[3])  # taskset -c CPU-LIST EXECUTABLE ...
        self.verify(arm, alias, full=False)
        try:
            fd = os.open(alias, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            fail(alias, "missing executable before exec")
        try:
            row = self.manifest["arms"][arm]
            if identity(os.fstat(fd)) != {key: row[key] for key in identity(os.fstat(fd))}:
                fail(alias, "executable changed before exec")
            command = [*argv[:3], f"/proc/self/fd/{fd}", *argv[4:]]
            return children.start(command, log, folder, pass_fds=(fd,))
        finally:
            os.close(fd)


def stage(args, out, sources, report):
    root = getattr(args, "binary_store", None)
    if root is None:
        report["space_preflight"] = space_check(out, sources.values())
    store = BinaryStore(root) if root is not None else BinaryStore.create(out, sources)
    binaries = store.aliases(out, sources)
    report["binary_store"] = store.binding()
    return store, binaries


def self_test():
    import contextlib
    import errno
    import io
    import tempfile
    import unittest
    from unittest import mock
    from types import SimpleNamespace
    import abbagate as abba
    from gate_receipt import object_file

    class Controls(unittest.TestCase):
        def setUp(self):
            root = Path(__file__).resolve().parents[1] / "build"
            root.mkdir(exist_ok=True)
            temporary = tempfile.TemporaryDirectory(dir=root)
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name)
            self.source = self.root / "source"
            self.source.write_bytes(b"identity fixture; never execute this file")
            self.source.chmod(0o755)
            self.run = self.root / "run"
            self.run.mkdir()
            self.sources = dict(A=self.source, B=self.source)

        def freeze(self):
            return BinaryStore.create(self.run, self.sources)

        def test_181_cells_and_all_phases_share_one_copy_and_receipt_identity(self):
            store = self.freeze()
            canonical = self.run / "binary-A"
            self.assertFalse(os.path.samefile(canonical, self.source))
            self.assertTrue(os.path.samefile(canonical, self.run / "binary-B"))
            before = store.path.read_bytes()
            inodes = set()
            for phase in ("reorder-controls", "calibration", "null", "holdout"):
                for n in range(181):
                    folder = self.run / phase / f"cell-{n}"
                    folder.mkdir(parents=True)
                    guard, binaries = stage(SimpleNamespace(binary_store=self.run), folder,
                                            self.sources, {})
                    for arm, alias in binaries.items():
                        guard.verify(arm, alias)
                        info = alias.stat()
                        inodes.add((info.st_dev, info.st_ino))
                        self.assertEqual(object_file(alias), ("100755", digest(self.source)))
            self.assertEqual(len(inodes), 1)
            self.assertEqual(store.path.read_bytes(), before)

        def test_distinct_arms_copy_once_each(self):
            second = self.root / "second"
            second.write_bytes(b"different identity fixture")
            second.chmod(0o755)
            self.sources["B"] = second
            store = self.freeze()
            self.assertNotEqual(store.verify("A"), store.verify("B"))
            self.assertFalse(os.path.samefile(self.run / "binary-A", self.run / "binary-B"))

        def test_old_source_mtime_not_inherited_and_source_rewrite_is_isolated(self):
            os.utime(self.source, (1, 1))
            store = self.freeze()
            checksum = store.verify("A")
            self.assertGreater((self.run / "binary-A").stat().st_mtime, 1)
            self.source.write_bytes(b"later build")
            self.assertEqual(store.verify("A"), checksum)

        def test_alias_must_be_hard_link_even_if_copy_has_identical_bytes(self):
            store = self.freeze()
            alias = self.root / "copy"
            shutil.copyfile(self.run / "binary-A", alias)
            alias.chmod(0o755)
            with self.assertRaisesRegex(BinaryGuardError, "not a hard link"):
                store.verify("A", alias)

        def test_cross_filesystem_alias_refuses_instead_of_copying(self):
            store = self.freeze()
            folder = self.root / "cell"
            folder.mkdir()
            with mock.patch.object(os, "link", side_effect=OSError(errno.EXDEV, "cross-device")):
                with self.assertRaisesRegex(BinaryGuardError, "copying is forbidden"):
                    store.aliases(folder, self.sources)
            self.assertEqual(list(folder.iterdir()), [])

        def test_deleted_snapshot_is_not_recreated_from_surviving_alias(self):
            store = self.freeze()
            folder = self.root / "cell"
            folder.mkdir()
            binaries = store.aliases(folder, self.sources)
            missing = self.run / "binary-B"
            missing.unlink()
            with self.assertRaisesRegex(BinaryGuardError, f"missing executable: {missing}.*disk guard"):
                store.verify("B", binaries["B"])
            self.assertTrue(binaries["B"].exists())
            self.assertFalse(missing.exists())

        def test_deleted_alias_and_manifest_name_the_missing_path(self):
            store = self.freeze()
            folder = self.root / "cell"
            folder.mkdir()
            alias = store.aliases(folder, self.sources)["A"]
            alias.unlink()
            with self.assertRaisesRegex(BinaryGuardError, f"missing executable: {alias}"):
                store.verify("A", alias)
            store.path.unlink()
            with self.assertRaisesRegex(BinaryGuardError, f"missing campaign manifest: {store.path}"):
                store.verify("A")

        def test_inode_replacement_and_preserved_mtime_corruption_fail(self):
            store = self.freeze()
            path = self.run / "binary-A"
            before = path.stat()
            original = path.read_bytes()
            path.write_bytes(b"x" * len(original))
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            with self.assertRaisesRegex(BinaryGuardError, "digest differs"):
                store.verify("A")
            path.unlink()
            path.write_bytes(original)
            path.chmod(0o755)
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            with self.assertRaisesRegex(BinaryGuardError, "inode/metadata differs"):
                store.verify("A")

        def test_changed_source_or_manifest_refuses_reuse(self):
            store = self.freeze()
            self.source.write_bytes(b"other build")
            with self.assertRaisesRegex(BinaryGuardError, "requested A bytes differ"):
                store.aliases(self.root, self.sources)
            store.path.write_bytes(store.raw + b" ")
            with self.assertRaisesRegex(BinaryGuardError, "manifest changed"):
                store.verify("A")

        def test_space_boundary_includes_payload_once_and_rejects_equality(self):
            footprint = self.source.stat().st_size + ARTIFACT_RESERVE
            for slack in (-1, 0, 1):
                with self.subTest(slack=slack), mock.patch.object(shutil, "disk_usage",
                        return_value=SimpleNamespace(free=DISK_GUARD_FLOOR + footprint + slack)):
                    if slack <= 0:
                        with self.assertRaisesRegex(BinaryGuardError, "footprint=.*disk guard floor="):
                            space_check(self.run, self.sources.values())
                    else:
                        budget = space_check(self.run, self.sources.values())
                        self.assertEqual(budget["footprint_bytes"], footprint)

        def test_cli_low_space_stops_before_any_snapshot_or_manifest(self):
            argv = ["abba_binaries.py", "--run", str(self.run), "--candidate", str(self.source)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(shutil, "disk_usage",
                    return_value=SimpleNamespace(free=DISK_GUARD_FLOOR)), \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(), 1)
            self.assertIn("No binary staging or measurement may start", output.getvalue())
            self.assertEqual(list(self.run.iterdir()), [])

        def test_deleted_binary_fails_real_measure_before_any_child_or_control(self):
            store = self.freeze()
            args = SimpleNamespace(server_cores="112", server_smt="", load_cores="113", load_smt="")
            children = mock.Mock()
            runner = abba.Runner(args, self.run, {"B": self.run / "binary-B"}, children)
            runner.binary_store = store
            cell = abba.Cell("t06", "1s", 1, 0, 0, "REORDER", 8, 512)
            runner.verify_binary(cell, "B")  # Cell digest already checked: check again before boot.
            runner.binaries["B"].unlink()
            with self.assertRaisesRegex(BinaryGuardError, "binary-B.*disk guard"):
                runner.measure(cell, "B", 1, 16, {})
            children.start.assert_not_called()

        def test_unlink_between_check_and_taskset_exec_keeps_open_inode_then_fails_guard(self):
            store = self.freeze()
            alias = self.run / "binary-B"
            closed = []
            def start(argv, log, cwd, *, pass_fds):
                fd, = pass_fds
                closed.append(fd)
                alias.unlink()  # The external prune hits the exec window.
                self.assertEqual(Path(argv[3]).read_bytes(), self.source.read_bytes())
                self.assertEqual(os.fstat(fd).st_ino, store.manifest["arms"]["B"]["inode"])
                return "mock child; no server started"
            result = store.start(SimpleNamespace(start=start), ["taskset", "-c", "112", alias],
                                 self.run / "server.log", self.run, "B")
            self.assertEqual(result, "mock child; no server started")
            with self.assertRaises(OSError):
                os.fstat(closed[0])
            with self.assertRaisesRegex(BinaryGuardError, "missing executable.*binary-B"):
                store.verify("B")

        def test_descriptor_is_closed_when_child_launch_fails(self):
            store = self.freeze()
            opened = []
            def start(argv, log, cwd, *, pass_fds):
                opened.extend(pass_fds)
                raise OSError("injected launch failure")
            with self.assertRaisesRegex(OSError, "injected launch failure"):
                store.start(SimpleNamespace(start=start), ["taskset", "-c", "112", self.run / "binary-B"],
                            self.run / "server.log", self.run, "B")
            with self.assertRaises(OSError):
                os.fstat(opened[0])

        def test_real_taskset_exec_survives_unlink_with_harmless_true_fixture(self):
            # Exercise pass_fds through the actual child launcher. This is only
            # /usr/bin/true, never a server, generator or measurement.
            self.source.write_bytes(Path(shutil.which("true")).read_bytes())
            store = self.freeze()
            alias = self.run / "binary-B"
            class UnlinkingChildren(abba.Children):
                def start(child_self, argv, log, cwd, *, pass_fds=()):
                    alias.unlink()
                    return super().start(argv, log, cwd, pass_fds=pass_fds)
            children = UnlinkingChildren()
            self.addCleanup(children.close)
            cpu = str(min(os.sched_getaffinity(0)))
            process = store.start(children, ["taskset", "-c", cpu, alias],
                                  self.run / "true.log", self.run, "B")
            self.assertEqual(process.wait(timeout=10), 0)
            children.stop(process)
            self.assertEqual(children.active, [])
            with self.assertRaisesRegex(BinaryGuardError, "missing executable.*binary-B"):
                store.verify("B")

        def test_each_cell_hashes_once_and_each_boot_rechecks_identity(self):
            store = self.freeze()
            args = SimpleNamespace(server_cores="112", server_smt="", load_cores="113", load_smt="")
            runner = abba.Runner(args, self.run, {"B": self.run / "binary-B"}, None)
            runner.binary_store = store
            with mock.patch.object(store, "verify", wraps=store.verify) as check:
                for name in ("t05", "t06"):
                    cell = abba.Cell(name, "1s", 1, 0, 0, "REORDER", 8, 512)
                    for _ in range(3):
                        runner.verify_binary(cell, "B")
            self.assertEqual([call.kwargs["full"] for call in check.call_args_list],
                             [True, False, False, True, False, False])

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls))
    return 0 if result.wasSuccessful() else 1


def main():
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    sources = {"A": args.reference or args.candidate, "B": args.candidate}
    try:
        # RUN must exist and be fresh; do not touch any binary before this check.
        budget = space_check(args.run, sources.values())
        store = BinaryStore.create(args.run, sources)
        budget["binary_store"] = store.binding()
        (args.run / "space-preflight.json").write_text(json.dumps(budget, indent=2) + "\n")
        print(json.dumps(budget, indent=2))
    except (OSError, ValueError, BinaryGuardError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
