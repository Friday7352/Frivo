from .download import checksum


def crc32c_file(path):
    with open(path, "rb") as f:
        return checksum(f.read())
