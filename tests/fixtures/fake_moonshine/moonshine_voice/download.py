import base64
import os
import zlib

# The test sets FAKE_MOONSHINE_URL to its own little server, and the file
# bodies are made from their names, so the test can serve exactly these.
FILES = ["encoder.ort", "decoder_kv.ort", "tokenizer.bin", "streaming_config.json"]


def body(arch, name):
    return (f"{int(arch)}:{name}:" * 4000).encode()


def checksum(data):
    return base64.b64encode(zlib.crc32(data).to_bytes(4, "big")).decode()


def find_model_info(language="en", model_arch=None):
    return {"model_arch": model_arch, "language": language,
            "download_url": f"{os.environ.get('FAKE_MOONSHINE_URL', '')}/model/{int(model_arch)}"}


def _primary_stt_group(model_info, include_word_timestamps=False):
    base = model_info["download_url"]
    files = []
    for name in FILES:
        data = body(model_info["model_arch"], name)
        files.append({"name": name, "url": f"{base}/{name}", "size": len(data),
                      "checksum": checksum(data), "checksum_type": "crc32c"})
    return {"base_url": base, "files": files}
