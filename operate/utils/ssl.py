# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""SSL certificate utilities."""

import datetime
import logging
import typing as t
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def create_ssl_certificate(
    ssl_dir: Path,
    key_filename: str = "key.pem",
    cert_filename: str = "cert.pem",
    validity_days: int = 365,
    key_size: int = 2048,
    common_name: str = "localhost",
) -> t.Tuple[Path, Path]:
    """
    Create SSL certificate and private key files.

    Args:
        ssl_dir: Path to the ssl directory
        key_filename: Name of the private key file
        cert_filename: Name of the certificate file
        validity_days: Number of days the certificate is valid
        key_size: RSA key size in bits
        common_name: Common name for the certificate

    Returns:
        Tuple of (key_path, cert_path) as Path objects
    """
    logger = logging.getLogger(__name__)

    # Create SSL directory
    ssl_dir.mkdir(parents=True, exist_ok=True)

    key_path = ssl_dir / key_filename
    cert_path = ssl_dir / cert_filename

    # Generate RSA private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
    )

    # Create certificate subject and issuer
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "CH"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Local"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Valory AG"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )

    # Create certificate
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(1)
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=validity_days)
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                content_commitment=False,
                data_encipherment=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    # Write private key to file
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    # Write certificate to file
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    logger.info(f"SSL certificate created successfully at {key_path} and {cert_path}")

    return key_path, cert_path
