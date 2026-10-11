"""Isolated native-worker death retry; not original-client runtime acceptance."""
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "death_retry_support", ROOT / "tests/SocialRegression/test_native_social.py")
support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(support)


class DeathRetryWireTests(unittest.TestCase):
    def test_three_death_retries_retain_partial_hp_and_mp(self):
        port = None
        for candidate in range(58100, 59000, 10):
            reserved = []
            try:
                for value in range(candidate, candidate + 9):
                    item = socket.socket()
                    reserved.append(item)
                    item.bind(("127.0.0.1", value))
                port = candidate
                break
            except OSError:
                pass
            finally:
                for item in reserved:
                    item.close()
        self.assertIsNotNone(port)
        with tempfile.TemporaryDirectory(prefix="nanaimo-death-retry-wire-") as directory:
            work = Path(directory)
            bridge = work / "bridge.exe"
            subprocess.run([str(ROOT / "tools/tcc/tcc.exe"), "-I", str(ROOT),
                            str(ROOT / "adapter/nanaimo_gameplay_bridge.c"), "-o", str(bridge)],
                           check=True, capture_output=True, timeout=120)
            profile = work / "profile.ini"
            profile.write_text("version=2\nname_hex=5265747279\nlevel=1\npet=0\n"
                               "hp_max=100\nhp_current=100\nmp_max=500\nmp_current=123\n",
                               encoding="ascii")
            connection = None
            with (work / "native.log").open("wb") as output:
                process = subprocess.Popen(
                    [str(bridge), str(port + 8), "0", "0", "0", str(profile), str(port)],
                    cwd=work, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    for _ in range(100):
                        try:
                            connection = socket.create_connection(("127.0.0.1", port), timeout=2)
                            break
                        except OSError:
                            time.sleep(.05)
                    self.assertIsNotNone(connection)
                    connection.settimeout(5)

                    def exchange(opcode, payload, reply):
                        connection.sendall(support.frame(opcode, payload))
                        return support.receive(connection, reply)

                    def resources():
                        state = exchange(0xF101, b"", 0xF102)
                        return struct.unpack_from("<I", state, 28)[0], struct.unpack_from("<I", state, 36)[0]

                    state = bytearray(support.seed(11, 0))
                    for offset, value in {16: 100, 20: 100, 24: 500, 28: 123, 60: 0}.items():
                        struct.pack_into("<I", state, offset, value)
                    exchange(0xF100, state, 0xF102)
                    exchange(0xCF6C, bytes(32), 0xCF6D)
                    for opcode, payload, reply in [
                        (0xC587, b"", 0xC588), (0xCF70, bytes(4), 0xCF71),
                        (0xCFEB, bytes(4), 0xCFEC), (0xCFD3, b"", 0xCFD4),
                        (0xCFD5, struct.pack("<I", 1), 0xCFD6), (0xCF7F, b"", 0xCF80)]:
                        exchange(opcode, payload, reply)
                    for cycle in range(3):
                        exchange(0xD014, struct.pack("<HHHBB", 20, 0, cycle, 12, 11), 0xD015)
                        self.assertEqual(resources(), (0, 123))
                        exchange(0xCF87, struct.pack("<HH", 123, 0), 0xCF88)
                        exchange(0xCF8B, bytes([0, 0, 1, 0]), 0xCF8C)
                        self.assertEqual(resources(), (16, 123))
                        exchange(0xC587, b"", 0xC588)
                        roster = exchange(0xCF70, bytes(4), 0xCF71)
                        self.assertEqual(struct.unpack_from("<HH", roster, 0x4E), (16, 123))
                        exchange(0xCFEB, bytes(4), 0xCFEC)
                        self.assertEqual(resources(), (16, 123))
                        exchange(0xCFD3, b"", 0xCFD4)
                        exchange(0xCFD5, struct.pack("<I", 1), 0xCFD6)
                        exchange(0xCF7F, b"", 0xCF80)
                        self.assertEqual(resources(), (16, 123))
                except Exception:
                    output.flush()
                    print((work / "native.log").read_text("utf-8", errors="replace")[-12000:])
                    raise
                finally:
                    if connection is not None:
                        connection.close()
                    process.terminate()
                    process.wait(timeout=10)
                    output.flush()
                    if "NANAIMO_DEATH_RETRY_EVIDENCE" in os.environ:
                        shutil.copyfile(work / "native.log", os.environ["NANAIMO_DEATH_RETRY_EVIDENCE"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
