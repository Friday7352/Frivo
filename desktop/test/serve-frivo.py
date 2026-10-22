"""
Runs a real Frivo (from ../../app) for the app's end-to-end test.

    python serve-frivo.py PORT [https|forged]

With "https", Frivo serves a certificate chain like its own: a "Frivo Local
CA" authority and a server certificate for localhost and 127.0.0.1 signed by
it, both sent. With "forged", the same authority's certificate is sent, but
after a server certificate it never signed: what someone else at the
address could send, since the authority's certificate isn't secret. Everything (data folder, certificates) is in a temporary
folder; nothing of a real Frivo install is touched. Needs Frivo's Python
packages (app\\requirements.txt).
"""
import datetime
import importlib.util
import ipaddress
import os
import shutil
import sys
import tempfile

port = int(sys.argv[1])
mode = sys.argv[2] if len(sys.argv) > 2 else "http"
https = mode in ("https", "forged")
repo_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app")

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="frivo-apptest-home-")
os.environ["VOICE_CONSOLE_DATA"] = tempfile.mkdtemp(prefix="frivo-apptest-data-")
work = tempfile.mkdtemp(prefix="frivo-apptest-")
for name in ("app.py", "voice_pack.py", "cleanup_rules.py", "builtin_ai.py"):
    shutil.copy(os.path.join(repo_app, name), os.path.join(work, name))
shutil.copytree(os.path.join(repo_app, "static"), os.path.join(work, "static"))
shutil.copytree(os.path.join(repo_app, "templates"), os.path.join(work, "templates"))


def make_chain(folder, forged=False):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Frivo Local CA")])
    pem = serialization.Encoding.PEM
    real_ca = None
    if forged:
        with open(os.path.join(folder, "ca.pem"), "rb") as f:
            real_ca = x509.load_pem_x509_certificate(f.read())
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "frivo")]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.DNSName("frivo.local"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    prefix = "forged-" if forged else ""
    chain = os.path.join(folder, prefix + "chain.pem")
    key_path = os.path.join(folder, prefix + "key.pem")
    with open(chain, "wb") as f:
        # Forged: signed by a throwaway authority, sent with the real one's.
        f.write(leaf.public_bytes(pem) + (real_ca or ca).public_bytes(pem))
    if not forged:
        with open(os.path.join(folder, "ca.pem"), "wb") as f:
            f.write(ca.public_bytes(pem))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(pem, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    return chain, key_path


spec = importlib.util.spec_from_file_location("frivo_apptest", os.path.join(work, "app.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules["frivo_apptest"] = mod
spec.loader.exec_module(mod)

# The certificate is made once per folder, so a restarted server (the test
# stops and starts it) keeps the same authority, like a real Frivo does.
cert_dir = os.environ.get("FRIVO_TEST_CERTS") or tempfile.mkdtemp(prefix="frivo-apptest-certs-")
os.makedirs(cert_dir, exist_ok=True)
if mode == "https":
    if not os.path.exists(os.path.join(cert_dir, "chain.pem")):
        make_chain(cert_dir)
    context = (os.path.join(cert_dir, "chain.pem"), os.path.join(cert_dir, "key.pem"))
elif mode == "forged":
    if not os.path.exists(os.path.join(cert_dir, "ca.pem")):
        make_chain(cert_dir)
    context = make_chain(cert_dir, forged=True)
else:
    context = None
print("serving", port, mode, flush=True)
mod.app.run(host="127.0.0.1", port=port, ssl_context=context, use_reloader=False, threaded=True)
