import os
import tempfile
import unittest

from smsrio import firmware


class FirmwareTest(unittest.TestCase):
    def test_missing_image(self):
        with self.assertRaises(FileNotFoundError):
            firmware.load(os.path.join(tempfile.gettempdir(), "absent-rio.inp"))

    def test_wrong_image(self):
        handle, path = tempfile.mkstemp(suffix=".inp")
        os.close(handle)
        with open(path, "wb") as output:
            output.write(b"\x00" * 128)
        try:
            with self.assertRaises(ValueError):
                firmware.load(path)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
