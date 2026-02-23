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

"""Tests for SSL certificate utilities."""

from pathlib import Path

from cryptography import x509

from operate.utils.ssl import create_ssl_certificate


class TestCreateSslCertificate:
    """Tests for create_ssl_certificate function."""

    def test_creates_files_in_existing_dir(self, tmp_path: Path) -> None:
        """Test certificate creation in an existing directory."""
        ssl_dir = tmp_path / "ssl"
        ssl_dir.mkdir()
        key_path, cert_path = create_ssl_certificate(ssl_dir)
        assert key_path == ssl_dir / "key.pem"
        assert cert_path == ssl_dir / "cert.pem"
        assert key_path.exists()
        assert cert_path.exists()

    def test_creates_dir_if_missing(self, tmp_path: Path) -> None:
        """Test that the directory is created if it does not exist."""
        ssl_dir = tmp_path / "nested" / "ssl"
        key_path, cert_path = create_ssl_certificate(ssl_dir)
        assert ssl_dir.exists()
        assert key_path.exists()
        assert cert_path.exists()

    def test_returns_path_objects(self, tmp_path: Path) -> None:
        """Test that the function returns a tuple of Path objects."""
        result = create_ssl_certificate(tmp_path)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], Path)
        assert isinstance(result[1], Path)

    def test_custom_filenames(self, tmp_path: Path) -> None:
        """Test certificate creation with custom filenames."""
        key_path, cert_path = create_ssl_certificate(
            tmp_path, key_filename="mykey.pem", cert_filename="mycert.pem"
        )
        assert key_path.name == "mykey.pem"
        assert cert_path.name == "mycert.pem"
        assert key_path.exists()
        assert cert_path.exists()

    def test_cert_is_valid_x509(self, tmp_path: Path) -> None:
        """Test that the generated certificate is a valid X.509 certificate."""
        _, cert_path = create_ssl_certificate(tmp_path)
        cert_data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        common_names = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        assert common_names[0].value == "localhost"

    def test_custom_common_name(self, tmp_path: Path) -> None:
        """Test certificate creation with a custom common name."""
        _, cert_path = create_ssl_certificate(tmp_path, common_name="myapp.local")
        cert_data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        common_names = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        assert common_names[0].value == "myapp.local"

    def test_custom_validity_days(self, tmp_path: Path) -> None:
        """Test certificate creation with a custom validity period."""
        _, cert_path = create_ssl_certificate(tmp_path, validity_days=30)
        cert_data = cert_path.read_bytes()
        cert = x509.load_pem_x509_certificate(cert_data)
        delta = cert.not_valid_after - cert.not_valid_before
        assert delta.days == 30

    def test_key_file_is_pem_encoded(self, tmp_path: Path) -> None:
        """Test that the private key file is PEM-encoded."""
        key_path, _ = create_ssl_certificate(tmp_path)
        key_data = key_path.read_bytes()
        assert key_data.startswith(b"-----BEGIN PRIVATE KEY-----")
