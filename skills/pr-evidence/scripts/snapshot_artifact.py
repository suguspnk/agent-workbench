#!/usr/bin/env python3
"""Copy one untrusted artifact into a bounded private snapshot without following links."""

from __future__ import annotations

import os
import stat
import sys


CHUNK_BYTES = 1024 * 1024


def fail() -> None:
    print("Artifact could not be safely snapshotted.", file=sys.stderr)
    raise SystemExit(2)


def main() -> None:
    if len(sys.argv) != 4:
        fail()
    source_path, snapshot_path, limit_text = sys.argv[1:]
    try:
        limit = int(limit_text)
    except ValueError:
        fail()
    if limit <= 0 or not hasattr(os, "O_NOFOLLOW"):
        fail()

    source_fd = -1
    snapshot_fd = -1
    created = False
    succeeded = False
    try:
        source_fd = os.open(
            source_path,
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or before.st_size > limit:
            fail()

        snapshot_fd = os.open(
            snapshot_path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        created = True
        copied = 0
        while True:
            chunk = os.read(source_fd, min(CHUNK_BYTES, limit + 1 - copied))
            if not chunk:
                break
            copied += len(chunk)
            if copied > limit:
                fail()
            view = memoryview(chunk)
            while view:
                written = os.write(snapshot_fd, view)
                if written <= 0:
                    fail()
                view = view[written:]

        after = os.fstat(source_fd)
        before_fields = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_fields = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_fields != after_fields or copied != before.st_size:
            fail()

        os.fchmod(snapshot_fd, 0o600)
        os.fsync(snapshot_fd)
        snapshot = os.fstat(snapshot_fd)
        if not stat.S_ISREG(snapshot.st_mode) or snapshot.st_size != copied:
            fail()
        succeeded = True
    except (OSError, OverflowError):
        fail()
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if snapshot_fd >= 0:
            os.close(snapshot_fd)
        if created and not succeeded:
            try:
                os.unlink(snapshot_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
