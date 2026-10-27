"""Private-network TLS proxy for the installed workstation. No public ACME calls."""
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "workstation-data"
TLS = DATA / "tls"
HEALTH_URL = 'https://127.0.0.1:8443/api/health'
START_TIMEOUT = 15


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verified_health():
    """Trust only this installation's CA; verify IP SAN and reject redirects."""
    try:
        context = ssl.create_default_context(cafile=str(TLS / 'GD-workstation-CA.crt'))
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context), NoRedirect())
        with opener.open(HEALTH_URL, timeout=2) as response:
            return response.status == 200 and json.load(response).get('application') == 'gd-workstation'
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def prepare():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    TLS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    root_key_path, root_cert_path = TLS / "root.key", TLS / "GD-workstation-CA.crt"
    if root_key_path.exists() and root_cert_path.exists():
        root_key = serialization.load_pem_private_key(root_key_path.read_bytes(), password=None)
        root_cert = x509.load_pem_x509_certificate(root_cert_path.read_bytes())
    else:
        root_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"GD Workstation Private CA")])
        root_cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(root_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=1825))
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
            .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True).sign(root_key,hashes.SHA256()))
        root_key_path.write_bytes(root_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        root_cert_path.write_bytes(root_cert.public_bytes(serialization.Encoding.PEM))
    addresses = {"127.0.0.1"}
    for _,_,_,_,address in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET):
        ip = ipaddress.ip_address(address[0])
        if ip.is_private and not ip.is_link_local and not ip.is_unspecified:
            addresses.add(str(ip))
    hosts = sorted(addresses)
    leaf_key=ec.generate_private_key(ec.SECP256R1())
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"GD Workstation")])
    leaf=(x509.CertificateBuilder().subject_name(name).issuer_name(root_cert.subject).public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(x)) for x in hosts]+[x509.DNSName("localhost")]),critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).sign(root_key,hashes.SHA256()))
    (TLS/'server.key').write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    (TLS/'server.crt').write_bytes(leaf.public_bytes(serialization.Encoding.PEM)+root_cert.public_bytes(serialization.Encoding.PEM))
    site = ", ".join("https://"+host+":8443" for host in hosts)
    configuration = "{\n admin off\n auto_https off\n}\n" + site + " {\n bind " + " ".join(hosts) + "\n"
    configuration += f' tls "{(TLS/"server.crt").as_posix()}" "{(TLS/"server.key").as_posix()}"\n'
    configuration += " @outside not remote_ip 127.0.0.1 ::1 192.168.0.0/16 10.0.0.0/8 172.16.0.0/12\n respond @outside 403\n reverse_proxy 127.0.0.1:8765\n}\n"
    (TLS/'Caddyfile').write_text(configuration,encoding='utf-8')
    (TLS/'addresses.json').write_text(json.dumps({'urls':['https://'+host+':8443' for host in hosts],'ca_certificate':str(root_cert_path)},indent=2),encoding='utf-8')
    return hosts


def start():
    binary = ROOT/'runtime/caddy/caddy.exe'
    if not binary.is_file():
        return False
    # Reuse the existing proxy, avoiding duplicate listeners or certificate replacement.
    if verified_health():
        return True
    # Never replace certificates or start another proxy on an occupied port
    # whose identity/certificate could not be verified.
    from workstation_launcher import port_in_use, stop_owned_process
    if port_in_use(8443):
        return False
    prepare()
    subprocess.run([str(binary),'validate','--config',str(TLS/'Caddyfile')],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    with (DATA/'https.log').open('ab') as log:
        process=subprocess.Popen([str(binary),'run','--config',str(TLS/'Caddyfile')],stdout=log,stderr=log,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (TLS/'proxy.pid').write_text(str(process.pid),encoding='ascii')
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if verified_health():
            return True
        time.sleep(.25)
    stop_owned_process(process)
    return False


if __name__=='__main__':
    print('Local CA-verified HTTPS health check passed' if start() else 'HTTPS health check failed; inspect workstation-data/https.log')
